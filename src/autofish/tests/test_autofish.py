import threading
import time
from pathlib import Path

import mss
import numpy as np
import pytest
from PIL import Image

import autofish.act.mouse as act_mouse
import autofish.act.worker as act_worker
from autofish import AutofishPipeline
from autofish.detect import apply_manual_bar
from autofish.events.bus import AutofishBus
from autofish.events.topics import FishingState, PosEvent, RoiEvent, Topic
from autofish.fishing_fsm import FishingStateMachine
from autofish.locate import Roi, save_roi
from autofish.preview import main as preview_main

REPO = Path(__file__).resolve().parents[3]
BOBBER_PNG = REPO / "data" / "test" / "0fd6f53c5a048267eb2254c47882f0d6.png"
ROI = Roi(left=0, top=0, width=1140, height=1015)


def load_rgb(path):
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)


def wait_until(pred, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def in_thread(fn, *args):
    """新线程里调用：截屏会话按线程缓存，确保用到打过补丁的 mss。"""
    out = {}

    def run():
        try:
            out["v"] = fn(*args)
        except BaseException as exc:  # noqa: BLE001
            out["e"] = exc

    t = threading.Thread(target=run)
    t.start()
    t.join(30)
    if "e" in out:
        raise out["e"]
    return out.get("v")


@pytest.fixture
def frame_source(monkeypatch):
    """替换 mss：任何截屏都返回 state["rgb"]（BGRA）。"""
    state = {"rgb": load_rgb(BOBBER_PNG), "grabs": []}
    mon = {"left": 0, "top": 0, "width": 1140, "height": 1015}

    class FakeMss:
        monitors = [dict(mon), dict(mon)]

        def grab(self, region):
            state["grabs"].append(dict(region))
            rgb = state["rgb"]
            alpha = np.full(rgb.shape[:2] + (1,), 255, np.uint8)
            return np.concatenate([rgb[:, :, ::-1], alpha], axis=2)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(mss, "mss", FakeMss)
    return state


@pytest.fixture
def fake_mouse(monkeypatch):
    """替换 pynput 鼠标控制器与系统键态读取，记录按下 / 松开。"""
    log = []

    class FakeController:
        def press(self, button):
            log.append("press")

        def release(self, button):
            log.append("release")

    monkeypatch.setattr(act_mouse, "Controller", FakeController)
    monkeypatch.setattr(act_mouse, "os_left_down", lambda: False)
    monkeypatch.setattr(act_worker, "os_left_down", lambda: False)
    return log


@pytest.fixture
def pipe(frame_source, fake_mouse):
    p = AutofishPipeline(capture_fps=20.0)
    yield p
    p.stop()


class Recorder:
    def __init__(self, pipe, topics):
        self._lock = threading.Lock()
        self.items = []
        for topic in topics:
            pipe.subscribe(topic, self._make(topic))

    def _make(self, topic):
        def cb(event):
            with self._lock:
                self.items.append((topic, event))

        return cb

    def of(self, topic):
        with self._lock:
            return [e for t, e in self.items if t == topic]

    def index(self, pred):
        with self._lock:
            for i, (t, e) in enumerate(self.items):
                if pred(t, e):
                    return i
        return -1


# ---------------- 集成：ROI → Frame → Pos → FishingState → ActionIntent → 鼠标 ----------------


def test_integration_roi_frame_pos_intent_mouse(pipe, frame_source, fake_mouse):
    apply_manual_bar(None)
    rec = Recorder(
        pipe, [Topic.FRAME, Topic.POS, Topic.FISHING_STATE, Topic.ACTION_INTENT]
    )
    pipe.set_decide_ranges(90.0, 92.0, 95.0, 97.0)  # 任何正常读数都 < 按下阈值 → 按住
    pipe.set_roi_manual(ROI)
    pipe.start_decide()
    pipe.start_act()
    in_thread(pipe.start_monitor)

    def pressed_intent():
        return [e for e in rec.of(Topic.ACTION_INTENT) if e.holding]

    assert wait_until(lambda: pressed_intent() and "press" in fake_mouse, timeout=15.0)

    frames = rec.of(Topic.FRAME)
    assert frames and frames[0].roi_version == 1
    assert np.array_equal(frames[0].frame, frame_source["rgb"])
    valid_pos = [p for p in rec.of(Topic.POS) if p.pos is not None]
    assert valid_pos, "真实截图上应识别到鱼漂读数"
    first_pos = valid_pos[0]
    assert 0.0 <= first_pos.pos <= 100.0
    assert first_pos.roi_version == 1
    assert first_pos.frame_seq in {f.seq for f in frames}

    i_frame = rec.index(lambda t, e: t == Topic.FRAME and e.seq == first_pos.frame_seq)
    i_pos = rec.index(lambda t, e: t == Topic.POS and e is first_pos)
    assert 0 <= i_frame < i_pos

    states = rec.of(Topic.FISHING_STATE)
    assert any(s.state == FishingState.FISHING for s in states)

    intent = pressed_intent()[0]
    assert intent.pos == pytest.approx(first_pos.pos)
    assert intent.ts >= first_pos.ts
    assert pipe.act.pressed
    snap = pipe.snapshot()
    assert snap.holding is True
    assert snap.fishing_state == FishingState.FISHING
    assert frame_source["grabs"]

    # 清空手框 → IDLE → 松开意图 → 假鼠标松开，且不再出帧
    pipe.clear_roi()
    assert wait_until(lambda: fake_mouse[-1:] == ["release"], timeout=3.0)
    assert pipe.snapshot().fishing_state == FishingState.IDLE
    assert rec.of(Topic.ACTION_INTENT)[-1].holding is False
    assert not pipe.act.pressed
    time.sleep(0.2)
    n = len(rec.of(Topic.FRAME))
    time.sleep(0.3)
    assert len(rec.of(Topic.FRAME)) == n

    pipe.stop()
    assert not (pipe.monitor_on or pipe.decide_on or pipe.act_on)
    assert not pipe.capture.is_running() and not pipe.detector.is_running()
    assert fake_mouse.count("press") == fake_mouse.count("release")


# ---------------- 流水线启停与 ROI ----------------


def test_start_stop_idempotent_and_no_grab_without_roi(pipe, frame_source):
    assert not (pipe.monitor_on or pipe.decide_on or pipe.act_on)
    in_thread(pipe.start_monitor)
    in_thread(pipe.start_monitor)
    pipe.start_decide()
    pipe.start_decide()
    pipe.start_act()
    pipe.start_act()
    assert pipe.monitor_on and pipe.decide_on and pipe.act_on
    assert pipe.capture.is_running() and pipe.detector.is_running()

    before = len(frame_source["grabs"])  # 只可能有预热
    time.sleep(0.3)
    assert len(frame_source["grabs"]) == before

    pipe.stop_act()
    assert not pipe.act_on and pipe.decide_on and pipe.monitor_on
    pipe.stop_decide()
    pipe.stop_decide()
    assert not pipe.decide_on and pipe.monitor_on
    pipe.stop_monitor()
    pipe.stop_monitor()
    assert not pipe.monitor_on
    assert not pipe.capture.is_running() and not pipe.detector.is_running()
    pipe.stop()

    in_thread(pipe.start_monitor)
    assert pipe.monitor_on and pipe.capture.is_running()
    pipe.stop()
    assert not pipe.monitor_on and not pipe.capture.is_running()


def test_roi_versions_and_sources(pipe):
    got = []
    pipe.subscribe(Topic.ROI, got.append)
    pipe.set_roi_manual(ROI)
    other = Roi(left=1, top=2, width=30, height=40)
    pipe.set_roi_manual(other)
    pipe.clear_roi()
    pipe.set_roi_manual(ROI)
    assert [e.version for e in got] == [1, 2, 3, 4]
    assert [e.roi for e in got] == [ROI, other, None, ROI]
    assert all(e.source == "manual" for e in got)
    assert got[0].score == 1.0
    assert pipe.bus.current_roi() == (ROI, 4)
    pipe.unsubscribe(Topic.ROI, got.append)
    pipe.clear_roi()
    assert len(got) == 4


def test_set_decide_ranges(pipe):
    pipe.set_decide_ranges(10.0, 20.0, 30.0, 40.0)
    low, high = pipe.decide.current_thresholds
    assert 10.0 <= low <= 20.0 and 30.0 <= high <= 40.0
    with pytest.raises(ValueError):
        pipe.set_decide_ranges(30.0, 40.0, 35.0, 50.0)
    with pytest.raises(ValueError):
        pipe.set_decide_ranges(20.0, 10.0, 30.0, 40.0)


# ---------------- 鱼漂状态机 ----------------


class FsmHarness:
    def __init__(self, lost_after=2, idle_after=4):
        self.bus = AutofishBus()
        self.fsm = FishingStateMachine(self.bus, lost_after=lost_after, idle_after=idle_after)
        self.events = []
        self.bus.subscribe(Topic.FISHING_STATE, self.events.append)
        self.version = 0
        self.seq = 0

    def roi(self, roi=ROI):
        self.version += 1
        self.bus.publish_roi(RoiEvent(roi=roi, version=self.version, ts=0.0, source="manual"))

    def pos(self, value):
        self.seq += 1
        self.bus.publish_pos(
            PosEvent(
                pos=value, hit=None, roi_version=self.version,
                frame_ts=0.0, ts=0.0, frame_seq=self.seq,
            )
        )

    def trail(self):
        return [(e.state, e.detail) for e in self.events]


def test_fsm_pos_driven_transitions():
    h = FsmHarness(lost_after=2, idle_after=4)
    h.roi()
    h.pos(None)
    assert h.events == []  # IDLE 下丢读数不发布
    h.pos(50.0)
    h.pos(55.0)
    h.pos(None)
    h.pos(None)
    h.pos(60.0)
    h.pos(None)
    h.pos(None)
    h.pos(None)
    h.pos(None)
    assert h.trail() == [
        (FishingState.FISHING, "pos_ok"),
        (FishingState.LOST, "pos_miss"),
        (FishingState.FISHING, "pos_ok"),
        (FishingState.LOST, "pos_miss"),
        (FishingState.IDLE, "pos_gone"),
    ]
    assert h.bus.snapshot().fishing_state == FishingState.IDLE


def test_fsm_roi_cleared_and_no_roi():
    h = FsmHarness()
    h.pos(50.0)  # 尚无 ROI
    assert h.trail() == [(FishingState.IDLE, "no_roi")]
    h.pos(50.0)
    assert len(h.events) == 1  # 相同状态与 detail 不重复

    h.roi()
    h.pos(50.0)
    h.pos(None)  # 丢读计数 1
    h.roi(None)
    assert h.trail()[-2:] == [
        (FishingState.FISHING, "pos_ok"),
        (FishingState.IDLE, "roi_cleared"),
    ]
    h.roi()
    h.pos(50.0)
    h.pos(None)  # ROI 清空已清零计数：只丢 1 帧不进 LOST
    assert h.trail()[-1] == (FishingState.FISHING, "pos_ok")


# ---------------- CLI：python -m autofish.preview ----------------


def test_preview_image_with_bobber(tmp_path, capsys):
    apply_manual_bar(None)
    out = tmp_path / "out" / "dbg.png"
    assert preview_main(["--image", str(BOBBER_PNG), "--out", str(out)]) == 0
    assert "pos=" in capsys.readouterr().out
    assert Image.open(out).size == Image.open(BOBBER_PNG).size


def test_preview_image_without_bobber(tmp_path, capsys):
    blank = tmp_path / "blank.png"
    Image.fromarray(np.zeros((60, 200, 3), np.uint8)).save(blank)
    out = tmp_path / "dbg.png"
    assert preview_main(["--image", str(blank), "--out", str(out)]) == 2
    assert "未找到" in capsys.readouterr().out
    assert Image.open(out).size == (200, 60)


def test_preview_missing_roi_file(tmp_path, frame_source, capsys):
    out = tmp_path / "dbg.png"
    code = preview_main(["--roi", str(tmp_path / "none.json"), "--out", str(out)])
    assert code == 1
    assert "ROI" in capsys.readouterr().err
    assert not out.exists()
    assert frame_source["grabs"] == []


def test_preview_grabs_roi_from_screen(tmp_path, frame_source):
    frame_source["rgb"] = np.zeros((40, 120, 3), np.uint8)
    roi_file = save_roi(Roi(left=7, top=9, width=120, height=40), tmp_path / "roi.json")
    out = tmp_path / "dbg.png"
    code = in_thread(preview_main, ["--roi", str(roi_file), "--out", str(out)])
    assert code == 2
    assert frame_source["grabs"] == [{"left": 7, "top": 9, "width": 120, "height": 40}]
    assert Image.open(out).size == (120, 40)


def test_preview_rejects_ui_flag():
    with pytest.raises(SystemExit) as exc:
        preview_main(["--ui"])
    assert exc.value.code == 2
