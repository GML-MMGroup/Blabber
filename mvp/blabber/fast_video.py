from __future__ import annotations

import math
import re
import subprocess
import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from pydub import AudioSegment

from blabber.compose import PAUSE_MS, load_dialogue_clip

FPS = 15
CANVAS_SIZE = (1024, 1024)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = PROJECT_ROOT / "assets"
CACHE_ROOT = Path(__file__).resolve().parent / "Avatar" / "fast_cache"
_TURN_FILENAME_RE = re.compile(r"^(\d+)_(.+)\.mp3$")


@dataclass(frozen=True)
class CharacterSpec:
    image: str
    side: str
    eye_y: float
    eye_left_x: float
    eye_right_x: float
    mouth_x: float
    mouth_y: float


CHARACTER_SETS = {
    "cartoon": {
        "background": "scene2.png",
        "HostA": CharacterSpec("cartoon-male.png", "left", .340, .405, .585, .50, .423),
        "HostB": CharacterSpec("cartoon-female.png", "right", .432, .400, .580, .50, .515),
    },
    "professional": {
        "background": "scene1.png",
        "HostA": CharacterSpec("profes-male.png", "left", .297, .405, .590, .50, .390),
        "HostB": CharacterSpec("profes-female.png", "right", .273, .405, .590, .50, .360),
    },
}


def _turn_files(clips_dir: Path) -> list[tuple[int, str, Path]]:
    turns = []
    for path in clips_dir.glob("*.mp3"):
        match = _TURN_FILENAME_RE.match(path.name)
        if match and path.stat().st_size:
            turns.append((int(match.group(1)), match.group(2), path))
    return sorted(turns, key=lambda item: item[0])


