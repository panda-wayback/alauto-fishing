"""段1：圈定范围。"""

from autofish.locate.roi import DEFAULT_ROI_PATH, Roi, load_roi, save_roi

__all__ = [
    "DEFAULT_ROI_PATH",
    "LocatorWorker",
    "Roi",
    "load_roi",
    "roi_from_green_rgb",
    "save_roi",
]


def __getattr__(name: str):
    if name == "LocatorWorker":
        from autofish.locate.worker import LocatorWorker

        return LocatorWorker
    if name == "roi_from_green_rgb":
        from autofish.locate.worker import roi_from_green_rgb

        return roi_from_green_rgb
    raise AttributeError(name)
