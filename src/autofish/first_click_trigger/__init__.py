"""声音触发第一点击：听到钓鱼开始声音 → 在当前光标按下左键 → 随机延时释放。"""

from __future__ import annotations

__all__ = ["FirstClickTrigger"]


def __getattr__(name: str):
    if name == "FirstClickTrigger":
        from autofish.first_click_trigger.trigger import FirstClickTrigger

        return FirstClickTrigger
    raise AttributeError(name)
