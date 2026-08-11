import asyncio
import os
import re
import subprocess
from pathlib import Path

import cv2
import numpy as np
from pydub import AudioSegment

from blabber import avatar, idle_motion
from blabber.compose import PAUSE_MS
from blabber.video_engine import LipSyncEngine, Wav2LipEngine

FPS = 25
_TURN_FILENAME_RE = re.compile(r"^(\d+)_(.+)\.mp3$")


def _turn_files(clips_dir: Path) -> list:
    turns = []
    for p in clips_dir.glob("*.mp3"):
        m = _TURN_FILENAME_RE.match(p.name)
        # Failed TTS attempts can leave a 0-byte file behind (main.py skips
        # them from the audio compose but doesn't clean up the file), so a
        # bare glob isn't enough to know which turns actually synthesized.
        if m and p.stat().st_size > 0:
            turns.append((int(m.group(1)), m.group(2), p))
    turns.sort(key=lambda t: t[0])
    return turns


def _audio_duration_seconds(path: Path) -> float:
    return len(AudioSegment.from_file(path)) / 1000.0


def _write_frames_to_video(frames: list, out_path: Path, fps: int) -> None:
    h, w = frames[0].shape[:2]
    writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for frame in frames:
        writer.write(frame)
    writer.release()


def _read_video_frames(path: Path) -> list:
    cap = cv2.VideoCapture(str(path))
    frames = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(frame)
    cap.release()
    return frames


def _paste_with_feather(background_frame: np.ndarray, crop_frame: np.ndarray, box, feather: int = 12) -> None:
    h, w = crop_frame.shape[:2]
    mask = np.zeros((h, w), dtype=np.float32)
    inner = min(feather, h // 2, w // 2)
    if inner > 0:
        mask[inner : h - inner, inner : w - inner] = 1.0
        mask = cv2.GaussianBlur(mask, (feather * 2 + 1, feather * 2 + 1), 0)
    else:
        mask[:] = 1.0
    mask3 = mask[..., None]
    region = background_frame[box.y1 : box.y2, box.x1 : box.x2].astype(np.float32)
    blended = region * (1 - mask3) + crop_frame.astype(np.float32) * mask3
    background_frame[box.y1 : box.y2, box.x1 : box.x2] = blended.astype(np.uint8)


async def _render_turn(
    index: int,
    speaker: str,
    audio_path: Path,
    background: np.ndarray,
    face_regions: dict,
    eye_regions: dict,
    fps: int,
    tmp_dir: Path,
    lipsync_engine: LipSyncEngine,
) -> Path:
    duration = _audio_duration_seconds(audio_path)
    idle_frames = idle_motion.render_idle_frames(background, duration, fps, eye_groups=list(eye_regions.values()))

    speaker_box = face_regions[speaker]
    crop_video_path = tmp_dir / f"{index:03d}_{speaker}_crop.mp4"
    _write_frames_to_video([speaker_box.crop(f) for f in idle_frames], crop_video_path, fps)

    synced_path = tmp_dir / f"{index:03d}_{speaker}_synced.mp4"
    await lipsync_engine.sync(crop_video_path, audio_path, synced_path)
    synced_frames = _read_video_frames(synced_path)

    final_frames = []
    for i, frame in enumerate(idle_frames):
        composed = frame.copy()
        if synced_frames:
            synced_frame = synced_frames[min(i, len(synced_frames) - 1)]
            _paste_with_feather(composed, synced_frame, speaker_box)
        final_frames.append(composed)

    out_path = tmp_dir / f"{index:03d}_{speaker}_final.mp4"
    _write_frames_to_video(final_frames, out_path, fps)
    return out_path


def _render_pause(index: int, background: np.ndarray, eye_regions: dict, duration: float, fps: int, tmp_dir: Path) -> Path:
    idle_frames = idle_motion.render_idle_frames(background, duration, fps, eye_groups=list(eye_regions.values()))
    out_path = tmp_dir / f"{index:03d}_pause.mp4"
    _write_frames_to_video(idle_frames, out_path, fps)
    return out_path


def _run_ffmpeg(cmd: list) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败: {' '.join(cmd)}\n{result.stderr[-4000:]}")


def _concat_videos(segment_paths: list, out_path: Path) -> None:
    list_file = out_path.parent / "concat_list.txt"
    list_file.write_text("".join(f"file '{p.resolve()}'\n" for p in segment_paths), encoding="utf-8")
    _run_ffmpeg([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out_path),
    ])


