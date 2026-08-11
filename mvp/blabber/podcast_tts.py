from __future__ import annotations

import asyncio
import inspect
import io
import json
import struct
import uuid
from dataclasses import asdict, dataclass
from enum import IntEnum
from pathlib import Path
from urllib.parse import urlparse

import websockets

from .schema import Episode, Turn


class MsgType(IntEnum):
    FULL_CLIENT_REQUEST = 0x1
    FULL_SERVER_RESPONSE = 0x9
    AUDIO_ONLY_SERVER = 0xB
    ERROR = 0xF


class Flag(IntEnum):
    NO_SEQUENCE = 0
    POSITIVE_SEQUENCE = 1
    NEGATIVE_SEQUENCE = 3
    WITH_EVENT = 4


class Event(IntEnum):
    START_CONNECTION = 1
    FINISH_CONNECTION = 2
    CONNECTION_STARTED = 50
    CONNECTION_FINISHED = 52
    START_SESSION = 100
    FINISH_SESSION = 102
    SESSION_STARTED = 150
    SESSION_FINISHED = 152
    PODCAST_ROUND_START = 360
    PODCAST_ROUND_RESPONSE = 361
    PODCAST_ROUND_END = 362
    PODCAST_END = 363


@dataclass
class Message:
    type: MsgType
    flag: Flag = Flag.NO_SEQUENCE
    event: int = 0
    session_id: str = ""
    connect_id: str = ""
    sequence: int = 0
    error_code: int = 0
    payload: bytes = b""

    def marshal(self) -> bytes:
        # V3 binary protocol: version/header size, message/flag,
        # JSON serialization/no compression, reserved byte.
        buffer = io.BytesIO()
        buffer.write(bytes((0x11, (self.type << 4) | self.flag, 0x10, 0x00)))
        if self.flag == Flag.WITH_EVENT:
            buffer.write(struct.pack(">i", self.event))
            if self.event not in {
                Event.START_CONNECTION,
                Event.FINISH_CONNECTION,
                Event.CONNECTION_STARTED,
            }:
                session = self.session_id.encode("utf-8")
                buffer.write(struct.pack(">I", len(session)))
                buffer.write(session)
        buffer.write(struct.pack(">I", len(self.payload)))
        buffer.write(self.payload)
        return buffer.getvalue()

    @classmethod
    def parse(cls, raw: bytes) -> "Message":
        if len(raw) < 4:
            raise RuntimeError("PodcastTTS 返回了不完整的数据帧")
        buffer = io.BytesIO(raw)
        first, type_and_flag, _serialization, _reserved = buffer.read(4)
        header_size = (first & 0x0F) * 4
        if header_size > 4:
            buffer.read(header_size - 4)
        msg_type = MsgType(type_and_flag >> 4)
        flag = Flag(type_and_flag & 0x0F)
        message = cls(type=msg_type, flag=flag)

        if msg_type == MsgType.ERROR:
            code = buffer.read(4)
            if len(code) == 4:
                message.error_code = struct.unpack(">I", code)[0]
        elif flag in {Flag.POSITIVE_SEQUENCE, Flag.NEGATIVE_SEQUENCE}:
            sequence = buffer.read(4)
            if len(sequence) == 4:
                message.sequence = struct.unpack(">i", sequence)[0]

        if flag == Flag.WITH_EVENT:
            event = buffer.read(4)
            if len(event) == 4:
                message.event = struct.unpack(">i", event)[0]
            if message.event not in {
                Event.START_CONNECTION,
                Event.FINISH_CONNECTION,
                Event.CONNECTION_STARTED,
                Event.CONNECTION_FINISHED,
            }:
                message.session_id = _read_sized_string(buffer)
            if message.event in {
                Event.CONNECTION_STARTED,
                Event.CONNECTION_FINISHED,
            }:
                message.connect_id = _read_sized_string(buffer)

        size_bytes = buffer.read(4)
        if len(size_bytes) == 4:
            payload_size = struct.unpack(">I", size_bytes)[0]
            message.payload = buffer.read(payload_size)
            if len(message.payload) != payload_size:
                raise RuntimeError("PodcastTTS 数据帧负载长度不正确")
        return message


def _read_sized_string(buffer: io.BytesIO) -> str:
    size_bytes = buffer.read(4)
    if len(size_bytes) != 4:
        return ""
    size = struct.unpack(">I", size_bytes)[0]
    return buffer.read(size).decode("utf-8") if size else ""


