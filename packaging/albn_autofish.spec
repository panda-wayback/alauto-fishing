# -*- mode: python ; coding: utf-8 -*-
"""macOS 单文件：autofish.preview --ui → dist/albn-autofish"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(SPECPATH).resolve().parent
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
    "common.pubsub",
]

for pkg in ("PySide6", "mss", "pynput"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

datas += collect_data_files("cv2")

a = Analysis(
    [str(ROOT / "run_preview_ui.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="albn-autofish",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
