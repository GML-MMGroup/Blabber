import math

import cv2
import numpy as np


def _breathing_scale(t: float, period: float = 3.2, amplitude: float = 0.012) -> float:
    return 1.0 + amplitude * math.sin(2 * math.pi * t / period)


def _sway_offset(t: float, period: float = 5.0, amplitude_px: float = 3.0) -> tuple:
    dx = amplitude_px * math.sin(2 * math.pi * t / period)
    dy = amplitude_px * 0.4 * math.cos(2 * math.pi * t / period * 0.7)
    return dx, dy


def _apply_transform(image: np.ndarray, scale: float, dx: float, dy: float) -> np.ndarray:
    h, w = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle=0, scale=scale)
    matrix[0, 2] += dx
    matrix[1, 2] += dy
    return cv2.warpAffine(image, matrix, (w, h), borderMode=cv2.BORDER_REPLICATE)


def _blink_factor(t: float, period: float = 4.0, blink_duration: float = 0.20) -> float:
    """A subtle procedural squint.

    Aggressively collapsing a single raster image creates visible skin
    streaks, so the MVP limits compression to 28%. Wav2Lip still receives
    natural eye motion without introducing block artifacts.
    """
    phase = t % period
    if phase > blink_duration:
        return 1.0
    half = blink_duration / 2
    progress = phase / half if phase < half else (blink_duration - phase) / half
    return max(0.72, 1.0 - progress * 0.28)


def _apply_blink(frame: np.ndarray, box, t: float, phase_offset: float = 0.0) -> None:
    """Vertically compresses one tightly calibrated eye box in place."""
    eye_band = frame[box.y1:box.y2, box.x1:box.x2]
    if eye_band.size == 0:
        return

    factor = _blink_factor(t + phase_offset)
    if factor >= 0.999:
        return

    band_h = eye_band.shape[0]
    squashed_h = max(1, int(band_h * factor))
    squashed = cv2.resize(eye_band, (eye_band.shape[1], squashed_h))
    pad_top = (band_h - squashed_h) // 2
    pad_bottom = band_h - squashed_h - pad_top
    rows = []
    if pad_top > 0:
        rows.append(np.repeat(squashed[:1], pad_top, axis=0))
    rows.append(squashed)
    if pad_bottom > 0:
        rows.append(np.repeat(squashed[-1:], pad_bottom, axis=0))
    blink_patch = np.concatenate(rows, axis=0)

    # Blend through a soft inset mask so the transformed patch has no hard
    # rectangular boundary against the surrounding face.
    mask = np.zeros((band_h, eye_band.shape[1]), dtype=np.float32)
    inset_x = min(8, max(2, eye_band.shape[1] // 8))
    inset_y = min(6, max(2, band_h // 8))
    mask[inset_y:band_h - inset_y, inset_x:eye_band.shape[1] - inset_x] = 1.0
    mask = cv2.GaussianBlur(mask, (15, 15), 0)[..., None]
    blended = eye_band.astype(np.float32) * (1 - mask) + blink_patch.astype(np.float32) * mask
    frame[box.y1:box.y2, box.x1:box.x2] = blended.astype(np.uint8)


def render_idle_frames(image: np.ndarray, duration_seconds: float, fps: int, eye_groups: list = None) -> list:
    """Procedurally animates `image` with breathing, sway and periodic blinks.

    Pure opencv/numpy, no ML model involved — cheap enough to regenerate
    per turn rather than caching.
    """
    total_frames = max(1, round(duration_seconds * fps))
    frames = []
    for i in range(total_frames):
        t = i / fps
        scale = _breathing_scale(t)
        dx, dy = _sway_offset(t)
        frame = _apply_transform(image, scale, dx, dy)
        if eye_groups:
            for host_index, eye_boxes in enumerate(eye_groups):
                # Both eyes for one host blink together; hosts are offset so
                # they do not blink in lockstep.
                for eye_box in eye_boxes:
                    _apply_blink(frame, eye_box, t, phase_offset=host_index * 1.7)
        frames.append(frame)
    return frames
