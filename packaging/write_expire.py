"""构建时按 ALBN_EXPIRE_DAYS 写入 assets/expire.json。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from common.expire import clear_expire_file, write_expire_from_days  # noqa: E402


def main() -> int:
    raw = (os.environ.get("ALBN_EXPIRE_DAYS") or "").strip()
    if not raw:
        clear_expire_file()
        print("ALBN_EXPIRE_DAYS 未设：不过期（已清除 expire.json）")
        return 0
    try:
        days = int(raw)
    except ValueError:
        print(f"ALBN_EXPIRE_DAYS 无效: {raw!r}", file=sys.stderr)
        return 2
    if days <= 0:
        clear_expire_file()
        print("ALBN_EXPIRE_DAYS<=0：不过期")
        return 0
    path = write_expire_from_days(days)
    print(f"已写入 {path}（{days} 天后过期）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
