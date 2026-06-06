# -*- mode: python ; coding: utf-8 -*-

import os


datas = []
for optional_file in (
    "chromedriver.exe",
    "LICENSE.chromedriver",
    "THIRD_PARTY_NOTICES.chromedriver",
):
    if os.path.exists(optional_file):
        datas.append((optional_file, "."))


a = Analysis(
    ["t12306_gui_0.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
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
    [],
    exclude_binaries=True,
    name="RailWatch 12306",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
    upx=True,
    upx_exclude=[],
    name="RailWatch 12306",
)
