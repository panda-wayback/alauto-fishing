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


@dataclass(frozen=True)
class AudioDeviceInfo:
    """音频设备摘要。"""

    index: int
    name: str
    is_input: bool
    channels: int
    samplerate: float
    is_loopback: bool = False


class AudioInput:
    """
    打开录音设备并持续产出单声道音频块。

    - Windows：默认尝试 WASAPI Loopback。
    - macOS：从选定输入设备录音（BlackHole 等）；须用设备默认采样率/声道数。
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
    def list_devices() -> list[AudioDeviceInfo]:
        """列出可用设备，供 UI 选择。"""
        devices: list[AudioDeviceInfo] = []
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0:
                devices.append(
                    AudioDeviceInfo(
                        index=i,
                        name=d["name"],
                        is_input=True,
                        channels=d["max_input_channels"],
                        samplerate=d.get("default_samplerate", 48000.0),
                        is_loopback=False,
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
                            channels=d["max_output_channels"],
                            samplerate=d.get("default_samplerate", 48000.0),
                            is_loopback=True,
                        )
                    )
        return devices

    def _device_info(self, device: int | str | None) -> dict:
        try:
            return dict(sd.query_devices(device))
        except Exception:
            return {
                "default_samplerate": 48000.0,
                "max_input_channels": 1,
            }

    def _resolve_device(self, device: int | str | None) -> int | str | None:
        if device is None:
            if sys.platform == "win32":
                return sd.default.device[1]
            return sd.default.device[0]
        return device

    def start(self) -> None:
        if self._stream is not None:
            return
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