def _border_connected_white_to_alpha(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = np.asarray(rgba).copy()
    white = np.all(pixels[:, :, :3] >= 242, axis=2).astype(np.uint8) * 255
    h, w = white.shape
    connected = white.copy()
    for corner in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if connected[corner[1], corner[0]] == 255:
            cv2.floodFill(connected, None, corner, 128)
    alpha = Image.fromarray(np.where(connected == 128, 0, 255).astype(np.uint8))
    rgba.putalpha(alpha.filter(ImageFilter.GaussianBlur(1.2)))
    return rgba


def _load_sprite(spec: CharacterSpec, height: int = 770) -> Image.Image:
    source = ASSET_ROOT / spec.image
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    cached = CACHE_ROOT / f"{source.stem}-v2-{height}.png"
    if not cached.is_file() or cached.stat().st_mtime < source.stat().st_mtime:
        cutout = _border_connected_white_to_alpha(Image.open(source))
        width = round(cutout.width * height / cutout.height)
        cutout.resize((width, height), Image.Resampling.LANCZOS).save(cached)
    return Image.open(cached).convert("RGBA")


def _audio_level(audio: AudioSegment, position_ms: int) -> float:
    sample = audio[max(0, position_ms - 35):position_ms + 35]
    if not sample or sample.dBFS == float("-inf"):
        return 0.0
    return max(0.0, min(1.0, (sample.dBFS + 42.0) / 30.0))


def _blink_amount(frame_index: int, speaker: str, fps: int) -> float:
    offset = 0 if speaker == "HostA" else round(1.7 * fps)
    cycle = round((4.3 if speaker == "HostA" else 5.1) * fps)
    phase = (frame_index + offset) % cycle
    if phase in (0, 3):
        return .55
    if phase in (1, 2):
        return 1.0
    return 0.0


def _animate_sprite(
    base: Image.Image,
    spec: CharacterSpec,
    mouth_level: float,
    blink: float,
) -> Image.Image:
    sprite = base.copy()
    draw = ImageDraw.Draw(sprite, "RGBA")
    w, h = sprite.size
    if blink:
        skin = sprite.getpixel((
            round(w * .5),
            min(h - 1, round(h * (spec.eye_y + .045))),
        ))
        skin = (*skin[:3], 250)
        eye_width = max(18, round(w * .075))
        eye_height = max(3, round(h * .006 * blink))
        for eye_x in (spec.eye_left_x, spec.eye_right_x):
            cx, cy = round(w * eye_x), round(h * spec.eye_y)
            draw.ellipse(
                (cx - eye_width, cy - eye_height, cx + eye_width, cy + eye_height),
                fill=skin,
            )
    if mouth_level > .08:
        cx, cy = round(w * spec.mouth_x), round(h * spec.mouth_y)
        mouth_width = max(24, round(w * (.050 + mouth_level * .018)))
        mouth_height = max(3, round(h * (.003 + mouth_level * .012)))
        draw.ellipse(
            (cx - mouth_width, cy - mouth_height, cx + mouth_width, cy + mouth_height),
            fill=(64, 24, 28, 238),
        )
        if mouth_level > .55:
            draw.arc(
                (cx - mouth_width + 4, cy - 1, cx + mouth_width - 4, cy + mouth_height),
                5, 175, fill=(244, 168, 160, 210), width=max(1, round(h * .002)),
            )
    return sprite


def _build_timeline(turns: list[tuple[int, str, Path]]) -> tuple[list[dict], int]:
    timeline = []
    cursor = 0
    for turn_index, (index, speaker, path) in enumerate(turns):
        audio = load_dialogue_clip(path)
        end = cursor + len(audio)
        timeline.append({
            "index": index, "speaker": speaker, "start": cursor,
            "end": end, "audio": audio,
        })
        cursor = end + (PAUSE_MS if turn_index < len(turns) - 1 else 0)
    return timeline, cursor


def _run_ffmpeg(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"ffmpeg 失败：{result.stderr[-3000:]}")


def render_character_track(
    run_dir: Path,
    character_set: str = "cartoon",
    out_path: Path | None = None,
    fps: int = FPS,
) -> Path:
    """Render reusable characters, motion and audio to an alpha WebM track."""
    selected = character_set if character_set in CHARACTER_SETS else "cartoon"
    config = CHARACTER_SETS[selected]
    turns = _turn_files(run_dir / "clips")
    if not turns:
        raise RuntimeError("没有可用于视频生成的 TTS 音频片段")
    sprites = {speaker: _load_sprite(config[speaker]) for speaker in ("HostA", "HostB")}
    timeline, duration_ms = _build_timeline(turns)
    track_dir = run_dir / "character_track"
    track_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_path or track_dir / f"{selected}-characters.webm"
    silent_path = track_dir / f"{selected}-characters-silent.webm"

    total_frames = max(1, math.ceil(duration_ms / 1000 * fps))
    encoder = subprocess.Popen([
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgba",
        "-s", f"{CANVAS_SIZE[0]}x{CANVAS_SIZE[1]}",
        "-r", str(fps), "-i", "-",
        "-an", "-c:v", "libvpx-vp9", "-deadline", "realtime",
        "-cpu-used", "5", "-crf", "31", "-b:v", "0",
        "-pix_fmt", "yuva420p", "-auto-alt-ref", "0",
        str(silent_path),
    ], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    if encoder.stdin is None:
        raise RuntimeError("无法启动透明角色动画编码器")
    timeline_index = 0
    smoothed_levels = {"HostA": 0.0, "HostB": 0.0}
    try:
        for frame_index in range(total_frames):
            time_ms = round(frame_index * 1000 / fps)
            while timeline_index + 1 < len(timeline) and time_ms >= timeline[timeline_index]["end"]:
                timeline_index += 1
            current = timeline[timeline_index]
            active_speaker = current["speaker"] if current["start"] <= time_ms < current["end"] else None
            level = (
                _audio_level(current["audio"], time_ms - current["start"])
                if active_speaker else 0.0
            )
            for speaker in smoothed_levels:
                target = level if speaker == active_speaker else 0.0
                factor = .48 if target > smoothed_levels[speaker] else .28
                smoothed_levels[speaker] += (target - smoothed_levels[speaker]) * factor
            frame = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
            for speaker in ("HostA", "HostB"):
                spec = config[speaker]
                breathing = math.sin(frame_index / fps * math.pi * 1.15 + (0 if speaker == "HostA" else 1.2))
                sway = math.sin(frame_index / fps * .85 + (0 if speaker == "HostA" else 2.0))
                scale = 1.0 + breathing * .006
                base = sprites[speaker]
                animated_base = base.resize(
                    (round(base.width * scale), round(base.height * scale)),
                    Image.Resampling.BICUBIC,
                )
                animated = _animate_sprite(
                    animated_base, spec, smoothed_levels[speaker],
                    _blink_amount(frame_index, speaker, fps),
                )
                x = (
                    12 + round(sway * 4) if spec.side == "left"
                    else CANVAS_SIZE[0] - animated.width - 12 + round(sway * 4)
                )
                y = CANVAS_SIZE[1] - animated.height + round(breathing * 3)
                frame.alpha_composite(animated, (x, y))
            encoder.stdin.write(frame.tobytes())
            if frame_index and frame_index % (fps * 10) == 0:
                print(f"[透明角色动画] {frame_index}/{total_frames} 帧", flush=True)
    finally:
        encoder.stdin.close()
    stderr = encoder.stderr.read().decode("utf-8", errors="replace") if encoder.stderr else ""
    if encoder.wait() != 0:
        raise RuntimeError(f"透明角色动画编码失败：{stderr[-3000:]}")

    _run_ffmpeg([
        "ffmpeg", "-y", "-c:v", "libvpx-vp9", "-i", str(silent_path),
        "-i", str(run_dir / "final.mp3"), "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "libopus", "-b:a", "128k", "-shortest", str(out_path),
    ])
    manifest = {
        "version": 1, "format": "webm-alpha", "character_set": selected,
        "width": CANVAS_SIZE[0], "height": CANVAS_SIZE[1], "fps": fps,
        "duration_ms": duration_ms, "audio_included": True,
        "transparent_background": True,
        "turns": [
            {"index": item["index"], "speaker": item["speaker"],
             "start_ms": item["start"], "end_ms": item["end"]}
            for item in timeline
        ],
    }
    (track_dir / f"{selected}-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return out_path


def compose_fast_episode_video(
    run_dir: Path,
    character_set: str = "cartoon",
    out_path: Path | None = None,
    fps: int = FPS,
) -> Path:
    selected = character_set if character_set in CHARACTER_SETS else "cartoon"
    config = CHARACTER_SETS[selected]
    track_path = run_dir / "character_track" / f"{selected}-characters.webm"
    if not track_path.is_file():
        render_character_track(run_dir, selected, track_path, fps)
    background_path = ASSET_ROOT / config["background"]
    out_path = out_path or run_dir / "final.mp4"
    _run_ffmpeg([
        "ffmpeg", "-y", "-loop", "1", "-i", str(background_path),
        "-c:v", "libvpx-vp9", "-i", str(track_path),
        "-filter_complex",
        f"[0:v]scale={CANVAS_SIZE[0]}:{CANVAS_SIZE[1]}[bg];[bg][1:v]overlay=0:0:format=auto[v]",
        "-map", "[v]", "-map", "1:a:0", "-c:v", "libx264",
        "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(out_path),
    ])
    return out_path
