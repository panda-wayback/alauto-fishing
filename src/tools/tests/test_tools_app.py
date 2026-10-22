import json
import os
import runpy
import warnings
from dataclasses import asdict
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QMessageBox, QPushButton

import autofish.first_click_trigger.paths as fct_paths
import common.expire as expire
import common.license as lic
import common.permissions as perms
from autofish.events.bus import AutofishBus
from autofish.events.topics import CastSessionState
from autofish.first_click_trigger.audio_input import AudioInput
from autofish.locate import (
    BarMark,
    Roi,
    bar_ref_path,
    load_bar_mark,
    load_roi,
    load_roi_source,
    save_roi,
)
from tools import preview_app, shell_config
from tools.preview_app import PreviewApp, launch_ui
from tools.shell_config import ShellSettings, save_shell_settings

ALL_KEYS = set(asdict(ShellSettings()))


class FakeDecide:
    def __init__(self):
        self.ranges = None

    def set_ranges(self, plo, phi, rlo, rhi):
        self.ranges = (plo, phi, rlo, rhi)

    @property
    def current_thresholds(self):
        plo, phi, rlo, rhi = self.ranges or (70.0, 74.0, 76.0, 79.0)
        return (plo + phi) / 2.0, (rlo + rhi) / 2.0


class FakeAct:
    pressed = False
    yielding = False

    def poll(self):
        pass


class FakeAutoCast:
    def __init__(self):
        self.active = False
        self.remaining = 0
        self.batch_total = 0
        self._wait_lo = 3.0
        self._wait_hi = 3.0
        self._full_charge_s = 1.0

    def start_batch(self, count: int) -> bool:
        if self.active:
            return False
        self.active = True
        n = max(1, min(20, int(count)))
        self.remaining = n
        self.batch_total = n
        return True

    def cancel_batch(self) -> None:
        self.active = False
        self.remaining = 0
        self.batch_total = 0

    def set_full_charge_s(self, seconds: float) -> None:
        self._full_charge_s = float(max(0.05, min(5.0, seconds)))


class FakeCursorArm:
    """测试用：不截屏、不起线程。"""

    def __init__(
        self, *, interval_s=0.3, size=100, on_armed_changed=None, on_frame=None
    ):
        self._armed = False
        self._enabled = False
        self._on = on_armed_changed
        self._on_frame = on_frame
        self._last_frame = None
        self.started = False

    @property
    def armed(self) -> bool:
        return self._armed

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def last_frame(self):
        return self._last_frame

    def start(self) -> None:
        self.started = True

    def stop(self, timeout: float = 2.0) -> None:
        self.started = False
        self._enabled = False
        was = self._armed
        self._armed = False
        self._last_frame = None
        if was and self._on is not None:
            self._on(False)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        if not self._enabled:
            self._last_frame = None
            if self._armed:
                self._armed = False
                if self._on is not None:
                    self._on(False)

    def is_running(self) -> bool:
        return self.started

    def force_armed(self, armed: bool) -> None:
        armed = bool(armed)
        if self._armed == armed:
            return
        self._armed = armed
        if self._on is not None:
            self._on(armed)


class FakePipeline:
    """替代 autofish.AutofishPipeline：只记录调用，不起截屏/控鼠线程。"""

    instances: list["FakePipeline"] = []

    def __init__(self, *, capture_fps=45.0, **_kw):
        self.bus = AutofishBus()
        self.decide = FakeDecide()
        self.act = FakeAct()
        self.auto_cast = FakeAutoCast()
        self.rois = []
        self.monitor_on = False
        self.decide_on = False
        self.act_on = False
        self.auto_cast_on = False
        self.stopped = False
        FakePipeline.instances.append(self)

    def subscribe(self, topic, cb):
        self.bus.subscribe(topic, cb)

    def unsubscribe(self, topic, cb):
        self.bus.unsubscribe(topic, cb)

    def snapshot(self):
        return self.bus.snapshot()

    def set_roi_manual(self, roi):
        self.rois.append(roi)

    def set_decide_ranges(self, plo, phi, rlo, rhi):
        self.decide.set_ranges(plo, phi, rlo, rhi)

    def start_monitor(self):
        self.monitor_on = True

    def stop_monitor(self):
        self.monitor_on = False

    def start_decide(self):
        self.decide_on = True

    def stop_decide(self):
        self.decide_on = False

    def start_act(self):
        self.act_on = True

    def stop_act(self):
        self.act_on = False

    def start_auto_cast(self):
        self.auto_cast_on = True

    def stop_auto_cast(self):
        self.auto_cast_on = False
        self.auto_cast.cancel_batch()

    def start_cast_batch(self, count):
        return self.auto_cast.start_batch(count)

    def cancel_cast_batch(self):
        self.auto_cast.cancel_batch()

    def set_cast_wait_range(self, lo_s, hi_s):
        self.auto_cast._wait_lo = float(lo_s)
        self.auto_cast._wait_hi = float(hi_s)

    def set_cast_full_charge_s(self, seconds: float) -> None:
        self.auto_cast.set_full_charge_s(seconds)

    def stop(self):
        self.monitor_on = self.decide_on = self.act_on = self.auto_cast_on = False
        self.auto_cast.cancel_batch()
        self.stopped = True


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    # offscreen 缺省字体族 "Sans Serif" 不存在时 Qt 会花数秒枚举别名
    families = set(QFontDatabase.families())
    for fam in ("Helvetica", "Arial", "DejaVu Sans"):
        if fam in families:
            app.setFont(QFont(fam))
            break
    return app


