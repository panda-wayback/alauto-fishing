"""真机自动拉鱼：五段实现（locate / capture / detect / decide / act）。"""

from autofish.bus import AutofishBus, AutofishSnapshot
from autofish.detect import (
    BobberHit,
    find_bobber,
    green_zone_mask,
    pixel_to_pos,
)
from autofish.capture import (
    DEFAULT_SCREEN_PATH,
    ScreenGrab,
    grab_primary,
    grab_roi,
    load_screen,
    save_screen,
)
from autofish.locate import DEFAULT_ROI_PATH, Roi, load_roi, save_roi
from autofish.pipeline import AutofishPipeline
from autofish.topics import FishingState, Topic

__all__ = [
    "AutofishBus",
    "AutofishPipeline",
    "AutofishSnapshot",
    "BobberHit",
    "DEFAULT_ROI_PATH",
    "DEFAULT_SCREEN_PATH",
    "FishingState",
    "Roi",
    "ScreenGrab",
    "Topic",
    "find_bobber",
    "grab_primary",
    "grab_roi",
    "green_zone_mask",
    "load_roi",
    "load_screen",
    "pixel_to_pos",
    "save_roi",
    "save_screen",
]
