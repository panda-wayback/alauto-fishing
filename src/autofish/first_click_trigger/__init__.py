"""声音开钓：会话机 + 模板匹配。"""

from __future__ import annotations

__all__ = ["FirstClickTrigger"]


def __getattr__(name: str):
    if name == "FirstClickTrigger":
        from autofish.first_click_trigger.trigger import FirstClickTrigger

        return FirstClickTrigger
    raise AttributeError(name)
