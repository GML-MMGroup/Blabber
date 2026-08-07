from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from add_action_subtitles import (
    DEFAULT_FONT as DEFAULT_SUBTITLE_FONT,
    build_cues,
    write_overlay_sequence,
    write_srt,
)
from blabber.compose import PAUSE_MS, load_dialogue_clip


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUN_DIR = PROJECT_ROOT / "mvp" / "output" / "20260728-170344"
DEFAULT_ACTION_ROOT = PROJECT_ROOT / "assets" / "action"
DEFAULT_BACKGROUND = (
    PROJECT_ROOT
    / "assets"
    / "background"
    / "scene2-background-mics-out-100px-1920x1080.png"
)
DEFAULT_FOREGROUND = (
    PROJECT_ROOT
    / "assets"
    / "background"
    / "scene2-foreground-mics-out-100px-alpha-1920x1080_副本.png"
)
TURN_RE = re.compile(r"^(\d+)_(HostA|HostB)\.mp3$")


@dataclass(frozen=True)
class Segment:
    kind: str
    speaker: str | None
    duration: float
    source_clip: str | None = None


@dataclass(frozen=True)
class ActionAsset:
    key: str
    path: Path
    input_index: int
    duration: float
    canvas_size: int
    render_scale: float = 1.0
    offset_x: int = 0
    offset_y: int = 0


def _probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(f"无法读取时长：{path}\n{result.stderr[-1000:]}")
    return float(result.stdout.strip())


def _turn_files(clips_dir: Path) -> list[tuple[int, str, Path]]:
    turns: list[tuple[int, str, Path]] = []
    for path in clips_dir.glob("*.mp3"):
        match = TURN_RE.match(path.name)
        if match and path.stat().st_size:
            turns.append((int(match.group(1)), match.group(2), path))
    return sorted(turns)


def _build_timeline(clips_dir: Path, audio_speed: float) -> list[Segment]:
    turns = _turn_files(clips_dir)
    if not turns:
        raise RuntimeError(f"{clips_dir} 下没有 HostA/HostB 音频切片")
    timeline: list[Segment] = []
    for position, (_, speaker, path) in enumerate(turns):
        # final.mp3 is built with the same trimmed clips and PAUSE_MS spacing.
        duration = len(load_dialogue_clip(path)) / 1000 / audio_speed
        timeline.append(Segment("turn", speaker, duration, path.name))
        if position < len(turns) - 1:
            timeline.append(
                Segment("pause", None, PAUSE_MS / 1000 / audio_speed)
            )
    return timeline


def _atempo_chain(speed: float) -> str:
    factors: list[float] = []
    remaining = speed
    while remaining > 2:
        factors.append(2)
        remaining /= 2
    while remaining < 0.5:
        factors.append(0.5)
        remaining /= 0.5
    factors.append(remaining)
    return ",".join(f"atempo={factor:.8f}" for factor in factors)


def _cycle_plan(
    desired_duration: float,
    source_duration: float,
    pause: bool,
    min_speed: float = 0.85,
    max_speed: float = 1.20,
) -> tuple[float, float, int]:
    if pause:
        return desired_duration, 1.0, 0
    cycles = max(1, round(desired_duration / source_duration))
    ideal_speed = cycles * source_duration / desired_duration
    playback_speed = min(max_speed, max(min_speed, ideal_speed))
    input_duration = desired_duration * playback_speed
    loops_used = max(1, math.ceil(input_duration / source_duration))
    return input_duration, playback_speed, loops_used


def _asset_key(speaker: str, speaking: bool) -> str:
    role = "dialogue" if speaking else "standby"
    actor = "host_a" if speaker == "HostA" else "host_b"
    return f"{actor}_{role}"


