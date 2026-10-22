"""读取系统当前光标位图（mss 截不到系统合成光标）。"""

from __future__ import annotations

import sys
from io import BytesIO

import numpy as np


def grab_system_cursor() -> np.ndarray | None:
    """当前系统光标 RGBA uint8 (H,W,4)；失败 None。

    游戏把鼠标换成漂形时，通常改的是系统光标；mss 画面截屏不含该层。
    """
    if sys.platform == "darwin":
        return _grab_macos()
    if sys.platform == "win32":
        return _grab_windows()
    return None


def grab_around_cursor(size: int = 100) -> np.ndarray | None:
    """兼容旧调用：改为返回系统光标 RGB（忽略 size）。

    新代码请用 grab_system_cursor。
    """
    rgba = grab_system_cursor()
    if rgba is None:
        return None
    return np.ascontiguousarray(rgba[..., :3])


def _grab_macos() -> np.ndarray | None:
    try:
        from AppKit import NSCursor
        from PIL import Image
    except ImportError:
        return None
    try:
        cur = NSCursor.currentSystemCursor()
        if cur is None:
            return None
        img = cur.image()
        if img is None:
            return None
        tiff = img.TIFFRepresentation()
        if tiff is None:
            return None
        pil = Image.open(BytesIO(bytes(tiff)))
        arr = np.asarray(pil.convert("RGBA"), dtype=np.uint8)
        if arr.ndim != 3 or arr.shape[0] < 4 or arr.shape[1] < 4:
            return None
        return np.ascontiguousarray(arr)
    except Exception:
        return None


def _grab_windows() -> np.ndarray | None:
    try:
        import ctypes
        from ctypes import wintypes

        from PIL import Image
    except ImportError:
        return None

    class CURSORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("hCursor", wintypes.HANDLE),
            ("ptScreenPos", wintypes.POINT),
        ]

    class ICONINFO(ctypes.Structure):
        _fields_ = [
            ("fIcon", wintypes.BOOL),
            ("xHotspot", wintypes.DWORD),
            ("yHotspot", wintypes.DWORD),
            ("hbmMask", wintypes.HBITMAP),
            ("hbmColor", wintypes.HBITMAP),
        ]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    ci = CURSORINFO()
    ci.cbSize = ctypes.sizeof(CURSORINFO)
    if not user32.GetCursorInfo(ctypes.byref(ci)):
        return None
    if not ci.hCursor:
        return None
    ii = ICONINFO()
    if not user32.GetIconInfo(ci.hCursor, ctypes.byref(ii)):
        return None
    try:
        # 画到 64×64 DIBs（多数光标够用）
        side = 64
        hdc = user32.GetDC(0)
        if not hdc:
            return None
        try:
            hdc_mem = gdi32.CreateCompatibleDC(hdc)
            hbmp = gdi32.CreateCompatibleBitmap(hdc, side, side)
            old = gdi32.SelectObject(hdc_mem, hbmp)
            # 白底再画光标，便于看清
            brush = gdi32.GetStockObject(0)  # WHITE_BRUSH
            rect = (ctypes.c_long * 4)(0, 0, side, side)
            user32.FillRect(hdc_mem, ctypes.byref(rect), brush)
            user32.DrawIconEx(
                hdc_mem, 0, 0, ci.hCursor, side, side, 0, None, 0x0003
            )  # DI_NORMAL
            # GetDIBits
            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ("biSize", wintypes.DWORD),
                    ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD),
                ]

            class BITMAPINFO(ctypes.Structure):
                _fields_ = [("bmiHeader", BITMAPINFOHEADER)]

            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = side
            bmi.bmiHeader.biHeight = -side  # top-down
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = 0
            buf = (ctypes.c_ubyte * (side * side * 4))()
            gdi32.GetDIBits(hdc_mem, hbmp, 0, side, buf, ctypes.byref(bmi), 0)
            gdi32.SelectObject(hdc_mem, old)
            gdi32.DeleteObject(hbmp)
            gdi32.DeleteDC(hdc_mem)
        finally:
            user32.ReleaseDC(0, hdc)
        bgra = np.frombuffer(buf, dtype=np.uint8).reshape(side, side, 4)
        rgba = np.empty_like(bgra)
        rgba[..., 0] = bgra[..., 2]
        rgba[..., 1] = bgra[..., 1]
        rgba[..., 2] = bgra[..., 0]
        rgba[..., 3] = bgra[..., 3]
        return np.ascontiguousarray(rgba)
    except Exception:
        return None
    finally:
        if ii.hbmColor:
            gdi32.DeleteObject(ii.hbmColor)
        if ii.hbmMask:
            gdi32.DeleteObject(ii.hbmMask)
