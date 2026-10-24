"""Build helper: write assets/expire.json from ALBN_EXPIRE_DAYS."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Windows CI often uses cp1252 stdout; force UTF-8 to avoid UnicodeEncodeError.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from common.expire import clear_expire_file, write_expire_from_days  # noqa: E402


def main() -> int:
    raw = (os.environ.get("ALBN_EXPIRE_DAYS") or "").strip()
    if not raw:
        clear_expire_file()
        print("ALBN_EXPIRE_DAYS unset: no expire (cleared expire.json)")
        return 0
    try:
        days = int(raw)
    except ValueError:
        print(f"ALBN_EXPIRE_DAYS invalid: {raw!r}", file=sys.stderr)
        return 2
    if days <= 0:
        clear_expire_file()
        print("ALBN_EXPIRE_DAYS<=0: no expire")
        return 0
    path = write_expire_from_days(days)
    print(f"wrote {path} (expire in {days} days)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
