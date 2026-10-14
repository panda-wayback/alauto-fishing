"""单文件入口：打开真机调试壳（等价于 `python -m tools.preview_app`）。"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from tools.preview_app import launch_ui

if __name__ == "__main__":
    raise SystemExit(launch_ui())