@pytest.fixture
def env(tmp_path, monkeypatch, app):
    data = tmp_path / "data"
    assets = tmp_path / "assets"
    state = tmp_path / "state"
    for d in (data, assets, state):
        d.mkdir()
    monkeypatch.setattr(shell_config, "data_root", lambda: data)
    monkeypatch.setattr(shell_config, "assets_dir", lambda: assets)
    monkeypatch.setattr(lic, "user_state_root", lambda: state)
    monkeypatch.setattr(lic, "data_root", lambda: data)
    monkeypatch.setattr(expire, "assets_dir", lambda: assets)
    monkeypatch.setattr(fct_paths, "data_root", lambda: data)
    monkeypatch.setattr(fct_paths, "assets_dir", lambda: assets)
    monkeypatch.setattr(fct_paths, "bundle_root", lambda: tmp_path / "bundle")
    monkeypatch.setattr(AudioInput, "list_devices", staticmethod(lambda: []))
    monkeypatch.setattr(
        perms,
        "current_status",
        lambda: perms.PermissionStatus(
            platform="test",
            screen_ok=None,
            screen_label="-",
            input_ok=None,
            input_label="-",
            is_admin=None,
        ),
    )
    monkeypatch.setattr(preview_app, "AutofishPipeline", FakePipeline)
    monkeypatch.setattr(preview_app, "CursorArmWatcher", FakeCursorArm)
    monkeypatch.setattr(preview_app, "os_left_down", lambda: False)
    monkeypatch.setattr(preview_app, "primary_screen_size", lambda: (1600, 1200))
    monkeypatch.setattr(preview_app.CastHotkeyListener, "start", lambda self: None)
    monkeypatch.setattr(preview_app.CastHotkeyListener, "stop", lambda self: None)
    monkeypatch.setattr(preview_app.CastRightClickListener, "start", lambda self: None)
    monkeypatch.setattr(preview_app.CastRightClickListener, "stop", lambda self: None)

    boxes = []
    for kind in ("warning", "information", "critical"):
        monkeypatch.setattr(
            QMessageBox,
            kind,
            staticmethod(lambda *a, _k=kind, **kw: boxes.append((_k, a))),
        )

    FakePipeline.instances.clear()
    ns = SimpleNamespace(
        app=app,
        data=data,
        assets=assets,
        state=state,
        roi=data / "roi.json",
        settings_file=data / "shell_settings.json",
        boxes=boxes,
    )
    yield ns
    for w in app.topLevelWidgets():
        if isinstance(w, (PreviewApp, QDialog)):
            if w.isVisible():
                w.close()
            w.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    FakePipeline.instances.clear()


def _make(env):
    win = PreviewApp(roi_path=env.roi)
    env.app.processEvents()
    return win


def _settings(env):
    return json.loads(env.settings_file.read_text(encoding="utf-8"))


def _pipe():
    assert FakePipeline.instances
    return FakePipeline.instances[-1]


def _expand_button(win):
    return next(b for b in win.findChildren(QPushButton) if b.text() == "主界面")


def _close(win, env):
    win.close()
    env.app.processEvents()


def test_default_roi_written_and_monitor_on(env):
    win = _make(env)
    assert env.roi.is_file()
    assert load_roi_source(env.roi) == "default"
    roi = load_roi(env.roi)
    assert roi == Roi(left=600, top=450, width=400, height=300)
    pipe = _pipe()
    assert pipe.rois[-1] == roi
    assert pipe.monitor_on
    assert win.chk_b.isChecked()
    assert pipe.decide_on and pipe.act_on
    assert pipe.decide.ranges == pytest.approx((70.6, 74.4, 76.6, 79.2))
    _close(win, env)


