import time

import numpy as np
import pytest

from autofish.events.bus import AutofishBus
from autofish.events.topics import CastSessionState, PosEvent, Topic
from autofish.first_click_trigger import FirstClickTrigger

S = CastSessionState


class Rig:
    def __init__(self, kit, fake_sd, mouse, tmp_path):
        self.kit = kit
        self.sd = fake_sd
        self.mouse = mouse
        self.bus = AutofishBus()
        self.events = []
        self.bus.subscribe(Topic.CAST_SESSION, self.events.append)
        self.subscribed = []
        orig = self.bus.subscribe

        def spy(topic, cb):
            self.subscribed.append(topic)
            orig(topic, cb)

        self.bus.subscribe = spy
        self.tpl_path = tmp_path / "tpl.npy"
        np.save(self.tpl_path, kit.splash())
        self.triggers = []
        self._seq = 0

    def make(self, *, template=True, bus=True, threshold=0.7):
        t = FirstClickTrigger(
            self.bus if bus else None,
            device=0,
            threshold=threshold,
            template_path=self.tpl_path if template else None,
        )
        t.set_click_timing(0.0, 0.0, 0.05, 0.05, 0.0, 0.0)
        self.triggers.append(t)
        return t

    def start(self, t):
        n = len(self.sd.streams)
        t.start()
        assert self.kit.wait_for(lambda: len(self.sd.streams) > n and self.sd.streams[-1].started)
        return self.sd.streams[-1]

    def feed(self, t, stream, wave):
        """推一块音频并等会话线程处理完（环缓长度增长）。"""
        before = t.recent_monitor_wave(20.0).size
        stream.push(wave)
        want = min(before + wave.size, int(20 * self.kit.SR))
        assert self.kit.wait_for(lambda: t.recent_monitor_wave(20.0).size >= want)

    def pos(self, value):
        self._seq += 1
        now = time.time()
        self.bus.publish_pos(
            PosEvent(pos=value, hit=None, roi_version=0, frame_ts=now, ts=now, frame_seq=self._seq)
        )

    def states(self):
        return [e.state for e in self.events]

    def wait_state(self, state, after=0, timeout=5.0):
        ok = self.kit.wait_for(
            lambda: any(e.state == state for e in self.events[after:]), timeout=timeout
        )
        assert ok, f"未等到 {state}，已有 {self.states()}"
        return next(e for e in self.events[after:] if e.state == state)

    def close(self):
        for t in self.triggers:
            t.stop()


@pytest.fixture
def rig(kit, fake_sd, fake_mouse, tmp_path):
    r = Rig(kit, fake_sd, fake_mouse, tmp_path)
    yield r
    r.close()


def test_construct_does_not_open_audio_and_starts_disabled(rig):
    t = rig.make()
    assert rig.sd.streams == []
    assert t.session_state == S.DISABLED
    assert t.has_template and t.samplerate == rig.kit.SR
    np.testing.assert_allclose(t.template_wave, rig.kit.splash())
    assert t.trigger_count == 0 and not t.is_running()
    assert rig.events == []


def test_full_cycle_wait_click_bobber_fishing_lost_and_cooldown(rig):
    kit = rig.kit
    t = rig.make()
    t.set_session_enabled(True)
    assert rig.events[-1].state == S.WAIT and rig.events[-1].detail == "a_on"
    stream = rig.start(t)
    assert rig.subscribed == [Topic.POS]

    rig.feed(t, stream, kit.clip())
    first = rig.wait_state(S.FIRST_CLICK)
    hit = first.splash
    assert first.detail == "splash"
    assert hit is not None and hit.score >= 0.7 and hit.threshold == pytest.approx(0.7)
    assert (hit.delay_s, hit.hold_s, hit.after_s) == (0.0, pytest.approx(0.05), 0.0)

    rig.wait_state(S.WAIT_BOBBER)
    assert rig.mouse.calls[:2] == [True, False]
    assert t.trigger_count == 1 and t.last_trigger_at > 0
    hits = t.live_hits_for_monitor(20.0)
    assert len(hits) == 1 and hits[0]["score"] == pytest.approx(hit.score)
    assert hits[0]["end_s"] - hits[0]["start_s"] == pytest.approx(kit.splash().size / kit.SR)

    rig.feed(t, stream, kit.clip())
    rig.pos(50.0)
    fishing = rig.wait_state(S.FISHING)
    assert fishing.detail == "bobber" and fishing.splash is None
    rig.feed(t, stream, kit.clip())
    time.sleep(0.1)
    assert rig.states().count(S.FIRST_CLICK) == 1 and rig.mouse.presses == 1

    n = len(rig.events)
    rig.pos(None)
    lost_at = time.time()
    back = rig.wait_state(S.WAIT, after=n)
    assert back.detail == "lost_1s" and back.ts - lost_at >= 0.95

    n = len(rig.events)
    rig.feed(t, stream, kit.clip())
    time.sleep(0.1)
    assert t.session_state == S.WAIT and len(rig.events) == n

    time.sleep(max(0.0, back.ts + 3.05 - time.time()))
    rig.feed(t, stream, kit.clip())
    again = rig.wait_state(S.FIRST_CLICK, after=n)
    assert again.splash is not None
    assert all(e.splash is None for e in rig.events if e.state != S.FIRST_CLICK)


