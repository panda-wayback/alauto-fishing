"""项目根 / data 根：源码与 PyInstaller 冻结共用。"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path


def bundle_root() -> Path:
    """只读资源根（assets 等）。冻结时为 _MEIPASS。"""
    meipass = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and meipass:
        return Path(meipass)
    return Path(__file__).resolve().parents[2]


def _dir_writable(root: Path) -> bool:
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".write_test"
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


@lru_cache(maxsize=1)
def data_root() -> Path:
    """可写 data/。冻结：Windows exe 同级 data\\（不可写退 LOCALAPPDATA）/ macOS Application Support / 其它 XDG。"""
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            root = Path.home() / "Library" / "Application Support" / "albn-autofish"
        elif sys.platform == "win32":
            beside_exe = Path(sys.executable).resolve().parent / "data"
            if _dir_writable(beside_exe):
                return beside_exe
            base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
            root = Path(base) / "albn-autofish"
        else:
            root = Path.home() / ".local" / "share" / "albn-autofish"
        root.mkdir(parents=True, exist_ok=True)
        return root
    return bundle_root() / "data"


def assets_dir() -> Path:
    return bundle_root() / "assets"
