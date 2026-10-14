"""first_click_trigger 测试共用假件：假 sounddevice、假鼠标、合成水花、数据目录重定向。"""

from __future__ import annotations

import sys
import time
from types import SimpleNamespace

import numpy as np
import pytest

SR = 8000


def make_splash(sr: int = SR, dur: float = 0.4, seed: int = 1) -> np.ndarray:
    """合成「水花」：带包络的扫频 + 噪声。"""
    rng = np.random.default_rng(seed)
    n = int(sr * dur)
    t = np.arange(n) / sr
    env = np.exp(-t * 12.0) * (1 - np.exp(-t * 200.0))
    tone = np.sin(2 * np.pi * (600 + 2500 * t) * t)
    return (0.6 * env * (0.6 * rng.standard_normal(n) + tone)).astype(np.float32)


def make_noise(seconds: float, sr: int = SR, level: float = 0.003, seed: int = 5) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (level * rng.standard_normal(int(sr * seconds))).astype(np.float32)


def splash_clip(sr: int = SR) -> np.ndarray:
    """环境底噪 + 水花 + 尾部底噪。"""
    return np.concatenate([make_noise(0.5, sr), make_splash(sr), make_noise(0.2, sr, seed=6)])


def wait_for(pred, timeout: float = 5.0, interval: float = 0.01) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(interval)
    return bool(pred())


@pytest.fixture
def kit():
    """合成音频与轮询工具（importlib 模式下测试文件无法直接 import conftest）。"""
    return SimpleNamespace(
        SR=SR,
        splash=make_splash,
        noise=make_noise,
        clip=splash_clip,
        wait_for=wait_for,
    )


class FakeStream:
    def __init__(self, sd, device=None, samplerate=None, blocksize=None, channels=None,
                 dtype=None, callback=None, **_kw):
        self.device = device
        self.samplerate = samplerate
        self.blocksize = blocksize
        self.channels = channels
        self.callback = callback
        self.started = False
        self.aborted = False
        self.closed = False
        sd.streams.append(self)

    def start(self):
        self.started = True

    def abort(self):
        self.aborted = True

    def stop(self):
        self.aborted = True

    def close(self):
        self.closed = True

    def push(self, mono) -> None:
        """模拟声卡回调：单声道按设备声道数复制成 (N, ch)。"""
        x = np.asarray(mono, dtype=np.float32).reshape(-1, 1)
        data = np.repeat(x, self.channels, axis=1)
        self.callback(data, len(data), {}, None)


class _Default:
    def __init__(self):
        self.device = [0, 3]


class FakeSounddevice:
    """替代 sounddevice 模块：设备表、InputStream、play/stop。"""

    def __init__(self):
        self.devices = [
            {"name": "BlackHole 2ch", "max_input_channels": 2, "max_output_channels": 2,
             "default_samplerate": float(SR), "hostapi": 0},
            {"name": "MacBook Pro Microphone", "max_input_channels": 1,
             "max_output_channels": 0, "default_samplerate": 48000.0, "hostapi": 0},
            {"name": "多输出设备", "max_input_channels": 2, "max_output_channels": 2,
             "default_samplerate": 48000.0, "hostapi": 0},
            {"name": "MacBook Pro Speakers", "max_input_channels": 0,
             "max_output_channels": 2, "default_samplerate": 48000.0, "hostapi": 0},
            {"name": "USB Mic 6ch", "max_input_channels": 6, "max_output_channels": 0,
             "default_samplerate": 44100.0, "hostapi": 0},
        ]
        self.default = _Default()
        self.streams: list[FakeStream] = []
        self.played: list[dict] = []
        self.stopped = 0
        self.open_error: Exception | None = None
        self.CallbackFlags = int

    def query_devices(self, device=None, kind=None):
        if device is None:
            return list(self.devices)
        return dict(self.devices[int(device)])

    def query_hostapis(self):
        return [{"name": "Core Audio"}]

    def InputStream(self, *args, **kwargs):  # noqa: N802
        if self.open_error is not None:
            raise self.open_error
        return FakeStream(self, *args, **kwargs)

    def WasapiSettings(self, **_kw):  # noqa: N802
        return None

    def play(self, data, samplerate=None, device=None, blocking=False):
        self.played.append({"data": np.array(data), "samplerate": samplerate, "device": device})

    def stop(self):
        self.stopped += 1


@pytest.fixture
def fake_sd(monkeypatch):
    """所有 sounddevice 调用落到假件；固定走 sounddevice 分支（Windows 下否则会枚举 soundcard）。"""
    fake = FakeSounddevice()
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    from autofish.first_click_trigger import audio_input

    monkeypatch.setattr(audio_input, "sd", fake)
    monkeypatch.setattr(sys, "platform", "darwin")
    return fake


class MouseLog:
    def __init__(self):
        self.calls: list = []
        self.down = False

    @property
    def presses(self) -> int:
        return sum(1 for c in self.calls if c is True)


@pytest.fixture
def fake_mouse(monkeypatch):
    """MouseActuator 换成只记录调用的假件，不碰系统鼠标。"""
    from autofish.act import MouseActuator

    log = MouseLog()

    def _init(self):
        pass

    def _set_holding(self, holding):
        log.calls.append(bool(holding))
        log.down = bool(holding)

    def _force_release(self):
        log.calls.append("release")
        log.down = False

    monkeypatch.setattr(MouseActuator, "__init__", _init)
    monkeypatch.setattr(MouseActuator, "set_holding", _set_holding)
    monkeypatch.setattr(MouseActuator, "force_release", _force_release)
    monkeypatch.setattr(MouseActuator, "pressed", property(lambda self: log.down))
    return log


@pytest.fixture
def lib_dirs(tmp_path, monkeypatch):
    """把模板库 / 会话 / 内置 / 包内种子目录全部重定向到 tmp_path。"""
    from autofish.first_click_trigger import paths

    data = tmp_path / "data"
    bundle = tmp_path / "bundle"
    assets = bundle / "assets"
    (assets / "audio").mkdir(parents=True)
    monkeypatch.setattr(paths, "data_root", lambda: data)
    monkeypatch.setattr(paths, "assets_dir", lambda: assets)
    monkeypatch.setattr(paths, "bundle_root", lambda: bundle)
    assert tmp_path in paths.user_template_dir().parents
    assert tmp_path in paths.user_audio_sessions_dir().parents
    return {"data": data, "bundle": bundle, "assets_audio": assets / "audio"}
