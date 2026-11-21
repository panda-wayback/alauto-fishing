"""读图 / 写图。不把路径交给 cv2.imread / cv2.imwrite（Windows 上非 ASCII 路径会失败）。"""

from __future__ import annotations

from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError as exc:  # pragma: no cover
    raise ImportError("需要安装 opencv-python-headless") from exc


def read_image(path: str | Path, flags: int = cv2.IMREAD_COLOR) -> np.ndarray | None:
    """读图。文件不存在抛 FileNotFoundError；内容无法解码返回 None。"""
    data = np.fromfile(path, dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, flags)


def write_image(path: str | Path, image: np.ndarray) -> bool:
    """按路径后缀写图。编码失败返回 False。"""
    dest = Path(path)
    ext = dest.suffix if dest.suffix else ".png"
    ok, buf = cv2.imencode(ext, image)
    if not ok:
        return False
    buf.tofile(dest)
    return True
