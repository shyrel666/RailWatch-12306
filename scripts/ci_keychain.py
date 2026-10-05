"""Point a temporary macOS HOME at the CI test keychain.

The Security framework reads the keychain search list and the default keychain
from $HOME. Smoke tests give the runtime a fresh HOME to isolate its data, which
leaves it without a default keychain; the first keychain write then opens a
"keychain cannot be found" dialog that blocks forever on a headless runner.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

ENV_NAME = "RAILWATCH_TEST_KEYCHAIN"


def use_test_keychain(home: str, keychain: Optional[str] = None) -> None:
    """Make the test keychain the search list and default keychain for `home`.

    Does nothing off macOS or when no test keychain is configured.
    """
    keychain = keychain or os.environ.get(ENV_NAME)
    if sys.platform != "darwin" or not keychain:
        return
    for folder in ("Keychains", "Preferences"):
        (Path(home) / "Library" / folder).mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, HOME=str(home))

    def security(*args: str) -> str:
        return subprocess.run(["security", *args], env=env, check=True, capture_output=True,
                              text=True, timeout=30).stdout

    security("list-keychains", "-d", "user", "-s", keychain)
    security("default-keychain", "-d", "user", "-s", keychain)
    current = security("default-keychain", "-d", "user").strip().strip('"')
    if os.path.realpath(current) != os.path.realpath(keychain):
        raise RuntimeError(f"HOME={home} 的默认钥匙串是 {current}，不是测试钥匙串 {keychain}")