def test_wait_bobber_times_out_after_3s(rig):
    t = rig.make()
    t.set_session_enabled(True)
    stream = rig.start(t)
    rig.feed(t, stream, rig.kit.clip())
    wb = rig.wait_state(S.WAIT_BOBBER)
    n = len(rig.events)
    back = rig.wait_state(S.WAIT, after=n, timeout=6.0)
    assert back.detail == "bobber_timeout"
    assert back.ts - wb.ts >= 2.95
    assert S.FISHING not in rig.states()


def test_disabled_never_listens_or_clicks(rig):
    t = rig.make()
    stream = rig.start(t)
    rig.feed(t, stream, rig.kit.clip())
    rig.pos(50.0)
    time.sleep(0.1)
    assert t.session_state == S.DISABLED
    assert S.FIRST_CLICK not in rig.states() and S.FISHING not in rig.states()
    assert rig.mouse.presses == 0
    assert Topic.ACTION_INTENT not in rig.subscribed


def test_disable_during_click_releases_mouse(rig):
    t = rig.make()
    t.set_click_timing(0.0, 0.0, 3.0, 3.0, 0.0, 0.0)
    t.set_session_enabled(True)
    stream = rig.start(t)
    rig.feed(t, stream, rig.kit.clip())
    assert rig.kit.wait_for(lambda: rig.mouse.down)
    t.set_session_enabled(False)
    assert not rig.mouse.down
    assert t.session_state == S.DISABLED and rig.events[-1].detail == "a_off"


def test_stop_interrupts_click_clamps_timing_and_aborts_audio(rig):
    t = rig.make()
    t.set_click_timing(5.0, 4.0, 9.0, 0.01, 0.3, 0.1)
    t.set_session_enabled(True)
    stream = rig.start(t)
    rig.feed(t, stream, rig.kit.clip())
    hit = rig.wait_state(S.FIRST_CLICK).splash
    assert 4.0 <= hit.delay_s <= 5.0
    assert 0.05 <= hit.hold_s <= 5.0
    assert 0.1 <= hit.after_s <= 0.3
    t0 = time.time()
    t.stop()
    assert time.time() - t0 < 2.0
    assert not t.is_running()
    assert stream.aborted and stream.closed
    assert t.session_state == S.WAIT and rig.events[-1].detail == "stopped"
    assert rig.mouse.presses == 0 and not rig.mouse.down
    rig.pos(50.0)
    assert t.session_state == S.WAIT


def test_audio_start_failure_logs_and_exits(rig):
    rig.sd.open_error = RuntimeError("no device")
    t = rig.make()
    t.start()
    assert rig.kit.wait_for(lambda: not t.is_running())
    logs = t.drain_logs("sound")
    assert any("音频启动失败" in m and "no device" in m for m in logs)


def test_monitor_wave_keeps_last_20s(rig):
    sr = rig.kit.SR
    t = rig.make()
    stream = rig.start(t)
    wave = (np.arange(21 * sr, dtype=np.float32) / (21 * sr)) * 0.5
    stream.push(wave)
    assert rig.kit.wait_for(lambda: t.recent_monitor_wave(30.0).size == 20 * sr)
    np.testing.assert_allclose(t.recent_monitor_wave(30.0), wave[-20 * sr:])
    np.testing.assert_allclose(t.recent_monitor_wave(5.0), wave[-5 * sr:])
    assert -20.0 < t.level_db < 0.0


def test_threshold_controls_hits(rig):
    t = rig.make(threshold=1.01)
    t.set_session_enabled(True)
    stream = rig.start(t)
    rig.feed(t, stream, rig.kit.clip())
    time.sleep(0.1)
    assert S.FIRST_CLICK not in rig.states()
    assert t.last_score >= 0.7
    t.set_threshold(0.7)
    rig.feed(t, stream, rig.kit.noise(0.05))
    rig.wait_state(S.FIRST_CLICK)


