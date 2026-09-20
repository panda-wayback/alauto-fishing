"""音频循环缓冲区：持续保存最近 N 秒音频，供标记时截取模板。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import numpy.typing as npt


class AudioRingBuffer:
    """线程不安全的循环缓冲区；由调用者保证单生产者/消费者时序。"""

    def __init__(self, capacity_samples: int) -> None:
        self.capacity = capacity_samples
        self._buf: "npt.NDArray[np.float32]" = np.zeros(
            capacity_samples, dtype=np.float32
        )
        self._pos = 0
        self._size = 0  # 已写入样本数，最多 capacity

    def reset(self) -> None:
        self._buf.fill(0.0)
        self._pos = 0
        self._size = 0

    @property
    def size(self) -> int:
        return self._size

    def extend(self, samples: "npt.NDArray[np.float32]") -> None:
        """追加单声道样本。"""
        n = len(samples)
        if n <= 0:
            return
        if n >= self.capacity:
            self._buf[:] = samples[-self.capacity :]
            self._pos = 0
            self._size = self.capacity
            return
        end = self._pos + n
        if end <= self.capacity:
            self._buf[self._pos : end] = samples
        else:
            first = self.capacity - self._pos
            self._buf[self._pos :] = samples[:first]
            self._buf[: end - self.capacity] = samples[first:]
        self._pos = end % self.capacity
        self._size = min(self.capacity, self._size + n)

    def last(self, n_samples: int) -> "npt.NDArray[np.float32]":
        """取最近 n_samples 个样本（按时间顺序）；不超过已写入量。"""
        n = min(n_samples, self._size, self.capacity)
        if n <= 0:
            return np.zeros(0, dtype=np.float32)
        if self._pos >= n:
            return self._buf[self._pos - n : self._pos].copy()
        # 已绕回：从末尾取一部分再接开头
        tail_len = n - self._pos
        return np.concatenate(
            [self._buf[self.capacity - tail_len :], self._buf[: self._pos]]
        ).copy()

    def extract_active_segment(
        self,
        samplerate: int,
        *,
        frame_ms: float = 12.0,
        hop_ms: float = 6.0,
        rel_threshold: float = 0.12,
        pad_before_ms: float = 30.0,
        pad_after_ms: float = 220.0,
        min_ms: float = 400.0,
        max_ms: float = 2000.0,
    ) -> tuple["npt.NDArray[np.float32]", float]:
        """
        在已录内容里找能量明显的一段：去掉前导空白，并向后多留一点录全。

        返回 (波形, 段内 rms)。
        """
        available = self.last(self._size)
        if available.size == 0:
            return available, 0.0

        frame = max(1, int(samplerate * frame_ms / 1000.0))
        hop = max(1, int(samplerate * hop_ms / 1000.0))
        if available.size < frame:
            rms = float(np.sqrt(np.mean(available**2)))
            return available.copy(), rms

        # 短时能量包络
        n_frames = 1 + (available.size - frame) // hop
        env = np.empty(n_frames, dtype=np.float64)
        for i in range(n_frames):
            s = i * hop
            chunk = available[s : s + frame]
            env[i] = float(np.sqrt(np.mean(chunk**2)))

        peak_i = int(np.argmax(env))
        peak = float(env[peak_i])
        if peak <= 0:
            return np.zeros(0, dtype=np.float32), 0.0

        # 相对峰值门限；再与噪声底取较大，避免背景音把区间拉太长
        noise = float(np.median(env))
        thr = max(peak * rel_threshold, noise * 3.0, peak * 0.05)

        left = peak_i
        while left > 0 and env[left - 1] >= thr:
            left -= 1
        right = peak_i
        # 衰减尾：门限略放宽，尽量录全
        tail_thr = max(thr * 0.55, peak * 0.04)
        while right < n_frames - 1 and env[right + 1] >= tail_thr:
            right += 1

        start = max(0, left * hop - int(samplerate * pad_before_ms / 1000.0))
        end = min(
            available.size,
            right * hop + frame + int(samplerate * pad_after_ms / 1000.0),
        )

        min_n = int(samplerate * min_ms / 1000.0)
        max_n = int(samplerate * max_ms / 1000.0)
        # 太短：优先向后补，再向前补
        while end - start < min_n:
            need = min_n - (end - start)
            take_right = min(need, available.size - end)
            end += take_right
            need -= take_right
            if need <= 0:
                break
            take_left = min(need, start)
            start -= take_left
            if take_right == 0 and take_left == 0:
                break
        # 太长：保住起跳，从后面裁
        if end - start > max_n:
            end = start + max_n

        wave = available[start:end].copy()
        rms = float(np.sqrt(np.mean(wave**2))) if wave.size else 0.0
        return wave, rms

    def peak_window(
        self,
        window_samples: int,
        hop_samples: int | None = None,
    ) -> tuple["npt.NDArray[np.float32]", float]:
        """兼容旧接口：固定窗找最响一段。"""
        available = self.last(self._size)
        if available.size < window_samples:
            rms = float(np.sqrt(np.mean(available**2))) if available.size else 0.0
            return available, rms

        hop = hop_samples or max(1, window_samples // 8)
        best_rms = -1.0
        best_i = 0
        for i in range(0, available.size - window_samples + 1, hop):
            chunk = available[i : i + window_samples]
            rms = float(np.sqrt(np.mean(chunk**2)))
            if rms > best_rms:
                best_rms = rms
                best_i = i
        wave = available[best_i : best_i + window_samples].copy()
        return wave, best_rms
