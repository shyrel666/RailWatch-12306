"""Local UI preferences shared by the Electron renderer and Python runtime."""

from __future__ import annotations

import base64
import json
import os
import tempfile
import threading
from typing import Literal

ThemeMode = Literal["system", "light", "dark"]
UI_PREFERENCES_FILE = "ui_preferences.json"
LOCAL_SECRET_PREFIX = "dpapi:"
_preferences_lock = threading.RLock()


def atomic_write_json(path: str, payload: object) -> None:
    """Replace a JSON file only after the complete new value reaches disk."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary_path, 0o600)
        except OSError:
            pass
        os.replace(temporary_path, path)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise


def protect_local_secret(value: object) -> str:
    """Protect a secret with the current Windows user's DPAPI credentials."""
    secret = str(value or "")
    if not secret or secret.startswith(LOCAL_SECRET_PREFIX) or os.name != "nt":
        return secret
    try:
        import win32crypt
    except ImportError as exc:  # Never silently downgrade to plaintext on Windows.
        raise RuntimeError("Windows 密钥保护组件不可用，通知凭据未保存。") from exc
    encrypted = win32crypt.CryptProtectData(secret.encode("utf-8"), None, None, None, None, 0)
    return LOCAL_SECRET_PREFIX + base64.b64encode(encrypted).decode("ascii")


def unprotect_local_secret(value: object) -> str:
    protected = str(value or "")
    if not protected.startswith(LOCAL_SECRET_PREFIX):
        return protected
    if os.name != "nt":
        return ""
    try:
        import win32crypt
        encrypted = base64.b64decode(protected[len(LOCAL_SECRET_PREFIX):], validate=True)
        return win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)[1].decode("utf-8")
    except (ImportError, ValueError, OSError, UnicodeDecodeError) as exc:
        raise ValueError("通知凭据无法使用当前 Windows 账户解密。") from exc


def normalize_theme(value: object) -> ThemeMode:
    selected = str(value).lower()
    return selected if selected in ("light", "dark") else "system"


def load_theme_preference(data_dir: str) -> ThemeMode:
    path = os.path.join(data_dir, UI_PREFERENCES_FILE)
    if not os.path.exists(path):
        return "system"
    try:
        with _preferences_lock:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        if isinstance(data, dict):
            return normalize_theme(data.get("theme", "system"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return "system"


def save_theme_preference(data_dir: str, mode: ThemeMode) -> None:
    path = os.path.join(data_dir, UI_PREFERENCES_FILE)
    with _preferences_lock:
        existing: dict = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                if isinstance(loaded, dict):
                    existing = loaded
            except (OSError, json.JSONDecodeError):
                existing = {}
        existing["theme"] = normalize_theme(mode)
        atomic_write_json(path, existing)
