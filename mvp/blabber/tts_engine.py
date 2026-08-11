from __future__ import annotations

import asyncio
import base64
import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path

class TTSEngine(ABC):
    @abstractmethod
    async def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        ...


class ByteDanceSeedAudioTTSEngine(TTSEngine):
    """Generative speech via ByteDance Seed Audio's synchronous create API."""

    ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/create"

    def __init__(self, api_key: str, timeout: float = 300.0) -> None:
        if not api_key:
            raise ValueError("BYTEDANCE_TTS_API_KEY 未配置")
        self.api_key = api_key
        self.timeout = timeout

    def _synthesize_sync(self, text: str, voice: str, out_path: Path) -> Path:
        if voice.startswith("S_"):
            raise ValueError("当前 TTS 已禁用音色 ID，请传入自然语言音色提示词")
        prompt = (
            "纯净录音，无背景音乐、无环境声、无音效。"
            f"{voice}用自然、有感染力的播客语气说道：“{text}”"
        )
        payload = {
            "model": "seed-audio-1.0",
            "text_prompt": prompt,
            "audio_config": {
                "format": "mp3",
                "sample_rate": 48000,
                "pitch_rate": 0,
                "speech_rate": 0,
                "loudness_rate": 0,
            },
            "watermark": {},
        }
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.ENDPOINT,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Api-Key": self.api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read())
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(
                f"字节 Seed Audio HTTP {error.code}: {detail}"
            ) from error
        audio = result.get("audio")
        if not audio:
            raise RuntimeError(f"字节 Seed Audio 未返回音频：{result}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(base64.b64decode(audio))
        return out_path

    async def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                return await asyncio.to_thread(
                    self._synthesize_sync, text, voice, out_path
                )
            except Exception as error:
                last_error = error
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
        raise last_error
