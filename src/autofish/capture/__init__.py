"""段2：截图。"""

from autofish.capture.screen import (
    DEFAULT_SCREEN_PATH,
    ScreenGrab,
    grab_primary,
    grab_roi,
    load_screen,
    roi_frame_size,
    save_screen,
    warmup,
)

__all__ = [
    "DEFAULT_SCREEN_PATH",
    "CaptureWorker",
    "ScreenGrab",
    "default_capture_fps",
    "grab_primary",
    "grab_roi",
    "load_screen",
    "roi_frame_size",
    "save_screen",
    "warmup",
]


def __getattr__(name: str):
    if name == "CaptureWorker":
        from autofish.capture.worker import CaptureWorker

        return CaptureWorker
    if name == "default_capture_fps":
        from autofish.capture.worker import default_capture_fps

        return default_capture_fps
    raise AttributeError(name)
