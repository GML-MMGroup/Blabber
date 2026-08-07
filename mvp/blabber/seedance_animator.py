from __future__ import annotations

import base64
import json
import mimetypes
import os
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from volcenginesdkarkruntime import Ark

DEFAULT_MODEL = "doubao-seedance-2-0-mini-260615"
BACKGROUND_COLORS = {
    "green": ("0x00FF00", "#00FF00", "green"),
    "blue": ("0x0000FF", "#0000FF", "blue"),
}


@dataclass(frozen=True)
class AlphaConfig:
    """Controls screen generation and keying."""

    screen: str = "green"
    key_color: str | None = None
    keyer: str = "chromakey"
    similarity: float = 0.18
    blend: float = 0.075
    despill: float = 0.42
    despill_expand: float = 0.08
    prepare_reference: bool = True
    force_key: bool = False

    def validate(self) -> None:
        if self.screen not in BACKGROUND_COLORS:
            raise ValueError(f"screen 只能是：{', '.join(BACKGROUND_COLORS)}")
        if self.keyer not in {"chromakey", "colorkey"}:
            raise ValueError("keyer 只能是 chromakey 或 colorkey")
        if not 0.01 <= self.similarity <= 1:
            raise ValueError("similarity 必须在 0.01–1 之间")
        if not 0 <= self.blend <= 1:
            raise ValueError("blend 必须在 0–1 之间")
        if not 0 <= self.despill <= 1:
            raise ValueError("despill 必须在 0–1 之间")
        if not 0 <= self.despill_expand <= 1:
            raise ValueError("despill_expand 必须在 0–1 之间")

    @property
    def colors(self) -> tuple[str, str, str]:
        return BACKGROUND_COLORS[self.screen]

    @property
    def ffmpeg_key_color(self) -> str:
        value = (self.key_color or self.colors[0]).strip()
        if value.startswith("#"):
            value = f"0x{value[1:]}"
        if not (
            value.startswith("0x")
            and len(value) == 8
            and all(char in "0123456789abcdefABCDEF" for char in value[2:])
        ):
            raise ValueError("key_color 必须为 #RRGGBB 或 0xRRGGBB")
        return value

# Seedance delivers an ordinary video. FFmpeg creates Alpha from a keyable
# screen, and validation prevents opaque videos being mislabeled as transparent.
DEFAULT_PROMPT = """
【主体与参考】
以@图片1中的单个人物为唯一主体，严格保持人物身份、脸型、五官、发型、服装、材质和画风一致，不改变年龄和体型。

【姿态与构图】
人物正面坐姿，面向镜头，腰部以上完整入镜。头顶、头发、双肩、双臂、手肘和双手均不得被画面边缘截断；人物四周至少保留画面宽高 12% 的安全留白。人物始终位于同一位置和同一尺寸。

【动作时间线】
0–0.3 秒：自然坐定，嘴巴闭合，轻微呼吸。
0.3–14.7 秒：像播客主持人一样自然说话，只做连续、克制、可循环的嘴唇开合；期间自然眨眼4次，伴随非常轻微的点头和肩部呼吸。
14.7–15 秒：停止说话，嘴巴自然闭合，回到与首帧接近的坐姿。
手臂和身体动作幅度小，不挥手，不起身，不转身，不改变坐姿，首尾帧与参考图片保持严格一致。

【摄影机与光照】
固定正面机位，中景，视角与正面播客摄影棚一致。镜头完全静止，不推拉、不平移、不摇镜、不变焦、不切镜。清晰度稳定，25 fps 观感。柔和棚拍主光从画面左前方照射，色温约 4000K，人物受光连续稳定。

【绿幕与后期要求】
这是用于色键抠像的素材，不是完整场景。除人物以外的每一个像素都必须是均匀、纯净、完全相同的 #00FF00；背景 RGB 必须尽量接近 (0,255,0)，饱和度 100%，亮度稳定。禁止灰色、灰绿色、低饱和绿色、渐变、暗角、阴影、地面、家具、桌面、沙发、麦克风、反光、光斑或景深虚化。背景从首帧到末帧不得发生任何颜色变化。人物不能穿绿色或出现绿色配饰。人物轮廓清晰，头发丝、衣服边缘和轻微运动模糊自然。

【禁止内容】
不要生成摄影棚、房间或真实环境。不要把幕布理解成墙面。不要生成灰色背景或自然背景。不新增人物或物体，不出现文字、字幕、Logo、水印、边框；不改变人物身份；不裁切人物；不生成复杂肢体动作；不产生镜头抖动。
""".strip()


def _data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"FFmpeg 处理失败：{result.stderr[-3000:]}")


def _probe_size(path: Path) -> tuple[int, int]:
    result = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "json", str(path),
    ], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"无法读取素材尺寸：{path}")
    stream = (json.loads(result.stdout or "{}").get("streams") or [{}])[0]
    return int(stream["width"]), int(stream["height"])


