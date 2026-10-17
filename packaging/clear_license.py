#!/usr/bin/env python3
"""清除本机密钥授权与首次激活台账，便于重测激活。"""
from __future__ import annotations

from common.paths import data_root, user_state_root


def main() -> int:
    paths = [
        user_state_root() / "license.json",
        user_state_root() / "license_ledger.json",
        data_root() / "license.json",  # 旧版位置，避免再被迁回
    ]
    removed: list[str] = []
    for p in paths:
        if p.is_file():
            p.unlink()
            removed.append(str(p))
    if removed:
        print("已删除:")
        for s in removed:
            print(f"  {s}")
    else:
        print("无授权文件（已是未激活状态）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