def _mux_audio(silent_video_path: Path, audio_path: Path, out_path: Path) -> None:
    _run_ffmpeg([
        "ffmpeg", "-y", "-i", str(silent_video_path), "-i", str(audio_path),
        "-c:v", "copy", "-c:a", "aac", "-shortest", str(out_path),
    ])


async def compose_episode_video(
    run_dir: Path,
    avatar_image: Path = avatar.DEFAULT_AVATAR_IMAGE,
    out_path: Path = None,
    fps: int = FPS,
    lipsync_engine: LipSyncEngine = None,
    parallel_workers: int | None = None,
) -> Path:
    out_path = out_path or run_dir / "final.mp4"
    lipsync_engine = lipsync_engine or Wav2LipEngine()

    clips_dir = run_dir / "clips"
    turns = _turn_files(clips_dir)
    if not turns:
        raise RuntimeError(f"{clips_dir} 下没有找到任何音频片段（*.mp3）")

    background = cv2.imread(str(avatar_image))
    if background is None:
        raise RuntimeError(f"无法读取形象素材图片: {avatar_image}")
    face_regions = avatar.get_face_regions(avatar_image)
    eye_regions = avatar.get_eye_regions(avatar_image)

    tmp_dir = run_dir / "video_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    for index, speaker, _ in turns:
        if speaker not in face_regions:
            raise RuntimeError(
                f"turn {index} 的说话人 '{speaker}' 在 avatar 人脸区域里没有配置"
            )

    requested_workers = parallel_workers
    if requested_workers is None:
        requested_workers = int(os.getenv("BLABBER_VIDEO_WORKERS", "0") or 0)
    workers = requested_workers or min(2, len(turns))
    workers = max(1, min(workers, len(turns)))
    semaphore = asyncio.Semaphore(workers)
    print(f"[视频合成] 使用 {workers} 个并行唇形任务", flush=True)

    async def render_turn(seg_i: int, turn: tuple) -> Path:
        index, speaker, audio_path = turn
        async with semaphore:
            print(
                f"[视频 {seg_i + 1}/{len(turns)}] 开始处理 "
                f"{audio_path.name}（{speaker}）",
                flush=True,
            )
            rendered = await _render_turn(
                index,
                speaker,
                audio_path,
                background,
                face_regions,
                eye_regions,
                fps,
                tmp_dir,
                lipsync_engine,
            )
            print(
                f"[视频 {seg_i + 1}/{len(turns)}] 片段完成: {rendered.name}",
                flush=True,
            )
            return rendered

    rendered_turns = await asyncio.gather(
        *(render_turn(seg_i, turn) for seg_i, turn in enumerate(turns))
    )
    segment_paths = []
    for seg_i, rendered in enumerate(rendered_turns):
        segment_paths.append(rendered)
        if seg_i != len(turns) - 1:
            index = turns[seg_i][0]
            segment_paths.append(
                _render_pause(
                    index,
                    background,
                    eye_regions,
                    PAUSE_MS / 1000.0,
                    fps,
                    tmp_dir,
                )
            )
    silent_path = tmp_dir / "silent_full.mp4"
    print(f"[视频合成] 正在拼接 {len(segment_paths)} 个片段", flush=True)
    _concat_videos(segment_paths, silent_path)
    print("[视频合成] 正在混入最终音频", flush=True)
    _mux_audio(silent_path, run_dir / "final.mp3", out_path)
    print(f"[视频合成] 完成: {out_path}", flush=True)
    return out_path
