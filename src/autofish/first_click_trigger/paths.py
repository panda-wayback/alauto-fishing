"""声音模板库与长录音会话路径（固定 data 目录，应用内选择）。"""

from __future__ import annotations

import json
import re
import shutil
import sys
import time
from pathlib import Path

from common.paths import assets_dir, bundle_root, data_root

_BUNDLED_DIR_REL = Path("audio")
# 平台默认内置；缺文件时再退回旧名
_BUNDLED_BY_PLATFORM = {
    "win32": ("windows.npy", "default.npy", "splash_template.npy"),
    "darwin": ("macos.npy", "default.npy", "splash_template.npy"),
}
_BUNDLED_PREFERRED_FALLBACK = ("default.npy", "splash_template.npy")
_ACTIVE_BUNDLED_PREFIX = "__bundled__:"
_ACTIVE_NAME = "active.json"
_SAFE_NAME = re.compile(r"^[\w.\u4e00-\u9fff\-]+$", re.UNICODE)


def assets_audio_dir() -> Path:
    return assets_dir() / _BUNDLED_DIR_REL


def list_bundled_templates() -> list[Path]:
    """`assets/audio/*.npy`（只读内置）。"""
    d = assets_audio_dir()
    if not d.is_dir():
        return []
    return sorted(d.glob("*.npy"), key=lambda x: x.name.lower())


def bundled_template_path() -> Path:
    """平台内置默认：Windows→windows.npy，macOS→macos.npy；缺则旧名再目录内第一个。"""
    d = assets_audio_dir()
    preferred = _BUNDLED_BY_PLATFORM.get(sys.platform, _BUNDLED_PREFERRED_FALLBACK)
    for name in preferred:
        cand = d / name
        if cand.is_file():
            return cand
    bundled = list_bundled_templates()
    if bundled:
        return bundled[0]
    return d / preferred[0]


def user_template_dir() -> Path:
    return data_root() / "audio_template"


def user_template_path() -> Path:
    """兼容旧路径：单一用户覆盖文件（仍可作为库中一项）。"""
    return user_template_dir() / "template.npy"


def user_heard_marks_dir() -> Path:
    return data_root() / "audio_heard_marks"


def user_audio_sessions_dir() -> Path:
    return data_root() / "audio_sessions"


def bundled_sessions_seed_dir() -> Path:
    """打包内种子会话：`seed/audio_sessions`（由 data/audio_sessions 打进包）。"""
    return bundle_root() / "seed" / "audio_sessions"


def ensure_session_seed() -> None:
    """用户目录缺某 session_* 时，从包内种子拷贝（不覆盖已有）。"""
    seed = bundled_sessions_seed_dir()
    if not seed.is_dir():
        return
    dest_root = user_audio_sessions_dir()
    dest_root.mkdir(parents=True, exist_ok=True)
    for src in seed.iterdir():
        if not src.is_dir() or not src.name.startswith("session_"):
            continue
        if not (src / "audio.npy").is_file():
            continue
        dest = dest_root / src.name
        if dest.exists():
            continue
        try:
            shutil.copytree(src, dest)
        except OSError:
            continue


def ensure_user_template_seed() -> None:
    """包内 `seed/audio_template/*.npy` → 用户库（缺则拷，不覆盖）。"""
    seed = bundle_root() / "seed" / "audio_template"
    if not seed.is_dir():
        return
    dest = user_template_dir()
    dest.mkdir(parents=True, exist_ok=True)
    for src in seed.glob("*.npy"):
        target = dest / src.name
        if target.exists():
            continue
        try:
            shutil.copy2(src, target)
        except OSError:
            continue


def _active_meta_path() -> Path:
    return user_template_dir() / _ACTIVE_NAME


def list_library_templates() -> list[Path]:
    """库内模板：用户目录下全部 .npy + assets/audio 下全部内置 .npy。"""
    ensure_user_template_seed()
    out: list[Path] = []
    seen: set[str] = set()
    d = user_template_dir()
    d.mkdir(parents=True, exist_ok=True)
    for p in sorted(d.glob("*.npy"), key=lambda x: x.name.lower()):
        out.append(p)
        try:
            seen.add(str(p.resolve()))
        except OSError:
            seen.add(str(p))
    for p in list_bundled_templates():
        try:
            key = str(p.resolve())
        except OSError:
            key = str(p)
        if key not in seen:
            out.append(p)
            seen.add(key)
    return out


def list_session_dirs() -> list[Path]:
    """固定目录下可加载的 session_*（含 audio.npy）；先落包内种子。"""
    ensure_session_seed()
    root = user_audio_sessions_dir()
    root.mkdir(parents=True, exist_ok=True)
    sessions: list[Path] = []
    for p in sorted(root.iterdir(), key=lambda x: x.name, reverse=True):
        if p.is_dir() and (p / "audio.npy").is_file() and (p / "meta.json").is_file():
            sessions.append(p)
    return sessions


