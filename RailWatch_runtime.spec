# -*- mode: python ; coding: utf-8 -*-

import os

from PyInstaller.utils.hooks import collect_submodules


# selenium >= 4.44 lazy-loads every browser submodule (chrome.options, edge.service, ...)
# through module __getattr__, so static import analysis never sees them and the frozen
# app only fails at runtime when the browser is first launched. Force-collect them.
hiddenimports = collect_submodules("selenium")


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
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# Fail the build instead of shipping an exe whose browser submodules are missing.
frozen_modules = {name for name, *_ in a.pure}
required_lazy_selenium = {
    "selenium.webdriver.chrome.options",
    "selenium.webdriver.chromium.options",
    "selenium.webdriver.edge.options",
    "selenium.webdriver.firefox.options",
}
missing = sorted(required_lazy_selenium - frozen_modules)
if missing:
    raise SystemExit(f"PyInstaller missed lazy-loaded selenium submodules: {missing}")

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
