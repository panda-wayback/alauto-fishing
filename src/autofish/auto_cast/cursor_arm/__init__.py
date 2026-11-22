"""系统光标外形认漂（可开抛门闩）。"""

from autofish.auto_cast.cursor_arm.detect import (
    classify_cursor_shape,
    see_fishing_hook,
    see_surface_bobber,
)
from autofish.auto_cast.cursor_arm.grab import grab_around_cursor, grab_system_cursor
from autofish.auto_cast.cursor_arm.watcher import CursorArmWatcher

__all__ = [
    "CursorArmWatcher",
    "classify_cursor_shape",
    "grab_around_cursor",
    "grab_system_cursor",
    "see_fishing_hook",
    "see_surface_bobber",
]
