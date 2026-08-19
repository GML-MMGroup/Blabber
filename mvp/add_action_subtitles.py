from __future__ import annotations

import argparse
import json
import re
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from blabber.media_tools import ffmpeg_binary


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUN_DIR = PROJECT_ROOT / "mvp" / "output" / "20260728-170344"
DEFAULT_FONT = Path("/System/Library/Fonts/STHeiti Medium.ttc")
CLAUSE_RE = re.compile(r".*?[，。！？；：…]+|.+$")


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    speaker: str
    text: str


def _strip_subtitle_punctuation(text: str) -> str:
    without_punctuation = "".join(
        character
        for character in text
        if character == "." or not unicodedata.category(character).startswith("P")
    )
    return re.sub(r"\s+", " ", without_punctuation).strip()


def _visible_length(text: str) -> int:
    return max(1, len(re.sub(r"[\s，。！？；：、“”‘’…—,.!?;:'\"-]", "", text)))


def _split_text(text: str, max_chars: int) -> list[str]:
    clauses = [item.strip() for item in CLAUSE_RE.findall(text) if item.strip()]
    pieces: list[str] = []
    for clause in clauses:
        while len(clause) > max_chars:
            pieces.append(clause[:max_chars])
            clause = clause[max_chars:]
        if clause:
            pieces.append(clause)

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) > max_chars:
            chunks.append(current)
            current = piece
        else:
            current += piece
    if current:
        chunks.append(current)
    return chunks or [text]


def build_cues(
    script: dict,
    manifest: dict,
    clips_dir: Path,
    max_chars: int,
) -> tuple[list[Cue], float]:
    turns = script.get("turns", [])
    segments = manifest.get("segments", [])

    turn_segments = [segment for segment in segments if segment.get("kind") == "turn"]
    if len(turns) != len(turn_segments):
        raise ValueError(
            f"script 台词数 ({len(turns)}) 与合成清单发言段数 "
            f"({len(turn_segments)}) 不一致"
        )

    cues: list[Cue] = []
    cursor = 0.0
    turn_index = 0
    for segment in segments:
        duration = float(segment["duration"])
        if segment.get("kind") != "turn":
            cursor += duration
            continue

        turn = turns[turn_index]
        speaker = str(segment["speaker"])
        source_clip = str(segment.get("source_clip") or "")
        expected_clip = f"{turn_index:02d}_{speaker}.mp3"
        if turn.get("speaker") != speaker:
            raise ValueError(
                f"第 {turn_index} 条说话人不一致："
                f"script={turn.get('speaker')}，manifest={speaker}"
            )
        if source_clip != expected_clip or not (clips_dir / source_clip).is_file():
            raise FileNotFoundError(
                f"第 {turn_index} 条切片不匹配或不存在：{source_clip}"
            )

        chunks = _split_text(str(turn["text"]).strip(), max_chars)
        weights = [_visible_length(chunk) for chunk in chunks]
        total_weight = sum(weights)
        chunk_cursor = cursor
        for index, (chunk, weight) in enumerate(zip(chunks, weights)):
            chunk_end = (
                cursor + duration
                if index == len(chunks) - 1
                else chunk_cursor + duration * weight / total_weight
            )
            cues.append(
                Cue(
                    chunk_cursor,
                    chunk_end,
                    speaker,
                    _strip_subtitle_punctuation(chunk),
                )
            )
            chunk_cursor = chunk_end

        cursor += duration
        turn_index += 1

    target_duration = float(manifest.get("target_duration") or cursor)
    return cues, target_duration


def _srt_time(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def write_srt(cues: list[Cue], output: Path) -> None:
    blocks = [
        f"{index}\n{_srt_time(cue.start)} --> {_srt_time(cue.end)}\n{cue.text}"
        for index, cue in enumerate(cues, start=1)
    ]
    output.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def _render_caption(
    text: str,
    output: Path,
    width: int,
    height: int,
    font: ImageFont.FreeTypeFont,
    margin_bottom: int,
) -> None:
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=2)
    text_height = bbox[3] - bbox[1]
    center_x = width // 2
    bottom = height - margin_bottom
    top = bottom - text_height
    draw.text(
        (center_x, top - bbox[1]),
        text,
        font=font,
        fill=(255, 255, 255, 255),
        anchor="ma",
        align="center",
        stroke_width=2,
        stroke_fill=(0, 0, 0, 230),
    )
    image.save(output)