@dataclass
class PodcastResult:
    task_id: str
    episode: Episode
    final_path: Path
    script_path: Path
    clips: list[dict]
    provider_audio_url: str | None = None


class VolcenginePodcastTTS:
    """Direct PodcastTTS client for the Volcengine V3 WebSocket API."""

    ENDPOINT = "wss://openspeech.bytedance.com/api/v3/sami/podcasttts"
    RESOURCE_ID = "volc.service_type.10050"
    APP_KEY = "aGjiRDfUWi"
    DEFAULT_SPEAKERS = (
        "zh_male_dayixiansheng_v2_saturn_bigtts",
        "zh_female_mizaitongxue_v2_saturn_bigtts",
    )

    def __init__(
        self,
        app_id: str,
        access_key: str,
        timeout: float = 300.0,
    ) -> None:
        if not app_id.strip() or not access_key.strip():
            raise ValueError("PodcastTTS App ID 或 Access Token 未配置")
        self.app_id = app_id.strip()
        self.access_key = access_key.strip()
        self.timeout = timeout

    def _request_headers(self, request_id: str) -> dict[str, str]:
        return {
            "X-Api-App-Id": self.app_id,
            "X-Api-Access-Key": self.access_key,
            "X-Api-Resource-Id": self.RESOURCE_ID,
            "X-Api-App-Key": self.APP_KEY,
            "X-Api-Request-Id": request_id,
        }

    @staticmethod
    def _is_retryable_stream_error(error: Exception) -> bool:
        detail = str(error).casefold()
        return any(marker in detail for marker in (
            "rst_stream",
            "stream terminated",
            "downstream podcast service",
            "connectionclosederror",
            "keepalive ping timeout",
            "read result timeout",
        ))

    async def generate(
        self,
        prompt: str | None,
        run_dir: Path,
        target_minutes: float | None = None,
        on_progress=None,
        *,
        input_text: str | None = None,
        input_url: str | None = None,
        topic: str | None = None,
        speakers: list[str] | tuple[str, str] | None = None,
        nlp_texts: list[dict[str, str]] | None = None,
        only_nlp_text: bool = False,
    ) -> PodcastResult:
        attempts = 3
        for attempt in range(1, attempts + 1):
            try:
                return await self._generate_once(
                    prompt,
                    run_dir,
                    target_minutes,
                    on_progress,
                    input_text=input_text,
                    input_url=input_url,
                    topic=topic,
                    speakers=speakers,
                    nlp_texts=nlp_texts,
                    only_nlp_text=only_nlp_text,
                )
            except Exception as error:
                if (
                    attempt >= attempts
                    or not self._is_retryable_stream_error(error)
                ):
                    raise
                clips_dir = run_dir / "clips"
                if clips_dir.is_dir():
                    for clip_path in clips_dir.glob("*.mp3"):
                        clip_path.unlink(missing_ok=True)
                for output_name in ("final.mp3", "script.json"):
                    (run_dir / output_name).unlink(missing_ok=True)
                delay = 2 ** (attempt - 1)
                print(
                    f"[PodcastTTS] 下游流中断，第 {attempt}/{attempts} 次失败，"
                    f"{delay} 秒后重试：{error}",
                    flush=True,
                )
                await _notify(on_progress, {
                    "stage": "podcast_retry",
                    "completed": attempt,
                    "total": attempts,
                    "retry_in_seconds": delay,
                    "retry_message": str(error),
                })
                await asyncio.sleep(delay)
        raise RuntimeError("PodcastTTS 重试状态异常")

    async def _generate_once(
        self,
        prompt: str | None,
        run_dir: Path,
        target_minutes: float | None = None,
        on_progress=None,
        *,
        input_text: str | None = None,
        input_url: str | None = None,
        topic: str | None = None,
        speakers: list[str] | tuple[str, str] | None = None,
        nlp_texts: list[dict[str, str]] | None = None,
        only_nlp_text: bool = False,
    ) -> PodcastResult:
        run_dir.mkdir(parents=True, exist_ok=True)
        clips_dir = run_dir / "clips"
        clips_dir.mkdir(parents=True, exist_ok=True)
        session_id = str(uuid.uuid4())
        request_id = str(uuid.uuid4())
        prompt_text = (prompt or "").strip()
        document_text = (input_text or "").strip()
        document_url = (input_url or "").strip()
        document_mode = bool(document_text or document_url)
        dialogue_mode = bool(nlp_texts)
        if dialogue_mode and (document_mode or prompt_text):
            raise ValueError("nlp_texts 不能与 prompt、input_text 或 input_url 同时提供")
        if document_mode and prompt_text:
            raise ValueError("话题模式和文档模式不能同时使用")
        if document_text and document_url:
            raise ValueError("input_text 和 input_url 只能提供一个")
        if not dialogue_mode and not document_mode and not prompt_text:
            raise ValueError("prompt、input_text、input_url 或 nlp_texts 至少提供一个")
        if dialogue_mode:
            if not 1 <= len(nlp_texts or []) <= 500:
                raise ValueError("nlp_texts 轮数必须在 1–500 之间")
            if any(
                not isinstance(item, dict)
                or not str(item.get("speaker", "")).strip()
                or not str(item.get("text", "")).strip()
                for item in nlp_texts or []
            ):
                raise ValueError("nlp_texts 包含无效对白")
        if document_url and urlparse(document_url).scheme not in {"http", "https"}:
            raise ValueError("input_url 必须是 http 或 https 地址")
        if target_minutes and not document_mode:
            prompt_text = f"{prompt_text}；时长约{target_minutes:g}分钟"
        selected_speakers = tuple(speakers or self.DEFAULT_SPEAKERS)
        if len(selected_speakers) != 2 or not all(selected_speakers):
            raise ValueError("PodcastTTS 必须配置两个有效发音人")
        request_payload = {
            "input_id": f"blabber-{session_id}",
            "input_text": document_text,
            "nlp_texts": nlp_texts,
            "prompt_text": prompt_text,
            "action": 3 if dialogue_mode else 0 if document_mode else 4,
            "use_head_music": False,
            "use_tail_music": False,
            "aigc_watermark": False,
            "input_info": {
                "input_url": document_url,
                "return_audio_url": True,
                "only_nlp_text": only_nlp_text,
            },
            "speaker_info": {
                "random_order": False,
                "speakers": list(selected_speakers),
            },
            "audio_config": {
                "format": "mp3",
                "sample_rate": 24000,
                "speech_rate": 0,
            },
        }
        headers = self._request_headers(request_id)
        connect_options = {
            "open_timeout": min(self.timeout, 60),
            "close_timeout": 10,
            "max_size": None,
        }
        header_argument = (
            "additional_headers"
            if "additional_headers" in inspect.signature(websockets.connect).parameters
            else "extra_headers"
        )
        connect_options[header_argument] = headers

        turns: list[Turn] = []
        clips: list[dict] = []
        podcast_audio = bytearray()
        round_audio = bytearray()
        # 官方响应中的 speaker 是请求的音色 ID。按请求数组显式绑定，
        # 避免把“第一个出声的人”误认为左侧 HostA。
        speaker_names: dict[str, str] = {
            selected_speakers[0]: "HostA",
            selected_speakers[1]: "HostB",
        }
        unknown_speakers: dict[str, str] = {}
        current_turn: Turn | None = None
        end_payload: dict = {}
        live_topic = (topic or prompt or document_url or "文档播客").strip()[:200]

        async with websockets.connect(self.ENDPOINT, **connect_options) as websocket:
            await websocket.send(_event_message(Event.START_CONNECTION).marshal())
            await self._expect(websocket, MsgType.FULL_SERVER_RESPONSE, Event.CONNECTION_STARTED)
            await websocket.send(
                _event_message(
                    Event.START_SESSION,
                    session_id,
                    json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
                ).marshal()
            )
            await self._expect(websocket, MsgType.FULL_SERVER_RESPONSE, Event.SESSION_STARTED)
            await websocket.send(
                _event_message(Event.FINISH_SESSION, session_id, b"{}").marshal()
            )

            while True:
                message = await self._receive(websocket)
                if message.type == MsgType.ERROR:
                    detail = message.payload.decode("utf-8", errors="replace")
                    raise RuntimeError(
                        f"PodcastTTS 服务错误 {message.error_code}: {detail}"
                    )
                if (
                    message.type == MsgType.AUDIO_ONLY_SERVER
                    and message.event == Event.PODCAST_ROUND_RESPONSE
                ):
                    round_audio.extend(message.payload)
                    continue
                if message.type != MsgType.FULL_SERVER_RESPONSE:
                    continue
                if message.event == Event.PODCAST_ROUND_START:
                    data = _json_payload(message)
                    provider_speaker = str(data.get("speaker") or "speaker")
                    if provider_speaker not in speaker_names:
                        unknown_speakers.setdefault(
                            provider_speaker,
                            "HostA" if not unknown_speakers else "HostB",
                        )
                    mapped_speaker = speaker_names.get(provider_speaker)
                    if mapped_speaker is None:
                        mapped_speaker = unknown_speakers[provider_speaker]
                    current_turn = Turn(
                        speaker=mapped_speaker,
                        text=str(data.get("text") or "").strip(),
                    )
                    turns.append(current_turn)
                    await _notify(on_progress, {
                        "stage": "podcast",
                        "completed": len(turns) - 1,
                        "total": len(turns) + 1,
                        "speaker": current_turn.speaker,
                        "text": current_turn.text,
                        "turns": [asdict(turn) for turn in turns],
                        "clips": list(clips),
                    })
                    continue
                if message.event == Event.PODCAST_ROUND_END:
                    data = _json_payload(message)
                    if data.get("is_error"):
                        raise RuntimeError(
                            f"PodcastTTS 切片生成失败：{json.dumps(data, ensure_ascii=False)}"
                        )
                    if current_turn is not None and round_audio:
                        index = len(clips)
                        clip_path = clips_dir / f"{index:02d}_{current_turn.speaker}.mp3"
                        clip_path.write_bytes(round_audio)
                        podcast_audio.extend(round_audio)
                        clips.append({
                            "index": index,
                            "speaker": current_turn.speaker,
                            "text": current_turn.text,
                            "path": str(clip_path),
                        })
                        round_audio.clear()
                        await _notify(on_progress, {
                            "stage": "podcast",
                            "completed": len(clips),
                            "total": len(clips) + 1,
                            "speaker": current_turn.speaker,
                            "text": current_turn.text,
                            "turns": [asdict(turn) for turn in turns],
                            "clips": list(clips),
                        })
                    continue
                if message.event == Event.PODCAST_END:
                    end_payload = _json_payload(message)
                    continue
                if message.event == Event.SESSION_FINISHED:
                    break

            await websocket.send(_event_message(Event.FINISH_CONNECTION).marshal())
            await self._expect(websocket, MsgType.FULL_SERVER_RESPONSE, Event.CONNECTION_FINISHED)

        if not turns:
            raise RuntimeError("PodcastTTS 未返回切片文本")
        episode_topic = live_topic or document_url or "文档播客"
        episode = Episode(topic=episode_topic[:200], turns=turns)
        script_path = run_dir / "script.json"
        script_path.write_text(
            json.dumps(asdict(episode), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        final_path = run_dir / "final.mp3"
        if only_nlp_text:
            return PodcastResult(
                task_id=session_id,
                episode=episode,
                final_path=final_path,
                script_path=script_path,
                clips=[],
                provider_audio_url=None,
            )
        if not podcast_audio:
            raise RuntimeError("PodcastTTS 未返回音频")
        final_path.write_bytes(podcast_audio)
        audio_url = end_payload.get("meta_info", {}).get("audio_url")
        return PodcastResult(
            task_id=session_id,
            episode=episode,
            final_path=final_path,
            script_path=script_path,
            clips=clips,
            provider_audio_url=audio_url if isinstance(audio_url, str) else None,
        )

    async def _receive(self, websocket) -> Message:
        raw = await asyncio.wait_for(websocket.recv(), timeout=self.timeout)
        if not isinstance(raw, bytes):
            raise RuntimeError("PodcastTTS 返回了非二进制数据帧")
        return Message.parse(raw)

    async def _expect(self, websocket, msg_type: MsgType, event: Event) -> Message:
        message = await self._receive(websocket)
        if message.type == MsgType.ERROR:
            detail = message.payload.decode("utf-8", errors="replace")
            raise RuntimeError(
                f"PodcastTTS 服务错误 {message.error_code}: {detail}"
            )
        if message.type != msg_type or message.event != event:
            raise RuntimeError(
                f"PodcastTTS 协议事件异常：收到 {message.type.name}/{message.event}，"
                f"期望 {msg_type.name}/{event.value}"
            )
        return message


def _event_message(event: Event, session_id: str = "", payload: bytes = b"{}") -> Message:
    return Message(
        type=MsgType.FULL_CLIENT_REQUEST,
        flag=Flag.WITH_EVENT,
        event=event,
        session_id=session_id,
        payload=payload,
    )


def _json_payload(message: Message) -> dict:
    try:
        value = json.loads(message.payload.decode("utf-8", errors="replace") or "{}")
    except json.JSONDecodeError as error:
        raise RuntimeError("PodcastTTS 返回了无效 JSON") from error
    return value if isinstance(value, dict) else {}


async def _notify(callback, payload: dict) -> None:
    if callback is None:
        return
    result = callback(payload)
    if inspect.isawaitable(result):
        await result
