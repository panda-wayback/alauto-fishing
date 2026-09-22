"""跨平台音频输入：Windows 用 soundcard 环回；macOS 用 sounddevice + 虚拟设备。"""

from __future__ import annotations

import queue
import sys
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    import numpy.typing as npt

try:
    import sounddevice as sd
except ImportError as exc:  # pragma: no cover
    raise ImportError("需要安装 sounddevice：pip install sounddevice") from exc

_sc: Any = None
if sys.platform == "win32":
    try:
        import soundcard as _sc  # type: ignore
    except ImportError:
        _sc = None


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
    """音频设备摘要。key：sc:<id> 或 sd:<index>。"""

    key: str
    name: str
    is_input: bool
    channels: int
    samplerate: float
    is_loopback: bool = False
    is_virtual_capture: bool = False

    @property
    def index(self) -> int | str:
        """兼容旧代码：sounddevice 为 int；soundcard 为 key 字符串。"""
        if self.key.startswith("sd:"):
            try:
                return int(self.key[3:])
            except ValueError:
                return self.key
        return self.key


class AudioInput:
    """
    打开录音设备并持续产出单声道音频块。

    - Windows：优先 soundcard（WASAPI 真环回，含 DELL 等扬声器 Loopback）。
    - macOS：sounddevice + BlackHole 等虚拟输入。
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
        self._key = self._normalize_key(device, loopback=loopback)
        self._loopback = bool(loopback) if loopback is not None else self._key_looks_loopback(
            self._key
        )
        info = self._probe(self._key)
        self.samplerate = int(samplerate or info["samplerate"])
        self.channels = int(channels or info["channels"])
        self.blocksize = int(blocksize)
        self._stream: Any = None
        self._sc_thread: threading.Thread | None = None
        self._sc_stop = threading.Event()
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
    def _key_looks_loopback(key: str | None) -> bool:
        if not key:
            return False
        return ":lb:" in key or key.endswith(":lb")

    @classmethod
    def _normalize_key(
        cls,
        device: int | str | None,
        *,
        loopback: bool | None,
    ) -> str:
        if device is None:
            pref = cls.preferred_capture_index()
            if pref is not None:
                # preferred_capture_index 现返回 key 字符串或旧 index
                if isinstance(pref, str) and (pref.startswith("sc:") or pref.startswith("sd:")):
                    return pref
                return f"sd:{int(pref)}"
            if sys.platform == "win32" and _sc is not None:
                mics = list(_sc.all_microphones(include_loopback=True))
                for m in mics:
                    if getattr(m, "isloopback", False):
                        return f"sc:lb:{m.id}"
                if mics:
                    m0 = mics[0]
                    tag = "lb" if getattr(m0, "isloopback", False) else "mic"
                    return f"sc:{tag}:{m0.id}"
            try:
                return f"sd:{int(sd.default.device[0])}"
            except Exception:
                return "sd:0"
        if isinstance(device, int):
            return f"sd:{device}"
        s = str(device)
        if s.startswith("sc:") or s.startswith("sd:"):
            return s
        # 旧 UI 可能只存了 sounddevice index 字符串
        if s.isdigit():
            return f"sd:{s}"
        # soundcard：按名称解析
        if sys.platform == "win32" and _sc is not None:
            want_lb = bool(loopback) if loopback is not None else ("loopback" in s.lower())
            try:
                mic = _sc.get_microphone(s, include_loopback=True)
                tag = "lb" if getattr(mic, "isloopback", False) or want_lb else "mic"
                return f"sc:{tag}:{mic.id}"
            except Exception:
                pass
        return s

    @staticmethod
    def list_devices() -> list[AudioDeviceInfo]:
        """Windows：soundcard（含 Loopback）；其它：sounddevice 输入。"""
        if sys.platform == "win32" and _sc is not None:
            return AudioInput._list_soundcard()
        return AudioInput._list_sounddevice()

    @staticmethod
    def _list_soundcard() -> list[AudioDeviceInfo]:
        assert _sc is not None
        devices: list[AudioDeviceInfo] = []
        try:
            mics = list(_sc.all_microphones(include_loopback=True))
        except Exception:
            return AudioInput._list_sounddevice()
        for m in mics:
            name = str(getattr(m, "name", "") or "")
            if AudioInput._name_is_skip_capture(name):
                continue
            is_lb = bool(getattr(m, "isloopback", False))
            label = name
            if is_lb and "loopback" not in name.lower():
                label = f"{name} (Loopback)"
            channels = 2
            try:
                channels = int(getattr(m, "channels", 2) or 2)
            except Exception:
                channels = 2
            tag = "lb" if is_lb else "mic"
            devices.append(
                AudioDeviceInfo(
                    key=f"sc:{tag}:{m.id}",
                    name=label,
                    is_input=True,
                    channels=max(1, channels),
                    samplerate=48000.0,
                    is_loopback=is_lb,
                    is_virtual_capture=is_lb or AudioInput._name_is_virtual_capture(name),
                )
            )
        devices.sort(
            key=lambda x: (0 if (x.is_virtual_capture or x.is_loopback) else 1, x.name.lower())
        )
        return devices

    @staticmethod
    def _list_sounddevice() -> list[AudioDeviceInfo]:
        devices: list[AudioDeviceInfo] = []
        wasapi = None
        if sys.platform == "win32":
            try:
                for i, h in enumerate(sd.query_hostapis()):
                    if "WASAPI" in str(h.get("name") or "").upper():
                        wasapi = int(i)
                        break
            except Exception:
                wasapi = None
        for i, d in enumerate(sd.query_devices()):
            name = str(d.get("name") or "")
            max_in = int(d.get("max_input_channels") or 0)
            if max_in <= 0:
                continue
            if AudioInput._name_is_skip_capture(name):
                continue
            if wasapi is not None and int(d.get("hostapi") or -1) != wasapi:
                continue
            is_lb = "loopback" in name.lower()
            devices.append(
                AudioDeviceInfo(
                    key=f"sd:{i}",
                    name=name,
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
    def preferred_capture_index() -> int | str | None:
        """优先环回/虚拟采集；返回 device key 或 None。"""
        for d in AudioInput.list_devices():
            if d.is_virtual_capture or d.is_loopback:
                return d.key
        return None

    def _probe(self, key: str) -> dict[str, int]:
        if key.startswith("sc:") and _sc is not None:
            mic_id = key.split(":", 2)[-1]
            try:
                mic = _sc.get_microphone(mic_id, include_loopback=True)
                ch = int(getattr(mic, "channels", 2) or 2)
                return {"samplerate": 48000, "channels": min(2, max(1, ch))}
            except Exception:
                return {"samplerate": 48000, "channels": 2}
        idx = 0
        if key.startswith("sd:"):
            try:
                idx = int(key[3:])
            except ValueError:
                idx = 0
        try:
            info = dict(sd.query_devices(idx))
            return {
                "samplerate": int(info.get("default_samplerate") or 48000),
                "channels": min(2, max(1, int(info.get("max_input_channels") or 1))),
            }
        except Exception:
            return {"samplerate": 48000, "channels": 1}

    def start(self) -> None:
        if self._stream is not None or self._sc_thread is not None:
            return
        if self._key.startswith("sc:"):
            self._start_soundcard()
        else:
            self._start_sounddevice()

    def _start_soundcard(self) -> None:
        if _sc is None:
            raise RuntimeError(
                "Windows 环回需要 soundcard：pip install soundcard"
            )
        mic_id = self._key.split(":", 2)[-1]
        try:
            mic = _sc.get_microphone(mic_id, include_loopback=True)
        except Exception as exc:
            raise RuntimeError(
                f"无法打开采集设备（{mic_id}）：{exc}。"
                "请选带 (Loopback) 的扬声器项（如 DELL …）。"
            ) from exc
        self._sc_stop.clear()
        self._sc_thread = threading.Thread(
            target=self._soundcard_loop,
            args=(mic,),
            name="SoundcardCapture",
            daemon=True,
        )
        self._sc_thread.start()

    def _soundcard_loop(self, mic: Any) -> None:
        ch = min(2, max(1, int(self.channels)))
        try:
            with mic.recorder(samplerate=self.samplerate, channels=ch) as rec:
                while not self._sc_stop.is_set():
                    try:
                        block = rec.record(numframes=self.blocksize)
                    except Exception:
                        if self._sc_stop.is_set():
                            break
                        continue
                    arr = np.asarray(block, dtype=np.float32)
                    if arr.ndim > 1 and arr.shape[1] > 1:
                        mono = arr.mean(axis=1).astype(np.float32)
                    else:
                        mono = arr.reshape(-1).astype(np.float32)
                    try:
                        self._queue.put_nowait(mono)
                    except queue.Full:
                        try:
                            self._queue.get_nowait()
                            self._queue.put_nowait(mono)
                        except queue.Empty:
                            pass
        except Exception:
            pass

    def _start_sounddevice(self) -> None:
        idx = 0
        if self._key.startswith("sd:"):
            try:
                idx = int(self._key[3:])
            except ValueError:
                idx = 0
        info = dict(sd.query_devices(idx))
        name = str(info.get("name") or "")
        if self._name_is_skip_capture(name):
            raise RuntimeError(
                f"不能从「{name}」录音（多输出/聚合只有播放）。"
                "系统输出选多输出；本程序设备选 BlackHole 2ch。"
            )
        max_in = int(info.get("max_input_channels") or 0)
        if max_in <= 0:
            raise RuntimeError(f"设备「{name}」无输入声道，无法录音")
        self.channels = min(2, max(1, max_in))
        kwargs: dict = {
            "samplerate": self.samplerate,
            "blocksize": self.blocksize,
            "channels": self.channels,
            "dtype": np.float32,
            "callback": self._callback,
        }
        if sys.platform == "win32":
            try:
                kwargs["extra_settings"] = sd.WasapiSettings(auto_convert=True)
            except TypeError:
                pass
        self._stream = sd.InputStream(device=idx, **kwargs)
        self._stream.start()

    def stop(self) -> None:
        self._sc_stop.set()
        thread = self._sc_thread
        self._sc_thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        stream = self._stream
        self._stream = None
        if stream is not None:
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
