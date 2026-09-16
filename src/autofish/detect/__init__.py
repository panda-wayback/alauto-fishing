"""段3：识别。"""

from autofish.detect.bobber import (
    BobberHit,
    find_bobber,
    find_green_bar,
    find_green_span,
    green_zone_mask,
    pixel_to_pos,
    white_mask,
)

__all__ = [
    "BobberHit",
    "DetectorWorker",
    "find_bobber",
    "find_green_bar",
    "find_green_span",
    "green_zone_mask",
    "pixel_to_pos",
    "white_mask",
]


def __getattr__(name: str):
    if name == "DetectorWorker":
        from autofish.detect.worker import DetectorWorker

        return DetectorWorker
    raise AttributeError(name)
