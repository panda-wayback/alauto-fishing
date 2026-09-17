"""项目根 / data 根：源码与 PyInstaller 冻结共用。"""

from __future__ import annotations

import sys
from pathlib import Path


def bundle_root() -> Path:
    """只读资源根（assets 等）。冻结时为 _MEIPASS。"""
    meipass = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and meipass:
        return Path(meipass)
    return Path(__file__).resolve().parents[2]


def data_root() -> Path:
    """可写 data/。冻结时用用户目录，.app 内部不可写。"""
    if getattr(sys, "frozen", False):
        root = Path.home() / "Library" / "Application Support" / "albn-autofish"
        root.mkdir(parents=True, exist_ok=True)
        return root
    return bundle_root() / "data"


def assets_dir() -> Path:
    return bundle_root() / "assets"