def test_no_template_never_triggers_then_set_template(rig):
    t = rig.make(template=False)
    assert not t.has_template and t.template_wave is None
    t.set_session_enabled(True)
    stream = rig.start(t)
    rig.feed(t, stream, rig.kit.clip())
    time.sleep(0.1)
    assert S.FIRST_CLICK not in rig.states()
    pad = np.zeros(rig.kit.SR // 2, dtype=np.float32)
    t.set_template(np.concatenate([pad, rig.kit.splash(), pad]))
    assert t.template_wave.size < rig.kit.splash().size + pad.size
    rig.feed(t, stream, rig.kit.clip())
    rig.wait_state(S.FIRST_CLICK)


def test_works_without_bus(rig):
    t = rig.make(bus=False)
    t.set_session_enabled(True)
    assert t.session_state == S.WAIT
    stream = rig.start(t)
    rig.feed(t, stream, rig.kit.clip())
    assert rig.kit.wait_for(lambda: t.session_state == S.WAIT_BOBBER)
    assert rig.events == []


def test_play_template_uses_speaker_and_normalizes(rig, tmp_path):
    t = rig.make(template=False)
    with pytest.raises(RuntimeError):
        t.play_template()
    t.load_template(rig.tpl_path)
    before = np.load(rig.tpl_path)
    t.play_template()
    played = rig.sd.played[-1]
    assert played["samplerate"] == rig.kit.SR and played["device"] == 3
    assert float(np.max(np.abs(played["data"]))) == pytest.approx(0.85, abs=1e-3)
    np.testing.assert_array_equal(np.load(rig.tpl_path), before)
    assert rig.sd.streams == []


def test_long_recording_saves_session_and_backtests(rig, lib_dirs):
    from autofish.first_click_trigger.paths import user_audio_sessions_dir

    kit = rig.kit
    t = rig.make()
    with pytest.raises(RuntimeError):
        t.stop_session_recording()
    stream = rig.start(t)
    t.start_session_recording()
    with pytest.raises(RuntimeError):
        t.start_session_recording()
    assert t.is_session_recording
    clip = kit.clip()
    stream.push(clip)
    assert t.session_record_duration_s == pytest.approx(clip.size / kit.SR)
    prev, sr, ranges = t.session_recording_preview()
    assert sr == kit.SR and prev.shape == clip.shape and ranges == []
    out = t.stop_session_recording()
    assert not t.is_session_recording
    assert out["paths"].root.parent == user_audio_sessions_dir()
    assert np.load(out["paths"].audio).shape == (clip.size, 2)
    np.testing.assert_allclose(out["wave"], clip, atol=1e-6)
    assert out["samplerate"] == kit.SR and out["ranges"] == []
    assert out["report"]["summary"]["n_hits"] == 1
    assert "找到 1 处" in out["report_text"]
    assert any("长录音已保存" in m for m in t.drain_logs("backtest"))

    rep = t.backtest_last_or_dir(out["paths"].root)
    assert rep["summary"]["n_hits"] == 1 and rep["report_text"]
    with pytest.raises(RuntimeError):
        t.backtest_last_or_dir(None)

    t.start_session_recording()
    with pytest.raises(RuntimeError):
        t.stop_session_recording()


def test_replace_template_from_range(rig, lib_dirs):
    from autofish.first_click_trigger.paths import get_active_template_name, user_template_dir

    kit = rig.kit
    t = rig.make(template=False)
    wave = kit.clip()
    seg = t.replace_template_from_range(wave, kit.SR, 0.5, 0.9, save_user=False)
    np.testing.assert_array_equal(seg, wave[int(0.5 * kit.SR): int(0.9 * kit.SR)])
    np.testing.assert_array_equal(t.template_wave, seg)
    assert not user_template_dir().exists() or list(user_template_dir().glob("*.npy")) == []
    seg2 = t.replace_template_from_range(wave, kit.SR, 0.9, 0.5)
    saved = list(user_template_dir().glob("*.npy"))
    assert len(saved) == 1 and get_active_template_name() == saved[0].name
    np.testing.assert_array_equal(np.load(saved[0]), seg2)
    with pytest.raises(ValueError):
        t.replace_template_from_range(wave, kit.SR, 50.0, 60.0)
    logs = t.drain_logs("backtest")
    assert any("模板已入库" in m for m in logs) and t.drain_logs("backtest") == []