def delete_session_dir(path: Path) -> None:
    """删除固定目录下的一条长录音会话（整目录）。"""
    import shutil

    path = Path(path)
    root = user_audio_sessions_dir().resolve()
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise RuntimeError(f"无效会话路径：{path}") from exc
    if not resolved.is_dir():
        raise RuntimeError("会话目录不存在")
    if resolved.parent != root or not resolved.name.startswith("session_"):
        raise RuntimeError("只能删除 data/audio_sessions/ 下的 session_* 目录")
    shutil.rmtree(resolved)


def get_active_template_name() -> str | None:
    meta = _active_meta_path()
    if not meta.is_file():
        return None
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
        name = data.get("file")
        return str(name) if name else None
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def set_active_template(path: Path | None) -> None:
    d = user_template_dir()
    d.mkdir(parents=True, exist_ok=True)
    meta = _active_meta_path()
    if path is None:
        if meta.is_file():
            meta.unlink()
        return
    path = Path(path)
    try:
        if is_bundled_template(path):
            payload = {
                "file": f"{_ACTIVE_BUNDLED_PREFIX}{path.name}",
                "label": path.name,
            }
        elif path.parent.resolve() == d.resolve():
            payload = {"file": path.name}
        else:
            payload = {"file": str(path)}
    except OSError:
        payload = {"file": path.name}
    meta.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_template_path() -> Path | None:
    """当前选中模板；无选中则优先库内用户文件，再内置。"""
    name = get_active_template_name()
    if name == "__bundled__":
        # 旧 active.json 兼容
        bundled = bundled_template_path()
        return bundled if bundled.is_file() else None
    if name and name.startswith(_ACTIVE_BUNDLED_PREFIX):
        fname = name[len(_ACTIVE_BUNDLED_PREFIX) :]
        cand = assets_audio_dir() / fname
        if cand.is_file():
            return cand
    if name:
        cand = Path(name)
        if not cand.is_absolute():
            cand = user_template_dir() / name
        if cand.is_file():
            return cand
    legacy = user_template_path()
    if legacy.is_file():
        return legacy
    lib = list_library_templates()
    user_ones = [p for p in lib if _is_user_library_file(p)]
    if user_ones:
        return user_ones[0]
    bundled = bundled_template_path()
    if bundled.is_file():
        return bundled
    return None


def _is_user_library_file(path: Path) -> bool:
    try:
        return path.parent.resolve() == user_template_dir().resolve()
    except OSError:
        return False


def is_bundled_template(path: Path | None) -> bool:
    if path is None:
        return False
    try:
        root = assets_audio_dir().resolve()
        resolved = path.resolve()
        return resolved.parent == root and resolved.suffix.lower() == ".npy"
    except OSError:
        return False


def template_source_label(path: Path | None) -> str:
    if path is None:
        return "无"
    if is_bundled_template(path):
        return f"内置 · {path.stem}"
    if _is_user_library_file(path):
        return path.stem
    return path.name


def next_auto_template_path() -> Path:
    """自动命名 tpl_YYYYMMDD_HHMMSS.npy，重名则加后缀。"""
    d = user_template_dir()
    d.mkdir(parents=True, exist_ok=True)
    base = time.strftime("tpl_%Y%m%d_%H%M%S")
    path = d / f"{base}.npy"
    n = 1
    while path.exists():
        path = d / f"{base}_{n}.npy"
        n += 1
    return path


def save_wave_as_library_template(wave, path: Path | None = None) -> Path:
    """写入库文件并设为当前选中。"""
    import numpy as np

    dest = path or next_auto_template_path()
    dest = Path(dest)
    if is_bundled_template(dest):
        raise RuntimeError("不能覆盖内置默认模板")
    if dest.parent.resolve() != user_template_dir().resolve():
        dest = user_template_dir() / dest.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    np.save(dest, np.asarray(wave, dtype=np.float32))
    set_active_template(dest)
    return dest


def rename_library_template(path: Path, new_stem: str) -> Path:
    """改名（仅用户库）；返回新路径。"""
    path = Path(path)
    if is_bundled_template(path):
        raise RuntimeError("内置默认不可改名")
    if not _is_user_library_file(path):
        raise RuntimeError("只能改名库内模板")
    stem = new_stem.strip()
    if stem.endswith(".npy"):
        stem = stem[:-4]
    if not stem or not _SAFE_NAME.match(stem):
        raise RuntimeError("名称只能含文字、数字、下划线、短横线")
    dest = path.with_name(f"{stem}.npy")
    if dest.exists() and dest.resolve() != path.resolve():
        raise RuntimeError(f"已存在同名模板：{dest.name}")
    old_name = path.name
    active = get_active_template_name()
    path.rename(dest)
    if active == old_name:
        set_active_template(dest)
    return dest


def delete_library_template(path: Path) -> None:
    path = Path(path)
    if is_bundled_template(path):
        raise RuntimeError("内置默认不可删除")
    if not _is_user_library_file(path):
        raise RuntimeError("只能删除库内模板")
    was_active = False
    try:
        cur = resolve_template_path()
        was_active = cur is not None and cur.resolve() == path.resolve()
    except OSError:
        was_active = get_active_template_name() == path.name
    path.unlink(missing_ok=True)
    if was_active:
        set_active_template(None)
        nxt = resolve_template_path()
        if nxt is not None:
            set_active_template(nxt)