def _has_alpha(path: Path) -> bool:
    result = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=pix_fmt:stream_tags=alpha_mode",
        "-of", "json", str(path),
    ], capture_output=True, text=True)
    if result.returncode:
        return False
    payload = json.loads(result.stdout or "{}")
    stream = (payload.get("streams") or [{}])[0]
    pixel_format = str(stream.get("pix_fmt", ""))
    tags = {
        str(key).lower(): str(value)
        for key, value in (stream.get("tags") or {}).items()
    }
    alpha_formats = ("rgba", "bgra", "argb", "abgr", "yuva", "gbrap", "ya")
    return (
        pixel_format.startswith(alpha_formats)
        or tags.get("alpha_mode") == "1"
    )


def _alpha_filter(
    source_has_alpha: bool,
    fps: int,
    config: AlphaConfig,
) -> str:
    if source_has_alpha and not config.force_key:
        return f"fps={fps},format=rgba"
    # Key first. Despill changes the screen color, so applying it first makes
    # the following key unable to recognize the requested screen.
    key = (
        f"{config.keyer}={config.ffmpeg_key_color}:"
        f"similarity={config.similarity}:blend={config.blend}"
    )
    before_key = "format=rgba," if config.keyer == "colorkey" else ""
    filters = [f"fps={fps}", f"{before_key}{key}"]
    if config.despill:
        filters.append(
            f"despill=type={config.colors[2]}:mix={config.despill}:"
            f"expand={config.despill_expand}"
        )
    filters.append("format=rgba")
    return ",".join(filters)


def _prepare_screen_reference(
    image_path: Path,
    destination: Path,
    config: AlphaConfig,
) -> Path:
    """Put an RGBA reference on the exact screen color before I2V generation."""
    if not config.prepare_reference:
        return image_path
    width, height = _probe_size(image_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i",
        f"color=c={config.ffmpeg_key_color}:s={width}x{height}",
        "-i", str(image_path),
        "-filter_complex", "[0:v][1:v]overlay=format=auto,format=rgb24",
        "-frames:v", "1", str(destination),
    ])
    return destination


def _screen_prompt(prompt: str, config: AlphaConfig) -> str:
    _, html_color, channel = config.colors
    color_name = "纯绿色" if channel == "green" else "纯蓝色"
    return (
        f"最高优先级输出约束：这是后期色键素材。背景必须是 {html_color} "
        f"{color_name}，RGB 颜色恒定、无纹理、无渐变、无阴影；"
        "不得生成灰色、低饱和背景或任何场景。参考图中的纯色背景必须原样保持。\n\n"
        f"{prompt.replace('#00FF00', html_color).replace('绿色', color_name)}"
    )


