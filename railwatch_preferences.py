"""Local UI preferences shared by the Electron renderer and Python runtime."""

from __future__ import annotations

import json
import os
from typing import Literal

ThemeMode = Literal["light", "dark"]
UI_PREFERENCES_FILE = "ui_preferences.json"


def normalize_theme(value: object) -> ThemeMode:
    return "dark" if str(value).lower() == "dark" else "light"


def load_theme_preference(data_dir: str) -> ThemeMode:
    path = os.path.join(data_dir, UI_PREFERENCES_FILE)
    if not os.path.exists(path):
        return "light"
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return normalize_theme(data.get("theme", "light"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return "light"


def save_theme_preference(data_dir: str, mode: ThemeMode) -> None:
    path = os.path.join(data_dir, UI_PREFERENCES_FILE)
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
    os.makedirs(data_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(existing, handle, ensure_ascii=False, indent=2)
