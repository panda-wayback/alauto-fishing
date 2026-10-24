import ctypes
import dataclasses
import subprocess
import sys
import types
from types import SimpleNamespace

import pytest

from common import permissions as perms

SYSTEM_MODULES = ("Quartz", "ApplicationServices", "Foundation", "mss")


@pytest.fixture(autouse=True)
def no_system_side_effects(monkeypatch):
    """默认屏蔽所有系统库与子进程；单个测试再按需注入假实现。"""
    for name in SYSTEM_MODULES:
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.setattr(ctypes, "windll", None, raising=False)
    runs = []

    def fake_run(cmd, *args, **kwargs):
        runs.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return runs


@pytest.fixture
def runs(no_system_side_effects):
    return no_system_side_effects


def _module(monkeypatch, name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    monkeypatch.setitem(sys.modules, name, mod)
    return mod


def _fake_mss(monkeypatch):
    class Sct:
        monitors = [{"left": 0, "top": 0, "width": 800, "height": 600}]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def grab(self, box):
            assert box["width"] <= 16 and box["height"] <= 16
            return SimpleNamespace(width=box["width"])

    _module(monkeypatch, "mss", mss=Sct)


def _fake_windll(monkeypatch, *, admin, shell_rc=42, shell_raises=False):
    calls = []

    def shell_execute(*args):
        calls.append(args)
        if shell_raises:
            raise OSError("denied")
        return shell_rc

    shell32 = SimpleNamespace(IsUserAnAdmin=lambda: int(admin), ShellExecuteW=shell_execute)
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(shell32=shell32), raising=False)
    return calls


def _open_urls(runs):
    return [c[1] for c in runs if c[0] == "open"]


# ---- current_status ----


def test_other_platform_status_unknown(monkeypatch, runs):
    monkeypatch.setattr(sys, "platform", "plan9")
    st = perms.current_status()
    assert st.platform == "plan9"
    assert (st.screen_ok, st.input_ok, st.is_admin) == (None, None, None)
    assert st.screen_label and st.input_label
    assert runs == []


@pytest.mark.parametrize("screen,access", [(True, False), (False, True)])
def test_macos_status_reflects_tcc(monkeypatch, runs, screen, access):
    monkeypatch.setattr(sys, "platform", "darwin")
    _module(monkeypatch, "Quartz", CGPreflightScreenCaptureAccess=lambda: screen)
    _module(monkeypatch, "ApplicationServices", AXIsProcessTrusted=lambda: access)
    st = perms.current_status()
    assert st.platform == "darwin"
    assert st.screen_ok is screen and st.input_ok is access
    assert st.is_admin is None
    assert st.screen_label == ("屏幕录制已授权" if screen else "屏幕录制未授权")
    assert st.input_label == ("辅助功能已授权" if access else "辅助功能未授权")
    assert runs == []


def test_macos_status_without_system_libs_does_not_raise(monkeypatch, runs):
    monkeypatch.setattr(sys, "platform", "darwin")
    st = perms.current_status()
    assert st.screen_ok is False and st.input_ok is False
    assert runs == []


@pytest.mark.parametrize("admin,screen", [(True, True), (False, False)])
def test_windows_status(monkeypatch, runs, admin, screen):
    monkeypatch.setattr(sys, "platform", "win32")
    calls = _fake_windll(monkeypatch, admin=admin)
    if screen:
        _fake_mss(monkeypatch)
    st = perms.current_status()
    assert st.platform == "win32"
    assert st.screen_ok is screen
    assert st.screen_label == ("截屏可用" if screen else "截屏异常")
    assert st.input_ok is True
    assert st.is_admin is admin
    assert ("已是管理员" in st.input_label) is admin
    assert calls == [] and runs == []


def test_permission_status_is_immutable(monkeypatch):
    monkeypatch.setattr(sys, "platform", "plan9")
    st = perms.current_status()
    with pytest.raises(dataclasses.FrozenInstanceError):
        st.screen_ok = True


# ---- request_* ----


def test_macos_request_screen_access(monkeypatch, runs):
    monkeypatch.setattr(sys, "platform", "darwin")
    asked = []
    _module(monkeypatch, "Quartz", CGRequestScreenCaptureAccess=lambda: asked.append(1))
    msg = perms.request_screen_access()
    assert isinstance(msg, str) and msg
    assert asked == [1]
    urls = _open_urls(runs)
    assert len(urls) == 1 and "Privacy_ScreenCapture" in urls[0]


@pytest.mark.parametrize("ok", [True, False])
def test_windows_request_screen_access(monkeypatch, runs, ok):
    monkeypatch.setattr(sys, "platform", "win32")
    if ok:
        _fake_mss(monkeypatch)
    msg = perms.request_screen_access()
    assert ("成功" in msg) is ok and ("失败" in msg) is (not ok)
    assert runs == []


