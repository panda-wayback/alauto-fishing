import json
import sys

import numpy as np
import pytest

from autofish.first_click_trigger import paths as P


def _npy(path, value=0.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, np.full(8, value, dtype=np.float32))
    return path


def _bundled(lib_dirs, *names):
    return [_npy(lib_dirs["assets_audio"] / n) for n in names]


@pytest.mark.parametrize(
    "platform, expected",
    [("win32", "windows.npy"), ("darwin", "macos.npy"), ("linux", "windows.npy")],
)
def test_bundled_default_by_platform(lib_dirs, monkeypatch, platform, expected):
    _bundled(lib_dirs, "a_first.npy", "macos.npy", "windows.npy")
    monkeypatch.setattr(sys, "platform", platform)
    assert P.bundled_template_path() == lib_dirs["assets_audio"] / expected


def test_bundled_default_falls_back_to_first(lib_dirs, monkeypatch):
    _bundled(lib_dirs, "zeta.npy", "Beta.npy")
    monkeypatch.setattr(sys, "platform", "darwin")
    assert P.bundled_template_path().name == "Beta.npy"
    assert [p.name for p in P.list_bundled_templates()] == ["Beta.npy", "zeta.npy"]


def test_resolve_falls_back_to_platform_bundled_or_none(lib_dirs, monkeypatch):
    assert P.resolve_template_path() is None
    _bundled(lib_dirs, "macos.npy", "windows.npy")
    monkeypatch.setattr(sys, "platform", "win32")
    assert P.resolve_template_path() == lib_dirs["assets_audio"] / "windows.npy"
    monkeypatch.setattr(sys, "platform", "darwin")
    assert P.resolve_template_path() == lib_dirs["assets_audio"] / "macos.npy"


def test_list_library_user_first_then_bundled_and_seeded(lib_dirs):
    _bundled(lib_dirs, "macos.npy")
    seed = lib_dirs["bundle"] / "seed" / "audio_template"
    _npy(seed / "seeded.npy", 1.0)
    _npy(seed / "mine.npy", 2.0)
    (seed / "active.json").write_text('{"file": "seeded.npy"}', encoding="utf-8")
    user = P.user_template_dir()
    _npy(user / "mine.npy", 3.0)
    lib = P.list_library_templates()
    assert [p.name for p in lib] == ["mine.npy", "seeded.npy", "macos.npy"]
    assert np.load(user / "mine.npy")[0] == 3.0
    assert not (user / "active.json").exists()
    assert P.is_bundled_template(lib[-1]) and not P.is_bundled_template(lib[0])
    assert not P.is_bundled_template(None)


def test_save_wave_sets_active_and_resolves(lib_dirs):
    _bundled(lib_dirs, "macos.npy")
    wave = np.linspace(-1, 1, 16)
    p = P.save_wave_as_library_template(wave)
    assert p.parent == P.user_template_dir() and p.name.startswith("tpl_")
    np.testing.assert_allclose(np.load(p), wave.astype(np.float32))
    assert np.load(p).dtype == np.float32
    assert P.get_active_template_name() == p.name
    assert P.resolve_template_path() == p
    assert P.template_source_label(p) == p.stem
    outside = lib_dirs["data"].parent / "elsewhere" / "named.npy"
    q = P.save_wave_as_library_template(wave, outside)
    assert q == P.user_template_dir() / "named.npy" and not outside.exists()
    assert P.resolve_template_path() == q


def test_save_wave_refuses_bundled(lib_dirs):
    (b,) = _bundled(lib_dirs, "macos.npy")
    with pytest.raises(RuntimeError):
        P.save_wave_as_library_template(np.zeros(4), b)


def test_active_bundled_and_clear(lib_dirs):
    (b,) = _bundled(lib_dirs, "macos.npy")
    _npy(P.user_template_dir() / "u.npy")
    P.set_active_template(b)
    assert P.get_active_template_name() == "__bundled__:macos.npy"
    assert P.resolve_template_path() == b
    assert P.template_source_label(b) == "内置 · macos"
    P.set_active_template(None)
    assert P.get_active_template_name() is None
    assert P.resolve_template_path() == P.user_template_dir() / "u.npy"
    assert P.template_source_label(None) == "无"


def test_next_auto_template_path_is_unique(lib_dirs):
    a = P.next_auto_template_path()
    _npy(a)
    b = P.next_auto_template_path()
    assert a != b and b.parent == P.user_template_dir() and b.suffix == ".npy"


def test_rename_library_template(lib_dirs):
    (b,) = _bundled(lib_dirs, "macos.npy")
    p = P.save_wave_as_library_template(np.zeros(4), P.user_template_dir() / "old.npy")
    other = _npy(P.user_template_dir() / "other.npy")
    new = P.rename_library_template(p, " 新名-1.npy ")
    assert new == P.user_template_dir() / "新名-1.npy" and new.is_file() and not p.exists()
    assert P.get_active_template_name() == "新名-1.npy"
    assert P.resolve_template_path() == new
    with pytest.raises(RuntimeError):
        P.rename_library_template(new, "bad/name")
    with pytest.raises(RuntimeError):
        P.rename_library_template(new, "other")
    with pytest.raises(RuntimeError):
        P.rename_library_template(b, "x")
    stray = _npy(lib_dirs["data"].parent / "stray.npy")
    with pytest.raises(RuntimeError):
        P.rename_library_template(stray, "x")
    assert other.is_file()


def test_delete_library_template_moves_active(lib_dirs, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    (b,) = _bundled(lib_dirs, "macos.npy")
    keep = _npy(P.user_template_dir() / "a_keep.npy")
    gone = P.save_wave_as_library_template(np.zeros(4), P.user_template_dir() / "b_gone.npy")
    P.delete_library_template(gone)
    assert not gone.exists()
    assert P.resolve_template_path() == keep
    assert P.get_active_template_name() == "a_keep.npy"
    P.delete_library_template(keep)
    assert P.resolve_template_path() == b
    with pytest.raises(RuntimeError):
        P.delete_library_template(b)
    assert b.is_file()


def test_session_dirs_list_seed_and_delete(lib_dirs):
    root = P.user_audio_sessions_dir()
    seed = P.bundled_sessions_seed_dir()
    assert seed == lib_dirs["bundle"] / "seed" / "audio_sessions"
    _npy(seed / "session_20200101_000000" / "audio.npy")
    (seed / "session_20200101_000000" / "meta.json").write_text(
        json.dumps({"samplerate": 8000}), encoding="utf-8"
    )
    for name in ("session_20210101_000000", "session_20220101_000000"):
        _npy(root / name / "audio.npy")
        (root / name / "meta.json").write_text("{}", encoding="utf-8")
    _npy(root / "session_20230101_000000" / "audio.npy")
    (root / "not_a_session").mkdir()
    listed = P.list_session_dirs()
    assert [p.name for p in listed] == [
        "session_20220101_000000",
        "session_20210101_000000",
        "session_20200101_000000",
    ]
    P.delete_session_dir(root / "session_20210101_000000")
    assert not (root / "session_20210101_000000").exists()
    with pytest.raises(RuntimeError):
        P.delete_session_dir(root / "session_20210101_000000")
    with pytest.raises(RuntimeError):
        P.delete_session_dir(root / "not_a_session")
    outside = lib_dirs["data"].parent / "session_x"
    outside.mkdir()
    with pytest.raises(RuntimeError):
        P.delete_session_dir(outside)
    assert outside.is_dir()
