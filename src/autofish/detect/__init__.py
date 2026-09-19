"""段3：识别。统一入口 detect(rgb)；方法可 set_detector 替换。"""

from autofish.detect.api import (
    BarDetector,
    apply_manual_bar,
    detect,
    find_bar,
    get_detector,
    set_detector,
    use_bobber_anchor,
    use_color_blocks,
    use_template,
)
from autofish.detect.bobber import (
    BobberHit,
    bobber_in_bar,
    find_bobber as find_bobber_color,
    find_green_bar,
    find_green_span,
    green_zone_mask,
    pixel_to_pos,
    white_mask,
)
from autofish.detect.bobber_anchor import BobberAnchorDetector
from autofish.detect.color_blocks import ColorBlocksDetector
from autofish.detect.find_bobber import BobberLoc, FindBobber
from autofish.detect.template_bar import TemplateBarDetector

# 兼容旧名：find_bobber = 当前识别器统一入口
find_bobber = detect

__all__ = [
    "BarDetector",
    "BobberAnchorDetector",
    "BobberHit",
    "BobberLoc",
    "ColorBlocksDetector",
    "DetectorWorker",
    "FindBobber",
    "TemplateBarDetector",
    "apply_manual_bar",
    "bobber_in_bar",
    "detect",
    "find_bar",
    "find_bobber",
    "find_bobber_color",
    "find_green_bar",
    "find_green_span",
    "get_detector",
    "green_zone_mask",
    "pixel_to_pos",
    "set_detector",
    "use_bobber_anchor",
    "use_color_blocks",
    "use_template",
    "white_mask",
]


def __getattr__(name: str):
    if name == "DetectorWorker":
        from autofish.detect.worker import DetectorWorker

        return DetectorWorker
    raise AttributeError(name)
