"""STFT 频谱图模板匹配：滑动时间对齐 + 能量起跳门控。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import numpy.typing as npt


DEFAULT_SAMPLERATE = 16000
N_FFT = 512
HOP_LENGTH = 256
TEMPLATE_DURATION_S = 1.5
MIN_ENERGY_DB = -50.0
# 搜索缓冲比模板多出的时长（秒），用于滑动对齐
SEARCH_PAD_S = 0.30
# 起跳：最近一段相对基线的最小倍率
ONSET_RATIO = 2.2
ONSET_RECENT_MS = 60.0
ONSET_BASELINE_MS = 250.0


class TemplateMatcher:
    """
    基于 STFT 频谱图的模板匹配器。

    - 维护「模板长 + 搜索余量」的滑动缓冲。
    - 在缓冲上滑动对齐，取最大相似度（解决稍早/稍晚对不齐）。
    - 仅当近期能量相对基线明显抬升（onset）时才允许触发。
    """

    def __init__(
        self,
        samplerate: int = DEFAULT_SAMPLERATE,
        template_duration_s: float = TEMPLATE_DURATION_S,
        threshold: float = 0.72,
        min_energy_db: float = MIN_ENERGY_DB,
        search_pad_s: float = SEARCH_PAD_S,
        onset_ratio: float = ONSET_RATIO,
    ) -> None:
        self.samplerate = samplerate
        self.template_duration_s = template_duration_s
        self.threshold = threshold
        self.min_energy_db = min_energy_db
        self.search_pad_s = search_pad_s
        self.onset_ratio = onset_ratio
        self._template_wave: "npt.NDArray[np.float32]" | None = None
        self._template_spec: "npt.NDArray[np.float32]" | None = None
        self._template_frames: int = 0
        self._template_len = 0
        self._buffer: "npt.NDArray[np.float32]" = np.zeros(1, dtype=np.float32)
        # 高频略加权，水花更脆
        self._freq_weights = self._make_freq_weights()

    @property
    def has_template(self) -> bool:
        return self._template_wave is not None

    def load_template(self, path: str | Path) -> None:
        data = np.load(path)
        if data.dtype != np.float32:
            data = data.astype(np.float32)
        if data.ndim > 1:
            data = data.mean(axis=1)
        self.set_template(data)

    def save_template(self, path: str | Path) -> None:
        if self._template_wave is None:
            raise RuntimeError("没有模板可保存")
        np.save(path, self._template_wave)

    def set_template(self, wave: "npt.NDArray[np.float32]") -> None:
        wave = np.asarray(wave, dtype=np.float32)
        if wave.ndim > 1:
            wave = wave.mean(axis=1)
        if wave.size == 0:
            raise ValueError("模板波形为空")
        max_len = int(max(self.template_duration_s, 2.0) * self.samplerate)
        if len(wave) > max_len:
            wave = wave[:max_len]
        self._template_wave = wave
        self._template_len = len(wave)
        self._template_spec = self._compute_spec(wave)
        self._template_frames = self._template_spec.shape[1]
        self.template_duration_s = len(wave) / float(self.samplerate)
        buf_len = self._template_len + int(self.search_pad_s * self.samplerate)
        self._buffer = np.zeros(buf_len, dtype=np.float32)

    def reset_buffer(self) -> None:
        self._buffer.fill(0.0)

    def feed(self, block: "npt.NDArray[np.float32]") -> tuple[bool, float]:
        """
        传入一帧音频，返回 (是否触发, 最佳相似度)。
        无模板时返回 (False, 0.0)。
        """
        if self._template_spec is None or self._template_len <= 0:
            return False, 0.0

        mono = block.mean(axis=1) if block.ndim > 1 else block
        mono = np.asarray(mono, dtype=np.float32)

        n = len(mono)
        if n >= len(self._buffer):
            self._buffer[:] = mono[-len(self._buffer) :]
        else:
            self._buffer = np.roll(self._buffer, -n)
            self._buffer[-n:] = mono

        # 整窗太静则跳过
        rms = float(np.sqrt(np.mean(self._buffer**2)))
        if rms <= 0 or 20 * np.log10(rms) < self.min_energy_db:
            return False, 0.0

        score, match_start = self._best_similarity(self._buffer)
        onset_ok = self._onset_at(self._buffer, match_start)
        triggered = bool(onset_ok and score >= self.threshold)
        return triggered, score

    def _onset_at(self, buf: "npt.NDArray[np.float32]", match_start: int) -> bool:
        """匹配段起点相对其前方基线是否突然变响。"""
        recent_n = max(1, int(self.samplerate * ONSET_RECENT_MS / 1000.0))
        base_n = max(recent_n, int(self.samplerate * ONSET_BASELINE_MS / 1000.0))
        if match_start <= 0:
            # 贴齐缓冲开头：用段头 vs 段中后部弱一点的条件
            head = buf[:recent_n]
            rest = buf[recent_n : recent_n + base_n]
            if rest.size == 0:
                return True
            r = float(np.sqrt(np.mean(head**2)))
            b = float(np.sqrt(np.mean(rest**2)))
            if b <= 1e-8:
                return r > 1e-4
            # 段头应不弱于后部（水花起跳在前）
            return r >= b * 0.85

        pre_start = max(0, match_start - base_n)
        baseline = buf[pre_start:match_start]
        head_end = min(buf.size, match_start + recent_n)
        head = buf[match_start:head_end]
        if baseline.size == 0 or head.size == 0:
            return True
        r = float(np.sqrt(np.mean(head**2)))
        b = float(np.sqrt(np.mean(baseline**2)))
        if b <= 1e-8:
            return r > 1e-4
        return (r / b) >= self.onset_ratio

    def _best_similarity(
        self, buf: "npt.NDArray[np.float32]"
    ) -> tuple[float, int]:
        """在缓冲上滑动模板窗，返回 (最大相似度, 起始下标)。"""
        tpl = self._template_len
        if buf.size < tpl:
            return 0.0, 0
        step = max(HOP_LENGTH // 2, int(self.samplerate * 0.01))
        best = 0.0
        best_start = 0
        last_start = buf.size - tpl
        for start in range(0, last_start + 1, step):
            seg = buf[start : start + tpl]
            spec = self._compute_spec(seg)
            score = self._similarity(spec, self._template_spec)
            if score > best:
                best = score
                best_start = start
        return float(best), best_start

    def _make_freq_weights(self) -> "npt.NDArray[np.float32]":
        """对中高频加权（水花更脆）。"""
        freqs = np.fft.rfftfreq(N_FFT, 1.0 / max(self.samplerate, 1))
        w = np.ones_like(freqs, dtype=np.float32)
        # 约 500Hz 以下降权，1.5k～8k 升权
        for i, f in enumerate(freqs):
            if f < 400:
                w[i] = 0.55
            elif f < 1500:
                w[i] = 0.85
            elif f < 8000:
                w[i] = 1.25
            else:
                w[i] = 1.0
        return w

    def _compute_spec(self, wave: "npt.NDArray[np.float32]") -> "npt.NDArray[np.float32]":
        """对数幅值 STFT，乘频段权重后按帧 L2 归一化。"""
        window = np.hanning(N_FFT).astype(np.float32)
        if len(wave) < N_FFT:
            wave = np.pad(wave, (0, N_FFT - len(wave)), mode="constant")
        hop = HOP_LENGTH
        n_frames = 1 + (len(wave) - N_FFT) // hop
        n_bins = N_FFT // 2 + 1
        weights = self._freq_weights
        if weights.shape[0] != n_bins:
            weights = self._make_freq_weights()
            self._freq_weights = weights
        spec = np.zeros((n_bins, n_frames), dtype=np.float32)
        for i in range(n_frames):
            frame = wave[i * hop : i * hop + N_FFT]
            if len(frame) < N_FFT:
                frame = np.pad(frame, (0, N_FFT - len(frame)), mode="constant")
            fft = np.fft.rfft(frame * window)
            mag = np.abs(fft) + 1e-10
            spec[:, i] = np.log1p(mag) * weights
        norm = np.linalg.norm(spec, axis=0, keepdims=True)
        norm[norm == 0] = 1.0
        return spec / norm

    @staticmethod
    def _similarity(
        spec_a: "npt.NDArray[np.float32]",
        spec_b: "npt.NDArray[np.float32]",
    ) -> float:
        min_frames = min(spec_a.shape[1], spec_b.shape[1])
        if min_frames <= 0:
            return 0.0
        a = spec_a[:, :min_frames]
        b = spec_b[:, :min_frames]
        dots = np.sum(a * b, axis=0)
        return float(np.mean(dots))