def convert_to_alpha_assets(
    source_path: Path,
    output_path: Path,
    fps: int = 25,
    formats: tuple[str, ...] = ("webm",),
    alpha_config: AlphaConfig | None = None,
) -> dict[str, Path]:
    """Convert a Seedance alpha/green-screen master to reusable alpha assets."""
    config = alpha_config or AlphaConfig()
    config.validate()
    allowed = {"webm", "mov", "png", "green", "mp4"}
    unknown = set(formats) - allowed
    if unknown:
        raise ValueError(f"未知输出格式：{', '.join(sorted(unknown))}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    stem = output_path.stem
    source_has_alpha = _has_alpha(source_path)
    filter_chain = _alpha_filter(source_has_alpha, fps, config)
    outputs: dict[str, Path] = {}

    if "mp4" in formats:
        mp4_path = output_path.with_suffix(".mp4")
        if source_path.resolve() != mp4_path.resolve():
            mp4_path.write_bytes(source_path.read_bytes())
        outputs["mp4"] = mp4_path
    if "green" in formats:
        green_path = output_path.parent / f"{stem}-greenscreen.mp4"
        if source_path.resolve() != green_path.resolve():
            green_path.write_bytes(source_path.read_bytes())
        outputs["green"] = green_path
    if "webm" in formats:
        webm_path = output_path.with_suffix(".webm")
        webm_temp = webm_path.with_name(f".{webm_path.stem}.tmp.webm")
        _run([
            "ffmpeg", "-y", "-i", str(source_path), "-an", "-vf", filter_chain,
            "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
            "-auto-alt-ref", "0", "-deadline", "good", "-cpu-used", "3",
            "-crf", "24", "-b:v", "0", str(webm_temp),
        ])
        os.replace(webm_temp, webm_path)
        outputs["webm"] = webm_path
    if "mov" in formats:
        mov_path = output_path.with_suffix(".mov")
        mov_temp = mov_path.with_name(f".{mov_path.stem}.tmp.mov")
        _run([
            "ffmpeg", "-y", "-i", str(source_path), "-an", "-vf", filter_chain,
            "-c:v", "prores_ks", "-profile:v", "4",
            "-pix_fmt", "yuva444p10le", str(mov_temp),
        ])
        os.replace(mov_temp, mov_path)
        outputs["mov"] = mov_path
    if "png" in formats:
        frames_dir = output_path.parent / f"{stem}-png"
        frames_dir.mkdir(parents=True, exist_ok=True)
        _run([
            "ffmpeg", "-y", "-i", str(source_path), "-an", "-vf", filter_chain,
            "-pix_fmt", "rgba", str(frames_dir / "frame-%06d.png"),
        ])
        outputs["png"] = frames_dir

    manifest = {
        "version": 2,
        "source": source_path.name,
        "source_has_alpha": source_has_alpha,
        "alpha_config": asdict(config),
        "resolved_key_color": (
            config.ffmpeg_key_color
            if not source_has_alpha or config.force_key
            else None
        ),
        "fps": fps,
        "time_base": f"1/{fps}",
        "outputs": {name: str(path) for name, path in outputs.items()},
    }
    manifest_path = output_path.parent / f"{stem}-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    outputs["manifest"] = manifest_path
    return outputs


def generate_character_motion(
    image_paths: list[Path],
    output_path: Path,
    prompt: str | None = None,
    model: str | None = None,
    duration: int = 5,
    resolution: str = "720p",
    ratio: str = "1:1",
    fps: int = 25,
    output_formats: tuple[str, ...] = ("webm", "green"),
    alpha_config: AlphaConfig | None = None,
    poll_interval: int = 5,
    timeout: int = 900,
) -> Path:
    """Generate one character at a time and return the primary alpha asset."""
    config = alpha_config or AlphaConfig()
    config.validate()
    prompt = (
        (prompt or "").strip()
        or os.getenv("SEEDANCE_PROMPT", "").strip()
        or DEFAULT_PROMPT
    )
    prompt = _screen_prompt(prompt, config)
    api_key = os.getenv("ARK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("未配置 ARK_API_KEY")
    # print(image_paths)
    if not image_paths or any(not path.is_file() for path in image_paths):
        raise ValueError("角色参考图不存在")
    if len(image_paths) != 1:
        raise ValueError(
            "透明人物动作应每次只生成一个人物；请分别生成两人，以避免遮挡和身份漂移"
        )
    if not 4 <= duration <= 15:
        raise ValueError("Seedance 2.0 Mini 时长需为 4–15 秒")
    if fps not in {25, 30, 60}:
        raise ValueError("动作素材帧率应为 25、30 或 60 fps")

    client = Ark(
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key=api_key,
        timeout=120,
    )
    prepared_reference = _prepare_screen_reference(
        image_paths[0],
        output_path.parent / f"{output_path.stem}-reference-{config.screen}.png",
        config,
    )
    # print(prompt)
    # time.sleep(10)
    content = [
        {"type": "text", "text": prompt},
        {
            "type": "image_url",
            "image_url": {"url": _data_url(prepared_reference)},
            "role": "reference_image",
        },
    ]
    task = client.content_generation.tasks.create(
        model=model or os.getenv("SEEDANCE_MODEL", DEFAULT_MODEL),
        content=content,
        duration=duration,
        resolution=resolution,
        ratio=ratio,
        generate_audio=False,
        # Mini/Fast do not accept camera_fixed; the prompt fixes the camera.
        watermark=False,
    )
    print(f"[Seedance] task={task.id}", flush=True)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = client.content_generation.tasks.get(task_id=task.id)
        print(f"[Seedance] status={result.status}", flush=True)
        if result.status == "succeeded":
            video_url = result.content.video_url
            output_path.parent.mkdir(parents=True, exist_ok=True)
            screen_path = (
                output_path.with_suffix(".mp4")
                if "mp4" in output_formats
                else output_path.parent
                / f"{output_path.stem}-{config.screen}screen-source.mp4"
            )
            opener = build_opener(ProxyHandler({}))
            with opener.open(video_url, timeout=180) as response:
                screen_path.write_bytes(response.read())
            print(
                f"[Seedance] {config.screen} 幕布母版（无 Alpha）：{screen_path}",
                flush=True,
            )
            outputs = convert_to_alpha_assets(
                screen_path,
                output_path,
                fps=fps,
                formats=output_formats,
                alpha_config=config,
            )
            for name, path in outputs.items():
                if name != "manifest":
                    print(f"[Seedance] {name} 输出：{path}", flush=True)
            for preferred in output_formats:
                if preferred in outputs:
                    return outputs[preferred]
            raise RuntimeError("未生成任何人物动作输出")
        if result.status in {"failed", "cancelled"}:
            message = getattr(result.error, "message", "") or "任务生成失败"
            code = getattr(result.error, "code", "")
            raise RuntimeError(f"Seedance {result.status}: {code} {message}".strip())
        time.sleep(poll_interval)
    raise TimeoutError(f"Seedance 任务 {task.id} 在 {timeout} 秒内未完成")
