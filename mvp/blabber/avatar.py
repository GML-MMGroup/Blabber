from dataclasses import dataclass
from pathlib import Path

AVATAR_DIR = Path(__file__).parent / "Avatar"
DEFAULT_AVATAR_IMAGE = AVATAR_DIR / "微信图片_20260723162722_383_2711.png"

# HostA/HostB order follows script_generator's speaker naming, mapped
# left-to-right in the source image.
SPEAKER_ORDER = ["HostA", "HostB"]


@dataclass
class BBox:
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    def crop(self, image):
        return image[self.y1 : self.y2, self.x1 : self.x2]


# Manually calibrated once (by visual inspection) for DEFAULT_AVATAR_IMAGE.
# opencv-python's newer wheel ships no Haar cascade data and no bundled DNN
# face detector model, so auto-detection isn't free here; since this MVP
# pins a single fixed avatar image, a hardcoded region per host is simpler
# and more reliable than pulling in another model just to detect two faces
# in one picture we've already looked at.
_KNOWN_FACE_REGIONS = {
    str(DEFAULT_AVATAR_IMAGE): {
        "HostA": BBox(80, 120, 560, 620),
        "HostB": BBox(680, 180, 1180, 680),
    }
}

# Tight per-eye regions for the default 1254×1254 two-host image. Keeping
# these separate from the much larger face crops prevents the blink effect
# from compressing forehead, hair, nose, and cheeks.
_KNOWN_EYE_REGIONS = {
    str(DEFAULT_AVATAR_IMAGE): {
        "HostA": [
            BBox(284, 370, 352, 429),
            BBox(378, 357, 442, 416),
        ],
        "HostB": [
            BBox(803, 455, 849, 515),
            BBox(886, 466, 956, 528),
        ],
    }
}


def get_face_regions(image_path: Path = DEFAULT_AVATAR_IMAGE) -> dict:
    """Returns {"HostA": BBox, "HostB": BBox} for the given avatar image."""
    image_path = Path(image_path)
    regions = _KNOWN_FACE_REGIONS.get(str(image_path))
    if regions is None:
        raise RuntimeError(
            f"{image_path.name} 还没有配置人脸区域，请先在 avatar.py 的 "
            "_KNOWN_FACE_REGIONS 里手动标定这张图里两个人的脸部框。"
        )
    return regions


def get_eye_regions(image_path: Path = DEFAULT_AVATAR_IMAGE) -> dict:
    """Returns tight eye boxes grouped by speaker for procedural blinking."""
    image_path = Path(image_path)
    regions = _KNOWN_EYE_REGIONS.get(str(image_path))
    if regions is None:
        raise RuntimeError(
            f"{image_path.name} 还没有配置眼睛区域，请先在 avatar.py 的 "
            "_KNOWN_EYE_REGIONS 里手动标定。"
        )
    return regions
