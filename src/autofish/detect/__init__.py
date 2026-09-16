"""段3：识别。"""

from autofish.detect.bobber import (
    BobberHit,
    find_bobber,
    green_zone_mask,
    orange_mask,
    pixel_to_pos,
)
from autofish.detect.hsv_calib import ZoneHsv, load_zone_hsv, sample_zone_hsv, save_zone_hsv
from autofish.detect.smooth import PosSmoother

__all__ = [
    "BobberHit",
    "DetectorWorker",
    "PosSmoother",
    "ZoneHsv",
    "find_bobber",
    "green_zone_mask",
    "load_zone_hsv",
    "orange_mask",
    "pixel_to_pos",
    "sample_zone_hsv",
    "save_zone_hsv",
]


def __getattr__(name: str):
    if name == "DetectorWorker":
        from autofish.detect.worker import DetectorWorker

        return DetectorWorker
    raise AttributeError(name)