def test_existing_roi_loaded_and_monitored(env):
    roi = Roi(left=10, top=20, width=300, height=80)
    save_roi(roi, env.roi, source="manual")
    win = _make(env)
    pipe = _pipe()
    assert pipe.rois[-1] == roi
    assert pipe.monitor_on
    assert load_roi_source(env.roi) == "manual"
    _close(win, env)


def test_cast_hotkey_batch_and_wait_persist(env):
    win = _make(env)
    pipe = _pipe()
    assert not pipe.auto_cast.active
    assert not win.chk_c.isChecked()
    win._on_cast_hotkey_start()
    assert not pipe.auto_cast.active
    win.chk_c.setChecked(True)
    assert pipe.auto_cast_on
    win._on_cast_hotkey_start()
    assert pipe.auto_cast.active and pipe.auto_cast_on
    assert pipe.auto_cast.remaining == 5
    win._on_cast_hotkey_start()
    assert pipe.auto_cast.remaining == 5
    win.bar_cast_count.setRange(2.0, 4.0)
    win.bar_cast_wait.setRange(1.0, 4.0)
    assert (pipe.auto_cast._wait_lo, pipe.auto_cast._wait_hi) == (1.0, 4.0)
    win._persist_timer.stop()
    win._persist_settings()
    raw = _settings(env)
    assert raw["cast_count_lo"] == 2
    assert raw["cast_count_hi"] == 4
    assert raw["cast_wait_lo_s"] == pytest.approx(1.0)
    assert raw["cast_wait_hi_s"] == pytest.approx(4.0)
    assert raw["auto_cast_enabled"] is True
    win._on_cast_hotkey_stop()
    assert not pipe.auto_cast.active and pipe.auto_cast.remaining == 0
    _close(win, env)


def test_toggle_c_gates_cast_and_right_click(env):
    win = _make(env)
    pipe = _pipe()
    assert not win.chk_c.isChecked()
    assert not pipe.auto_cast_on
    win.chk_c.setChecked(True)
    assert pipe.auto_cast_on
    assert win._cursor_arm is not None and win._cursor_arm.enabled
    assert not win.lbl_arm_preview.isHidden()
    win._cursor_arm.force_armed(True)
    assert win.lbl_cast.text() == "就绪"
    assert win.lbl_cast_remain.text() == "5"
    assert "抛杆认漂" not in win.log.toPlainText()
    win._on_cast_right_click()
    assert pipe.auto_cast.active
    assert win.lbl_cast_remain.text() == "5/5"
    win._on_cast_right_click()
    assert not pipe.auto_cast.active
    win.chk_c.setChecked(False)
    assert not pipe.auto_cast_on
    assert win.lbl_arm_preview.isHidden()
    assert win.lbl_cast_remain.text() == "—"
    assert _settings(env)["auto_cast_enabled"] is False
    _close(win, env)


def test_restore_c_on_from_settings(env):
    save_shell_settings(ShellSettings(auto_cast_enabled=True))
    win = _make(env)
    pipe = _pipe()
    assert win.chk_c.isChecked()
    assert pipe.auto_cast_on
    _close(win, env)


def test_persist_cast_batch_settings_restore_on_start(env):
    save_shell_settings(
        ShellSettings(
            cast_count_lo=3,
            cast_count_hi=7,
            cast_start_hotkey="F7",
            cast_stop_hotkey="F10",
            cast_wait_lo_s=3.0,
            cast_wait_hi_s=6.0,
        )
    )
    win = _make(env)
    pipe = _pipe()
    assert win.bar_cast_count.range() == pytest.approx((3.0, 7.0))
    assert win._settings.cast_start_hotkey == "F7"
    assert win._settings.cast_stop_hotkey == "F10"
    assert not pipe.auto_cast.active
    assert (pipe.auto_cast._wait_lo, pipe.auto_cast._wait_hi) == (3.0, 6.0)
    _close(win, env)


def test_toggle_b_controls_decide_act_and_persists(env):
    win = _make(env)
    pipe = _pipe()
    win.chk_b.setChecked(False)
    assert not pipe.decide_on and not pipe.act_on
    assert pipe.monitor_on
    assert _settings(env)["auto_bobber_enabled"] is False
    win.chk_b.setChecked(True)
    assert pipe.decide_on and pipe.act_on
    assert _settings(env)["auto_bobber_enabled"] is True
    _close(win, env)


