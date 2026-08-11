from pathlib import Path

from pydub import AudioSegment
from pydub.silence import detect_nonsilent

from .media_tools import ensure_media_tools_on_path, ffmpeg_binary

ensure_media_tools_on_path()
AudioSegment.converter = ffmpeg_binary()

PAUSE_MS = 180
SILENCE_GUARD_MS = 70


def load_dialogue_clip(path: Path) -> AudioSegment:
    """Load one TTS turn with provider-added head/tail silence normalized."""
    clip = AudioSegment.from_file(path)
    threshold = max(-48, clip.dBFS - 24) if clip.dBFS != float("-inf") else -48
    ranges = detect_nonsilent(
        clip,
        min_silence_len=80,
        silence_thresh=threshold,
        seek_step=5,
    )
    if ranges:
        start = max(0, ranges[0][0] - SILENCE_GUARD_MS)
        end = min(len(clip), ranges[-1][1] + SILENCE_GUARD_MS)
        clip = clip[start:end]
    fade_ms = min(20, max(0, len(clip) // 8))
    return clip.fade_in(fade_ms).fade_out(fade_ms)


def compose_episode(clip_paths: list[Path], out_path: Path) -> Path:
    """Concatenate per-line clips into one episode, with a short pause
    between turns to mimic natural conversational spacing."""
    pause = AudioSegment.silent(duration=PAUSE_MS)
    episode = AudioSegment.empty()
    for i, clip_path in enumerate(clip_paths):
        episode += load_dialogue_clip(clip_path)
        if i != len(clip_paths) - 1:
            episode += pause

    out_path.parent.mkdir(parents=True, exist_ok=True)
    episode.export(out_path, format="mp3")
    return out_path
