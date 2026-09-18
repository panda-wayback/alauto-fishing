"""运行权限：截屏 / 控鼠状态查询与授权引导（macOS + Windows）。"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionStatus:
    """跨平台权限快照。"""

    platform: str  # "darwin" | "win32" | other
    screen_ok: bool | None
    """截屏是否可用；None=未知。"""
    screen_label: str
    input_ok: bool | None
    """控鼠相关是否就绪；None=未知。"""
    input_label: str
    is_admin: bool | None
    """Windows 是否管理员；其它平台 None。"""


def current_status() -> PermissionStatus:
    if sys.platform == "darwin":
        return _status_macos()
    if sys.platform == "win32":
        return _status_windows()
    return PermissionStatus(
        platform=sys.platform,
        screen_ok=None,
        screen_label="本平台未做权限检测",
        input_ok=None,
        input_label="本平台未做权限检测",
        is_admin=None,
    )


def request_screen_access() -> str:
    """引导屏幕/截屏授权。返回给用户看的短句。"""
    if sys.platform == "darwin":
        _macos_request_screen()
        _macos_open_screen_settings()
        return "已请求屏幕录制授权，并打开系统设置；勾选本程序后返回。"
    if sys.platform == "win32":
        ok = _probe_screen_grab()
        return "截屏测试成功。" if ok else "截屏测试失败：检查杀软或显示驱动。"
    return "当前系统无需专门的屏幕隐私授权。"


def request_input_access() -> str:
    """引导控鼠/辅助功能授权。返回短句。"""
    if sys.platform == "darwin":
        _macos_request_accessibility(prompt=True)
        _macos_open_accessibility_settings()
        return "已弹出辅助功能授权，并打开系统设置；勾选本程序后返回。"
    if sys.platform == "win32":
        if _windows_is_admin():
            return "已是管理员，可直接控鼠；若仍无效，检查杀软。"
        if restart_as_admin():
            return "已请求以管理员重新启动，请在 UAC 中确认。"
        return "提权重启失败；请右键本程序「以管理员身份运行」。"
    return "当前系统无辅助功能开关。"


def restart_as_admin() -> bool:
    """
    Windows：以管理员重新启动当前进程。
    成功拉起新进程返回 True（调用方应退出旧进程）；其它平台 False。
    """
    if sys.platform != "win32":
        return False
    if _windows_is_admin():
        return True
    try:
        import ctypes

        exe = sys.executable
        if getattr(sys, "frozen", False):
            params = " ".join(f'"{a}"' for a in sys.argv[1:])
            rc = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", exe, params or None, None, 1
            )
        else:
            script = os.path.abspath(sys.argv[0])
            args = " ".join([f'"{script}"', *[f'"{a}"' for a in sys.argv[1:]]])
            rc = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", exe, args, None, 1
            )
        return int(rc) > 32
    except Exception:
        return False


# ---- macOS ----


def _status_macos() -> PermissionStatus:
    screen = _macos_screen_trusted()
    access = _macos_accessibility_trusted()
    return PermissionStatus(
        platform="darwin",
        screen_ok=screen,
        screen_label="屏幕录制已授权" if screen else "屏幕录制未授权",
        input_ok=access,
        input_label="辅助功能已授权" if access else "辅助功能未授权",
        is_admin=None,
    )


def _macos_screen_trusted() -> bool:
    try:
        from Quartz import (  # type: ignore[import-untyped]
            CGPreflightScreenCaptureAccess,
        )

        return bool(CGPreflightScreenCaptureAccess())
    except Exception:
        return _probe_screen_grab()


def _macos_request_screen() -> None:
    try:
        from Quartz import (  # type: ignore[import-untyped]
            CGRequestScreenCaptureAccess,
        )

        CGRequestScreenCaptureAccess()
    except Exception:
        _probe_screen_grab()


def _macos_accessibility_trusted() -> bool:
    try:
        from ApplicationServices import (  # type: ignore[import-untyped]
            AXIsProcessTrusted,
        )

        return bool(AXIsProcessTrusted())
    except Exception:
        try:
            from Quartz import AXIsProcessTrusted  # type: ignore[import-untyped]

            return bool(AXIsProcessTrusted())
        except Exception:
            return False


def _macos_request_accessibility(*, prompt: bool) -> bool:
    try:
        from ApplicationServices import (  # type: ignore[import-untyped]
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )
        from Foundation import NSDictionary  # type: ignore[import-untyped]

        opts = NSDictionary.dictionaryWithDictionary_(
            {kAXTrustedCheckOptionPrompt: bool(prompt)}
        )
        return bool(AXIsProcessTrustedWithOptions(opts))
    except Exception:
        return _macos_accessibility_trusted()


def _macos_open_screen_settings() -> None:
    urls = (
        "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
        "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension",
    )
    for url in urls:
        try:
            subprocess.run(["open", url], check=False)
            return
        except Exception:
            continue


def _macos_open_accessibility_settings() -> None:
    urls = (
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
        "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension",
    )
    for url in urls:
        try:
            subprocess.run(["open", url], check=False)
            return
        except Exception:
            continue


# ---- Windows ----


def _status_windows() -> PermissionStatus:
    admin = _windows_is_admin()
    screen = _probe_screen_grab()
    return PermissionStatus(
        platform="win32",
        screen_ok=screen,
        screen_label="截屏可用" if screen else "截屏异常",
        input_ok=True,
        input_label=(
            "已是管理员（利于控鼠）"
            if admin
            else "非管理员（游戏提权时请提权重启）"
        ),
        is_admin=admin,
    )


def _windows_is_admin() -> bool:
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _probe_screen_grab() -> bool:
    """轻量截一小块，验证截屏链路。"""
    try:
        import mss

        with mss.mss() as sct:
            mon = sct.monitors[0]
            box = {
                "left": int(mon["left"]),
                "top": int(mon["top"]),
                "width": min(16, int(mon["width"])),
                "height": min(16, int(mon["height"])),
            }
            shot = sct.grab(box)
            return shot is not None and shot.width > 0
    except Exception:
        return False
