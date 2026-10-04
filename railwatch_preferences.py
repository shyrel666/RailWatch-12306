"""Local UI preferences shared by the Electron renderer and Python runtime."""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import threading
import time
from typing import Dict, Literal, Mapping, Optional

from railwatch_config_contract import validate_trip_draft

ThemeMode = Literal["system", "light", "dark"]
UI_PREFERENCES_FILE = "ui_preferences.json"
TRIP_DRAFT_FILE = "trip_draft.json"
LOCAL_SECRET_PREFIX = "dpapi:"
KEYCHAIN_SECRET_PREFIX = "keychain:"
KEYCHAIN_SERVICE = "org.railwatch.railwatch12306"
KEYCHAIN_ACCOUNT = "notification-secrets"
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


def uses_system_keychain() -> bool:
    """macOS keeps notification secrets in the login keychain, not in the JSON file."""
    return sys.platform == "darwin"


def keychain_marker(slot: str) -> str:
    return KEYCHAIN_SECRET_PREFIX + slot


def _keychain_error_named(exc: BaseException, name: str) -> bool:
    seen: Optional[BaseException] = exc
    while seen is not None:
        if type(seen).__name__ == name:
            return True
        seen = seen.__cause__ or seen.__context__
    return False


def keychain_access_denied(exc: BaseException) -> bool:
    return _keychain_error_named(exc, "KeyringLocked")


class MacSecretStore:
    """Keep every notification secret in ONE generic-password keychain item.

    An ad-hoc signed build is a new keychain client after each upgrade, so
    every item asks for authorization again; one item means one prompt.
    """

    def __init__(self, backend=None, service: str = KEYCHAIN_SERVICE, account: str = KEYCHAIN_ACCOUNT):
        self._backend = backend
        self.service = service
        self.account = account

    def _keyring(self):
        if self._backend is None:
            # Use the macOS backend directly: entry-point discovery and keyringrc
            # files are not reliable inside a frozen runtime.
            try:
                from keyring.backends.macOS import Keyring
                from keyring.backends.macOS import api  # noqa: F401 - fails without Security.framework
            except Exception as exc:
                raise RuntimeError("macOS 钥匙串组件不可用。") from exc
            self._backend = Keyring()
        return self._backend

    def read_all(self) -> Optional[Dict[str, str]]:
        """Return the stored secrets, or None when the item does not exist."""
        raw = self._keyring().get_password(self.service, self.account)
        if raw is None:
            return None
        try:
            data = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("钥匙串中的通知凭据格式无效。") from exc
        if not isinstance(data, dict) or not all(isinstance(key, str) and isinstance(value, str)
                                                 for key, value in data.items()):
            raise ValueError("钥匙串中的通知凭据格式无效。")
        return data

    def write_all(self, secrets: Mapping[str, str]) -> None:
        values = {key: value for key, value in secrets.items() if value}
        if not values:
            self.delete()
            return
        self._keyring().set_password(self.service, self.account, json.dumps(values, ensure_ascii=False))

    def delete(self) -> None:
        try:
            self._keyring().delete_password(self.service, self.account)
        except Exception as exc:
            if not _keychain_error_named(exc, "NotFound"):
                raise


def protect_local_secret(value: object, slot: str = "") -> str:
    """Protect a secret: a Windows DPAPI blob, or a macOS keychain marker.

    On macOS the caller stores the value itself with MacSecretStore; the file
    only records which slot of the keychain item holds it.
    """
    secret = str(value or "")
    if secret and uses_system_keychain():
        if not slot:
            raise RuntimeError("通知凭据缺少钥匙串字段名，未保存。")
        return keychain_marker(slot)
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


def unprotect_local_secret(value: object, slot: str = "") -> str:
    protected = str(value or "")
    if protected.startswith(KEYCHAIN_SECRET_PREFIX):
        if not uses_system_keychain():
            raise ValueError("通知凭据保存在 macOS 钥匙串中，当前系统无法读取。")
        if protected != keychain_marker(slot):
            raise ValueError("通知凭据的钥匙串标记无效。")
        # Reading may wait for user authorization; MacSecretStore does it off the startup path.
        raise ValueError("钥匙串中的通知凭据需由后台读取。")
    if not protected.startswith(LOCAL_SECRET_PREFIX):
        return protected
    if uses_system_keychain():
        raise ValueError("通知凭据来自 Windows，无法在 macOS 上解密，请重新填写。")
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
            "auto_rehearsal": data.get("auto_rehearsal") is True,
        }


def save_ui_preferences(data_dir: str, patch: dict) -> dict:
    if not isinstance(patch, dict) or set(patch) - {"theme", "close_to_tray", "auto_rehearsal"}:
        raise ValueError("界面偏好更新字段无效。")
    if "theme" in patch and patch["theme"] not in ("system", "light", "dark"):
        raise ValueError("主题必须为 system、light 或 dark。")
    if "close_to_tray" in patch and not isinstance(patch["close_to_tray"], bool):
        raise ValueError("关闭到托盘必须为布尔值。")
    if "auto_rehearsal" in patch and not isinstance(patch["auto_rehearsal"], bool):
        raise ValueError("自动彩排必须为布尔值。")
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
