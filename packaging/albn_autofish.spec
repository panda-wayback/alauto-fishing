# -*- mode: python ; coding: utf-8 -*-
"""macOS .app（onedir）：autofish.preview --ui → dist/<APP_NAME>

环境变量（本地反复测授权时用）：
  ALBN_BUNDLE_ID   默认 com.albn.autofish
  ALBN_APP_NAME    默认 albn-autofish.app（须以 .app 结尾）
  ALBN_DISPLAY_NAME 默认 Albn Autofish
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(SPECPATH).resolve().parent
BUNDLE_ID = os.environ.get("ALBN_BUNDLE_ID", "com.albn.autofish")
APP_NAME = os.environ.get("ALBN_APP_NAME", "albn-autofish.app")
DISPLAY_NAME = os.environ.get("ALBN_DISPLAY_NAME", "Albn Autofish")
if not APP_NAME.endswith(".app"):
    APP_NAME = f"{APP_NAME}.app"

datas = [(str(ROOT / "assets"), "assets")]
binaries = []
hiddenimports = [
    "autofish",
    "autofish.preview",
    "tools.preview_app",
    "tools.dual_range_axis",
    "sim",
    "sim.config",
    "sim.game",
    "ui.render",
    "common.paths",
    "common.permissions",
    "common.pubsub",
]

for pkg in ("mss", "pynput"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

datas += collect_data_files("cv2")

excludes = [
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtNfc",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialBus",
    "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio",
    "PySide6.QtSql",
    "PySide6.QtStateMachine",
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
    "PySide6.QtWebView",
    "PySide6.scripts",
    "PySide6.QtUiTools",
    "tkinter",
]

a = Analysis(
    [str(ROOT / "run_preview_ui.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="albn-autofish",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="albn-autofish",
)

app = BUNDLE(
    coll,
    name=APP_NAME,
    icon=None,
    bundle_identifier=BUNDLE_ID,
    info_plist={
        "CFBundleName": DISPLAY_NAME,
        "CFBundleDisplayName": DISPLAY_NAME,
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1.0.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "12.0",
        "NSAppleEventsUsageDescription": "自动拉鱼需要控制鼠标。",
        "NSScreenCaptureUsageDescription": "自动拉鱼需要截取游戏画面以识别张力条。",
    },
)
