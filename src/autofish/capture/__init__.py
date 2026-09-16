"""段2：截图。"""

from autofish.capture.screen import (
    DEFAULT_SCREEN_PATH,
    ScreenGrab,
    grab_primary,
    grab_roi,
    load_screen,
    save_screen,
    warmup,
)

__all__ = [
    "DEFAULT_SCREEN_PATH",
    "CaptureWorker",
    "ScreenGrab",
    "grab_primary",
    "grab_roi",
    "load_screen",
    "save_screen",
    "warmup",
]


def __getattr__(name: str):
    if name == "CaptureWorker":
        from autofish.capture.worker import CaptureWorker

        return CaptureWorker
    raise AttributeError(name)
