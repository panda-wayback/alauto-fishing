"""段1：圈定范围。"""

from autofish.locate.roi import (
    DEFAULT_BAR_TEMPLATE,
    DEFAULT_ROI_PATH,
    Roi,
    load_roi,
    save_roi,
)

__all__ = [
    "DEFAULT_BAR_TEMPLATE",
    "DEFAULT_ROI_PATH",
    "LocatorWorker",
    "Roi",
    "load_roi",
    "save_roi",
]


def __getattr__(name: str):
    if name == "LocatorWorker":
        from autofish.locate.worker import LocatorWorker

        return LocatorWorker
    raise AttributeError(name)
