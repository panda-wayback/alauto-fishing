"""手动标定的屏幕截取区域；可选手动条界（Frame 坐标）。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from common.paths import data_root

DEFAULT_ROI_PATH = data_root() / "roi.json"
DEFAULT_BAR_REF_PATH = data_root() / "bar_ref.png"
# 无存盘时：居中，宽高各为屏幕 1/4
_DEFAULT_ROI_FRAC = 0.25
ROI_SOURCE_DEFAULT = "default"
ROI_SOURCE_MANUAL = "manual"


@dataclass(frozen=True)
class Roi:
    left: int
    top: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("ROI width/height must be positive")
        if self.left < 0 or self.top < 0:
            raise ValueError("ROI left/top must be >= 0")

    def as_mss(self) -> dict[str, int]:
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }


def default_center_roi(screen_w: int, screen_h: int) -> Roi:
    """主屏居中默认手框：宽、高各为屏幕的 1/4。"""
    if screen_w <= 0 or screen_h <= 0:
        raise ValueError("screen size must be positive")
    width = max(32, int(round(screen_w * _DEFAULT_ROI_FRAC)))
    height = max(32, int(round(screen_h * _DEFAULT_ROI_FRAC)))
    width = min(width, screen_w)
    height = min(height, screen_h)
    left = max(0, (screen_w - width) // 2)
    top = max(0, (screen_h - height) // 2)
    return Roi(left=left, top=top, width=width, height=height)


def primary_screen_size() -> tuple[int, int]:
    """主屏逻辑宽高（mss monitor[1]）。"""
    try:
        import mss
    except ImportError as exc:  # pragma: no cover
        raise ImportError("需要安装 mss") from exc
    with mss.mss() as sct:
        mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        return int(mon["width"]), int(mon["height"])


@dataclass(frozen=True)
class BarMark:
    """Frame 内条左右界（与当前 ROI 截帧同坐标系）。"""

    left: float
    right: float
    top: float = 0.0
    height: float = 0.0

    def __post_init__(self) -> None:
        if self.right - self.left < 8:
            raise ValueError("bar width too small")
        if self.height < 0:
            raise ValueError("bar height must be >= 0")

    @property
    def width(self) -> float:
        return float(self.right - self.left)

    def as_box(self) -> tuple[float, float, float, float]:
        """(left, top, width, height)。"""
        h = self.height if self.height > 0 else 1.0
        return (float(self.left), float(self.top), float(self.width), float(h))


def _bar_from_data(data: dict) -> BarMark | None:
    if "bar_left" not in data or "bar_right" not in data:
        return None
    return BarMark(
        left=float(data["bar_left"]),
        right=float(data["bar_right"]),
        top=float(data.get("bar_top", 0.0)),
        height=float(data.get("bar_height", 0.0)),
    )


def load_roi(path: Path | None = None) -> Roi:
    p = path or DEFAULT_ROI_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    return Roi(
        left=int(data["left"]),
        top=int(data["top"]),
        width=int(data["width"]),
        height=int(data["height"]),
    )


def load_bar_mark(path: Path | None = None) -> BarMark | None:
    p = path or DEFAULT_ROI_PATH
    if not p.is_file():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    try:
        return _bar_from_data(data)
    except ValueError:
        return None


def load_roi_source(path: Path | None = None) -> str:
    """存盘来源：manual | default；缺省或未知当 manual（手调优先语义）。"""
    p = path or DEFAULT_ROI_PATH
    if not p.is_file():
        return ROI_SOURCE_DEFAULT
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ROI_SOURCE_MANUAL
    src = str(data.get("source", ROI_SOURCE_MANUAL)).strip().lower()
    if src == ROI_SOURCE_DEFAULT:
        return ROI_SOURCE_DEFAULT
    return ROI_SOURCE_MANUAL


def save_roi(
    roi: Roi,
    path: Path | None = None,
    *,
    bar: BarMark | None = None,
    keep_bar: bool = False,
    source: str | None = None,
) -> Path:
    """写 ROI。keep_bar=True 时保留文件中已有手动条界；bar= 显式写入或清除。
    source= manual|default；None 则保留文件已有来源（无则 manual）。"""
    p = path or DEFAULT_ROI_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(roi)
    if source is None:
        src = load_roi_source(p) if p.is_file() else ROI_SOURCE_MANUAL
    elif source == ROI_SOURCE_DEFAULT:
        src = ROI_SOURCE_DEFAULT
    else:
        src = ROI_SOURCE_MANUAL
    data["source"] = src
    existing_bar: BarMark | None = None
    if p.is_file() and (keep_bar or bar is not None):
        try:
            existing_bar = _bar_from_data(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, ValueError, KeyError, TypeError):
            existing_bar = None
    use = bar if bar is not None else (existing_bar if keep_bar else None)
    if use is not None:
        data["bar_left"] = float(use.left)
        data["bar_right"] = float(use.right)
        data["bar_top"] = float(use.top)
        data["bar_height"] = float(use.height)
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return p


def clear_bar_mark(path: Path | None = None) -> None:
    p = path or DEFAULT_ROI_PATH
    if not p.is_file():
        return
    data = json.loads(p.read_text(encoding="utf-8"))
    for k in ("bar_left", "bar_right", "bar_top", "bar_height"):
        data.pop(k, None)
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def bar_ref_path(roi_path: Path | None = None) -> Path:
    p = roi_path or DEFAULT_ROI_PATH
    if p == DEFAULT_ROI_PATH:
        return DEFAULT_BAR_REF_PATH
    return p.with_name("bar_ref.png")


def clear_bar_ref(roi_path: Path | None = None) -> None:
    ref = bar_ref_path(roi_path)
    if ref.is_file():
        ref.unlink()
