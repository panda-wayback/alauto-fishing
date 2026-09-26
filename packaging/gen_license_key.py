#!/usr/bin/env python3
"""按天数生成激活密钥。

用法（仓库根）:
  PYTHONPATH=src python packaging/gen_license_key.py 30
  PYTHONPATH=src python packaging/gen_license_key.py 7 --count 3
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from common.license import issue_key, parse_key  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 albn-autofish 激活密钥")
    ap.add_argument("days", type=int, help="可用天数（如 7 / 30）")
    ap.add_argument("--count", type=int, default=1, help="生成条数")
    args = ap.parse_args()
    if args.days <= 0:
        print("days 须为正整数", file=sys.stderr)
        return 2
    if args.count <= 0:
        print("count 须为正整数", file=sys.stderr)
        return 2
    for i in range(args.count):
        key = issue_key(args.days)
        body = parse_key(key)
        print(key)
        print(f"  # days={body['days']} n={body.get('n')}", file=sys.stderr)
        if i + 1 < args.count:
            print(file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