def test_macos_request_input_access(monkeypatch, runs):
    monkeypatch.setattr(sys, "platform", "darwin")
    seen = []

    def trusted_with_options(opts):
        seen.append(opts)
        return False

    _module(
        monkeypatch,
        "ApplicationServices",
        AXIsProcessTrustedWithOptions=trusted_with_options,
        kAXTrustedCheckOptionPrompt="prompt",
    )
    _module(
        monkeypatch,
        "Foundation",
        NSDictionary=SimpleNamespace(dictionaryWithDictionary_=dict),
    )
    msg = perms.request_input_access()
    assert isinstance(msg, str) and msg
    assert seen == [{"prompt": True}]
    urls = _open_urls(runs)
    assert len(urls) == 1 and "Privacy_Accessibility" in urls[0]


@pytest.mark.parametrize(
    "admin,rc,expect",
    [(True, 42, "已是管理员"), (False, 42, "已请求以管理员重新启动"), (False, 5, "提权重启失败")],
)
def test_windows_request_input_access(monkeypatch, runs, admin, rc, expect):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "argv", ["app.py"])
    calls = _fake_windll(monkeypatch, admin=admin, shell_rc=rc)
    assert expect in perms.request_input_access()
    assert len(calls) == (0 if admin else 1)
    assert runs == []


def test_other_platform_requests_have_no_side_effects(monkeypatch, runs):
    monkeypatch.setattr(sys, "platform", "plan9")
    assert perms.request_screen_access()
    assert perms.request_input_access()
    assert runs == []


# ---- reset_macos_tcc ----


def test_reset_tcc_noop_off_macos(monkeypatch, runs):
    monkeypatch.setattr(sys, "platform", "win32")
    assert perms.reset_macos_tcc() == "仅 macOS 支持清理授权。"
    assert runs == []


def test_reset_tcc_default_ids(monkeypatch, runs):
    monkeypatch.setattr(sys, "platform", "darwin")
    msg = perms.reset_macos_tcc()
    tcc = [c for c in runs if c[0] == "tccutil"]
    assert sorted(tcc) == sorted(
        ["tccutil", "reset", svc, bid]
        for bid in ("com.albn.autofish", "com.albn.autofish.dev")
        for svc in ("Accessibility", "ScreenCapture")
    )
    assert "成功 4" in msg and "失败 0" in msg
    urls = _open_urls(runs)
    assert any("Privacy_ScreenCapture" in u for u in urls)
    assert any("Privacy_Accessibility" in u for u in urls)


def test_reset_tcc_counts_failures_and_swallows_errors(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    seen = []

    def fake_run(cmd, *args, **kwargs):
        seen.append(list(cmd))
        if cmd[0] == "tccutil" and cmd[2] == "ScreenCapture":
            raise FileNotFoundError("tccutil")
        rc = 0 if cmd[0] == "open" or cmd[3] == "ok.id" else 1
        return subprocess.CompletedProcess(cmd, rc, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    msg = perms.reset_macos_tcc(("ok.id", "bad.id"))
    assert len([c for c in seen if c[0] == "tccutil"]) == 4
    assert "成功 1" in msg and "失败 3" in msg


# ---- restart_as_admin ----


def test_restart_as_admin_off_windows(monkeypatch, runs):
    monkeypatch.setattr(sys, "platform", "darwin")
    calls = _fake_windll(monkeypatch, admin=False)
    assert perms.restart_as_admin() is False
    assert calls == [] and runs == []


def test_restart_as_admin_already_admin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    calls = _fake_windll(monkeypatch, admin=True)
    assert perms.restart_as_admin() is True
    assert calls == []


@pytest.mark.parametrize("frozen", [False, True])
def test_restart_as_admin_runas(monkeypatch, tmp_path, frozen):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
    script = str(tmp_path / "app.py")
    monkeypatch.setattr(sys, "argv", [script, "--flag"])
    calls = _fake_windll(monkeypatch, admin=False, shell_rc=42)
    assert perms.restart_as_admin() is True
    assert len(calls) == 1
    _, verb, exe, params, *_ = calls[0]
    assert verb == "runas" and exe == sys.executable
    assert '"--flag"' in params
    assert (script in params) is (not frozen)


@pytest.mark.parametrize("rc,raises", [(32, False), (0, False), (42, True)])
def test_restart_as_admin_failure_returns_false(monkeypatch, rc, raises):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "argv", ["app.py"])
    _fake_windll(monkeypatch, admin=False, shell_rc=rc, shell_raises=raises)
    assert perms.restart_as_admin() is False
