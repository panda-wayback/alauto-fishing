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

    - Windows：对输出设备用 WASAPI Loopback（录该设备正在播放的混音）。
    - macOS：从选定输入设备录音（BlackHole 等）；须用设备默认采样率/声道数。
    """

    def __init__(
        self,
        device: int | str | None = None,
        samplerate: int | None = None,
        blocksize: int = 1024,
        channels: int | None = None,
        *,
        loopback: bool | None = None,
    ) -> None:
        self._device = self._resolve_device(device)
        info = self._device_info(self._device)
        max_in = int(info.get("max_input_channels") or 0)
        max_out = int(info.get("max_output_channels") or 0)
        if loopback is None:
            # 输出-only 设备在 Windows 上当作环回
            self._loopback = bool(
                sys.platform == "win32" and max_out > 0 and max_in <= 0
            )
        else:
            self._loopback = bool(loopback)
        self.samplerate = int(samplerate or info.get("default_samplerate") or 48000)
        if self._loopback:
            ch_src = max_out
        else:
            ch_src = max_in
        self.channels = int(channels or min(2, max(1, ch_src)))
        self.blocksize = blocksize
        self._stream: sd.InputStream | None = None
        self._queue: "queue.Queue[npt.NDArray[np.float32]]" = queue.Queue(maxsize=8)

    @property
    def loopback(self) -> bool:
        return self._loopback

    @staticmethod
    def _name_is_virtual_capture(name: str) -> bool:
        lower = name.lower()
        return any(k in lower for k in _VIRTUAL_CAPTURE_NAMES)

    @staticmethod
    def _name_is_skip_capture(name: str) -> bool:
        lower = name.lower()
        return any(k in lower for k in _SKIP_CAPTURE_NAMES)

    @staticmethod
    def _wasapi_hostapi() -> int | None:
        try:
            for i, h in enumerate(sd.query_hostapis()):
                if "WASAPI" in str(h.get("name") or "").upper():
                    return int(i)
        except Exception:
            return None
        return None

    @staticmethod
    def list_devices() -> list[AudioDeviceInfo]:
        """列出可用采集项；Windows 仅 WASAPI 下列输出环回。"""
        devices: list[AudioDeviceInfo] = []
        wasapi = AudioInput._wasapi_hostapi() if sys.platform == "win32" else None
        for i, d in enumerate(sd.query_devices()):
            name = str(d.get("name") or "")
            max_in = int(d.get("max_input_channels") or 0)
            if max_in <= 0:
                continue
            if AudioInput._name_is_skip_capture(name):
                continue
            # Windows：优先只列 WASAPI 输入，避免 MME 重复项
            if wasapi is not None and int(d.get("hostapi") or -1) != wasapi:
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
                if wasapi is not None and int(d.get("hostapi") or -1) != wasapi:
                    continue
                max_out = int(d.get("max_output_channels") or 0)
                if max_out <= 0:
                    continue
                name = str(d.get("name") or "")
                devices.append(
                    AudioDeviceInfo(
                        index=i,
                        name=f"{name} (Loopback)",
                        is_input=False,
                        channels=max_out,
                        samplerate=float(d.get("default_samplerate") or 48000.0),
                        is_loopback=True,
                        is_virtual_capture=False,
                    )
                )
        devices.sort(
            key=lambda x: (0 if (x.is_virtual_capture or x.is_loopback) else 1, x.index)
        )
        return devices

    @staticmethod
    def preferred_capture_index() -> int | None:
        """优先环回/虚拟采集；找不到则 None。"""
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
                "max_output_channels": 0,
            }

    def _resolve_device(self, device: int | str | None) -> int | str | None:
        if device is not None:
            return device
        if sys.platform == "win32":
            # 默认输出 → 环回录系统声
            try:
                return sd.default.device[1]
            except Exception:
                return sd.default.device[0]
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
        max_out = int(info.get("max_output_channels") or 0)
        if self._loopback:
            if max_out <= 0:
                raise RuntimeError(
                    f"设备「{name}」无法 Loopback（无输出声道）。"
                    "请选带 (Loopback) 的播放设备。"
                )
            ch = min(2, max(1, max_out))
        else:
            if max_in <= 0:
                raise RuntimeError(f"设备「{name}」无输入声道，无法录音")
            ch = min(2, max(1, max_in))
        self.channels = ch
        kwargs: dict = {
            "samplerate": self.samplerate,
            "blocksize": self.blocksize,
            "channels": self.channels,
            "dtype": np.float32,
            "callback": self._callback,
        }
        if self._loopback:
            kwargs["extra_settings"] = sd.WasapiSettings(loopback=True)
        self._stream = sd.InputStream(device=self._device, **kwargs)
        self._stream.start()

    def stop(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is not None:
            # abort 比 stop 更快结束回调；Windows WASAPI 上尤重要
            try:
                stream.abort()
            except Exception:
                try:
                    stream.stop()
                except Exception:
                    pass
            try:
                stream.close()
            except Exception:
                pass
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
