"""打包过期：读 assets/expire.json；到期尽删安装目录。"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

from common.paths import assets_dir

_EXPIRE_NAME = "expire.json"


def expire_path() -> Path:
    return assets_dir() / _EXPIRE_NAME


def load_expire_on() -> date | None:
    """有合法 expire_on 则返回；无文件/坏文件 → None（不过期）。"""
    path = expire_path()
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(raw, dict):
        return None
    text = raw.get("expire_on")
    if not text:
        return None
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


def is_expired(*, today: date | None = None) -> bool:
    exp = load_expire_on()
    if exp is None:
        return False
    return (today or date.today()) >= exp


def write_expire_from_days(days: int, *, built_on: date | None = None) -> Path:
    """构建用：从 built_on（默认今天）起 days 天后到期，写入 assets/expire.json。"""
    n = int(days)
    if n <= 0:
        raise ValueError("days must be positive")
    start = built_on or date.today()
    payload = {
        "expire_on": (start + timedelta(days=n)).isoformat(),
        "days": n,
        "built_on": start.isoformat(),
    }
    path = expire_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def clear_expire_file() -> None:
    path = expire_path()
    if path.is_file():
        path.unlink()


def install_root() -> Path | None:
    """冻结包安装根：macOS .app / Windows onedir；源码 None。"""
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        for p in exe.parents:
            if p.suffix == ".app":
                return p
        return None
    return exe.parent


def try_self_delete() -> None:
    """尽力删除安装目录；失败忽略。"""
    root = install_root()
    if root is None:
        return
    try:
        shutil.rmtree(root, ignore_errors=True)
    except OSError:
        pass


def expire_message() -> str:
    exp = load_expire_on()
    if exp is None:
        return "本版本已过期，无法继续使用。"
    return f"本版本已于 {exp.isoformat()} 过期，无法继续使用。"