def _concat_quote(path: Path) -> str:
    return str(path.resolve()).replace("'", "'\\''")


def write_overlay_sequence(
    cues: list[Cue],
    target_duration: float,
    work_dir: Path,
    width: int,
    height: int,
    font_path: Path,
    font_size: int,
    margin_bottom: int,
) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(str(font_path), font_size)
    blank = work_dir / "blank.png"
    Image.new("RGBA", (width, height), (0, 0, 0, 0)).save(blank)

    intervals: list[tuple[Path, float]] = []
    cursor = 0.0
    for index, cue in enumerate(cues):
        if cue.start > cursor + 0.0001:
            intervals.append((blank, cue.start - cursor))
        caption = work_dir / f"caption-{index:03d}.png"
        _render_caption(
            cue.text,
            caption,
            width,
            height,
            font,
            margin_bottom,
        )
        intervals.append((caption, cue.end - cue.start))
        cursor = cue.end
    if target_duration > cursor:
        intervals.append((blank, target_duration - cursor))

    concat_path = work_dir / "subtitle-overlay.concat"
    lines: list[str] = []
    for path, duration in intervals:
        lines.extend(
            [
                f"file '{_concat_quote(path)}'",
                f"duration {duration:.9f}",
            ]
        )
    lines.append(f"file '{_concat_quote(intervals[-1][0])}'")
    concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return concat_path


def _burn_subtitles(
    video: Path,
    concat_path: Path,
    output: Path,
    fps: int,
    duration: float,
    crf: int,
    preset: str,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg_binary(),
        "-hide_banner",
        "-y",
        "-i",
        str(video),
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-filter_complex",
        f"[1:v]fps={fps},format=rgba[sub];[0:v][sub]overlay=0:0:shortest=1[v]",
        "-map",
        "[v]",
        "-map",
        "0:a?",
        "-t",
        f"{duration:.6f}",
        "-c:v",
        "libx264",
        "-crf",
        str(crf),
        "-preset",
        preset,
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(output),
    ]
    print("[字幕] 启动 FFmpeg 烧录")
    subprocess.run(command, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="依据 script、音频切片和动作合成清单生成并烧录中文字幕"
    )
    parser.add_argument("run_dir", nargs="?", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--video", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--script", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--srt", type=Path)
    parser.add_argument("--font", type=Path, default=DEFAULT_FONT)
    parser.add_argument("--font-size", type=int, default=48)
    parser.add_argument("--max-chars", type=int, default=22)
    parser.add_argument("--margin-bottom", type=int, default=150)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--crf", type=int, default=18)
    parser.add_argument("--preset", default="slow")
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    video = (
        args.video.resolve()
        if args.video
        else run_dir / "final-action-1.2x-meta.mp4"
    )
    manifest = (
        args.manifest.resolve()
        if args.manifest
        else run_dir / "final-action-1.2x-meta.json"
    )
    script = args.script.resolve() if args.script else run_dir / "script.json"
    output = (
        args.output.resolve()
        if args.output
        else run_dir / "final-action-1.2x-meta-subtitled.mp4"
    )
    srt = (
        args.srt.resolve()
        if args.srt
        else run_dir / "final-action-1.2x-meta.srt"
    )

    for label, path in {
        "video": video,
        "manifest": manifest,
        "script": script,
        "font": args.font,
    }.items():
        if not path.is_file():
            raise FileNotFoundError(f"{label} 不存在：{path}")

    script_data = json.loads(script.read_text(encoding="utf-8"))
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    cues, target_duration = build_cues(
        script_data,
        manifest_data,
        run_dir / "clips",
        args.max_chars,
    )
    write_srt(cues, srt)
    concat_path = write_overlay_sequence(
        cues,
        target_duration,
        run_dir / "video_tmp" / "subtitles",
        1920,
        1080,
        args.font.resolve(),
        args.font_size,
        args.margin_bottom,
    )
    _burn_subtitles(
        video,
        concat_path,
        output,
        args.fps,
        target_duration,
        args.crf,
        args.preset,
    )
    print(f"[字幕] SRT：{srt}")
    print(f"[字幕] 成片：{output}")


if __name__ == "__main__":
    main()