def _pick_action_asset(
    action_root: Path,
    character: str,
    action: str,
) -> Path:
    action_dir = action_root / character
    candidates = sorted(
        action_dir.glob(f"{character}-{action}-*-alpha-prores4444.mov"),
        key=_probe_duration,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(
            f"没有找到 {character} 的 {action} Alpha 元视频：{action_dir}"
        )
    return candidates[0]


def _build_filter(
    timeline: list[Segment],
    assets: dict[str, ActionAsset],
    audio_speed: float,
    fps: int,
    min_action_speed: float,
    max_action_speed: float,
    host_a_x: int,
    host_a_y: int,
    host_b_x: int,
    host_b_y: int,
    foreground_key_color: str | None,
    foreground_key_similarity: float,
    foreground_key_blend: float,
    include_subtitles: bool,
) -> tuple[str, list[dict]]:
    actor_segments: dict[str, list[str]] = {"host_a": [], "host_b": []}
    branches: dict[str, list[tuple[str, Segment, str]]] = {
        key: [] for key in assets
    }
    manifest_segments: list[dict] = []

    for segment_index, segment in enumerate(timeline):
        manifest_item = asdict(segment)
        manifest_item["index"] = segment_index
        manifest_item["actors"] = {}
        for speaker, actor in (("HostA", "host_a"), ("HostB", "host_b")):
            speaking = segment.kind == "turn" and segment.speaker == speaker
            key = _asset_key(speaker, speaking)
            asset = assets[key]
            output_label = f"{actor}_segment_{segment_index}"
            branches[key].append((output_label, segment, actor))
            actor_segments[actor].append(f"[{output_label}]")
            input_duration, playback_speed, cycles = _cycle_plan(
                segment.duration,
                asset.duration,
                segment.kind == "pause",
                min_action_speed,
                max_action_speed,
            )
            manifest_item["actors"][actor] = {
                "asset": assets[key].path.name,
                "state": "speaking" if speaking else "standby",
                "cycles": cycles,
                "playback_speed": round(playback_speed, 6),
                "source_duration": round(input_duration, 6),
                "render_scale": asset.render_scale,
                "offset_x": asset.offset_x,
                "offset_y": asset.offset_y,
            }
        manifest_segments.append(manifest_item)

    filters: list[str] = []
    for key, asset_branches in branches.items():
        asset = assets[key]
        split_labels = "".join(
            f"[{key}_raw_{index}]" for index in range(len(asset_branches))
        )
        filters.append(
            f"[{asset.input_index}:v]split={len(asset_branches)}{split_labels}"
        )
        for branch_index, (output_label, segment, _) in enumerate(asset_branches):
            input_duration, playback_speed, _ = _cycle_plan(
                segment.duration,
                asset.duration,
                segment.kind == "pause",
                min_action_speed,
                max_action_speed,
            )
            render_size = round(asset.canvas_size * asset.render_scale)
            pad_x = max(0, asset.offset_x)
            pad_y = max(0, asset.offset_y)
            crop_x = max(0, -asset.offset_x)
            crop_y = max(0, -asset.offset_y)
            padded_width = max(
                asset.canvas_size + crop_x,
                render_size + pad_x,
            )
            padded_height = max(
                asset.canvas_size + crop_y,
                render_size + pad_y,
            )
            filters.append(
                f"[{key}_raw_{branch_index}]"
                f"trim=duration={input_duration:.9f},"
                f"setpts=(PTS-STARTPTS)/{playback_speed:.9f},"
                f"fps={fps},"
                f"scale={render_size}:{render_size},"
                "format=rgba,"
                f"pad={padded_width}:{padded_height}:{pad_x}:{pad_y}:"
                "color=0x00000000,"
                f"crop={asset.canvas_size}:{asset.canvas_size}:"
                f"{crop_x}:{crop_y}"
                f"[{output_label}]"
            )

    for actor in ("host_a", "host_b"):
        filters.append(
            "".join(actor_segments[actor])
            + f"concat=n={len(timeline)}:v=1:a=0[{actor}_timeline]"
        )

    foreground_filters: list[str]
    if foreground_key_color:
        foreground_filters = [
            "[5:v]scale=1920:1080,format=rgba,"
            f"colorkey={foreground_key_color}:"
            f"{foreground_key_similarity}:{foreground_key_blend},"
            "split[foreground_color][foreground_alpha_source]",
            "[foreground_alpha_source]alphaextract,erosion[foreground_alpha]",
            "[foreground_color][foreground_alpha]alphamerge[foreground]",
        ]
    else:
        foreground_filters = [
            "[5:v]scale=1920:1080,format=rgba[foreground]"
        ]
    filters.extend(
        [
            "[0:v]scale=1920:1080,format=rgba[background]",
            *foreground_filters,
            "[background][host_a_timeline]"
            f"overlay=x={host_a_x}:y={host_a_y}:format=auto[with_host_a]",
            "[with_host_a][host_b_timeline]"
            f"overlay=x={host_b_x}:y={host_b_y}:format=auto[with_actors]",
            "[with_actors][foreground]"
            "overlay=x=0:y=0:format=auto[scene]",
        ]
    )
    if include_subtitles:
        filters.extend(
            [
                f"[7:v]fps={fps},format=rgba[subtitle_overlay]",
                "[scene][subtitle_overlay]"
                "overlay=x=0:y=0:shortest=1,format=yuv420p[video]",
            ]
        )
    else:
        filters.append("[scene]format=yuv420p[video]")
    filters.append(
        f"[6:a]{_atempo_chain(audio_speed)},"
        "loudnorm=I=-16:TP=-1.5:LRA=11,"
        "aresample=48000[audio]"
    )
    return ";\n".join(filters), manifest_segments


def _run(command: list[str]) -> None:
    print("[动作视频] 启动 FFmpeg 合成", flush=True)
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stderr is not None
    tail: list[str] = []
    for line in process.stderr:
        tail.append(line)
        if len(tail) > 80:
            tail.pop(0)
        if "frame=" in line:
            print(f"\r{line.strip()}", end="", flush=True)
    return_code = process.wait()
    if return_code:
        reason = (
            f"进程被信号 {-return_code} 终止，通常表示系统资源不足"
            if return_code < 0
            else f"进程退出码 {return_code}"
        )
        raise RuntimeError(
            f"FFmpeg 合成失败（{reason}）：\n" + "".join(tail[-40:])
        )
    print()


def _prepare_pingpong_asset(
    asset: ActionAsset,
    cache_dir: Path,
    fps: int,
) -> Path:
    """生成并复用正放+倒放动作素材，避免每个切片重复缓存倒放帧。"""
    stat = asset.path.stat()
    signature = (
        f"{asset.path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}:{fps}"
    )
    digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:16]
    cache_dir.mkdir(parents=True, exist_ok=True)
    output = cache_dir / f"{asset.path.stem}-{fps}fps-{digest}-pingpong.mov"
    if output.is_file() and output.stat().st_size:
        return output

    temporary = output.with_name(f"{output.stem}.rendering.mov")
    print(f"[动作视频] 准备正放+倒放素材：{asset.path.name}", flush=True)
    _run([
        "ffmpeg", "-y", "-filter_threads", "1",
        "-i", str(asset.path),
        "-filter_complex",
        f"[0:v]fps={fps},setpts=PTS-STARTPTS,split=2[forward][reverse_input];"
        "[reverse_input]reverse,setpts=PTS-STARTPTS[reverse];"
        "[forward][reverse]concat=n=2:v=1:a=0,format=yuva444p10le[video]",
        "-map", "[video]", "-an", "-c:v", "prores_ks",
        "-profile:v", "4", "-pix_fmt", "yuva444p10le",
        "-vendor", "apl0", "-threads", "2", str(temporary),
    ])
    temporary.replace(output)
    return output


