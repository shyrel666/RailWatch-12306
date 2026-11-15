"""Temporary user profiles for the smoke tests.

A per-user Windows install keeps the app, its data and the Chrome profile under
C:\\Users\\<account>. Chinese account names, often with a space, are common, so
the smoke tests can repeat their checks under such a folder.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

NON_ASCII_PROFILE = "张三 的电脑"


@contextmanager
def temporary_profile(prefix: str, non_ascii: bool = False) -> Iterator[str]:
    """Yield a temporary home folder; with `non_ascii`, one named like a Chinese account."""
    # A virus scanner may still hold a copied executable, so cleanup errors are not failures.
    with tempfile.TemporaryDirectory(prefix=prefix, ignore_cleanup_errors=True) as temporary:
        # Canonical path: macOS /var is a symlink and Windows runners reach TEMP through an 8.3 alias.
        home = os.path.realpath(temporary)
        if non_ascii:
            home = os.path.join(home, NON_ASCII_PROFILE)
            os.mkdir(home)
        yield home


def install_under_profile(executable: Path, bundle: Path, profile: str) -> Path:
    """Copy the app folder `bundle` to where a per-user install lives and return its executable there."""
    target = Path(profile) / "Programs" / bundle.name
    shutil.copytree(bundle, target)
    return target / executable.relative_to(bundle)
