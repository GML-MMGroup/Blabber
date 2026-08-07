from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import numpy as np


def _subject_alpha(frame: np.ndarray) -> np.ndarray:
    """Extract a generated character from the light neutral Seedance backdrop."""
    h, w = frame.shape[:2]
    small = cv2.resize(frame, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    sh, sw = small.shape[:2]
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    saturation, value = hsv[:, :, 1], hsv[:, :, 2]
    mask = np.full((sh, sw), cv2.GC_BGD, np.uint8)
    mask[8:sh - 24, round(sw*.08):round(sw*.92)] = cv2.GC_PR_FGD
    # Confident colored/dark pixels anchor hair, skin, clothing and headphones.
    confident = ((saturation > 48) | (value < 105))
    center = np.zeros_like(confident)
    center[10:sh - 24, round(sw*.14):round(sw*.86)] = True
    mask[confident & center] = cv2.GC_FGD
    mask[:8] = cv2.GC_BGD
    mask[:, :round(sw*.07)] = cv2.GC_BGD
    mask[:, -round(sw*.07):] = cv2.GC_BGD
    mask[-24:] = cv2.GC_BGD
    bg_model = np.zeros((1, 65), np.float64)
    fg_model = np.zeros((1, 65), np.float64)
    cv2.grabCut(small, mask, None, bg_model, fg_model, 2, cv2.GC_INIT_WITH_MASK)
    alpha = np.where(
        (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0,
    ).astype(np.uint8)
    alpha = cv2.morphologyEx(alpha, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    alpha = cv2.resize(alpha, (w, h), interpolation=cv2.INTER_LINEAR)
    return cv2.GaussianBlur(alpha, (0, 0), 1.8)


def _foreground_occlusion(scene: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Build target-scene table and microphone layers that sit before actors."""
    h, w = scene.shape[:2]
    alpha = np.zeros((h, w), np.uint8)
    table_y = round(h * .801)
    table_ramp = np.linspace(0, 255, 10, dtype=np.uint8)
    alpha[table_y:table_y + 10] = table_ramp[:, None]
    alpha[table_y + 10:] = 255

    # Explicit scene2 geometry keeps microphones entirely in front without
    # accidentally promoting similarly dark couch/brick pixels.
    mic = np.zeros_like(alpha)
    cv2.ellipse(mic, (278, 672), (51, 96), -34, 0, 360, 255, -1)
    cv2.ellipse(mic, (939, 704), (51, 98), -35, 0, 360, 255, -1)
    cv2.line(mic, (273, 728), (273, 1048), 255, 31)
    cv2.line(mic, (967, 760), (967, 1048), 255, 31)
    cv2.ellipse(mic, (273, 1053), (116, 37), 0, 0, 360, 255, -1)
    cv2.ellipse(mic, (967, 1053), (116, 37), 0, 0, 360, 255, -1)
    for p1, p2 in [
        ((198, 615), (352, 765)), ((216, 590), (365, 728)),
        ((850, 650), (1025, 815)), ((867, 621), (1038, 778)),
    ]:
        cv2.line(mic, p1, p2, 255, 12)
    alpha = np.maximum(alpha, cv2.GaussianBlur(mic, (0, 0), .9))
    return scene, alpha


def _contact_shadow(
    canvas: np.ndarray,
    center_x: int,
    center_y: int,
    axes: tuple[int, int],
    strength: float = .34,
) -> None:
    """Add a soft grounding shadow where the actor meets the seat/table plane."""
    mask = np.zeros(canvas.shape[:2], np.uint8)
    cv2.ellipse(mask, (center_x, center_y), axes, 0, 0, 360, 255, -1)
    mask = cv2.GaussianBlur(mask, (0, 0), axes[1] * .55)
    amount = mask.astype(np.float32)[:, :, None] / 255 * strength
    # Warm shadows retain a little red bounce from the brick/neon environment.
    shadow_color = np.array([8, 12, 20], np.float32)
    canvas[:] = (
        canvas.astype(np.float32) * (1 - amount)
        + shadow_color * amount
    ).astype(np.uint8)


def _place_actor(
    canvas: np.ndarray,
    actor: np.ndarray,
    alpha: np.ndarray,
    center_x: int,
    bottom_y: int,
    height: int,
) -> np.ndarray:
    scale = height / actor.shape[0]
    width = round(actor.shape[1] * scale)
    actor = cv2.resize(actor, (width, height), interpolation=cv2.INTER_LANCZOS4)
    alpha = cv2.resize(alpha, (width, height), interpolation=cv2.INTER_LINEAR)
    x1, y1 = center_x - width // 2, bottom_y - height
    x2, y2 = x1 + width, y1 + height

    # Warm reflected studio light and reduce the source's bright-wall spill.
    graded = actor.astype(np.float32)
    graded[:, :, 0] *= .75
    graded[:, :, 1] *= .88
    graded[:, :, 2] *= 1.07
    # Match the darker studio exposure while keeping faces readable.
    graded = (graded - 128) * .96 + 124
    graded = np.clip(graded, 0, 255).astype(np.uint8)

    # Soft cast shadow gives separation from the couch/wall.
    shadow_alpha = cv2.GaussianBlur(alpha, (0, 0), 20).astype(np.float32) / 255 * .32
    sx1, sy1 = x1 + 14, y1 + 17
    region = canvas[sy1:sy1 + height, sx1:sx1 + width].astype(np.float32)
    region *= (1 - shadow_alpha[:, :, None])
    canvas[sy1:sy1 + height, sx1:sx1 + width] = region.astype(np.uint8)

    # Edge decontamination: shrink the opaque core slightly and let scene light
    # bleed through the final two pixels instead of retaining a pale source halo.
    alpha = cv2.erode(alpha, np.ones((3, 3), np.uint8))
    alpha = cv2.GaussianBlur(alpha, (0, 0), 1.2)
    a = alpha.astype(np.float32)[:, :, None] / 255
    region = canvas[y1:y2, x1:x2].astype(np.float32)
    canvas[y1:y2, x1:x2] = (
        graded.astype(np.float32) * a + region * (1 - a)
    ).astype(np.uint8)
    return canvas


def composite_action_scene(
    male_video: Path,
    female_video: Path,
    background: Path,
    output: Path,
) -> Path:
    scene = cv2.imread(str(background))
    if scene is None:
        raise ValueError(f"无法读取背景：{background}")
    scene = cv2.resize(scene, (1254, 1254), interpolation=cv2.INTER_LANCZOS4)
    # Depth of field: distant wall is softer, couch remains moderately sharp,
    # and the foreground table/microphones are restored at full detail later.
    far = cv2.GaussianBlur(scene, (0, 0), 2.2)
    near = cv2.GaussianBlur(scene, (0, 0), .7)
    depth = np.linspace(0, 1, scene.shape[0], dtype=np.float32)[:, None, None]
    base = (far.astype(np.float32) * (1 - depth) + near.astype(np.float32) * depth)
    base = base.astype(np.uint8)
    foreground, foreground_alpha = _foreground_occlusion(scene)

    male = cv2.VideoCapture(str(male_video))
    female = cv2.VideoCapture(str(female_video))
    if not male.isOpened() or not female.isOpened():
        raise ValueError("无法读取 action 中的角色视频")
    fps = min(male.get(cv2.CAP_PROP_FPS), female.get(cv2.CAP_PROP_FPS)) or 24
    frames = int(min(
        male.get(cv2.CAP_PROP_FRAME_COUNT),
        female.get(cv2.CAP_PROP_FRAME_COUNT),
    ))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f"{output.stem}-temporary.mp4")
    writer = cv2.VideoWriter(
        str(temporary), cv2.VideoWriter_fourcc(*"mp4v"), fps, (1254, 1254),
    )
    if not writer.isOpened():
        raise RuntimeError("无法创建场景合成视频")

    for index in range(frames):
        ok_m, frame_m = male.read()
        ok_f, frame_f = female.read()
        if not ok_m or not ok_f:
            break
        canvas = base.copy()
        _contact_shadow(canvas, 420, 984, (220, 58), .40)
        _contact_shadow(canvas, 835, 984, (220, 58), .40)
        canvas = _place_actor(
            canvas, frame_m, _subject_alpha(frame_m),
            center_x=420, bottom_y=1092, height=730,
        )
        canvas = _place_actor(
            canvas, frame_f, _subject_alpha(frame_f),
            center_x=835, bottom_y=1092, height=730,
        )
        a = foreground_alpha.astype(np.float32)[:, :, None] / 255
        canvas = (
            foreground.astype(np.float32) * a + canvas.astype(np.float32) * (1 - a)
        ).astype(np.uint8)
        writer.write(canvas)
        if index and index % 48 == 0:
            print(f"[场景合成] {index}/{frames} 帧", flush=True)
    writer.release()
    male.release()
    female.release()

    result = subprocess.run([
        "ffmpeg", "-y", "-i", str(temporary), "-c:v", "libx264",
        "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(output),
    ], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"视频编码失败：{result.stderr[-2000:]}")
    return output
