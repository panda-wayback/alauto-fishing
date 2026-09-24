"""进程内类型化 Event Bus（通用，无业务主题）。"""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Callable, Hashable
from typing import Any

Subscriber = Callable[[Any], None]


class EventBus:
    """线程安全：subscribe / unsubscribe / publish；订阅者异常不拖垮总线。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subs: dict[Hashable, list[Subscriber]] = defaultdict(list)

    def subscribe(self, topic: Hashable, callback: Subscriber) -> None:
        with self._lock:
            if callback not in self._subs[topic]:
                self._subs[topic].append(callback)

    def unsubscribe(self, topic: Hashable, callback: Subscriber) -> None:
        with self._lock:
            try:
                self._subs[topic].remove(callback)
            except ValueError:
                pass

    def publish(self, topic: Hashable, event: Any) -> None:
        with self._lock:
            callbacks = list(self._subs[topic])
        for cb in callbacks:
            try:
                cb(event)
            except Exception:  # noqa: BLE001
                pass
