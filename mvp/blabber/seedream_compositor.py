from __future__ import annotations

import base64
import mimetypes
import os
import subprocess
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = PROJECT_ROOT / "assets"
OUTPUT_ROOT = Path(__file__).resolve().parents[1] / "generated_scenes"

PRESET_IMAGES = {
    "cartoon": (
        "character/funny-podcast-duck.png",
        "character/funny-podcast-dog.png",
        "background/zoo_background.png",
    ),
}

DEFAULT_PROMPT = (
    "图一是鸭子主持人嘎嘎，图二是狗狗主持人阿汪，图三是动物园播客背景。"
    "将图一和图二的两位角色自然合成到图三的场景中，嘎嘎坐在左侧麦克风前，"
    "阿汪坐在右侧麦克风前。严格保持两位角色的脸部特征、服装、耳机和"
    "原有美术风格，保持背景的空间布局、灯光和 ON AIR 标牌。人物比例协调，"
    "视线自然，双手与桌面关系合理，画面为正方形播客视频封面构图。不要增加"
    "第三个角色，不要改变角色物种，不要添加水印或额外文字。"
)


def _data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def generate_composite_scene(
    character_set: str,
    prompt: str | None = None,
) -> Path:
    api_key = os.getenv("ARK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("未配置 ARK_API_KEY")
    if character_set not in PRESET_IMAGES:
        raise ValueError("未知的人物组合")
    try:
        from volcenginesdkarkruntime import Ark
    except ImportError as error:
        raise RuntimeError(
            "未安装 volcengine-python-sdk[ark]"
        ) from error

    source_names = PRESET_IMAGES[character_set]
    images = [_data_url(ASSET_ROOT / name) for name in source_names]
    client = Ark(
        base_url=os.getenv(
            "ARK_BASE_URL",
            "https://ark.cn-beijing.volces.com/api/v3",
        ).strip(),
        api_key=api_key,
    )
    response = client.images.generate(
        model=os.getenv(
            "ARK_IMAGE_MODEL",
            "doubao-seedream-5-0-lite-260128",
        ).strip(),
        prompt=(prompt or DEFAULT_PROMPT).strip(),
        image=images,
        size="2K",
        output_format="png",
        response_format="url",
        watermark=False,
    )
    try:
        image_url = response.data[0].url
    except (AttributeError, IndexError, TypeError) as error:
        raise RuntimeError(f"Seedream 未返回图片：{response}") from error

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_ROOT / f"{character_set}-{uuid.uuid4().hex[:12]}.png"
    result = subprocess.run(
        [
            "curl", "-L", "--fail", "--silent", "--show-error",
            "--max-time", "180", "-o", str(out_path), image_url,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode or not out_path.is_file() or not out_path.stat().st_size:
        raise RuntimeError(f"Seedream 图片下载失败：{result.stderr[-500:]}")
    return out_path
