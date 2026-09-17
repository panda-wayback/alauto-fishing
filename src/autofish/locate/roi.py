"""手动标定的屏幕截取区域。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from common.paths import data_root

DEFAULT_ROI_PATH = data_root() / "roi.json"


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


def load_roi(path: Path | None = None) -> Roi:
    p = path or DEFAULT_ROI_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    return Roi(
        left=int(data["left"]),
        top=int(data["top"]),
        width=int(data["width"]),
        height=int(data["height"]),
    )


def save_roi(roi: Roi, path: Path | None = None) -> Path:
    p = path or DEFAULT_ROI_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(roi), indent=2) + "\n", encoding="utf-8")
    return p
