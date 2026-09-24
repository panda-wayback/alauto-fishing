"""段3：识别。统一入口 detect(rgb)。"""

from autofish.detect.api import (
    BarDetector,
    apply_manual_bar,
    detect,
    get_detector,
)
from autofish.detect.bobber import BobberHit
from autofish.detect.bobber_anchor import BobberAnchorDetector
from autofish.detect.find_bobber import BobberLoc, FindBobber

__all__ = [
    "BarDetector",
    "BobberAnchorDetector",
    "BobberHit",
    "BobberLoc",
    "DetectorWorker",
    "FindBobber",
    "apply_manual_bar",
    "detect",
    "get_detector",
]


def __getattr__(name: str):
    if name == "DetectorWorker":
        from autofish.detect.worker import DetectorWorker

        return DetectorWorker
    raise AttributeError(name)
