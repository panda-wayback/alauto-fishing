import sys
from pathlib import Path

from common.paths import assets_dir, bundle_root, data_root, user_state_root


def test_source_mode_roots(monkeypatch, fresh_paths):
    monkeypatch.delattr(sys, "frozen", raising=False)
    root = bundle_root()
    assert (root / "src" / "common").is_dir()
    assert assets_dir() == root / "assets"
    assert data_root() == root / "data"


def test_frozen_bundle_root_is_meipass(sandbox):
    assert bundle_root() == Path(sandbox.bundle)
    assert assets_dir() == Path(sandbox.bundle) / "assets"


def test_frozen_darwin_data_root(sandbox, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    root = data_root()
    assert root == sandbox.home / "Library" / "Application Support" / "albn-autofish"
    assert root.is_dir()


def test_frozen_win32_data_root_beside_exe(sandbox, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    root = data_root()
    assert root == sandbox.install.resolve() / "data"
    assert root.is_dir()


def test_frozen_win32_data_root_falls_back_when_unwritable(sandbox, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    (sandbox.install / "data").write_text("not a dir")
    root = data_root()
    assert root == sandbox.local / "albn-autofish"
    assert root.is_dir()


def test_frozen_other_platform_data_root(sandbox, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    root = data_root()
    assert root == sandbox.home / ".local" / "share" / "albn-autofish"
    assert root.is_dir()


def test_user_state_root_per_platform_and_mode(sandbox, monkeypatch):
    expected = {
        "darwin": sandbox.home / "Library" / "Application Support" / "albn-autofish",
        "win32": sandbox.local / "albn-autofish",
        "linux": sandbox.home / ".local" / "share" / "albn-autofish",
    }
    for platform, want in expected.items():
        monkeypatch.setattr(sys, "platform", platform)
        for frozen in (True, False):
            monkeypatch.setattr(sys, "frozen", frozen, raising=False)
            user_state_root.cache_clear()
            root = user_state_root()
            assert root == want
            assert root.is_dir()


def test_user_state_root_win32_without_localappdata(sandbox, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert user_state_root() == sandbox.home / "AppData" / "Local" / "albn-autofish"


def test_roots_are_cached_until_cache_clear(sandbox, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    first_data, first_state = data_root(), user_state_root()
    other = sandbox.root / "other_home"
    other.mkdir()
    monkeypatch.setenv("HOME", str(other))
    monkeypatch.setenv("USERPROFILE", str(other))
    assert data_root() == first_data
    assert user_state_root() == first_state
    data_root.cache_clear()
    user_state_root.cache_clear()
    assert data_root() == other / ".local" / "share" / "albn-autofish"
    assert user_state_root() == other / ".local" / "share" / "albn-autofish"
