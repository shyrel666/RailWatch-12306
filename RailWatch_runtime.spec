# -*- mode: python ; coding: utf-8 -*-

import os
import sys

from PyInstaller.utils.hooks import collect_submodules

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"

# The interpreter running this spec is the one that gets frozen. Refuse any
# version other than the one pinned for CI and release builds, so a local
# default Python cannot end up inside an installer.
with open(os.path.join(SPECPATH, ".python-version"), encoding="utf-8") as pinned_file:
    pinned_python = ".".join(pinned_file.read().strip().split(".")[:2])
running_python = "%d.%d" % sys.version_info[:2]
if running_python != pinned_python:
    raise SystemExit(
        f"The runtime must be built with Python {pinned_python} (.python-version), not {running_python}. "
        "Use `npm run build:runtime`: it builds from requirements.lock in its own virtual environment."
    )

# selenium >= 4.44 lazy-loads every browser submodule (chrome.options, edge.service, ...)
# through module __getattr__, so static import analysis never sees them and the frozen
# app only fails at runtime when the browser is first launched. Force-collect them.
hiddenimports = collect_submodules("selenium")
if IS_WINDOWS:
    hiddenimports.append("win32crypt")
if IS_MACOS:
    # Notification secrets use the macOS keychain backend directly (MacSecretStore).
    hiddenimports += ["keyring.backends.macOS", "keyring.backends.macOS.api"]


# The CLI evaluates this spec before adding its directory to the module search
# path. Resolve local policy data explicitly so console-script builds include it.
datas = [(os.path.join(SPECPATH, "railwatch_policies", name), "railwatch_policies")
         for name in ("query_strategies.json", "date_strategies.json", "order_policies.json",
                      "notification_channels.json", "train_codes.json", "idle_policies.json")]
# macOS downloads its driver into the data directory on first environment check.
for optional_file in (
    *(("chromedriver.exe",) if IS_WINDOWS else ()),
    "LICENSE.chromedriver",
    "THIRD_PARTY_NOTICES.chromedriver",
):
    if os.path.exists(optional_file):
        datas.append((optional_file, "."))


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

# onedir with UPX disabled across platforms: avoids per-launch %TEMP% unpacking,
# _MEI* temp leaks on force-stop, UPX AV false positives, and keeps every Mach-O
# binary separate for macOS .app signing.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="railwatch_runtime",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
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
    name="railwatch_runtime",
)
