import json
import shutil
import sys
from datetime import date

import pytest

from common import expire


@pytest.fixture
def rmtree_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(shutil, "rmtree", lambda path, **kw: calls.append(path))
    return calls


def test_no_expire_file_means_not_expired(sandbox):
    assert not expire.expire_path().exists()
    assert expire.load_expire_on() is None
    assert expire.is_expired(today=date(2999, 1, 1)) is False


def test_write_expire_from_days_and_is_expired(sandbox):
    path = expire.write_expire_from_days(30, built_on=date(2026, 1, 1))
    assert path == sandbox.bundle / "assets" / "expire.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw == {"expire_on": "2026-01-31", "days": 30, "built_on": "2026-01-01"}
    assert expire.load_expire_on() == date(2026, 1, 31)
    assert expire.is_expired(today=date(2026, 1, 30)) is False
    assert expire.is_expired(today=date(2026, 1, 31)) is True
    assert expire.is_expired(today=date(2026, 2, 1)) is True


@pytest.mark.parametrize("days", [0, -1])
def test_write_expire_rejects_non_positive_days(sandbox, days):
    with pytest.raises(ValueError):
        expire.write_expire_from_days(days)
    assert not expire.expire_path().exists()


@pytest.mark.parametrize(
    "content", ["{not json", "[1, 2]", '{"days": 3}', '{"expire_on": "nope"}']
)
def test_bad_expire_file_means_not_expired(sandbox, content):
    path = expire.expire_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    assert expire.load_expire_on() is None
    assert expire.is_expired(today=date(2999, 1, 1)) is False


def test_clear_expire_file_is_idempotent(sandbox):
    path = expire.write_expire_from_days(1)
    expire.clear_expire_file()
    assert not path.exists()
    expire.clear_expire_file()


def test_expire_message(sandbox):
    generic = expire.expire_message()
    assert "过期" in generic
    expire.write_expire_from_days(10, built_on=date(2026, 3, 1))
    assert "2026-03-11" in expire.expire_message()


def test_install_root(sandbox, monkeypatch, fresh_paths):
    monkeypatch.setattr(sys, "platform", "win32")
    assert expire.install_root() == sandbox.install.resolve()

    app = sandbox.root / "Albn.app"
    exe = app / "Contents" / "MacOS" / "albn"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "executable", str(exe))
    assert expire.install_root() == app.resolve()

    monkeypatch.setattr(sys, "executable", str(sandbox.install / "albn"))
    assert expire.install_root() is None

    monkeypatch.delattr(sys, "frozen", raising=False)
    assert expire.install_root() is None


def test_try_self_delete_noop_in_source_mode(monkeypatch, rmtree_calls):
    monkeypatch.delattr(sys, "frozen", raising=False)
    expire.try_self_delete()
    assert rmtree_calls == []


def test_try_self_delete_targets_install_root_only(sandbox, monkeypatch, rmtree_calls):
    monkeypatch.setattr(sys, "platform", "win32")
    expire.try_self_delete()
    assert rmtree_calls == [sandbox.install.resolve()]

    def boom(path, **kw):
        raise OSError("busy")

    monkeypatch.setattr(shutil, "rmtree", boom)
    expire.try_self_delete()
