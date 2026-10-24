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
_NS_WINDOW_MINIATURIZE_BUTTON = 1
_NS_WINDOW_STYLE_MINIATURIZABLE = 1 << 2  # NSWindowStyleMaskMiniaturizable


def _ns_window(widget: Any) -> Any | None:
    """取 NSWindow。PyObjC 12+ 无法再用 winId→objc_object，改为按标题匹配。"""
    if sys.platform != "darwin":
        return None
    try:
        from AppKit import NSApp  # type: ignore[import-untyped]
    except ImportError:
        return None
    try:
        title = str(widget.windowTitle() or "")
    except Exception:  # noqa: BLE001
        title = ""
    try:
        windows = list(NSApp.windows() or [])
    except Exception:  # noqa: BLE001
        return None
    if title:
        for aw in windows:
            try:
                if str(aw.title() or "") == title:
                    return aw
            except Exception:  # noqa: BLE001
                continue
    # 仅一扇有标题的可见窗时兜底
    titled: list[Any] = []
    for aw in windows:
        try:
            if str(aw.title() or ""):
                titled.append(aw)
        except Exception:  # noqa: BLE001
            continue
    if len(titled) == 1:
        return titled[0]
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
        hide_miniaturize_button(widget)
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
        hide_miniaturize_button(widget)
    except Exception:  # noqa: BLE001
        pass


def hide_miniaturize_button(widget: Any) -> None:
    """去掉 macOS 黄钮：清 Miniaturizable 并隐藏按钮。"""
    nsw = _ns_window(widget)
    if nsw is None:
        return
    try:
        mask = int(nsw.styleMask())
        if mask & _NS_WINDOW_STYLE_MINIATURIZABLE:
            nsw.setStyleMask_(mask & ~_NS_WINDOW_STYLE_MINIATURIZABLE)
        btn = nsw.standardWindowButton_(_NS_WINDOW_MINIATURIZE_BUTTON)
        if btn is not None:
            btn.setHidden_(True)
            btn.setEnabled_(False)
    except Exception:  # noqa: BLE001
        pass
