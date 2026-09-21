"""音频检测：能量突增 + 可选频段门限（无模板时的兜底）。"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import numpy.typing as npt


class AudioDetector:
    """
    滑动窗口检测音频事件（兜底模式）。

    参数：
        samplerate: 采样率
        threshold_db: RMS 能量门限（dBFS，默认 -30）
        min_duration_ms: 最短持续时间（毫秒），默认 80
        cooldown_ms: 命中后冷却（毫秒），默认 10000
        freq_range_hz: 频段过滤 (low, high)；None 表示全频段
    """

    def __init__(
        self,
        samplerate: int = 16000,
        threshold_db: float = -30.0,
        min_duration_ms: float = 80.0,
        cooldown_ms: float = 10000.0,
        freq_range_hz: tuple[float, float] | None = None,
    ) -> None:
        self.samplerate = samplerate
        self.threshold_db = threshold_db
        self.min_duration_ms = min_duration_ms
        self.cooldown_ms = cooldown_ms
        self.freq_range_hz = freq_range_hz
        self.threshold_linear = 10 ** (threshold_db / 20.0)
        self._min_frames = max(
            1, int(min_duration_ms / 1000.0 * samplerate / 1024)
        )
        self._cooldown_frames = max(
            1, int(cooldown_ms / 1000.0 * samplerate / 1024)
        )
        self._above_count = 0
        self._cooldown_count = 0
        self._window = deque(maxlen=self._min_frames)

    def reset(self) -> None:
        self._above_count = 0
        self._cooldown_count = 0
        self._window.clear()

    def feed(self, block: "npt.NDArray[np.float32]") -> bool:
        """
        传入一帧音频，返回是否检测到一次触发事件。
        已处于冷却期时自动忽略并倒计时。
        """
        if self._cooldown_count > 0:
            self._cooldown_count -= 1
            return False

        energy = self._band_energy(block)
        if energy >= self.threshold_linear:
            self._above_count += 1
            self._window.append(energy)
        else:
            self._above_count = 0
            self._window.clear()

        if self._above_count >= self._min_frames:
            self._cooldown_count = self._cooldown_frames
            self._above_count = 0
            self._window.clear()
            return True
        return False

    def _band_energy(self, block: "npt.NDArray[np.float32]") -> float:
        """计算（频段内）RMS。"""
        if self.freq_range_hz is None:
            return float(np.sqrt(np.mean(block**2)))

        n = len(block)
        if n < 2:
            return 0.0

        fft = np.fft.rfft(block, n=n)
        magnitude = np.abs(fft) / n
        freqs = np.fft.rfftfreq(n, 1.0 / self.samplerate)
        low, high = self.freq_range_hz
        mask = (freqs >= low) & (freqs <= high)
        band = magnitude[mask]
        if band.size == 0:
            return 0.0
        return float(np.sqrt(np.sum(band**2)))
