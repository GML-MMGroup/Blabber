from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=None)
def resolve_media_binary(name: str) -> str:
    """Resolve ffmpeg/ffprobe even when a Windows service has a stale PATH."""
    normalized = name.lower().removesuffix(".exe")
    env_name = f"{normalized.upper()}_BINARY"
    configured = os.environ.get(env_name)
    if configured and Path(configured).is_file():
        return str(Path(configured).resolve())

    discovered = shutil.which(normalized)
    if discovered:
        return discovered

    candidates: list[Path] = []
    if os.name == "nt":
        local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        winget_root = local_app_data / "Microsoft" / "WinGet" / "Packages"
        if winget_root.is_dir():
            candidates.extend(winget_root.glob(f"Gyan.FFmpeg_*/*/bin/{normalized}.exe"))
        candidates.extend([
            Path("C:/Program Files/ffmpeg/bin") / f"{normalized}.exe",
            Path("C:/ffmpeg/bin") / f"{normalized}.exe",
        ])

    existing = [path for path in candidates if path.is_file()]
    if existing:
        return str(max(existing, key=lambda path: path.stat().st_mtime))

    raise FileNotFoundError(
        f"找不到 {normalized}。请安装 FFmpeg，或通过 {env_name} 指定可执行文件路径。"
    )


def ffmpeg_binary() -> str:
    return resolve_media_binary("ffmpeg")


def ffprobe_binary() -> str:
    return resolve_media_binary("ffprobe")

def ensure_media_tools_on_path() -> None:
    """Expose the resolved tool directory to libraries that only inspect PATH."""
    binary_dir = str(Path(ffmpeg_binary()).parent)
    current = os.environ.get("PATH", "")
    entries = current.split(os.pathsep) if current else []
    if binary_dir.casefold() not in {entry.casefold() for entry in entries}:
        os.environ["PATH"] = binary_dir + (os.pathsep + current if current else "")