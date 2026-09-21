"""跨平台音频输入：Windows WASAPI Loopback / macOS CoreAudio（虚拟设备）。"""

from __future__ import annotations

import queue
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import numpy.typing as npt

try:
    import sounddevice as sd
except ImportError as exc:  # pragma: no cover
    raise ImportError("需要安装 sounddevice：pip install sounddevice") from exc


# macOS：系统「多输出」只负责播放；程序必须从 BlackHole 等虚拟「输入」录音
_VIRTUAL_CAPTURE_NAMES = (
    "blackhole",
    "soundflower",
    "loopback",
    "vb-audio",
    "cable",
)
_SKIP_CAPTURE_NAMES = (
    "多输出",
    "multi-output",
    "aggregate device",
    "聚合",
)


@dataclass(frozen=True)
class AudioDeviceInfo:
    """音频设备摘要。"""

    index: int
    name: str
    is_input: bool
    channels: int
    samplerate: float
    is_loopback: bool = False
    is_virtual_capture: bool = False


class AudioInput:
    """
    打开录音设备并持续产出单声道音频块。

    - Windows：默认尝试 WASAPI Loopback。
    - macOS：从选定输入设备录音（BlackHole 等）；须用设备默认采样率/声道数。
      系统输出用「多输出设备」时，本类仍只开 BlackHole 输入，禁止开多输出本身。
    """

    def __init__(
        self,
        device: int | str | None = None,
        samplerate: int | None = None,
        blocksize: int = 1024,
        channels: int | None = None,
    ) -> None:
        self._device = self._resolve_device(device)
        info = self._device_info(self._device)
        # BlackHole 等虚拟设备：用设备默认参数，避免 16k 单声道开流得到静音
        self.samplerate = int(samplerate or info.get("default_samplerate") or 48000)
        max_in = int(info.get("max_input_channels") or 1)
        self.channels = int(channels or min(2, max(1, max_in)))
        self.blocksize = blocksize
        self._stream: sd.InputStream | None = None
        self._queue: "queue.Queue[npt.NDArray[np.float32]]" = queue.Queue(maxsize=8)

    @staticmethod
    def _name_is_virtual_capture(name: str) -> bool:
        lower = name.lower()
        return any(k in lower for k in _VIRTUAL_CAPTURE_NAMES)

    @staticmethod
    def _name_is_skip_capture(name: str) -> bool:
        lower = name.lower()
        return any(k in lower for k in _SKIP_CAPTURE_NAMES)

    @staticmethod
    def list_devices() -> list[AudioDeviceInfo]:
        """列出可用输入设备；跳过多输出/聚合（无输入，录了也是静音）。"""
        devices: list[AudioDeviceInfo] = []
        for i, d in enumerate(sd.query_devices()):
            name = str(d.get("name") or "")
            max_in = int(d.get("max_input_channels") or 0)
            if max_in <= 0:
                continue
            if AudioInput._name_is_skip_capture(name):
                continue
            devices.append(
                AudioDeviceInfo(
                    index=i,
                    name=name,
                    is_input=True,
                    channels=max_in,
                    samplerate=float(d.get("default_samplerate") or 48000.0),
                    is_loopback=False,
                    is_virtual_capture=AudioInput._name_is_virtual_capture(name),
                )
            )
        if sys.platform == "win32":
            for i, d in enumerate(sd.query_devices()):
                if d.get("max_output_channels", 0) > 0:
                    devices.append(
                        AudioDeviceInfo(
                            index=i,
                            name=f"{d['name']} (Loopback)",
                            is_input=False,
                            channels=int(d["max_output_channels"]),
                            samplerate=float(d.get("default_samplerate") or 48000.0),
                            is_loopback=True,
                            is_virtual_capture=False,
                        )
                    )
        # 虚拟采集（BlackHole）排前面，方便默认选中
        devices.sort(
            key=lambda x: (0 if (x.is_virtual_capture or x.is_loopback) else 1, x.index)
        )
        return devices

    @staticmethod
    def preferred_capture_index() -> int | None:
        """优先 BlackHole 等虚拟输入；找不到则 None。"""
        for d in AudioInput.list_devices():
            if d.is_virtual_capture or d.is_loopback:
                return d.index
        return None

    def _device_info(self, device: int | str | None) -> dict:
        try:
            return dict(sd.query_devices(device))
        except Exception:
            return {
                "default_samplerate": 48000.0,
                "max_input_channels": 1,
            }

    def _resolve_device(self, device: int | str | None) -> int | str | None:
        if device is not None:
            return device
        if sys.platform == "win32":
            return sd.default.device[1]
        pref = self.preferred_capture_index()
        if pref is not None:
            return pref
        return sd.default.device[0]

    def start(self) -> None:
        if self._stream is not None:
            return
        info = self._device_info(self._device)
        name = str(info.get("name") or "")
        if self._name_is_skip_capture(name):
            raise RuntimeError(
                f"不能从「{name}」录音（多输出/聚合只有播放）。"
                "系统输出选多输出；本程序设备选 BlackHole 2ch。"
            )
        max_in = int(info.get("max_input_channels") or 0)
        if max_in <= 0:
            raise RuntimeError(f"设备「{name}」无输入声道，无法录音")
        kwargs: dict = {
            "samplerate": self.samplerate,
            "blocksize": self.blocksize,
            "channels": self.channels,
            "dtype": np.float32,
            "callback": self._callback,
        }
        if sys.platform == "win32":
            kwargs["extra_settings"] = sd.WasapiSettings(loopback=True)
        self._stream = sd.InputStream(device=self._device, **kwargs)
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def read(self) -> "npt.NDArray[np.float32]" | None:
        """读取一块单声道音频；非阻塞，无数据返回 None。"""
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def _callback(
        self,
        indata: "npt.NDArray[np.float32]",
        frames: int,
        time_info: dict,
        status: sd.CallbackFlags,
    ) -> None:
        if status:
            pass
        # 统一成单声道，供后续检测
        if indata.ndim > 1 and indata.shape[1] > 1:
            mono = indata.mean(axis=1).astype(np.float32)
        else:
            mono = indata.reshape(-1).astype(np.float32)
        try:
            self._queue.put_nowait(mono)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(mono)
            except queue.Empty:
                pass

    def __enter__(self) -> "AudioInput":
        self.start()
        return self

    def __exit__(self, *args) -> None:
        self.stop()
