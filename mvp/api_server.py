from __future__ import annotations

import asyncio
import argparse
import base64
import binascii
import html
import hashlib
import io
import json
import mimetypes
import os
import re
import subprocess
import threading
import time
import uuid
import zipfile
from dataclasses import asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from math import ceil
from pathlib import Path
from urllib.parse import unquote, urlparse

from pypdf import PdfReader

from blabber.video_compose import compose_episode_video
from blabber.video_engine import CHECKPOINT_PATH, VENDOR_DIR
from blabber.fast_video import compose_fast_episode_video, render_character_track
from blabber.image_voice_analyzer import analyze_character_voice
from blabber.podcast_tts import VolcenginePodcastTTS
from blabber.schema import Episode, Turn
from blabber.seedream_compositor import generate_composite_scene
from blabber.voices import CHARACTER_SETS, DEFAULT_CHARACTER_SET
from compose_action_video import (
    DEFAULT_SUBTITLE_FONT,
    compose as compose_action_video,
)
from main import OUTPUT_ROOT, _pick_generator, run

MVP_ROOT = Path(__file__).parent.resolve()
PROJECT_ROOT = MVP_ROOT.parent
ENV_PATH = MVP_ROOT / ".env"
OPEN_NOTEBOOK_ROOT = PROJECT_ROOT / "open-notebook"
OPEN_NOTEBOOK_ENV_PATH = OPEN_NOTEBOOK_ROOT / ".env"
OPEN_NOTEBOOK_COMPOSE_PATH = OPEN_NOTEBOOK_ROOT / "docker-compose.yml"
HISTORY_PATH = OUTPUT_ROOT / "jobs-history.json"

ENV_CONFIG_FIELDS = (
    {"key": "VOLCENGINE_SPEECH_APP_ID", "group": "豆包语音 PodcastTTS", "label": "App ID", "default": "", "help": "在豆包语音控制台的应用管理中获取。"},
    {"key": "VOLCENGINE_SPEECH_ACCESS_KEY", "group": "豆包语音 PodcastTTS", "label": "Access Token", "default": "", "secret": True, "help": "PodcastTTS 的 X-Api-Access-Key；不是 ark- 开头的方舟 API Key。"},
)
ENV_FIELD_BY_KEY = {field["key"]: field for field in ENV_CONFIG_FIELDS}
ENV_FILE_ALLOWED_KEYS = {
    *ENV_FIELD_BY_KEY,
    # Optional Ark credential is edited directly in mvp/.env rather than
    # exposed through the browser configuration form.
    "ARK_API_KEY",
}


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if key not in ENV_FILE_ALLOWED_KEYS:
            continue
        raw_value = raw_value.strip()
        try:
            value = json.loads(raw_value) if raw_value.startswith('"') else raw_value
        except json.JSONDecodeError:
            value = raw_value.strip('"\'')
        values[key] = str(value)
    return values


def _load_saved_environment() -> None:
    loaded = {
        **_read_env_file(ENV_PATH),
        **_read_env_file(OPEN_NOTEBOOK_ENV_PATH),
    }
    for key, value in loaded.items():
        os.environ[key] = value
    for field in ENV_CONFIG_FIELDS:
        if field.get("default", ""):
            os.environ.setdefault(field["key"], str(field["default"]))


def _validate_environment(values: dict[str, str]) -> None:
    for key, value in values.items():
        field = ENV_FIELD_BY_KEY[key]
        if "\x00" in value or "\n" in value or "\r" in value or len(value) > 4096:
            raise ValueError(f"{field['label']} 格式无效")
        if not value:
            continue
        if field.get("kind") == "url" and urlparse(value).scheme not in {"http", "https"}:
            raise ValueError(f"{field['label']} 必须是 http 或 https 地址")
        if field.get("kind") == "service_url" and urlparse(value).scheme not in {"http", "https", "ws", "wss"}:
            raise ValueError(f"{field['label']} 必须是 http、https、ws 或 wss 地址")
        if field.get("kind") == "number":
            try:
                number = float(value)
            except ValueError as error:
                raise ValueError(f"{field['label']} 必须是数字") from error
            if not float(field["minimum"]) <= number <= float(field["maximum"]):
                raise ValueError(f"{field['label']} 超出允许范围")
    host = values.get("MVP_HOST", "")
    if host and not re.fullmatch(r"[A-Za-z0-9.:_-]+", host):
        raise ValueError("监听地址格式无效")


