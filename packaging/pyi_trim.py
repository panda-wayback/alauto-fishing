# -*- coding: utf-8 -*-
"""PyInstaller Analysis 产物裁剪：去掉未使用的 Qt / OpenCV 重量级文件。"""

from __future__ import annotations

# 路径/名字含任一子串则剔除（大小写敏感即可覆盖 Qt 常见命名）
_DENY_SUBSTR = (
    "WebEngine",
    "Qt3D",
    "QtQuick",
    "QtQml",
    "QtPdf",
    "QtCharts",
    "QtDataVisualization",
    "QtVirtualKeyboard",
    "QtSensors",
    "QtPositioning",
    "QtLocation",
    "QtBluetooth",
    "QtNfc",
    "QtSerialBus",
    "QtSerialPort",
    "QtSql",
    "QtTest",
    "QtTextToSpeech",
    "QtRemoteObjects",
    "QtScxml",
    "QtWebChannel",
    "QtWebSockets",
    "QtWebView",
    "QtMultimedia",
    "QtSpatialAudio",
    "Designer",
    "Linguist",
    "Assistant.app",
    "lupdate",
    "lrelease",
    "qmllint",
    "haarcascade",
    "devtools_resources.debug",
)


def _keep(entry: tuple) -> bool:
    name = str(entry[0]) if entry else ""
    path = str(entry[1]) if len(entry) > 1 else ""
    blob = f"{name}|{path}"
    return not any(s in blob for s in _DENY_SUBSTR)


def trim_analysis(a) -> None:
    """原地过滤 a.binaries / a.datas / a.pure（若可迭代）。"""
    a.binaries = [x for x in a.binaries if _keep(x)]
    a.datas = [x for x in a.datas if _keep(x)]
    # pure 为模块 TOC；再挡一层 Addons 模块名
    if getattr(a, "pure", None) is not None:
        a.pure = [x for x in a.pure if _keep(x)]