def _segment_actor_filter(
    input_index: int,
    output_label: str,
    asset: ActionAsset,
    segment: Segment,
    fps: int,
    min_action_speed: float,
    max_action_speed: float,
) -> str:
    input_duration, playback_speed, _ = _cycle_plan(
        segment.duration,
        asset.duration,
        segment.kind == "pause",
        min_action_speed,
        max_action_speed,
    )
    render_size = round(asset.canvas_size * asset.render_scale)
    pad_x = max(0, asset.offset_x)
    pad_y = max(0, asset.offset_y)
    crop_x = max(0, -asset.offset_x)
    crop_y = max(0, -asset.offset_y)
    padded_width = max(asset.canvas_size + crop_x, render_size + pad_x)
    padded_height = max(asset.canvas_size + crop_y, render_size + pad_y)
    return (
        f"[{input_index}:v]trim=duration={input_duration:.9f},"
        f"setpts=(PTS-STARTPTS)/{playback_speed:.9f},"
        f"fps={fps},scale={render_size}:{render_size},format=rgba,"
        f"pad={padded_width}:{padded_height}:{pad_x}:{pad_y}:"
        "color=0x00000000,"
        f"crop={asset.canvas_size}:{asset.canvas_size}:{crop_x}:{crop_y}"
        f"[{output_label}]"
    )