def _write_environment(values: dict[str, str]) -> None:
    preserved_lines = []
    if ENV_PATH.is_file():
        for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key = stripped.split("=", 1)[0].strip()
            if key not in ENV_FIELD_BY_KEY:
                preserved_lines.append(raw_line)
    lines = [
        "# Blabber 网页服务配置；由本地 api_server 管理，请勿提交到 Git。",
        *[
            f"{field['key']}={json.dumps(values[field['key']], ensure_ascii=False)}"
            for field in ENV_CONFIG_FIELDS
            if field.get("storage") != "docker"
            if values.get(field["key"], "")
        ],
        *preserved_lines,
        "",
    ]
    temporary = ENV_PATH.with_suffix(".env.tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(ENV_PATH)


def _write_open_notebook_environment(values: dict[str, str]) -> None:
    OPEN_NOTEBOOK_ROOT.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Open Notebook Docker 配置；由 Blabber api_server 管理。",
        *[
            f"{field['key']}={json.dumps(values[field['key']], ensure_ascii=False)}"
            for field in ENV_CONFIG_FIELDS
            if field.get("storage") == "docker"
            if values.get(field["key"], "")
        ],
        "",
    ]
    temporary = OPEN_NOTEBOOK_ENV_PATH.with_suffix(".env.tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(OPEN_NOTEBOOK_ENV_PATH)


def _apply_open_notebook_compose() -> str:
    if not OPEN_NOTEBOOK_COMPOSE_PATH.is_file():
        raise RuntimeError("未找到 open-notebook/docker-compose.yml")
    completed = subprocess.run(
        [
            "docker", "compose", "-f", str(OPEN_NOTEBOOK_COMPOSE_PATH),
            "up", "-d", "--build", "--remove-orphans",
        ],
        cwd=OPEN_NOTEBOOK_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()[-1000:]
        raise RuntimeError(f"Docker Compose 应用失败：{detail}")
    return "Open Notebook 容器配置已构建并启动"


def _open_notebook_container_running() -> bool:
    if not OPEN_NOTEBOOK_COMPOSE_PATH.is_file():
        return False
    try:
        completed = subprocess.run(
            [
                "docker", "compose", "-f", str(OPEN_NOTEBOOK_COMPOSE_PATH),
                "ps", "--status", "running", "--services",
            ],
            cwd=OPEN_NOTEBOOK_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0 and "open_notebook" in completed.stdout.split()


def _public_environment() -> dict:
    fields = []
    for field in ENV_CONFIG_FIELDS:
        key = field["key"]
        current = os.getenv(key, field.get("default", ""))
        public_field = {**field}
        if field.get("secret"):
            public_field["default"] = ""
        public_field.update({
            "value": "" if field.get("secret") else current,
            "configured": bool(current),
        })
        fields.append(public_field)
    return {
        "fields": fields,
        "services": {
            "podcast": bool(
                os.getenv("VOLCENGINE_SPEECH_APP_ID", "").strip()
                and os.getenv("VOLCENGINE_SPEECH_ACCESS_KEY", "").strip()
            ),
        },
    }


_load_saved_environment()
HOST = os.getenv("MVP_HOST", "127.0.0.1").strip() or "127.0.0.1"
PORT = int(float(os.getenv("MVP_PORT", "8787")))
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
VIDEO_RENDER_LOCK = threading.Lock()

ACTION_CHARACTERS = {"male", "female", "dog", "duck"}
ACTION_CHARACTER_SPEAKER_IDS = {
    "male": "zh_male_dayixiansheng_v2_saturn_bigtts",
    "dog": "zh_male_dayixiansheng_v2_saturn_bigtts",
    "female": "zh_female_mizaitongxue_v2_saturn_bigtts",
    "duck": "zh_female_mizaitongxue_v2_saturn_bigtts",
}
ACTION_CHARACTER_VOICE_PROMPTS = {
    "male": (
        "青年男性，普通话标准，声音清朗温暖，带自然笑意和少年感；"
        "性格阳光外向、亲切有活力，语速稍快但吐字清楚，像朋友聊天般轻松。"
    ),
    "female": (
        "青年女性，普通话标准，声音温暖明亮、柔和甜润但不过分稚嫩；"
        "性格亲切活泼，带自然笑意，节奏轻快，像充满好奇心的年轻播客主持人。"
    ),
    "dog": (
        "青年男性卡通角色，普通话标准，声音阳光清朗、热情有活力；"
        "语气忠诚友善又略带顽皮，节奏轻快，像幽默亲切的年轻播客主持人。"
    ),
    "duck": (
        "青年女性卡通角色，普通话标准，声音清脆明亮、机灵俏皮；"
        "语气自信活泼，带自然笑意，吐字清楚，像反应敏捷的年轻播客主持人。"
    ),
}
ACTION_SCENES = {
    "studio": {
        "background": PROJECT_ROOT / "assets" / "background" / "scene2-background-mics-out-100px-1920x1080.png",
        "foreground": PROJECT_ROOT / "assets" / "background" / "scene2-foreground-mics-out-100px-alpha-1920x1080_副本.png",
        "foreground_key_color": None,
    },
    "studio-clean": {
        "background": PROJECT_ROOT / "assets" / "background" / "scene2-background-mics-out-100px-1920x1080.png",
        "foreground": PROJECT_ROOT / "assets" / "background" / "scene2-foreground-mics-out-100px-alpha-1920x1080_副本.png",
        "foreground_key_color": None,
    },
    "zoo": {
        "background": PROJECT_ROOT / "assets" / "background" / "zoo_background.png",
        "foreground": PROJECT_ROOT / "assets" / "background" / "zoo_foreground.png",
        "foreground_key_color": "0xFF00FF",
    },
    "library": {
        "background": PROJECT_ROOT / "assets" / "background" / "library_background.png",
        "foreground": PROJECT_ROOT / "assets" / "background" / "library_foreground.png",
        "foreground_key_color": None,
    },
    "seaside": {
        "background": PROJECT_ROOT / "assets" / "background" / "seaside_background.png",
        "foreground": PROJECT_ROOT / "assets" / "background" / "seaside_foreground.png",
        "foreground_key_color": "0xFF00FF",
    },
    "space": {
        "background": PROJECT_ROOT / "assets" / "background" / "space_background.png",
        "foreground": PROJECT_ROOT / "assets" / "background" / "space_foreground.png",
        "foreground_key_color": None,
    },
    "ink-tea": {
        "background": PROJECT_ROOT / "assets" / "background" / "ink_tea_background.png",
        "foreground": PROJECT_ROOT / "assets" / "background" / "ink_tea_foreground.png",
        "foreground_key_color": None,
    },
    "anime-neon": {
        "background": PROJECT_ROOT / "assets" / "background" / "scene_anime_neon_background.png",
        "foreground": PROJECT_ROOT / "assets" / "background" / "scene_anime_neon_foreground.png",
        "foreground_key_color": None,
    },
    "flat-tech": {
        "background": PROJECT_ROOT / "assets" / "background" / "scene_flat_tech_background.png",
        "foreground": PROJECT_ROOT / "assets" / "background" / "scene_flat_tech_foreground.png",
        "foreground_key_color": None,
    },
    "lowpoly": {
        "background": PROJECT_ROOT / "assets" / "background" / "scene_lowpoly_background.png",
        "foreground": PROJECT_ROOT / "assets" / "background" / "scene_lowpoly_foreground.png",
        "foreground_key_color": None,
    },
}


def _clamp_number(value, minimum: float, maximum: float, fallback: float) -> float:
    try:
        return min(maximum, max(minimum, float(value)))
    except (TypeError, ValueError):
        return fallback


def _normalize_creative_config(raw_config) -> dict:
    raw = raw_config if isinstance(raw_config, dict) else {}
    background = str(raw.get("background", "studio"))
    if background not in ACTION_SCENES:
        background = "studio"

    raw_characters = raw.get("characters")
    characters = ["male", "female"]
    if isinstance(raw_characters, list):
        chosen = [str(item) for item in raw_characters[:2]]
        if len(chosen) == 2 and all(item in ACTION_CHARACTERS for item in chosen):
            characters = chosen

    defaults = ({"x": 18, "y": 0, "scale": 1}, {"x": 58, "y": 0, "scale": 1})
    raw_placements = raw.get("placements")
    placements = []
    for index, default in enumerate(defaults):
        source = (
            raw_placements[index]
            if isinstance(raw_placements, list)
            and index < len(raw_placements)
            and isinstance(raw_placements[index], dict)
            else {}
        )
        placements.append({
            "x": _clamp_number(source.get("x"), 0, 70, default["x"]),
            "y": _clamp_number(source.get("y"), -15, 20, default["y"]),
            "scale": _clamp_number(source.get("scale"), .6, 1.45, default["scale"]),
        })
    return {
        "background": background,
        "characters": characters,
        "placements": placements,
        "scene": str(raw.get("scene", "balanced"))[:40],
        "voices": raw.get("voices", []),
    }


def _speaker_ids_for_config(creative_config: dict) -> list[str]:
    return [
        ACTION_CHARACTER_SPEAKER_IDS[character]
        for character in creative_config["characters"]
    ]


def _compose_action_episode_video(
    run_dir: Path,
    creative_config: dict,
    progress_callback=None,
) -> Path:
    config = _normalize_creative_config(creative_config)
    scene = ACTION_SCENES[config["background"]]
    placements = config["placements"]
    sizes = [round(700 * placement["scale"]) for placement in placements]
    # 前端使用百分比的 left/bottom，这里换算为 1920x1080 合成坐标。
    positions = [
        (round(1920 * placement["x"] / 100), round(245 - placement["y"] * 8))
        for placement in placements
    ]
    output = run_dir / "final-studio.mp4"
    temporary = run_dir / "final-studio.rendering.mp4"
    temporary_manifest = temporary.with_suffix(".json")
    output_manifest = output.with_suffix(".json")
    try:
        rendered = compose_action_video(argparse.Namespace(
            run_dir=run_dir,
            action_root=PROJECT_ROOT / "assets" / "action",
            host_a_character=config["characters"][0],
            host_b_character=config["characters"][1],
            background=scene["background"],
            foreground=scene["foreground"],
            foreground_key_color=scene["foreground_key_color"],
            foreground_key_similarity=.18,
            foreground_key_blend=.04,
            output=temporary,
            subtitles=True,
            subtitle_script=None,
            subtitle_srt=None,
            subtitle_font=DEFAULT_SUBTITLE_FONT,
            subtitle_font_size=48,
            subtitle_max_chars=22,
            subtitle_margin_bottom=150,
            audio_speed=1.0,
            min_action_speed=.85,
            max_action_speed=1.2,
            fps=24,
            host_a_size=sizes[0],
            host_b_size=sizes[1],
            host_a_x=positions[0][0],
            host_a_y=positions[0][1],
            host_b_x=positions[1][0],
            host_b_y=positions[1][1],
            host_b_dialogue_scale=1.0,
            host_b_dialogue_offset_x=0,
            host_b_dialogue_offset_y=0,
            crf=18,
            preset="medium",
            progress_callback=progress_callback,
        ))
        rendered.replace(output)
        if temporary_manifest.is_file():
            temporary_manifest.replace(output_manifest)
        return output
    finally:
        # FFmpeg 失败时只清理临时半成品，绝不覆盖已有的可播放视频。
        temporary.unlink(missing_ok=True)
        temporary_manifest.unlink(missing_ok=True)


def _safe_media_path(raw_path: str) -> Path | None:
    relative = unquote(raw_path.removeprefix("/mvp-media/"))
    candidate = (MVP_ROOT / relative).resolve()
    if MVP_ROOT not in candidate.parents or not candidate.is_file():
        return None
    return candidate


def _media_url(path: Path) -> str:
    return f"/mvp-media/{path.resolve().relative_to(MVP_ROOT).as_posix()}"


def _is_playable_video(path: Path | None) -> bool:
    if path is None or not path.is_file() or path.stat().st_size < 10_000:
        return False
    try:
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1", str(path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return probe.returncode == 0 and float(probe.stdout.strip()) > 0
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def _existing_video_path(job: dict, run_dir: Path) -> Path | None:
    raw_url = job.get("video_url")
    if isinstance(raw_url, str):
        path = _safe_media_path(raw_url)
        if _is_playable_video(path):
            return path
    for name in ("final-studio.mp4", "final.mp4"):
        path = run_dir / name
        if _is_playable_video(path):
            return path
    return None


def _sync_edited_script(job: dict, run_dir: Path, raw_episode) -> bool:
    """校验并保存前端编辑文本；返回脚本内容是否发生变化。"""
    if raw_episode is None:
        return False
    if not isinstance(raw_episode, dict) or not isinstance(
        raw_episode.get("turns"), list
    ):
        raise ValueError("修改后的脚本格式无效")

    current_episode = job.get("episode")
    if not isinstance(current_episode, dict):
        script_path = run_dir / "script.json"
        try:
            current_episode = json.loads(script_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("当前任务没有可编辑的原始脚本") from error
    current_turns = current_episode.get("turns")
    edited_turns = raw_episode["turns"]
    if not isinstance(current_turns, list) or len(edited_turns) != len(current_turns):
        raise ValueError("修改后的对白数量必须与已生成的音频切片一致")

    normalized_turns = []
    for index, (raw_turn, current_turn) in enumerate(
        zip(edited_turns, current_turns)
    ):
        if not isinstance(raw_turn, dict) or not isinstance(current_turn, dict):
            raise ValueError(f"第 {index + 1} 条对白格式无效")
        speaker = str(raw_turn.get("speaker", "")).strip()
        expected_speaker = str(current_turn.get("speaker", "")).strip()
        text = str(raw_turn.get("text", "")).strip()
        if speaker != expected_speaker:
            raise ValueError(
                f"第 {index + 1} 条对白说话人不能修改，否则会与音频错位"
            )
        if not text or len(text) > 2000:
            raise ValueError(f"第 {index + 1} 条对白文本不能为空且不能超过 2000 字")
        normalized_turns.append({"speaker": speaker, "text": text})

    normalized = {
        "topic": str(
            raw_episode.get("topic") or current_episode.get("topic") or ""
        ).strip()[:200],
        "turns": normalized_turns,
    }
    current_normalized = {
        "topic": str(current_episode.get("topic", "")).strip()[:200],
        "turns": [
            {
                "speaker": str(turn.get("speaker", "")).strip(),
                "text": str(turn.get("text", "")).strip(),
            }
            for turn in current_turns
            if isinstance(turn, dict)
        ],
    }
    changed = normalized != current_normalized
    if not changed:
        return False

    script_path = run_dir / "script.json"
    temporary = script_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(script_path)
    updated_clips = []
    for index, clip in enumerate(job.get("clips", [])):
        if not isinstance(clip, dict):
            continue
        updated_clip = dict(clip)
        if index < len(normalized_turns):
            updated_clip["text"] = normalized_turns[index]["text"]
        updated_clips.append(updated_clip)
    _update_job(
        str(job["id"]),
        episode=normalized,
        clips=updated_clips,
        video_url=None,
        subtitle_script_synced=True,
    )
    return True


def _save_jobs_locked() -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    records = sorted(
        JOBS.values(),
        key=lambda item: str(item.get("updated_at", "")),
        reverse=True,
    )[:200]
    temporary = HISTORY_PATH.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(HISTORY_PATH)


def _store_job(job: dict) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    job.setdefault("created_at", now)
    job["updated_at"] = now
    with JOBS_LOCK:
        JOBS[job["id"]] = job
        _save_jobs_locked()


def _update_job(job_id: str, **changes) -> None:
    with JOBS_LOCK:
        changes["updated_at"] = datetime.now().isoformat(timespec="seconds")
        JOBS[job_id].update(changes)
        _save_jobs_locked()


def _load_job_history() -> None:
    records = []
    if HISTORY_PATH.is_file():
        try:
            loaded = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
            records = loaded if isinstance(loaded, list) else []
        except (OSError, json.JSONDecodeError):
            records = []
    for record in records[:200]:
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            continue
        if record.get("video_url") and not _is_playable_video(
            _safe_media_path(str(record["video_url"]))
        ):
            record.pop("video_url", None)
        if record.get("status") in {"queued", "running"}:
            record.update({
                "status": "failed",
                "stage": "interrupted",
                "error": "任务因服务重启而中断，可从历史记录重新发起",
            })
        JOBS[record["id"]] = record
    completed_dirs = sorted(
        (path.parent for path in OUTPUT_ROOT.glob("*/final.mp3")),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[:200]
    known_dirs = {
        str(Path(job["run_dir"]).resolve())
        for job in JOBS.values()
        if job.get("run_dir")
    }
    for run_dir in completed_dirs:
        if str(run_dir.resolve()) in known_dirs:
            continue
        script_path = run_dir / "script.json"
        try:
            episode = (
                json.loads(script_path.read_text(encoding="utf-8"))
                if script_path.is_file()
                else None
            )
        except (OSError, json.JSONDecodeError):
            episode = None
        turns = episode.get("turns", []) if isinstance(episode, dict) else []
        clips = []
        for index, clip_path in enumerate(sorted((run_dir / "clips").glob("*.mp3"))):
            turn = turns[index] if index < len(turns) and isinstance(turns[index], dict) else {}
            clips.append({
                "index": index,
                "speaker": str(turn.get("speaker", "")),
                "text": str(turn.get("text", "")),
                "audio_url": _media_url(clip_path),
            })
        manifest = {}
        manifest_path = run_dir / "podcast-result.json"
        if manifest_path.is_file():
            try:
                loaded_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest = loaded_manifest if isinstance(loaded_manifest, dict) else {}
            except (OSError, json.JSONDecodeError):
                pass
        source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
        updated_at = datetime.fromtimestamp(run_dir.stat().st_mtime).isoformat(timespec="seconds")
        job_id = "archive-" + hashlib.sha256(str(run_dir).encode("utf-8")).hexdigest()[:12]
        archived = {
            "id": job_id,
            "kind": "document-podcast" if source else "topic-podcast",
            "status": "complete",
            "stage": "complete",
            "topic": episode.get("topic", run_dir.name) if isinstance(episode, dict) else run_dir.name,
            "episode": episode,
            "clips": clips,
            "audio_url": _media_url(run_dir / "final.mp3"),
            "script_url": _media_url(script_path) if script_path.is_file() else None,
            "provider_audio_url": manifest.get("provider_audio_url"),
            "source_type": source.get("type"),
            "input_url": source.get("url"),
            "file_name": source.get("file_name"),
            "run_dir": str(run_dir),
            "completed": len(clips),
            "total": len(clips),
            "created_at": updated_at,
            "updated_at": updated_at,
        }
        for video_name in ("final-studio.mp4", "final.mp4"):
            video_path = run_dir / video_name
            if _is_playable_video(video_path):
                archived["video_url"] = _media_url(video_path)
                break
        JOBS[job_id] = archived
    _save_jobs_locked()


def _request_fingerprint(payload: dict) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _find_completed_job(fingerprint: str) -> dict | None:
    with JOBS_LOCK:
        matches = [
            job for job in JOBS.values()
            if job.get("fingerprint") == fingerprint
            and job.get("status") == "complete"
            and isinstance(job.get("audio_url"), str)
            and _safe_media_path(job["audio_url"]) is not None
        ]
        if not matches:
            return None
        return max(matches, key=lambda item: str(item.get("updated_at", ""))).copy()


def _live_progress(job_id: str, topic: str, payload: dict) -> None:
    changes = dict(payload)
    turns = changes.pop("turns", None)
    raw_clips = changes.pop("clips", None)
    if isinstance(turns, list):
        changes["episode"] = {"topic": topic[:200], "turns": turns}
    if isinstance(raw_clips, list):
        changes["clips"] = [
            {
                "index": int(clip.get("index", index)),
                "speaker": str(clip.get("speaker", "")),
                "text": str(clip.get("text", "")),
                "audio_url": _media_url(Path(str(clip["path"]))),
            }
            for index, clip in enumerate(raw_clips)
            if isinstance(clip, dict) and clip.get("path")
        ]
    _update_job(job_id, status="running", **changes)


def _generate_audio(
    job_id: str,
    prompt: str,
    target_minutes: float,
    character_set: str,
    custom_voices: dict[str, str] | None,
    speaker_ids: list[str],
    episode: Episode | None,
) -> None:
    def progress(payload: dict) -> None:
        _live_progress(job_id, prompt, payload)

    try:
        final_path = asyncio.run(
            run(
                prompt,
                target_minutes,
                on_progress=progress,
                character_set=character_set,
                custom_voices=custom_voices,
                speaker_ids=speaker_ids,
                episode=episode,
            )
        )
        _complete_audio_job(job_id, final_path)
    except Exception as error:
        _update_job(job_id, status="failed", stage="failed", error=str(error))


def _complete_audio_job(job_id: str, final_path: Path) -> None:
    script_path = final_path.parent / "script.json"
    episode_payload = None
    if script_path.is_file():
        episode_payload = json.loads(script_path.read_text(encoding="utf-8"))
    turns = (
        episode_payload.get("turns", [])
        if isinstance(episode_payload, dict)
        else []
    )
    clips = []
    for index, clip_path in enumerate(
        sorted((final_path.parent / "clips").glob("*.mp3"))
    ):
        turn = turns[index] if index < len(turns) else {}
        clips.append({
            "index": index,
            "speaker": turn.get("speaker", ""),
            "text": turn.get("text", ""),
            "audio_url": _media_url(clip_path),
        })
    provider_audio_url = None
    manifest_path = final_path.parent / "podcast-result.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(manifest.get("provider_audio_url"), str):
            provider_audio_url = manifest["provider_audio_url"]
    _update_job(
        job_id,
        status="complete",
        stage="complete",
        audio_url=_media_url(final_path),
        script_url=_media_url(script_path),
        episode=episode_payload,
        clips=clips,
        provider_audio_url=provider_audio_url,
        run_dir=str(final_path.parent),
    )


def _generate_document(
    job_id: str,
    input_text: str,
    input_url: str,
    topic: str,
    file_name: str = "",
    file_base64: str = "",
    creative_config: dict | None = None,
) -> None:
    def progress(payload: dict) -> None:
        _live_progress(job_id, topic, payload)

    try:
        if file_name:
            input_text = _extract_uploaded_document(file_name, file_base64)
        app_id = os.getenv("VOLCENGINE_SPEECH_APP_ID", "").strip()
        access_key = os.getenv("VOLCENGINE_SPEECH_ACCESS_KEY", "").strip()
        if not app_id or not access_key:
            raise RuntimeError("PodcastTTS App ID 或 Access Token 未配置")
        run_dir = OUTPUT_ROOT / (
            datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{job_id[:4]}"
        )
        result = asyncio.run(
            VolcenginePodcastTTS(
                app_id,
                access_key,
                timeout=float(os.getenv("BYTEDANCE_TTS_TIMEOUT", "300")),
            ).generate(
                None,
                run_dir,
                on_progress=progress,
                input_text=input_text or None,
                input_url=input_url or None,
                topic=topic,
                speakers=_speaker_ids_for_config(
                    _normalize_creative_config(creative_config)
                ),
            )
        )
        (run_dir / "podcast-result.json").write_text(
            json.dumps({
                "task_id": result.task_id,
                "provider_audio_url": result.provider_audio_url,
                "clips": result.clips,
                "source": {
                    "type": "file" if file_name else "url" if input_url else "text",
                    "url": input_url or None,
                    "file_name": file_name or None,
                },
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _complete_audio_job(job_id, result.final_path)
    except Exception as error:
        _update_job(job_id, status="failed", stage="failed", error=str(error))


def _extract_uploaded_document(file_name: str, encoded: str) -> str:
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("上传文件不是有效的 Base64 数据") from error
    if not raw:
        raise ValueError("上传文件为空")
    if len(raw) > 20 * 1024 * 1024:
        raise ValueError("上传文件不能超过 20MB")
    suffix = Path(file_name).suffix.lower()
    text: str
    if suffix in {".txt", ".md", ".markdown", ".json", ".csv"}:
        text = raw.decode("utf-8-sig", errors="replace")
    elif suffix in {".html", ".htm"}:
        decoded = raw.decode("utf-8-sig", errors="replace")
        decoded = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", decoded)
        text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", decoded))
    elif suffix == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                document_xml = archive.read("word/document.xml").decode("utf-8")
        except (KeyError, zipfile.BadZipFile, UnicodeDecodeError) as error:
            raise ValueError("DOCX 文件损坏或格式不受支持") from error
        document_xml = re.sub(r"</w:p>", "\n", document_xml)
        document_xml = re.sub(r"<w:tab[^>]*/>", "\t", document_xml)
        text = html.unescape(re.sub(r"<[^>]+>", "", document_xml))
    elif suffix == ".pdf":
        try:
            reader = PdfReader(io.BytesIO(raw))
            if len(reader.pages) > 500:
                raise ValueError("PDF 不能超过 500 页")
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except ValueError:
            raise
        except Exception as error:
            raise ValueError("PDF 文件损坏、加密或无法提取文字") from error
    else:
        raise ValueError(
            "仅支持 TXT、Markdown、HTML、JSON、CSV、DOCX 和 PDF 文件"
        )
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise ValueError("文件中没有可提取的文本；扫描版 PDF 请先进行 OCR")
    if len(text) > 200_000:
        raise ValueError("文件提取文本不能超过 200000 字符")
    return text


def _generate_script(job_id: str, prompt: str, target_minutes: float) -> None:
    _update_job(job_id, status="running", stage="script")

    def progress(completed: int, total: int) -> None:
        _update_job(
            job_id,
            status="running",
            stage="script",
            completed=completed,
            total=total,
        )

    try:
        generator = _pick_generator()
        episode = generator.generate(prompt, target_minutes, on_progress=progress)
    except Exception as error:
        _update_job(
            job_id,
            status="failed",
            stage="script_failed",
            error=f"OpenNotebook 脚本生成失败：{error}",
        )
        return
    try:
        _update_job(
            job_id,
            status="complete",
            stage="script_complete",
            completed=JOBS[job_id].get("total", 1) or 1,
            episode=asdict(episode),
            warning=None,
        )
    except Exception as error:
        _update_job(job_id, status="failed", stage="script_failed", error=str(error))


def _generate_video(
    job_id: str,
    run_dir: Path,
    mode: str,
    character_set: str,
    creative_config: dict | None = None,
) -> None:
    try:
        _update_job(
            job_id, status="queued", stage="video_waiting", completed=0, total=2,
            error=None,
        )
        print(f"[视频任务 {job_id}] 正在等待渲染资源", flush=True)
        with VIDEO_RENDER_LOCK:
            print(f"[视频任务 {job_id}] 已启动，工程目录: {run_dir}", flush=True)
            _update_job(
                job_id, status="running", stage="video", completed=1, total=2,
                error=None,
            )
            if mode == "action":
                final_path = _compose_action_episode_video(
                    run_dir,
                    creative_config or {},
                    lambda completed, total, phase: _update_job(
                        job_id,
                        status="running",
                        stage=f"video_{phase}",
                        completed=completed,
                        total=total,
                    ),
                )
            elif mode == "fast":
                final_path = compose_fast_episode_video(
                    run_dir, character_set=character_set
                )
            else:
                final_path = asyncio.run(compose_episode_video(run_dir))
        _update_job(
            job_id,
            status="complete",
            stage="video_complete",
            completed=2,
            total=2,
            video_url=_media_url(final_path),
        )
        print(f"[视频任务 {job_id}] 已完成: {final_path}", flush=True)
    except Exception as error:
        _update_job(job_id, status="failed", stage="video_failed", error=str(error))
        print(f"[视频任务 {job_id}] 失败: {error}", flush=True)


def _generate_character_track(job_id: str, run_dir: Path, character_set: str) -> None:
    try:
        _update_job(job_id, status="running", stage="character_track", error=None)
        track_path = render_character_track(run_dir, character_set=character_set)
        manifest_path = track_path.parent / f"{character_set}-manifest.json"
        _update_job(
            job_id, status="complete", stage="character_track_complete",
            character_track_url=_media_url(track_path),
            character_manifest_url=_media_url(manifest_path),
        )
    except Exception as error:
        _update_job(
            job_id, status="failed", stage="character_track_failed", error=str(error),
        )


def _public_job(job: dict) -> dict:
    return {
        key: value for key, value in job.items()
        if key not in {"run_dir", "fingerprint"}
    }


_load_job_history()


class Handler(BaseHTTPRequestHandler):
    server_version = "BlabberMVP/1.0"

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/mvp/config":
            self._json(200, _public_environment())
            return

        if path == "/api/mvp/health":
            demo_dir = OUTPUT_ROOT / "20260724-115351"
            notebook_url = os.getenv("OPEN_NOTEBOOK_URL", "").strip()
            self._json(200, {
                "ok": True,
                "features": ["script", "podcast-document", "tts", "image-voice", "audio", "character-track", "fast-video", "action-video", "video-generate", "video-demo"],
                "script_generator": "open-notebook" if notebook_url else "mock",
                "open_notebook_configured": bool(notebook_url),
                "tts_engine": (
                    "volcengine-podcast-tts"
                    if (
                        os.getenv("VOLCENGINE_SPEECH_APP_ID", "").strip()
                        and os.getenv("VOLCENGINE_SPEECH_ACCESS_KEY", "").strip()
                    )
                    else "edge-tts"
                ),
                "character_sets": sorted(CHARACTER_SETS),
                "default_character_set": DEFAULT_CHARACTER_SET,
                "image_voice_configured": bool(
                    os.getenv("VISION_API_KEY", "").strip()
                    and os.getenv("VISION_MODEL_ID", "").strip()
                ),
                "seedream_configured": bool(
                    os.getenv("ARK_API_KEY", "").strip()
                ),
                "video_runtime_ready": (VENDOR_DIR / "inference.py").is_file() and CHECKPOINT_PATH.is_file(),
                "demo": {
                    "topic": "宠物猫",
                    "audio_url": _media_url(demo_dir / "final.mp3"),
                    "video_url": _media_url(demo_dir / "final.mp4"),
                    "script_url": _media_url(demo_dir / "script.json"),
                },
            })
            return

        if path == "/api/mvp/history":
            with JOBS_LOCK:
                items = sorted(
                    (
                        _public_job(job) for job in JOBS.values()
                        if job.get("kind") != "script"
                    ),
                    key=lambda item: str(item.get("updated_at", "")),
                    reverse=True,
                )[:50]
            self._json(200, {"items": items})
            return

        if path.startswith("/api/mvp/jobs/") and path.endswith("/events"):
            job_id = path.split("/")[-2]
            with JOBS_LOCK:
                exists = job_id in JOBS
            if not exists:
                self._json(404, {"error": "任务不存在"})
                return
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            previous = ""
            try:
                while True:
                    with JOBS_LOCK:
                        job = JOBS.get(job_id)
                        payload = _public_job(job) if job else None
                    if payload is None:
                        break
                    serialized = json.dumps(payload, ensure_ascii=False)
                    if serialized != previous:
                        self.wfile.write(f"data: {serialized}\n\n".encode("utf-8"))
                        self.wfile.flush()
                        previous = serialized
                    if payload.get("status") in {"complete", "failed"}:
                        break
                    time.sleep(.25)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        if path.startswith("/api/mvp/jobs/"):
            job_id = path.rsplit("/", 1)[-1]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                payload = _public_job(job) if job else None
            self._json(200 if payload else 404, payload or {"error": "任务不存在"})
            return

        if path.startswith("/mvp-media/"):
            media_path = _safe_media_path(path)
            if media_path is None:
                self._json(404, {"error": "文件不存在"})
                return
            size = media_path.stat().st_size
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", mimetypes.guess_type(media_path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.end_headers()
            try:
                with media_path.open("rb") as file:
                    while chunk := file.read(1024 * 1024):
                        self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        self._json(404, {"error": "接口不存在"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            body = self._body()
        except (json.JSONDecodeError, ValueError):
            self._json(400, {"error": "请求内容不是有效 JSON"})
            return

        if path == "/api/mvp/config":
            raw_values = body.get("values")
            raw_clear = body.get("clear", [])
            if not isinstance(raw_values, dict) or not isinstance(raw_clear, list):
                self._json(400, {"error": "配置格式无效"})
                return
            unknown = (set(raw_values) | set(raw_clear)) - set(ENV_FIELD_BY_KEY)
            if unknown:
                self._json(400, {"error": f"不支持的配置项：{', '.join(sorted(unknown))}"})
                return
            values = {
                field["key"]: os.getenv(field["key"], "").strip()
                for field in ENV_CONFIG_FIELDS
                if os.getenv(field["key"], "").strip()
            }
            previous_effective_values = {
                field["key"]: os.getenv(
                    field["key"], field.get("default", "")
                ).strip()
                for field in ENV_CONFIG_FIELDS
            }
            for key, raw_value in raw_values.items():
                value = str(raw_value).strip()
                if ENV_FIELD_BY_KEY[key].get("secret") and not value:
                    continue
                if value:
                    values[key] = value
                else:
                    values.pop(key, None)
            for key in raw_clear:
                values.pop(str(key), None)
            try:
                _validate_environment(values)
                _write_environment(values)
            except (OSError, ValueError) as error:
                self._json(400, {"error": str(error)})
                return
            for key in ENV_FIELD_BY_KEY:
                if key in values:
                    os.environ[key] = values[key]
                else:
                    os.environ.pop(key, None)
            response = _public_environment()
            response["saved"] = True
            response["restart_required"] = any(
                field.get("restart")
                and previous_effective_values[field["key"]]
                != values.get(field["key"], field.get("default", ""))
                for field in ENV_CONFIG_FIELDS
            )
            self._json(200, response)
            return

        if path == "/api/mvp/analyze-character":
            try:
                result = analyze_character_voice(
                    str(body.get("image", "")),
                    str(body.get("speaker", "")),
                )
            except (ValueError, RuntimeError) as error:
                self._json(400, {"error": str(error)})
                return
            self._json(200, result)
            return

        if path == "/api/mvp/composite-scene":
            character_set = str(
                body.get("character_set", DEFAULT_CHARACTER_SET)
            ).strip()
            prompt = str(body.get("prompt", "")).strip() or None
            try:
                output = generate_composite_scene(character_set, prompt)
            except (ValueError, RuntimeError, Exception) as error:
                self._json(502, {"error": str(error)})
                return
            self._json(200, {
                "character_set": character_set,
                "image_url": _media_url(output),
            })
            return

        if path.startswith("/api/mvp/jobs/") and path.endswith("/character-track"):
            job_id = path.split("/")[-2]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                run_dir = Path(job["run_dir"]) if job and job.get("run_dir") else None
            if job is None:
                self._json(404, {"error": "任务不存在"})
                return
            if run_dir is None or not (run_dir / "final.mp3").is_file():
                self._json(409, {"error": "请先完成音频生成"})
                return
            character_set = str(job.get("character_set", DEFAULT_CHARACTER_SET))
            _update_job(job_id, status="queued", stage="character_track_queued", error=None)
            threading.Thread(
                target=_generate_character_track,
                args=(job_id, run_dir, character_set),
                daemon=True,
            ).start()
            with JOBS_LOCK:
                payload = _public_job(JOBS[job_id])
            self._json(202, payload)
            return

        if path.startswith("/api/mvp/jobs/") and path.endswith("/video"):
            job_id = path.split("/")[-2]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                run_dir = Path(job["run_dir"]) if job and job.get("run_dir") else None
            if job is None:
                self._json(404, {"error": "任务不存在"})
                return
            if run_dir is None or not (run_dir / "final.mp3").is_file():
                self._json(409, {"error": "请先完成音频生成"})
                return
            if (
                str(job.get("stage", "")).startswith("video")
                and job.get("status") in {"queued", "running"}
            ):
                self._json(409, {"error": "该任务的视频已在排队或生成中"})
                return
            try:
                script_changed = _sync_edited_script(
                    job, run_dir, body.get("episode")
                )
            except (OSError, ValueError) as error:
                self._json(400, {"error": str(error)})
                return
            existing_video = _existing_video_path(job, run_dir)
            if (
                existing_video is not None
                and not bool(body.get("force"))
                and not script_changed
            ):
                _update_job(
                    job_id,
                    status="complete",
                    stage="video_complete",
                    completed=2,
                    total=2,
                    video_url=_media_url(existing_video),
                    error=None,
                )
                with JOBS_LOCK:
                    payload = _public_job(JOBS[job_id])
                payload["reused"] = True
                self._json(200, payload)
                return
            mode = str(body.get("mode", "fast")).strip()
            if mode not in {"fast", "wav2lip", "action"}:
                self._json(400, {"error": "未知的视频生成模式"})
                return
            if mode == "wav2lip" and (
                not (VENDOR_DIR / "inference.py").is_file()
                or not CHECKPOINT_PATH.is_file()
            ):
                self._json(503, {"error": "Wav2Lip 推理脚本或模型权重不可用"})
                return
            character_set = str(
                job.get("character_set", DEFAULT_CHARACTER_SET)
            )
            creative_config = _normalize_creative_config(
                body.get("creative_config", job.get("creative_config"))
            )
            _update_job(
                job_id,
                status="queued",
                stage="video_queued",
                completed=0,
                total=2,
                creative_config=creative_config,
                video_url=None if script_changed or bool(body.get("force")) else job.get("video_url"),
                error=None,
            )
            print(f"[视频任务 {job_id}] 已进入队列（{mode}）", flush=True)
            threading.Thread(
                target=_generate_video,
                args=(job_id, run_dir, mode, character_set, creative_config),
                daemon=True,
            ).start()
            with JOBS_LOCK:
                payload = _public_job(JOBS[job_id])
            self._json(202, payload)
            return

        if path == "/api/mvp/document-jobs":
            creative_config = _normalize_creative_config(
                body.get("creative_config")
            )
            raw_input_text = body.get("input_text", "")
            raw_input_url = body.get("input_url", "")
            raw_topic = body.get("topic", "")
            raw_file_name = body.get("file_name", "")
            raw_file_base64 = body.get("file_base64", "")
            if not all(
                isinstance(value, str)
                for value in (
                    raw_input_text,
                    raw_input_url,
                    raw_topic,
                    raw_file_name,
                    raw_file_base64,
                )
            ):
                self._json(400, {"error": "文档参数必须是字符串"})
                return
            input_text = raw_input_text.strip()
            input_url = raw_input_url.strip()
            topic = raw_topic.strip()[:200]
            file_name = Path(raw_file_name.strip()).name[:255]
            file_base64 = raw_file_base64.strip()
            source_count = sum(bool(value) for value in (
                input_text,
                input_url,
                file_name and file_base64,
            ))
            if bool(file_name) != bool(file_base64):
                self._json(400, {
                    "error": "file_name 和 file_base64 必须同时提供",
                })
                return
            if source_count != 1:
                self._json(400, {
                    "error": "input_text、input_url 和上传文件必须且只能提供一个",
                })
                return
            if len(input_text) > 200_000:
                self._json(400, {"error": "input_text 不能超过 200000 字符"})
                return
            if len(input_url) > 4096:
                self._json(400, {"error": "input_url 过长"})
                return
            if len(file_base64) > 28 * 1024 * 1024:
                self._json(400, {"error": "上传文件不能超过 20MB"})
                return
            if input_url and urlparse(input_url).scheme not in {"http", "https"}:
                self._json(400, {"error": "input_url 必须是 http 或 https 地址"})
                return
            if not topic:
                topic = (
                    Path(file_name).stem[:200]
                    if file_name
                    else urlparse(input_url).netloc if input_url else "文档播客"
                )
            source_signature = (
                {"type": "file", "sha256": hashlib.sha256(file_base64.encode("ascii")).hexdigest()}
                if file_name
                else {"type": "url", "value": input_url}
                if input_url
                else {"type": "text", "value": input_text}
            )
            fingerprint = _request_fingerprint({
                "kind": "document-podcast",
                "source": source_signature,
                "topic": topic,
                "speakers": _speaker_ids_for_config(creative_config),
            })
            cached_job = _find_completed_job(fingerprint)
            if cached_job is not None:
                payload = _public_job(cached_job)
                payload["reused"] = True
                self._json(200, payload)
                return
            job_id = uuid.uuid4().hex[:12]
            job = {
                "id": job_id,
                "kind": "document-podcast",
                "status": "queued",
                "stage": "queued",
                "topic": topic,
                "source_type": "file" if file_name else "url" if input_url else "text",
                "input_url": input_url or None,
                "file_name": file_name or None,
                "creative_config": creative_config,
                "fingerprint": fingerprint,
                "completed": 0,
                "total": 0,
            }
            _store_job(job)
            threading.Thread(
                target=_generate_document,
                args=(
                    job_id,
                    input_text,
                    input_url,
                    topic,
                    file_name,
                    file_base64,
                    creative_config,
                ),
                daemon=True,
            ).start()
            self._json(202, _public_job(job))
            return

        prompt = str(body.get("prompt", "")).strip()
        try:
            target_minutes = float(body.get("target_minutes", 2))
        except (TypeError, ValueError):
            target_minutes = 2
        character_set = str(
            body.get("character_set", DEFAULT_CHARACTER_SET)
        ).strip()
        raw_custom_voices = body.get("custom_voices")
        custom_voices = None
        if isinstance(raw_custom_voices, dict):
            custom_voices = {
                speaker: str(raw_custom_voices.get(speaker, "")).strip()[:300]
                for speaker in ("HostA", "HostB")
                if str(raw_custom_voices.get(speaker, "")).strip()
            }
        episode = None
        raw_episode = body.get("episode")
        if isinstance(raw_episode, dict):
            raw_turns = raw_episode.get("turns")
            if not isinstance(raw_turns, list) or not 1 <= len(raw_turns) <= 500:
                self._json(400, {"error": "episode.turns 格式无效"})
                return
            turns = []
            for raw_turn in raw_turns:
                if not isinstance(raw_turn, dict):
                    self._json(400, {"error": "对白格式无效"})
                    return
                speaker = str(raw_turn.get("speaker", "")).strip()
                text = str(raw_turn.get("text", "")).strip()
                if speaker not in {"HostA", "HostB"} or not text or len(text) > 2000:
                    self._json(400, {"error": "对白说话人或文本无效"})
                    return
                turns.append(Turn(speaker=speaker, text=text))
            episode = Episode(
                topic=str(raw_episode.get("topic", "")).strip()[:200] or prompt,
                turns=turns,
            )

        if not prompt:
            self._json(400, {"error": "请先描述播客主题"})
            return
        if not 0.5 <= target_minutes <= 35:
            self._json(400, {"error": "目标时长需在 0.5–35 分钟之间"})
            return
        if character_set not in CHARACTER_SETS:
            self._json(400, {"error": "未知的人物组合"})
            return

        if path == "/api/mvp/script":
            try:
                episode = _pick_generator().generate(prompt, target_minutes)
            except Exception as exc:
                print(f"[MVP API] 脚本生成失败: {exc}")
                self._json(502, {"error": f"脚本生成失败：{exc}"})
                return
            self._json(200, asdict(episode))
            return

        if path == "/api/mvp/script-jobs":
            job_id = uuid.uuid4().hex[:12]
            job = {
                "id": job_id,
                "kind": "script",
                "status": "queued",
                "stage": "queued",
                "prompt": prompt,
                "target_minutes": target_minutes,
                "completed": 0,
                "total": max(
                    1,
                    ceil(
                        target_minutes
                        / float(os.getenv("OPEN_NOTEBOOK_CHUNK_MINUTES", "2"))
                    ),
                ),
            }
            _store_job(job)
            threading.Thread(
                target=_generate_script,
                args=(job_id, prompt, target_minutes),
                daemon=True,
            ).start()
            self._json(202, _public_job(job))
            return

        if path == "/api/mvp/jobs":
            creative_config = _normalize_creative_config(
                body.get("creative_config")
            )
            resolved_voices = dict(custom_voices or {})
            for speaker, character in zip(
                ("HostA", "HostB"), creative_config["characters"]
            ):
                default_voice_prompt = ACTION_CHARACTER_VOICE_PROMPTS.get(character)
                if default_voice_prompt:
                    # Always derive the voice prompt from the final character
                    # selection. This also replaces stale speaker IDs sent by an
                    # older frontend cached in the browser.
                    resolved_voices[speaker] = default_voice_prompt
            custom_voices = resolved_voices or None
            fingerprint = _request_fingerprint({
                "kind": "topic-podcast",
                "prompt": prompt,
                "target_minutes": target_minutes,
                "character_set": character_set,
                "voices": custom_voices,
                "speakers": _speaker_ids_for_config(creative_config),
                "episode": asdict(episode) if episode else None,
            })
            cached_job = _find_completed_job(fingerprint)
            if cached_job is not None:
                payload = _public_job(cached_job)
                payload["reused"] = True
                self._json(200, payload)
                return
            job_id = uuid.uuid4().hex[:12]
            job = {
                "id": job_id,
                "kind": "topic-podcast",
                "status": "queued",
                "stage": "queued",
                "prompt": prompt,
                "topic": prompt[:200],
                "target_minutes": target_minutes,
                "character_set": character_set,
                "custom_voices": custom_voices,
                "creative_config": creative_config,
                "episode": asdict(episode) if episode else None,
                "fingerprint": fingerprint,
                "completed": 0,
                "total": 0,
                "skipped": 0,
            }
            _store_job(job)
            threading.Thread(
                target=_generate_audio,
                args=(
                    job_id,
                    prompt,
                    target_minutes,
                    character_set,
                    custom_voices,
                    _speaker_ids_for_config(creative_config),
                    episode,
                ),
                daemon=True,
            ).start()
            self._json(202, _public_job(job))
            return

        self._json(404, {"error": "接口不存在"})

    def log_message(self, format: str, *args) -> None:
        print(f"[MVP API] {self.address_string()} - {format % args}")


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Blabber MVP API: http://{HOST}:{PORT}")
    print("按 Ctrl+C 停止服务")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
