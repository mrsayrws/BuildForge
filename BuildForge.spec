# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

APP_DIR = Path(SPECPATH).resolve()

a = Analysis(
    [str(APP_DIR / "launcher.py")],
    pathex=[str(APP_DIR)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "PIL", "numpy", "setuptools"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BuildForge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(APP_DIR / "assets" / "buildforge.ico"),
    version=str(APP_DIR / "assets" / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="BuildForge",
)
