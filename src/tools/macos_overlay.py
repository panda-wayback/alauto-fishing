"""macOS：提高窗口层级，尽量叠在全屏/最大化游戏之上。"""

from __future__ import annotations

import sys
from typing import Any

# NSWindowCollectionBehavior
_CAN_JOIN_ALL_SPACES = 1 << 0
_FULL_SCREEN_AUXILIARY = 1 << 8
_OVERLAY_BEHAVIOR = _CAN_JOIN_ALL_SPACES | _FULL_SCREEN_AUXILIARY

# 高于普通浮层；仍低于部分独占全屏防护
_STATUS_WINDOW_LEVEL = 25  # NSStatusWindowLevel
_NORMAL_WINDOW_LEVEL = 0


def _ns_window(widget: Any) -> Any | None:
    if sys.platform != "darwin":
        return None
    try:
        from ctypes import c_void_p

        import objc  # type: ignore[import-untyped]
    except ImportError:
        return None
    try:
        wid = int(widget.winId())
        if wid == 0:
            return None
        nsview = objc.objc_object(c_void_p(wid))
        return nsview.window()
    except Exception:  # noqa: BLE001
        return None


def elevate_over_fullscreen(widget: Any) -> bool:
    """紧凑态：抬高层级 + 可跟随全屏 Space。成功返回 True。"""
    nsw = _ns_window(widget)
    if nsw is None:
        return False
    try:
        nsw.setLevel_(_STATUS_WINDOW_LEVEL)
        nsw.setCollectionBehavior_(_OVERLAY_BEHAVIOR)
        nsw.setHidesOnDeactivate_(False)
        return True
    except Exception:  # noqa: BLE001
        return False


def restore_window_level(widget: Any, *, floating: bool) -> None:
    """完整态：恢复普通/置顶层级。"""
    nsw = _ns_window(widget)
    if nsw is None:
        return
    try:
        # 3 ≈ NSFloatingWindowLevel；0 = 普通
        nsw.setLevel_(3 if floating else _NORMAL_WINDOW_LEVEL)
        # 清掉「加入全屏」行为，避免完整态也挤进游戏 Space
        nsw.setCollectionBehavior_(0)
    except Exception:  # noqa: BLE001
        pass