def _render_low_memory_video(
    args: argparse.Namespace,
    timeline: list[Segment],
    assets: dict[str, ActionAsset],
    inputs: dict[str, Path],
    output: Path,
    subtitle_concat: Path | None,
    target_duration: float,
) -> None:
    """逐段渲染，并以正放、倒放的乒乓序列平滑循环动作素材。"""
    work_dir = args.run_dir.resolve() / "video_tmp" / f"{output.stem}-segments"
    work_dir.mkdir(parents=True, exist_ok=True)
    segment_paths: list[Path] = []
    progress_callback = getattr(args, "progress_callback", None)
    pingpong_cache_dir = args.run_dir.resolve().parent / ".action-pingpong-cache"
    pingpong_paths = {
        asset.path: _prepare_pingpong_asset(asset, pingpong_cache_dir, args.fps)
        for asset in assets.values()
    }

    for index, segment in enumerate(timeline):
        host_a_key = _asset_key(
            "HostA", segment.kind == "turn" and segment.speaker == "HostA"
        )
        host_b_key = _asset_key(
            "HostB", segment.kind == "turn" and segment.speaker == "HostB"
        )
        host_a = assets[host_a_key]
        host_b = assets[host_b_key]
        segment_path = work_dir / f"{index:04d}.mp4"
        segment_paths.append(segment_path)
        filters = [
            _segment_actor_filter(
                1, "host_a", host_a, segment, args.fps,
                args.min_action_speed, args.max_action_speed,
            ),
            _segment_actor_filter(
                2, "host_b", host_b, segment, args.fps,
                args.min_action_speed, args.max_action_speed,
            ),
            "[0:v]scale=1920:1080,format=rgba[background]",
        ]
        if args.foreground_key_color:
            filters.extend([
                "[3:v]scale=1920:1080,format=rgba,"
                f"colorkey={args.foreground_key_color}:"
                f"{args.foreground_key_similarity}:"
                f"{args.foreground_key_blend},"
                "split[foreground_color][foreground_alpha_source]",
                "[foreground_alpha_source]alphaextract,erosion[foreground_alpha]",
                "[foreground_color][foreground_alpha]alphamerge[foreground]",
            ])
        else:
            filters.append("[3:v]scale=1920:1080,format=rgba[foreground]")
        filters.extend([
            "[background][host_a]"
            f"overlay=x={args.host_a_x}:y={args.host_a_y}:format=auto[with_host_a]",
            "[with_host_a][host_b]"
            f"overlay=x={args.host_b_x}:y={args.host_b_y}:format=auto[with_actors]",
            "[with_actors][foreground]"
            "overlay=x=0:y=0:format=auto,format=yuv420p[video]",
        ])
        command = [
            "ffmpeg", "-y", "-filter_threads", "1",
            "-filter_complex_threads", "1",
            "-loop", "1", "-framerate", str(args.fps),
            "-i", str(inputs["background"]),
            "-stream_loop", "-1", "-i", str(pingpong_paths[host_a.path]),
            "-stream_loop", "-1", "-i", str(pingpong_paths[host_b.path]),
            "-loop", "1", "-framerate", str(args.fps),
            "-i", str(inputs["foreground"]),
            "-filter_complex", ";\n".join(filters),
            "-map", "[video]", "-t", f"{segment.duration:.9f}",
            "-r", str(args.fps), "-an", "-c:v", "libx264",
            "-preset", "veryfast", "-crf", "16", "-threads", "2",
            "-pix_fmt", "yuv420p", str(segment_path),
        ]
        print(
            f"[动作视频] 渲染切片 {index + 1}/{len(timeline)}",
            flush=True,
        )
        _run(command)
        if callable(progress_callback):
            progress_callback(index + 1, len(timeline) + 1, "rendering")

    concat_list = work_dir / "segments.txt"
    concat_list.write_text(
        "".join(f"file '{path.as_posix().replace(chr(39), chr(39) * 3)}'\n" for path in segment_paths),
        encoding="utf-8",
    )
    scene_path = work_dir / "scene.mp4"
    _run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list), "-c", "copy", str(scene_path),
    ])

    command = [
        "ffmpeg", "-y", "-filter_threads", "1",
        "-filter_complex_threads", "1", "-i", str(scene_path),
        "-i", str(inputs["audio"]),
    ]
    audio_filter = (
        f"[1:a]{_atempo_chain(args.audio_speed)},"
        "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[audio]"
    )
    if subtitle_concat:
        command.extend([
            "-f", "concat", "-safe", "0", "-i", str(subtitle_concat),
            "-filter_complex",
            f"[2:v]fps={args.fps},format=rgba[subtitle_overlay];"
            "[0:v][subtitle_overlay]overlay=x=0:y=0:shortest=1,"
            f"format=yuv420p[video];{audio_filter}",
            "-map", "[video]", "-map", "[audio]", "-c:v", "libx264",
            "-preset", "veryfast", "-crf", str(args.crf), "-threads", "2",
        ])
    else:
        command.extend([
            "-filter_complex", audio_filter,
            "-map", "0:v:0", "-map", "[audio]", "-c:v", "copy",
        ])
    command.extend([
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-disposition:a:0", "default", "-t", f"{target_duration:.9f}",
        "-shortest", str(output),
    ])
    print("[动作视频] 拼接音频与字幕", flush=True)
    if callable(progress_callback):
        progress_callback(len(timeline), len(timeline) + 1, "finalizing")
    _run(command)


