# -*- mode: python ; coding: utf-8 -*-
"""macOS .app：密钥生成窗 → dist/<APP_NAME>（仅本机发密钥用）"""

import os
import sys
from pathlib import Path

_PACKAGING = Path(SPECPATH).resolve()
ROOT = _PACKAGING.parent
sys.path.insert(0, str(_PACKAGING))
from pyi_trim import trim_analysis  # noqa: E402

BUNDLE_ID = os.environ.get("ALBN_KEYGEN_BUNDLE_ID", "com.albn.license-keygen")
APP_NAME = os.environ.get("ALBN_KEYGEN_APP_NAME", "albn-license-keygen.app")
DISPLAY_NAME = os.environ.get("ALBN_KEYGEN_DISPLAY_NAME", "Albn License Keygen")
if not APP_NAME.endswith(".app"):
    APP_NAME = f"{APP_NAME}.app"

datas = []
binaries = []
hiddenimports = [
    "common.license",
    "common.paths",
]

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
    "pygame",
    "sim",
    "ui",
    "matplotlib",
    "cv2",
    "mss",
    "pynput",
    "sounddevice",
    "soundcard",
    "autofish",
    "algo",
    "tools",
]

a = Analysis(
    [str(ROOT / "packaging" / "gen_license_ui.py")],
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
trim_analysis(a)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="albn-license-keygen",
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
    name="albn-license-keygen",
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
    },
)
