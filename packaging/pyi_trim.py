# -*- coding: utf-8 -*-
"""PyInstaller Analysis 产物裁剪：去掉未使用的 Qt / OpenCV / 模拟器依赖。"""

from __future__ import annotations

# 路径/名字含任一子串则剔除（比较时转小写）
_DENY_SUBSTR = (
    "webengine",
    "qt3d",
    "qtquick",
    "qtqml",
    "qtpdf",
    "qtcharts",
    "qtdatavisualization",
    "qtvirtualkeyboard",
    "virtualkeyboard",
    "qtsensors",
    "qtpositioning",
    "qtlocation",
    "qtbluetooth",
    "qtnfc",
    "qtserialbus",
    "qtserialport",
    "qtsql",
    "qttest",
    "qttexttospeech",
    "qtremoteobjects",
    "qtscxml",
    "qtwebchannel",
    "qtwebsockets",
    "qtwebview",
    "qtmultimedia",
    "qtspatialaudio",
    "designer",
    "linguist",
    "assistant.app",
    "lupdate",
    "lrelease",
    "qmllint",
    "haarcascade",
    "devtools_resources.debug",
    # 模拟器依赖：壳包不需要
    "pygame",
    "libsdl2",
    "sdl2",
    "libflac",  # 随 pygame 进来；壳用 sounddevice/soundcard
)


def _keep(entry: tuple) -> bool:
    name = str(entry[0]) if entry else ""
    path = str(entry[1]) if len(entry) > 1 else ""
    blob = f"{name}|{path}".lower()
    return not any(s in blob for s in _DENY_SUBSTR)


def trim_analysis(a) -> None:
    """原地过滤 a.binaries / a.datas / a.pure（若可迭代）。"""
    a.binaries = [x for x in a.binaries if _keep(x)]
    a.datas = [x for x in a.datas if _keep(x)]
    if getattr(a, "pure", None) is not None:
        a.pure = [x for x in a.pure if _keep(x)]