def test_toggle_a_without_device_keeps_preference(env):
    win = _make(env)
    win.chk_a.setChecked(True)
    env.app.processEvents()
    assert win.chk_a.isChecked()
    assert _settings(env)["sound_enabled"] is True
    assert _pipe().snapshot().cast_session == CastSessionState.DISABLED
    win.chk_a.setChecked(False)
    assert _settings(env)["sound_enabled"] is False
    _close(win, env)


def test_restore_b_off_from_settings(env):
    save_shell_settings(ShellSettings(auto_bobber_enabled=False))
    win = _make(env)
    pipe = _pipe()
    assert not win.chk_b.isChecked()
    assert not pipe.decide_on and not pipe.act_on
    assert pipe.monitor_on
    _close(win, env)


def test_compact_hud_shows_cast_remain(env):
    win = _make(env)
    pipe = _pipe()
    win.chk_c.setChecked(True)
    win._cursor_arm.force_armed(True)
    win._on_cast_hotkey_start()
    assert pipe.auto_cast.active
    win._set_compact_mode(True)
    assert win._compact
    assert "5/5" in win._hud.lbl_cast.text()
    win._hud.sld_opacity.setValue(70)
    assert win.windowOpacity() == pytest.approx(0.70, abs=0.02)
    assert _settings(env)["hud_opacity"] == pytest.approx(0.70, abs=0.02)
    win._set_compact_mode(False)
    assert win.windowOpacity() == pytest.approx(1.0)
    _close(win, env)


def test_float_button_toggles_compact_and_persists(env):
    win = _make(env)
    win.show()
    env.app.processEvents()
    full_w = win.width()
    assert full_w >= 360
    win.btn_float.click()
    env.app.processEvents()
    expand = _expand_button(win)
    assert expand.isVisible()
    assert not win.btn_float.isVisible()
    assert win.width() < 360
    assert win.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert _settings(env)["compact_mode"] is True

    expand.click()
    env.app.processEvents()
    assert win.btn_float.isVisible()
    assert not expand.isVisible()
    assert win.width() == full_w
    assert _settings(env)["compact_mode"] is False
    _close(win, env)


def test_startup_compact_from_settings(env):
    save_shell_settings(ShellSettings(compact_mode=True))
    win = _make(env)
    assert win.isVisible()
    assert _expand_button(win).isVisible()
    assert not win.btn_float.isVisible()
    assert _settings(env)["compact_mode"] is True
    _close(win, env)


def test_close_persists_all_keys_and_stops_pipeline(env):
    win = _make(env)
    pipe = _pipe()
    _close(win, env)
    assert set(_settings(env)) == ALL_KEYS
    assert pipe.stopped
    assert not (pipe.monitor_on or pipe.decide_on or pipe.act_on)


def _write_expired(env):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    (env.assets / "expire.json").write_text(
        json.dumps({"expire_on": yesterday}), encoding="utf-8"
    )


def _close_windows_soon(app, seen):
    def closer():
        for w in app.topLevelWidgets():
            if isinstance(w, PreviewApp) and w.isVisible():
                seen.append(w.roi_path)
                w.close()
        app.quit()

    QTimer.singleShot(0, closer)


def test_launch_refused_when_package_expired(env):
    _write_expired(env)
    assert launch_ui(roi_path=env.roi) == 1
    assert [k for k, _ in env.boxes] == ["critical"]
    assert FakePipeline.instances == []
    assert not env.roi.exists()


def _yes(monkeypatch):
    monkeypatch.setattr(
        preview_app.QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )


def _no(monkeypatch):
    monkeypatch.setattr(
        preview_app.QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No),
    )


