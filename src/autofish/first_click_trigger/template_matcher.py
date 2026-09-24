"""Mel 频谱图模板匹配：滑动 NCC + 分数抬升门控（CPU，无模型）。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np

if TYPE_CHECKING:
    import numpy.typing as npt


DEFAULT_SAMPLERATE = 48000
TEMPLATE_DURATION_S = 2.0
# 游戏环回常见峰值短时 RMS 约 -45dB；门限留足余量，过严会整段「太静」跳过匹配
MIN_ENERGY_DB = -80.0
# 长缓冲 pad；短/长双后缀窗取较高分（不做多起点滑扫，以免抬高环境基线）
SEARCH_PAD_S = 2.0
SHORT_SEARCH_PAD_S = 0.80
N_MELS = 64
FMIN_HZ = 80.0
FMAX_HZ = 12000.0
# Mel-NCC；干净短模板自匹配可接近 1.0；另需抬升
DEFAULT_THRESHOLD = 0.70
MIN_SCORE_RISE = 0.08
SCORE_EMA_ALPHA = 0.12
# 入 Mel 前：用短时帧峰值高分位当「有效峰值」，避免单样本/尖刺杂音抢走归一化
NORM_PEAK_PERCENTILE = 95.0
NORM_TARGET_PEAK = 0.9


class TemplateMatcher:
    """
    在 Mel 频谱图上做 matchTemplate 找短模板；
    过阈值且相对近期基线突然抬升才命中。
    实时：长缓冲 + 短/长双后缀窗取较高分。
    """

    def __init__(
        self,
        samplerate: int = DEFAULT_SAMPLERATE,
        template_duration_s: float = TEMPLATE_DURATION_S,
        threshold: float = DEFAULT_THRESHOLD,
        min_energy_db: float = MIN_ENERGY_DB,
        search_pad_s: float = SEARCH_PAD_S,
        min_score_rise: float = MIN_SCORE_RISE,
    ) -> None:
        self.samplerate = int(samplerate)
        self.template_duration_s = template_duration_s
        self.threshold = threshold
        self.min_energy_db = min_energy_db
        self.search_pad_s = search_pad_s
        self.min_score_rise = min_score_rise
        self._n_fft, self._hop = self._fft_params(self.samplerate)
        self._mel_fb = self._make_mel_filterbank()
        self._template_wave: "npt.NDArray[np.float32]" | None = None
        self._template_img: "npt.NDArray[np.float32]" | None = None
        self._template_len = 0
        self._buffer: "npt.NDArray[np.float32]" = np.zeros(1, dtype=np.float32)
        self._score_ema: float = 0.0
        self.last_reject: str = ""
        self.last_prominence: float = 0.0
        self.last_ambient: float = 0.0
        self.last_rise: float = 0.0
        self.last_window: str = ""

    @staticmethod
    def _fft_params(samplerate: int) -> tuple[int, int]:
        if samplerate >= 40000:
            return 1024, 256
        return 512, 128

    @property
    def has_template(self) -> bool:
        return self._template_wave is not None

    @property
    def template_wave(self) -> "npt.NDArray[np.float32] | None":
        """当前模板波形副本；无模板返回 None。"""
        if self._template_wave is None:
            return None
        return self._template_wave.copy()

    @property
    def score_baseline(self) -> float:
        return float(self._score_ema)

    def bump_score_baseline(self, score: float) -> None:
        """命中后抬高 EMA 基线（回测合并近邻时用）。"""
        self._score_ema = max(self._score_ema, float(score))

    def load_template(self, path: str | Path) -> None:
        data = np.load(path)
        if data.dtype != np.float32:
            data = data.astype(np.float32)
        if data.ndim > 1:
            data = data.mean(axis=1)
        # 用户波形选区已裁好，加载时不再能量裁切
        self.set_template(data, trim_energy=False)

    def save_template(self, path: str | Path) -> None:
        if self._template_wave is None:
            raise RuntimeError("没有模板可保存")
        np.save(path, self._template_wave)

    def set_template(
        self, wave: "npt.NDArray[np.float32]", *, trim_energy: bool = True
    ) -> None:
        wave = np.asarray(wave, dtype=np.float32)
        if wave.ndim > 1:
            wave = wave.mean(axis=1)
        if wave.size == 0:
            raise ValueError("模板波形为空")
        max_len = int(max(self.template_duration_s, 2.0) * self.samplerate)
        if len(wave) > max_len:
            wave = wave[:max_len]
        if trim_energy:
            wave = self._trim_energy(wave)
        self._template_wave = wave
        self._template_len = len(wave)
        self._template_img = self._wave_to_mel(wave)
        self.template_duration_s = len(wave) / float(self.samplerate)
        buf_len = self._template_len + int(self.search_pad_s * self.samplerate)
        self._buffer = np.zeros(max(buf_len, self._template_len + 1), dtype=np.float32)
        self._score_ema = 0.0
        self.last_reject = ""
        self.last_prominence = 0.0
        self.last_rise = 0.0
        self.last_window = ""

    def reset_buffer(self) -> None:
        self._buffer.fill(0.0)
        self._score_ema = 0.0
        self.last_reject = ""
        self.last_prominence = 0.0
        self.last_rise = 0.0
        self.last_window = ""

    def reset_score_baseline(self) -> None:
        """入听声态时清抬升基线（保留音频缓冲），与回测从零基线一致。"""
        self._score_ema = 0.0
        self.last_reject = ""
        self.last_rise = 0.0

    def clone_for_offline(self) -> "TemplateMatcher":
        """拷贝模板与参数，供回测独占（避免与实时 feed 抢缓冲）。"""
        other = TemplateMatcher(
            samplerate=self.samplerate,
            template_duration_s=self.template_duration_s,
            threshold=self.threshold,
            min_energy_db=self.min_energy_db,
            search_pad_s=self.search_pad_s,
            min_score_rise=self.min_score_rise,
        )
        if self._template_wave is None:
            raise RuntimeError("没有模板可回测")
        other.set_template(self._template_wave.copy(), trim_energy=False)
        return other

    def _buffer_loud_enough(self, buf: "npt.NDArray[np.float32]") -> bool:
        """
        不以整窗平均 RMS 判静音（水花很短、前后很静时整窗会被拖到 -60dB 以下）。
        看短时窗最大 RMS，能抓住稀疏突发。
        """
        if buf.size == 0:
            return False
        win = max(self._n_fft, int(0.05 * self.samplerate))
        if buf.size <= win:
            rms = float(np.sqrt(np.mean(buf**2)))
        else:
            step = max(win // 2, 1)
            peak = 0.0
            for i in range(0, buf.size - win + 1, step):
                r = float(np.sqrt(np.mean(buf[i : i + win] ** 2)))
                if r > peak:
                    peak = r
            rms = peak
        if rms <= 0:
            return False
        return 20.0 * float(np.log10(rms)) >= self.min_energy_db

    def feed(
        self,
        block: "npt.NDArray[np.float32]",
        *,
        update_baseline: bool = True,
    ) -> tuple[bool, float]:
        if self._template_img is None or self._template_len <= 0:
            return False, 0.0

        mono = block.mean(axis=1) if block.ndim > 1 else block
        mono = np.asarray(mono, dtype=np.float32)

        n = len(mono)
        if n >= len(self._buffer):
            self._buffer[:] = mono[-len(self._buffer) :]
        else:
            self._buffer = np.roll(self._buffer, -n)
            self._buffer[-n:] = mono

        if not self._buffer_loud_enough(self._buffer):
            self.last_reject = "太静"
            # 静音始终衰减基线（与是否听声无关），避免非听声态卡住高基线后无法抬升
            self._score_ema *= 0.95
            return False, 0.0

        report = self.analyze_buffer(
            self._buffer, update_baseline=update_baseline
        )
        self.last_prominence = float(report["prominence"])
        self.last_rise = float(report["rise"])
        self.last_ambient = float(report["ambient"])
        self.last_window = str(report.get("window") or "")
        score = float(report["score"])
        if report["would_trigger"]:
            self.last_reject = ""
            if update_baseline:
                self._score_ema = max(self._score_ema, score)
            return True, score
        if score >= self.threshold * 0.9 and report["reason"]:
            self.last_reject = str(report["reason"])
        else:
            self.last_reject = (
                str(report["reason"] or "") if score >= self.threshold * 0.9 else ""
            )
        return False, score

    def analyze_buffer(
        self,
        buf: "npt.NDArray[np.float32]",
        *,
        update_baseline: bool = False,
    ) -> dict[str, Any]:
        score, match_start, prom, which = self._match_mel_dual(buf)
        baseline = self._score_ema
        rise = score - baseline
        if update_baseline:
            self._score_ema = (
                (1.0 - SCORE_EMA_ALPHA) * self._score_ema + SCORE_EMA_ALPHA * score
            )

        reason = ""
        would = False
        if score < self.threshold:
            reason = f"相似不足 {score:.2f}<{self.threshold:.2f}"
        elif rise < self.min_score_rise:
            reason = f"未抬升 {rise:.2f}<{self.min_score_rise:.2f}（基线{baseline:.2f}）"
        else:
            would = True

        return {
            "score": score,
            "rise": rise,
            "match_start": match_start,
            "prominence": prom,
            "ambient": baseline,
            "threshold": self.threshold,
            "would_trigger": would,
            "reason": reason,
            "window": which,
        }

    def analyze_clip(
        self,
        wave: "npt.NDArray[np.float32]",
    ) -> dict[str, Any]:
        wave = np.asarray(wave, dtype=np.float32)
        if wave.ndim > 1:
            wave = wave.mean(axis=1)
        need = self._template_len + int(0.25 * self.samplerate)
        if wave.size < need:
            wave = np.pad(wave, (need - wave.size, 0), mode="constant")
        saved = self._score_ema
        self._score_ema = 0.0
        report = self.analyze_buffer(wave, update_baseline=False)
        if report["score"] >= self.threshold:
            report["would_trigger"] = True
            report["reason"] = ""
        self._score_ema = saved
        return report

    def _match_mel_dual(
        self, buf: "npt.NDArray[np.float32]"
    ) -> tuple[float, int, float, str]:
        """
        轻量双后缀窗：短（模板+0.8s）与长（模板+search_pad）各取窗内 max，
        再取两者较高分。不做沿缓冲多起点滑扫。
        """
        if self._template_len <= 0 or buf.size < self._template_len:
            return 0.0, 0, 0.0, ""

        long_n = self._template_len + int(self.search_pad_s * self.samplerate)
        short_n = self._template_len + int(SHORT_SEARCH_PAD_S * self.samplerate)
        long_n = max(long_n, self._template_len + 1)
        short_n = max(short_n, self._template_len + 1)

        long_buf = buf[-long_n:] if buf.size > long_n else buf
        short_buf = buf[-short_n:] if buf.size > short_n else buf

        s_long, m_long, p_long = self._match_mel(long_buf)
        if short_buf.size == long_buf.size and short_n >= long_n:
            off = max(0, buf.size - long_buf.size)
            return s_long, m_long + off, p_long, "long"

        s_short, m_short, p_short = self._match_mel(short_buf)
        if s_short >= s_long:
            off = max(0, buf.size - short_buf.size)
            return s_short, m_short + off, p_short, "short"
        off = max(0, buf.size - long_buf.size)
        return s_long, m_long + off, p_long, "long"

    def _match_mel(
        self, buf: "npt.NDArray[np.float32]"
    ) -> tuple[float, int, float]:
        tpl_img = self._template_img
        if tpl_img is None or buf.size < self._template_len:
            return 0.0, 0, 0.0

        img = self._wave_to_mel(buf)
        th, tw = tpl_img.shape[:2]
        ih, iw = img.shape[:2]
        if ih < th or iw < tw:
            return 0.0, 0, 0.0

        result = cv2.matchTemplate(img, tpl_img, cv2.TM_CCOEFF_NORMED)
        _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(result)
        score = float(max_val)
        peak_frame = int(max_loc[0])
        match_start = int(peak_frame * self._hop)
        match_start = max(0, min(match_start, max(0, buf.size - self._template_len)))

        flat = result.ravel()
        if flat.size < 2:
            return score, match_start, 0.0
        order = np.argsort(flat)[::-1]
        best_i = int(order[0])
        best_yx = np.unravel_index(best_i, result.shape)
        exclude = max(2, int(0.04 * self.samplerate / self._hop))
        second = 0.0
        for idx in order[1:]:
            yx = np.unravel_index(int(idx), result.shape)
            if abs(int(yx[1]) - int(best_yx[1])) > exclude:
                second = float(flat[idx])
                break
        return score, match_start, float(score - second)

    def _trim_energy(
        self, wave: "npt.NDArray[np.float32]", rel: float = 0.22, pad_s: float = 0.06
    ) -> "npt.NDArray[np.float32]":
        n_fft, hop = self._n_fft, self._hop
        if len(wave) < n_fft * 2:
            return wave
        rms: list[tuple[int, float]] = []
        for i in range(0, len(wave) - n_fft, hop):
            rms.append((i, float(np.sqrt(np.mean(wave[i : i + n_fft] ** 2)))))
        if not rms:
            return wave
        peak = max(r for _, r in rms)
        if peak < 1e-8:
            return wave
        thr = peak * rel
        active = [i for i, r in rms if r >= thr]
        if not active:
            return wave
        pad = int(pad_s * self.samplerate)
        a0 = max(0, active[0] - pad)
        a1 = min(len(wave), active[-1] + n_fft + pad)
        trimmed = wave[a0:a1]
        if len(trimmed) < int(0.15 * self.samplerate):
            return wave
        return trimmed

    def _make_mel_filterbank(self) -> "npt.NDArray[np.float32]":
        n_fft = self._n_fft
        sr = self.samplerate
        n_bins = n_fft // 2 + 1
        fmax = min(FMAX_HZ, sr / 2.0 - 1.0)

        def hz2mel(f: float) -> float:
            return 2595.0 * np.log10(1.0 + f / 700.0)

        def mel2hz(m: float) -> float:
            return 700.0 * (10.0 ** (m / 2595.0) - 1.0)

        mels = np.linspace(hz2mel(FMIN_HZ), hz2mel(fmax), N_MELS + 2)
        hz = np.array([mel2hz(float(m)) for m in mels])
        bins = np.floor((n_fft + 1) * hz / sr).astype(int)
        bins = np.clip(bins, 0, n_bins - 1)
        fb = np.zeros((N_MELS, n_bins), dtype=np.float32)
        for i in range(N_MELS):
            left, center, right = int(bins[i]), int(bins[i + 1]), int(bins[i + 2])
            if center <= left:
                center = left + 1
            if right <= center:
                right = center + 1
            for j in range(left, center):
                fb[i, j] = (j - left) / float(center - left)
            for j in range(center, right):
                fb[i, j] = (right - j) / float(right - center)
        return fb

    def _wave_to_mel(self, wave: "npt.NDArray[np.float32]") -> "npt.NDArray[np.float32]":
        n_fft, hop = self._n_fft, self._hop
        wave = np.asarray(wave, dtype=np.float32)
        if wave.ndim > 1:
            wave = wave.mean(axis=1)
        # 短时帧峰值高分位归一：抗单峰杂音；干净段接近旧「样本峰值归一」
        wave = self._normalize_for_mel(wave)
        window = np.hanning(n_fft).astype(np.float32)
        if len(wave) < n_fft:
            wave = np.pad(wave, (0, n_fft - len(wave)), mode="constant")
        n_frames = 1 + (len(wave) - n_fft) // hop
        n_bins = n_fft // 2 + 1
        if self._mel_fb.shape[1] != n_bins:
            self._mel_fb = self._make_mel_filterbank()
        if n_frames <= 0:
            return np.zeros((N_MELS, 1), dtype=np.float32)
        # 批量分帧 + rfft（替代逐帧 Python 循环）
        shape = (n_frames, n_fft)
        strides = (hop * wave.strides[0], wave.strides[0])
        frames = np.lib.stride_tricks.as_strided(
            wave, shape=shape, strides=strides, writeable=False
        )
        windowed = frames * window
        mag = np.abs(np.fft.rfft(windowed, axis=1)) + 1e-10
        spec = mag.T.astype(np.float32)
        mel = self._mel_fb @ spec
        mel = np.log1p(mel)
        mel = mel - float(np.mean(mel))
        return np.ascontiguousarray(mel, dtype=np.float32)

    def _normalize_for_mel(
        self, wave: "npt.NDArray[np.float32]"
    ) -> "npt.NDArray[np.float32]":
        """用各短时帧 |x| 峰值的高分位当有效峰值，再缩放到 NORM_TARGET_PEAK。"""
        if wave.size == 0:
            return wave
        n_fft, hop = self._n_fft, self._hop
        if wave.size < n_fft:
            peak = float(np.max(np.abs(wave)))
            if peak <= 1e-8:
                return wave
            return (wave * (NORM_TARGET_PEAK / peak)).astype(np.float32)
        n_frames = 1 + (wave.size - n_fft) // hop
        shape = (n_frames, n_fft)
        strides = (hop * wave.strides[0], wave.strides[0])
        frames = np.lib.stride_tricks.as_strided(
            wave, shape=shape, strides=strides, writeable=False
        )
        frame_peaks = np.max(np.abs(frames), axis=1)
        peak = float(np.percentile(frame_peaks.astype(np.float64), NORM_PEAK_PERCENTILE))
        if peak <= 1e-8:
            peak = float(np.max(np.abs(wave)))
        if peak <= 1e-8:
            return wave
        return (wave * (NORM_TARGET_PEAK / peak)).astype(np.float32)
