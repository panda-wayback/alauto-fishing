"""跨平台音频输入：Windows WASAPI Loopback / macOS CoreAudio（虚拟设备）。"""

from __future__ import annotations

import inspect
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
    "vb-audio",
    "cable",
    "stereomix",
    "stereo mix",
    "what u hear",
    "wave out mix",
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

    - Windows：只用 PortAudio 已枚举的 **Loopback 输入**（max_input>0）；
      官方 sounddevice 的 WasapiSettings **无 loopback 参数**，
      禁止再对「纯输出设备」伪造环回。
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
        name = str(info.get("name") or "")
        idx = self._device if isinstance(self._device, int) else None
        detected_lb = self._detect_loopback(idx, name, max_in)
        if loopback is None:
            self._loopback = detected_lb
        else:
            self._loopback = bool(loopback)
        self.samplerate = int(samplerate or info.get("default_samplerate") or 48000)
        self.channels = int(channels or min(2, max(1, max_in or 1)))
        self.blocksize = blocksize
        self._stream: sd.InputStream | None = None
        self._queue: "queue.Queue[npt.NDArray[np.float32]]" = queue.Queue(maxsize=8)

    @property
    def loopback(self) -> bool:
        return self._loopback

    @staticmethod
    def _name_is_virtual_capture(name: str) -> bool:
        lower = name.lower()
        if "loopback" in lower:
            return True
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
    def _pa_is_loopback(index: int | None) -> bool:
        """PortAudio PaWasapi_IsLoopback（仅 Windows 库有符号）。"""
        if index is None or sys.platform != "win32":
            return False
        try:
            return bool(sd._lib.PaWasapi_IsLoopback(int(index)))
        except Exception:
            return False

    @classmethod
    def _detect_loopback(cls, index: int | None, name: str, max_in: int) -> bool:
        if max_in <= 0:
            return False
        if "loopback" in name.lower():
            return True
        return cls._pa_is_loopback(index)

    @staticmethod
    def _wasapi_extra_settings(*, want_loopback: bool):
        """
        构造 WasapiSettings。

        sounddevice≥0.4 官方签名无 loopback；若未来版本支持则自动带上。
        auto_convert 便于环回采样率与系统混音不一致时仍能打开。
        """
        try:
            params = inspect.signature(sd.WasapiSettings.__init__).parameters
        except (TypeError, ValueError):
            params = {}
        kwargs: dict = {}
        if "auto_convert" in params:
            kwargs["auto_convert"] = True
        if want_loopback and "loopback" in params:
            kwargs["loopback"] = True
        if not kwargs:
            return None
        return sd.WasapiSettings(**kwargs)

    @staticmethod
    def list_devices() -> list[AudioDeviceInfo]:
        """列出可采集输入；Windows 标出真实 Loopback 输入（非伪造输出项）。"""
        devices: list[AudioDeviceInfo] = []
        wasapi = AudioInput._wasapi_hostapi() if sys.platform == "win32" else None
        for i, d in enumerate(sd.query_devices()):
            name = str(d.get("name") or "")
            max_in = int(d.get("max_input_channels") or 0)
            if max_in <= 0:
                continue
            if AudioInput._name_is_skip_capture(name):
                continue
            if wasapi is not None and int(d.get("hostapi") or -1) != wasapi:
                continue
            is_lb = AudioInput._detect_loopback(i, name, max_in)
            # 展示名：PortAudio 已含 [Loopback] 则不重复；否则补后缀便于选择
            label = name
            if is_lb and "loopback" not in name.lower():
                label = f"{name} (Loopback)"
            devices.append(
                AudioDeviceInfo(
                    index=i,
                    name=label,
                    is_input=True,
                    channels=max_in,
                    samplerate=float(d.get("default_samplerate") or 48000.0),
                    is_loopback=is_lb,
                    is_virtual_capture=AudioInput._name_is_virtual_capture(name),
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
        pref = self.preferred_capture_index()
        if pref is not None:
            return pref
        try:
            return sd.default.device[0]
        except Exception:
            return None

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
            raise RuntimeError(
                f"设备「{name}」无输入声道，无法录音。"
                "Windows 请选名称含 Loopback / 立体声混音 的**输入**项；"
                "不要选纯播放设备（当前 sounddevice 无法对输出伪造环回）。"
            )
        # 若调用方仍把「旧版伪造输出环回」传进来，给出明确错误
        if self._loopback and max_in <= 0:
            raise RuntimeError(
                f"设备「{name}」不是可采集的 Loopback 输入。"
                "请重新打开设备列表，选带 Loopback 且能采集的那一项。"
            )
        self.channels = min(2, max(1, max_in))
        kwargs: dict = {
            "samplerate": self.samplerate,
            "blocksize": self.blocksize,
            "channels": self.channels,
            "dtype": np.float32,
            "callback": self._callback,
        }
        if sys.platform == "win32":
            extra = self._wasapi_extra_settings(want_loopback=self._loopback)
            if extra is not None:
                kwargs["extra_settings"] = extra
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
