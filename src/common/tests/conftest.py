import sys
from types import SimpleNamespace

import pytest

from common import paths


def _clear_path_caches():
    paths.data_root.cache_clear()
    paths.user_state_root.cache_clear()


@pytest.fixture
def fresh_paths():
    _clear_path_caches()
    yield
    _clear_path_caches()


@pytest.fixture
def sandbox(tmp_path, monkeypatch, fresh_paths):
    """冻结态，HOME / LOCALAPPDATA / _MEIPASS / sys.executable 全部落到 tmp_path。"""
    home = tmp_path / "home"
    bundle = tmp_path / "bundle"
    install = tmp_path / "install"
    local = tmp_path / "localappdata"
    for d in (home, bundle, install):
        d.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(sys, "executable", str(install / "app.exe"))
    return SimpleNamespace(
        root=tmp_path, home=home, bundle=bundle, install=install, local=local
    )
