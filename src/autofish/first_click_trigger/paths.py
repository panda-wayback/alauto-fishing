"""声音模板路径：内置默认（assets）与用户覆盖（可写 data）。"""

from __future__ import annotations

from pathlib import Path

from common.paths import assets_dir, data_root

_BUNDLED_REL = Path("audio") / "splash_template.npy"
_USER_REL = Path("audio_template") / "template.npy"


def bundled_template_path() -> Path:
    """只读内置默认；随包分发。"""
    return assets_dir() / _BUNDLED_REL


def user_template_dir() -> Path:
    return data_root() / "audio_template"


def user_template_path() -> Path:
    """用户覆盖（标记/保存写入这里）。"""
    return data_root() / _USER_REL


def resolve_template_path() -> Path | None:
    """优先用户覆盖，否则内置默认；皆无则 None。"""
    user = user_template_path()
    if user.is_file():
        return user
    bundled = bundled_template_path()
    if bundled.is_file():
        return bundled
    return None


def template_source_label(path: Path | None) -> str:
    if path is None:
        return "无"
    try:
        if path.resolve() == user_template_path().resolve():
            return f"用户覆盖 · {path.name}"
    except OSError:
        pass
    try:
        if path.resolve() == bundled_template_path().resolve():
            return f"内置默认 · {path.name}"
    except OSError:
        pass
    return path.name