def compose(args: argparse.Namespace) -> Path:
    run_dir = args.run_dir.resolve()
    action_root = args.action_root.resolve()
    output = (
        args.output.resolve()
        if args.output
        else run_dir / f"final-action-{args.audio_speed:g}x.mp4"
    )
    manifest_path = output.with_suffix(".json")
    inputs = {
        "background": args.background.resolve(),
        "foreground": args.foreground.resolve(),
        "audio": run_dir / "final.mp3",
        "host_a_dialogue": _pick_action_asset(
            action_root, args.host_a_character, "dialogue"
        ),
        "host_a_standby": _pick_action_asset(
            action_root, args.host_a_character, "standby"
        ),
        "host_b_dialogue": _pick_action_asset(
            action_root, args.host_b_character, "dialogue"
        ),
        "host_b_standby": _pick_action_asset(
            action_root, args.host_b_character, "standby"
        ),
    }
    for label, path in inputs.items():
        if not path.is_file():
            raise FileNotFoundError(f"{label} 素材不存在：{path}")
    if args.audio_speed <= 0:
        raise ValueError("audio-speed 必须大于 0")
    if not 0 < args.min_action_speed <= args.max_action_speed:
        raise ValueError("动作速度必须满足 0 < min-action-speed <= max-action-speed")
    if args.host_b_dialogue_scale <= 0:
        raise ValueError("host-b-dialogue-scale 必须大于 0")

    timeline = _build_timeline(run_dir / "clips", args.audio_speed)
    assets = {
        "host_a_dialogue": ActionAsset(
            "host_a_dialogue",
            inputs["host_a_dialogue"],
            1,
            _probe_duration(inputs["host_a_dialogue"]),
            args.host_a_size,
        ),
        "host_a_standby": ActionAsset(
            "host_a_standby",
            inputs["host_a_standby"],
            2,
            _probe_duration(inputs["host_a_standby"]),
            args.host_a_size,
        ),
        "host_b_dialogue": ActionAsset(
            "host_b_dialogue",
            inputs["host_b_dialogue"],
            3,
            _probe_duration(inputs["host_b_dialogue"]),
            args.host_b_size,
            args.host_b_dialogue_scale,
            args.host_b_dialogue_offset_x,
            args.host_b_dialogue_offset_y,
        ),
        "host_b_standby": ActionAsset(
            "host_b_standby",
            inputs["host_b_standby"],
            4,
            _probe_duration(inputs["host_b_standby"]),
            args.host_b_size,
        ),
    }
    filter_graph, manifest_segments = _build_filter(
        timeline,
        assets,
        args.audio_speed,
        args.fps,
        args.min_action_speed,
        args.max_action_speed,
        args.host_a_x,
        args.host_a_y,
        args.host_b_x,
        args.host_b_y,
        args.foreground_key_color,
        args.foreground_key_similarity,
        args.foreground_key_blend,
        args.subtitles,
    )
    target_duration = sum(segment.duration for segment in timeline)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": 2,
        "action_loop": "pingpong_forward_reverse",
        "audio_speed": args.audio_speed,
        "fps": args.fps,
        "min_action_speed": args.min_action_speed,
        "max_action_speed": args.max_action_speed,
        "characters": {
            "HostA": args.host_a_character,
            "HostB": args.host_b_character,
        },
        "host_b_dialogue_transform": {
            "scale": args.host_b_dialogue_scale,
            "offset_x": args.host_b_dialogue_offset_x,
            "offset_y": args.host_b_dialogue_offset_y,
        },
        "positions": {
            "HostA": {"x": args.host_a_x, "y": args.host_a_y},
            "HostB": {"x": args.host_b_x, "y": args.host_b_y},
        },
        "foreground_key": {
            "color": args.foreground_key_color,
            "similarity": args.foreground_key_similarity,
            "blend": args.foreground_key_blend,
        },
        "target_duration": round(target_duration, 6),
        "inputs": {key: str(path) for key, path in inputs.items()},
        "output": str(output),
        "segments": manifest_segments,
    }

    subtitle_concat: Path | None = None
    if args.subtitles:
        script_path = (
            args.subtitle_script.resolve()
            if args.subtitle_script
            else run_dir / "script.json"
        )
        if not script_path.is_file():
            raise FileNotFoundError(f"字幕台词不存在：{script_path}")
        if not args.subtitle_font.is_file():
            raise FileNotFoundError(f"字幕字体不存在：{args.subtitle_font}")
        script_data = json.loads(script_path.read_text(encoding="utf-8"))
        cues, subtitle_duration = build_cues(
            script_data,
            manifest,
            run_dir / "clips",
            args.subtitle_max_chars,
        )
        if abs(subtitle_duration - target_duration) > 0.01:
            raise ValueError(
                "字幕时间线与视频时间线不一致："
                f"{subtitle_duration:.3f}s != {target_duration:.3f}s"
            )
        srt_path = (
            args.subtitle_srt.resolve()
            if args.subtitle_srt
            else output.with_suffix(".srt")
        )
        write_srt(cues, srt_path)
        subtitle_concat = write_overlay_sequence(
            cues,
            target_duration,
            run_dir / "video_tmp" / f"subtitles-{output.stem}",
            1920,
            1080,
            args.subtitle_font.resolve(),
            args.subtitle_font_size,
            args.subtitle_margin_bottom,
        )
        manifest["subtitles"] = {
            "enabled": True,
            "script": str(script_path),
            "srt": str(srt_path),
            "cue_count": len(cues),
            "font": str(args.subtitle_font.resolve()),
            "font_size": args.subtitle_font_size,
            "max_chars": args.subtitle_max_chars,
            "margin_bottom": args.subtitle_margin_bottom,
        }
    else:
        manifest["subtitles"] = {"enabled": False}

    _render_low_memory_video(
        args,
        timeline,
        assets,
        inputs,
        output,
        subtitle_concat,
        target_duration,
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="使用四条透明人物动作和分句音频合成双人播客视频"
    )
    parser.add_argument("run_dir", type=Path, nargs="?", default=DEFAULT_RUN_DIR)
    parser.add_argument(
        "--action-root",
        "--action-dir",
        dest="action_root",
        type=Path,
        default=DEFAULT_ACTION_ROOT,
        help="包含各角色子目录及 Alpha 元视频的动作素材根目录",
    )
    parser.add_argument(
        "--host-a-character",
        default="male",
        help="HostA 的角色目录和素材文件名前缀，默认 male",
    )
    parser.add_argument(
        "--host-b-character",
        default="female",
        help="HostB 的角色目录和素材文件名前缀，默认 female",
    )
    parser.add_argument("--background", type=Path, default=DEFAULT_BACKGROUND)
    parser.add_argument("--foreground", type=Path, default=DEFAULT_FOREGROUND)
    parser.add_argument(
        "--foreground-key-color",
        help="前景为纯色幕布时的色键颜色，例如 0xFF00FF；Alpha PNG 留空",
    )
    parser.add_argument(
        "--foreground-key-similarity",
        type=float,
        default=0.18,
        help="前景色键颜色容差，默认 0.18",
    )
    parser.add_argument(
        "--foreground-key-blend",
        type=float,
        default=0.04,
        help="前景色键边缘柔化，默认 0.04",
    )
    parser.add_argument("--output", type=Path)
    subtitle_group = parser.add_mutually_exclusive_group()
    subtitle_group.add_argument(
        "--subtitles",
        dest="subtitles",
        action="store_true",
        help="在本次视频合成中烧录字幕（默认）",
    )
    subtitle_group.add_argument(
        "--no-subtitles",
        dest="subtitles",
        action="store_false",
        help="只合成画面和音频，不生成或烧录字幕",
    )
    parser.set_defaults(subtitles=True)
    parser.add_argument(
        "--subtitle-script",
        type=Path,
        help="字幕台词 JSON，默认使用 run_dir/script.json",
    )
    parser.add_argument(
        "--subtitle-srt",
        type=Path,
        help="SRT 输出路径，默认与输出视频同名",
    )
    parser.add_argument(
        "--subtitle-font",
        type=Path,
        default=DEFAULT_SUBTITLE_FONT,
        help="字幕字体文件",
    )
    parser.add_argument("--subtitle-font-size", type=int, default=48)
    parser.add_argument("--subtitle-max-chars", type=int, default=22)
    parser.add_argument("--subtitle-margin-bottom", type=int, default=150)
    parser.add_argument("--audio-speed", type=float, default=1.2)
    parser.add_argument("--min-action-speed", type=float, default=0.85)
    parser.add_argument("--max-action-speed", type=float, default=1.20)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument(
        "--host-a-size", "--male-size", dest="host_a_size",
        type=int, default=735,
    )
    parser.add_argument(
        "--host-b-size", "--female-size", dest="host_b_size",
        type=int, default=675,
    )
    parser.add_argument("--host-a-x", type=int, default=184)
    parser.add_argument("--host-a-y", type=int, default=195)
    parser.add_argument("--host-b-x", type=int, default=900)
    parser.add_argument(
        "--host-b-y",
        "--female-y",
        dest="host_b_y",
        type=int,
        default=205,
        help="HostB 整条角色轨在最终画面中的纵坐标，默认 205",
    )
    parser.add_argument(
        "--host-b-dialogue-scale",
        "--female-dialogue-scale",
        dest="host_b_dialogue_scale",
        type=float,
        default=1,
        help="HostB 说话素材在角色轨道内的缩放，默认 1",
    )
    parser.add_argument(
        "--host-b-dialogue-offset-x",
        "--female-dialogue-offset-x",
        dest="host_b_dialogue_offset_x",
        type=int,
        default=0,
        help="HostB 说话素材的轨道内水平偏移，默认 0",
    )
    parser.add_argument(
        "--host-b-dialogue-offset-y",
        "--female-dialogue-offset-y",
        dest="host_b_dialogue_offset_y",
        type=int,
        default=0,
        help="HostB 说话素材的轨道内垂直偏移，默认 0",
    )
    parser.add_argument("--crf", type=int, default=18)
    parser.add_argument("--preset", default="slow")
    args = parser.parse_args()
    output = compose(args)
    print(f"[动作视频] 合成完成：{output}")


if __name__ == "__main__":
    main()
