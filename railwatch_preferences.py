"""Local UI preferences shared by the Electron renderer and Python runtime."""

from __future__ import annotations

import base64
import json
import os
import tempfile
import threading
import time
from typing import Literal

from railwatch_config_contract import validate_trip_draft

ThemeMode = Literal["system", "light", "dark"]
UI_PREFERENCES_FILE = "ui_preferences.json"
TRIP_DRAFT_FILE = "trip_draft.json"
LOCAL_SECRET_PREFIX = "dpapi:"
# One process-wide lock covers read/merge/write, including notification settings
# in the bridge. Electron's single-instance lock owns cross-process admission.
PREFERENCES_LOCK = threading.RLock()


def atomic_write_json(path: str, payload: object) -> None:
    """Replace a JSON file only after the complete new value reaches disk."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=directory
    )
    try:
        handle = os.fdopen(descriptor, "w", encoding="utf-8")
        # The stream now owns the descriptor. Its number can be reused by
        # another thread as soon as the context manager closes it.
        descriptor = None
        with handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary_path, 0o600)
        except OSError:
            pass
        os.replace(temporary_path, path)
    except BaseException:
        if descriptor is not None:
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
        import pywintypes
    except ImportError as exc:  # Never silently downgrade to plaintext on Windows.
        raise RuntimeError("Windows 密钥保护组件不可用，通知凭据未保存。") from exc
    try:
        encrypted = win32crypt.CryptProtectData(secret.encode("utf-8"), None, None, None, None, 0)
    except pywintypes.error as exc:
        raise RuntimeError("Windows 密钥保护失败，通知凭据未保存。") from exc
    return LOCAL_SECRET_PREFIX + base64.b64encode(encrypted).decode("ascii")


def unprotect_local_secret(value: object) -> str:
    protected = str(value or "")
    if not protected.startswith(LOCAL_SECRET_PREFIX):
        return protected
    if os.name != "nt":
        return ""
    try:
        import win32crypt
        import pywintypes
    except ImportError as exc:
        raise ValueError("通知凭据无法使用当前 Windows 账户解密。") from exc
    try:
        encrypted = base64.b64decode(protected[len(LOCAL_SECRET_PREFIX):], validate=True)
        return win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)[1].decode("utf-8")
    except (pywintypes.error, ValueError, OSError) as exc:
        raise ValueError("通知凭据无法使用当前 Windows 账户解密。") from exc


def normalize_theme(value: object) -> ThemeMode:
    selected = str(value).lower()
    return selected if selected in ("light", "dark") else "system"


def _read_ui_preferences(data_dir: str) -> dict:
    path = os.path.join(data_dir, UI_PREFERENCES_FILE)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}


def load_ui_preferences(data_dir: str) -> dict:
    with PREFERENCES_LOCK:
        data = _read_ui_preferences(data_dir)
        # Return only public UI fields; old files may contain unrelated secrets.
        return {
            "theme": normalize_theme(data.get("theme", "system")),
            "close_to_tray": data.get("close_to_tray") is True,
        }


def save_ui_preferences(data_dir: str, patch: dict) -> dict:
    if not isinstance(patch, dict) or set(patch) - {"theme", "close_to_tray"}:
        raise ValueError("界面偏好更新字段无效。")
    if "theme" in patch and patch["theme"] not in ("system", "light", "dark"):
        raise ValueError("主题必须为 system、light 或 dark。")
    if "close_to_tray" in patch and not isinstance(patch["close_to_tray"], bool):
        raise ValueError("关闭到托盘必须为布尔值。")
    with PREFERENCES_LOCK:
        if patch:
            existing = _read_ui_preferences(data_dir)
            existing.update(patch)
            atomic_write_json(os.path.join(data_dir, UI_PREFERENCES_FILE), existing)
        return load_ui_preferences(data_dir)


def load_theme_preference(data_dir: str) -> ThemeMode:
    return load_ui_preferences(data_dir)["theme"]


def save_theme_preference(data_dir: str, mode: ThemeMode) -> None:
    save_ui_preferences(data_dir, {"theme": normalize_theme(mode)})


def load_trip_draft(data_dir: str) -> dict:
    """Read an independently persisted, possibly incomplete trip draft."""
    path = os.path.join(data_dir, TRIP_DRAFT_FILE)
    try:
        with PREFERENCES_LOCK:
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
        draft = validate_trip_draft(payload)
        return {"status": "available", "draft": draft, "warning": None}
    except FileNotFoundError:
        return {"status": "missing", "draft": None, "warning": None}
    except (OSError, ValueError, TypeError):
        # Preserve the original file and keep the saved config/order independent.
        return {"status": "invalid", "draft": None, "warning": "草稿无法读取或版本不受支持，已保留原文件。"}


def save_trip_draft(data_dir: str, config: dict, revision: int) -> dict:
    """Persist a newer revision only; malformed old drafts are archived intact."""
    if type(revision) is not int or revision < 1:
        raise ValueError("草稿修订号无效。")
    payload = validate_trip_draft({"schema_version": 1, "revision": revision,
                                   "saved_at": time.time(), "config": config})
    path = os.path.join(data_dir, TRIP_DRAFT_FILE)
    with PREFERENCES_LOCK:
        existing = load_trip_draft(data_dir)
        if existing["status"] == "available" and revision <= existing["draft"]["revision"]:
            raise ValueError("草稿修订号已过期，请重新加载最新草稿。")
        if existing["status"] == "invalid":
            backup = f"{path}.invalid-{time.time_ns()}"
            os.replace(path, backup)
        atomic_write_json(path, payload)
    return payload
