"""音频循环缓冲区：持续保存最近 N 秒音频。"""

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