def test_restore_defaults_resets_settings_and_roi(env, monkeypatch):
    save_shell_settings(
        ShellSettings(
            sound_threshold=0.55,
            sound_enabled=True,
            auto_bobber_enabled=False,
            compact_mode=True,
            audio_device_name="BlackHole 2ch",
            window_x=10,
            window_y=20,
            window_w=500,
            window_h=800,
            press_lo=62.0,
            press_interval_s=0.2,
            click_delay_lo_s=1.0,
            click_delay_hi_s=2.0,
        )
    )
    (env.assets / "shell_settings.json").write_text(
        json.dumps({"sound_threshold": 0.81, "sound_enabled": False, "press_lo": 71.2}),
        encoding="utf-8",
    )
    save_roi(
        Roi(11, 22, 200, 100),
        env.roi,
        bar=BarMark(10, 80, 0, 12, frame_width=200),
        source="manual",
    )
    ref = bar_ref_path(env.roi)
    ref.write_bytes(b"png")
    _yes(monkeypatch)
    win = _make(env)
    assert win._compact
    assert win.chk_b.isChecked() is False
    win.btn_restore_defaults.click()
    env.app.processEvents()
    raw = _settings(env)
    assert raw["sound_threshold"] == pytest.approx(0.81)
    assert raw["press_lo"] == pytest.approx(71.2)
    assert raw["sound_enabled"] is False
    assert raw["auto_bobber_enabled"] is True
    assert raw["compact_mode"] is False
    assert raw["audio_device_name"] == ""
    assert (raw["window_x"], raw["window_y"], raw["window_w"], raw["window_h"]) == (
        -1,
        -1,
        0,
        0,
    )
    assert (raw["hud_x"], raw["hud_y"]) == (-1, -1)
    assert raw["press_interval_s"] == pytest.approx(0.0)
    assert (raw["click_delay_lo_s"], raw["click_delay_hi_s"]) == (0.3, 1.5)
    assert load_roi(env.roi) == Roi(left=600, top=450, width=400, height=300)
    assert load_roi_source(env.roi) == "default"
    assert load_bar_mark(env.roi) is None
    assert not ref.exists()
    assert win.chk_a.isChecked() is False
    assert win.chk_b.isChecked() is True
    assert win.chk_c.isChecked() is False
    assert win.range_axis.ranges()[0] == pytest.approx(71.2)
    assert win.sld_press_interval.value() == 0
    assert win.bar_delay.range() == pytest.approx((0.3, 1.5))
    assert win._sound_panel.current_threshold() == pytest.approx(0.81)
    assert not win._compact
    assert (win.width(), win.height()) == (460, 800)
    assert _pipe().decide_on and _pipe().act_on
    assert _pipe().monitor_on
    assert _pipe().rois[-1] == load_roi(env.roi)
    _close(win, env)


def test_restore_defaults_cancel_keeps_settings_and_roi(env, monkeypatch):
    save_shell_settings(ShellSettings(sound_threshold=0.55, press_lo=62.0))
    save_roi(Roi(11, 22, 200, 100), env.roi, source="manual")
    _no(monkeypatch)
    win = _make(env)
    before = env.settings_file.read_text(encoding="utf-8")
    win.btn_restore_defaults.click()
    env.app.processEvents()
    assert env.settings_file.read_text(encoding="utf-8") == before
    assert load_roi(env.roi) == Roi(11, 22, 200, 100)
    assert load_roi_source(env.roi) == "manual"
    assert win.range_axis.ranges()[0] == pytest.approx(62.0)
    _close(win, env)


def test_launch_refused_when_activation_cancelled(env, monkeypatch):
    shown = []

    def fake_exec(self):
        shown.append(self)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    assert launch_ui(roi_path=env.roi) == 1
    assert len(shown) == 1
    assert FakePipeline.instances == []
    assert not lic.is_licensed()


def test_launch_activates_key_in_dialog_then_opens(env, monkeypatch):
    key = lic.issue_key(30)

    def fake_exec(self):
        self.findChild(QLineEdit).setText(key)
        next(b for b in self.findChildren(QPushButton) if b.text() == "激活").click()
        return QDialog.DialogCode(self.result())

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    seen = []
    _close_windows_soon(env.app, seen)
    assert launch_ui(roi_path=env.roi) == 0
    assert lic.is_licensed()
    assert (env.state / "license.json").is_file()
    assert seen == [env.roi]
    assert _pipe().stopped


def test_launch_licensed_skips_dialog_and_uses_roi_path(env, monkeypatch):
    lic.activate_key(lic.issue_key(30))

    def no_dialog(self):
        raise AssertionError("激活框不应弹出")

    monkeypatch.setattr(QDialog, "exec", no_dialog)
    seen = []
    _close_windows_soon(env.app, seen)
    assert launch_ui(roi_path=env.roi) == 0
    assert seen == [env.roi]
    assert env.roi.is_file()
    assert set(_settings(env)) == ALL_KEYS


def test_python_m_exits_1_when_expired(env):
    _write_expired(env)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        with pytest.raises(SystemExit) as exc:
            runpy.run_module("tools.preview_app", run_name="__main__")
    assert exc.value.code == 1
    assert FakePipeline.instances == []
