# -*- mode: python ; coding: utf-8 -*-

import os


# The CLI evaluates this spec before adding its directory to the module search
# path. Resolve local policy data explicitly so console-script builds include it.
datas = [(os.path.join(SPECPATH, "railwatch_policies", "query_strategies.json"), "railwatch_policies")]
for optional_file in (
    "chromedriver.exe",
    "LICENSE.chromedriver",
    "THIRD_PARTY_NOTICES.chromedriver",
):
    if os.path.exists(optional_file):
        datas.append((optional_file, "."))

assets_dir = "assets"
if os.path.isdir(assets_dir):
    datas.append((assets_dir, assets_dir))


a = Analysis(
    ["railwatch_runtime.py"],
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
    a.binaries,
    a.datas,
    [],
    name="railwatch_runtime",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
