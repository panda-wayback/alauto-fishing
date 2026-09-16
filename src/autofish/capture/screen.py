"""截屏（mss，复用实例约 50fps）。坐标与输出均为逻辑点；ROI 帧宽高=手框。"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from autofish.locate.roi import Roi

try:
    import mss
except ImportError as exc:  # pragma: no cover
    raise ImportError("需要安装 mss：pip install mss") from exc

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_SCREEN_PATH = _ROOT / "data" / "screen.png"

# 复用单例，避免每次新建实例（新建会明显变慢）
# mss 非线程安全：Locator / Capture 并发 grab 会卡住，必须串行。
_sct: mss.mss | None = None
_sct_lock = threading.RLock()


def _session() -> mss.mss:
    global _sct
    with _sct_lock:
        if _sct is None:
            _sct = mss.mss()
        return _sct


def warmup() -> None:
    """预热 mss，避免冷启动首帧异常慢。"""
    with _sct_lock:
        sct = _session()
        mon = sct.monitors[1]
        sct.grab(
            {
                "left": int(mon["left"]),
                "top": int(mon["top"]),
                "width": 8,
                "height": 8,
            }
        )


_scale_cache: float | None = None


def _primary_scale_once(mon: dict) -> float:
    """调用方须已持有 `_sct_lock`。"""
    global _scale_cache
    if _scale_cache is not None:
        return _scale_cache
    shot = _session().grab(mon)
    physical_w = shot.width
    logical_w = int(mon["width"])
    _scale_cache = physical_w / logical_w if logical_w else 1.0
    return _scale_cache


@dataclass(frozen=True)
class ScreenGrab:
    """主屏截图（物理像素）；origin 为逻辑点坐标的主屏原点。"""

    rgb: np.ndarray
    origin_left: int
    origin_top: int
    scale: float


def grab_primary() -> ScreenGrab:
    """截主屏，缩放到逻辑点空间（供显示与框选），scale 记录物理/逻辑倍率。"""
    import cv2

    with _sct_lock:
        mon = _session().monitors[1]
        shot = _session().grab(mon)
        bgra = np.asarray(shot, dtype=np.uint8)
        rgb = np.ascontiguousarray(bgra[:, :, :3][:, :, ::-1])
        scale = _primary_scale_once(mon)
        origin_left = int(mon["left"])
        origin_top = int(mon["top"])
    w = max(1, round(rgb.shape[1] / scale))
    h = max(1, round(rgb.shape[0] / scale))
    pts = cv2.resize(rgb, (w, h), interpolation=cv2.INTER_AREA)
    return ScreenGrab(
        rgb=pts,
        origin_left=origin_left,
        origin_top=origin_top,
        scale=scale,
    )


def grab_roi(roi: Roi) -> np.ndarray:
    """截 ROI（逻辑点），返回与手框同尺寸的逻辑像素 RGB，shape=(height, width, 3)。"""
    import cv2

    with _sct_lock:
        mon = _session().monitors[1]
        shot = _session().grab(roi.as_mss())
        bgra = np.asarray(shot, dtype=np.uint8)
        rgb = np.ascontiguousarray(bgra[:, :, :3][:, :, ::-1])
        scale = _primary_scale_once(mon)
    # Retina 等：物理缓冲须缩回逻辑点，与框选宽高一致，禁止比手框「虚大」
    if abs(scale - 1.0) > 1e-3 or rgb.shape[1] != roi.width or rgb.shape[0] != roi.height:
        rgb = cv2.resize(
            rgb, (roi.width, roi.height), interpolation=cv2.INTER_AREA
        )
    return rgb


def save_screen(grab: ScreenGrab, path: Path | None = None) -> Path:
    from PIL import Image

    p = path or DEFAULT_SCREEN_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(grab.rgb).save(p)
    meta = p.with_suffix(".meta.json")
    meta.write_text(
        "{\n"
        f'  "origin_left": {grab.origin_left},\n'
        f'  "origin_top": {grab.origin_top},\n'
        f'  "scale": {grab.scale},\n'
        f'  "width": {grab.rgb.shape[1]},\n'
        f'  "height": {grab.rgb.shape[0]}\n'
        "}\n",
        encoding="utf-8",
    )
    return p


def load_screen(path: Path | None = None) -> ScreenGrab:
    from PIL import Image

    p = path or DEFAULT_SCREEN_PATH
    rgb = np.asarray(Image.open(p).convert("RGB"), dtype=np.uint8)
    meta_path = p.with_suffix(".meta.json")
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return ScreenGrab(
            rgb=rgb,
            origin_left=int(meta["origin_left"]),
            origin_top=int(meta["origin_top"]),
            scale=float(meta.get("scale", 1.0)),
        )
    return ScreenGrab(rgb=rgb, origin_left=0, origin_top=0, scale=1.0)