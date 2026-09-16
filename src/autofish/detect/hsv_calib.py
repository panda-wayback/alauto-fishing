"""绿区 HSV 标定：点选吸色，容差对齐 AutoFishing auto_hsv。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError as exc:  # pragma: no cover
    raise ImportError("需要安装 opencv-python-headless") from exc

from autofish.detect.bobber import DEFAULT_LOWER_ZONE, DEFAULT_UPPER_ZONE

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_HSV_PATH = _ROOT / "data" / "hsv_zone.json"

# AutoFishing auto_hsv 默认容差
_H_TOL = 31
_S_TOL = 70
_V_TOL = 69


@dataclass(frozen=True)
class ZoneHsv:
    lower: np.ndarray
    upper: np.ndarray


def default_zone_hsv() -> ZoneHsv:
    return ZoneHsv(lower=DEFAULT_LOWER_ZONE.copy(), upper=DEFAULT_UPPER_ZONE.copy())


def load_zone_hsv(path: Path | None = None) -> ZoneHsv:
    p = path or DEFAULT_HSV_PATH
    if not p.exists():
        return default_zone_hsv()
    data = json.loads(p.read_text(encoding="utf-8"))
    return ZoneHsv(
        lower=np.array(data["lower"], dtype=np.uint8),
        upper=np.array(data["upper"], dtype=np.uint8),
    )


def save_zone_hsv(zone: ZoneHsv, path: Path | None = None) -> Path:
    p = path or DEFAULT_HSV_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "lower": [int(x) for x in zone.lower.tolist()],
        "upper": [int(x) for x in zone.upper.tolist()],
    }
    p.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return p


def sample_zone_hsv(
    rgb: np.ndarray,
    x: int,
    y: int,
    *,
    radius: int = 4,
    h_tol: int = _H_TOL,
    s_tol: int = _S_TOL,
    v_tol: int = _V_TOL,
) -> ZoneHsv:
    """在 (x,y) 邻域取 HSV 均值，按容差扩成 lower/upper。"""
    h, w = rgb.shape[:2]
    x0, x1 = max(0, x - radius), min(w, x + radius + 1)
    y0, y1 = max(0, y - radius), min(h, y + radius + 1)
    patch = rgb[y0:y1, x0:x1]
    bgr = cv2.cvtColor(patch, cv2.COLOR_RGB2BGR)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(np.float32)
    mean = hsv.mean(axis=0)
    mh, ms, mv = mean
    lower = np.array(
        [
            max(0, int(mh - h_tol)),
            max(0, int(ms - s_tol)),
            max(0, int(mv - v_tol)),
        ],
        dtype=np.uint8,
    )
    upper = np.array(
        [
            min(179, int(mh + h_tol)),
            min(255, int(ms + s_tol)),
            min(255, int(mv + v_tol)),
        ],
        dtype=np.uint8,
    )
    return ZoneHsv(lower=lower, upper=upper)
