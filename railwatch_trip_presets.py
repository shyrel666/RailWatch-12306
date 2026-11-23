"""Local trip presets and backups limited to trip and route fields."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
import unicodedata
import uuid

from railwatch_config_contract import TRIP_DRAFT_VERSION, TRIP_FIELD_KEYS, default_config, validate_trip_draft
from railwatch_preferences import PREFERENCES_LOCK, atomic_write_json
from railwatch_trip_choices import (
    FILE_NAME as TRIP_CHOICES_FILE,
    MAX_FAVORITES,
    MAX_ROUTES,
    load_trip_choices,
    normalize_favorite_trains,
    normalize_trip_route,
)

FILE_NAME = "trip_presets.json"
SCHEMA_VERSION = 1
MAX_PRESETS = 20
PRESET_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
PUBLIC_TRIP_FIELDS = tuple(key for key in TRIP_FIELD_KEYS if key not in ("passengers", "passenger_selections"))


def _preset_name(value: object) -> str:
    if (not isinstance(value, str) or not 1 <= len(value.strip()) <= 40
            or any(unicodedata.category(char) in ("Cc", "Cs") for char in value)):
        raise ValueError("行程方案名称须为 1 至 40 个字符，且不能包含控制字符。")
    return value.strip()


def _preset_id(value: object) -> str:
    if not isinstance(value, str) or not PRESET_ID.fullmatch(value):
        raise ValueError("行程方案 ID 无效。")
    return value


def _trip_config(config: object, *, imported: bool = False) -> dict:
    if not isinstance(config, dict):
        raise ValueError("行程方案配置必须为对象。")
    keys = PUBLIC_TRIP_FIELDS if imported else TRIP_FIELD_KEYS
    selected = {key: config[key] for key in keys if key in config}
    if imported:
        selected.update(auto_submit=False, auto_alternate=False)
    draft = validate_trip_draft({"schema_version": TRIP_DRAFT_VERSION, "revision": 0,
                                 "saved_at": 0, "config": selected})
    defaults = default_config()
    return {key: draft["config"].get(key, defaults[key]) for key in TRIP_FIELD_KEYS}


def _preset(item: object, *, imported: bool = False) -> dict:
    if not isinstance(item, dict):
        raise ValueError("行程方案必须为对象。")
    return {"id": _preset_id(item.get("id")), "name": _preset_name(item.get("name")),
            "config": _trip_config(item.get("config"), imported=imported)}


def _read_presets(data_dir: str) -> list[dict]:
    try:
        with open(os.path.join(data_dir, FILE_NAME), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, RecursionError):
        return []
    if (not isinstance(data, dict) or type(data.get("schema_version")) is not int
            or data["schema_version"] != SCHEMA_VERSION or not isinstance(data.get("items"), list)):
        return []
    items = []
    ids, names = set(), set()
    for raw in data["items"]:
        try:
            item = _preset(raw)
        except (ValueError, RecursionError):
            continue
        if item["id"] in ids or item["name"] in names:
            continue
        items.append(item)
        ids.add(item["id"])
        names.add(item["name"])
        if len(items) == MAX_PRESETS:
            break
    return items


def _write_presets(data_dir: str, items: list[dict]) -> None:
    atomic_write_json(os.path.join(data_dir, FILE_NAME), {"schema_version": SCHEMA_VERSION, "items": items})


def load_trip_presets(data_dir: str) -> dict:
    with PREFERENCES_LOCK:
        return {"items": _read_presets(data_dir)}


def save_trip_preset(data_dir: str, name: object, config: object, preset_id: object = None) -> dict:
    name = _preset_name(name)
    config = _trip_config(config)
    with PREFERENCES_LOCK:
        items = _read_presets(data_dir)
        if preset_id is None:
            if len(items) == MAX_PRESETS:
                raise ValueError(f"最多保存 {MAX_PRESETS} 个行程方案。")
            preset_id = uuid.uuid4().hex
            index = len(items)
        else:
            preset_id = _preset_id(preset_id)
            index = next((i for i, item in enumerate(items) if item["id"] == preset_id), None)
            if index is None:
                raise ValueError("行程方案已不存在，请重新加载。")
        if any(item["name"] == name and item["id"] != preset_id for item in items):
            raise ValueError("已有同名行程方案，请换一个名称。")
        items[index:index + 1] = [{"id": preset_id, "name": name, "config": config}]
        _write_presets(data_dir, items)
        return {"saved_id": preset_id, "items": items}


def delete_trip_preset(data_dir: str, preset_id: object) -> dict:
    preset_id = _preset_id(preset_id)
    with PREFERENCES_LOCK:
        current = _read_presets(data_dir)
        items = [item for item in current if item["id"] != preset_id]
        if len(items) != len(current):
            _write_presets(data_dir, items)
        return {"items": items}


def export_sanitized_bundle(data_dir: str) -> dict:
    with PREFERENCES_LOCK:
        presets = [{"id": item["id"], "name": item["name"],
                    "config": {key: item["config"][key] for key in PUBLIC_TRIP_FIELDS}}
                   for item in _read_presets(data_dir)]
        return {"schema_version": SCHEMA_VERSION, "exported_at": time.time(), "presets": presets,
                **load_trip_choices(data_dir)}


def _merged_presets(current: list[dict], incoming: object) -> list[dict]:
    if not isinstance(incoming, list) or len(incoming) > MAX_PRESETS:
        raise ValueError(f"备份中的行程方案须为列表，且最多包含 {MAX_PRESETS} 项。")
    by_name = {item["name"]: item for item in current}
    seen_names = set()
    for raw in incoming:
        item = _preset(raw, imported=True)
        name = item["name"]
        if name in seen_names:
            raise ValueError("备份中包含同名行程方案。")
        seen_names.add(name)
        item["id"] = by_name[name]["id"] if name in by_name else uuid.uuid4().hex
        by_name[name] = item
    if len(by_name) > MAX_PRESETS:
        raise ValueError(f"合并后将超过 {MAX_PRESETS} 个行程方案，请先删除不需要的方案。")
    return list(by_name.values())


def _route_key(route: dict) -> tuple[str, str]:
    return route["from_station"], route["to_station"]


def _merged_choices(current: dict, bundle: dict) -> dict:
    result = {}
    for field in ("favorites", "recent_routes"):
        incoming = bundle.get(field, [])
        if not isinstance(incoming, list) or len(incoming) > MAX_ROUTES:
            raise ValueError(f"备份中的收藏或最近路线须为列表，且每类最多包含 {MAX_ROUTES} 条。")
        if not incoming:
            result[field] = current[field]
            continue
        routes = {_route_key(item): item for item in current[field]}
        for item in incoming:
            if not isinstance(item, dict):
                raise ValueError("备份中的路线必须为对象。")
            route = normalize_trip_route(item.get("from_station"), item.get("to_station"))
            key = _route_key(route)
            if field == "favorites":
                trains = normalize_favorite_trains(item.get("trains"))
                local = routes.get(key, {}).get("trains", [])
                route["trains"] = list(dict.fromkeys([*local, *trains]))[:MAX_FAVORITES]
                if not route["trains"]:
                    continue
            routes[key] = route
        # Keep unrelated local entries when the existing route limits are reached.
        result[field] = list(routes.values())[:MAX_ROUTES]
    return result


def _write_import(data_dir: str, items: list[dict], choices: dict, *, presets_changed: bool, choices_changed: bool) -> None:
    choices_path = os.path.join(data_dir, TRIP_CHOICES_FILE)
    choices_data = {"schema_version": 1, **choices}
    if not choices_changed:
        if presets_changed:
            _write_presets(data_dir, items)
        return
    if not presets_changed:
        atomic_write_json(choices_path, choices_data)
        return

    # Keep a copy of the old route file so a rejected second write can roll back
    # with a rename even when writing to disk is what failed.
    os.makedirs(data_dir, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".trip-import-", dir=data_dir) as rollback_dir:
        backup = os.path.join(rollback_dir, TRIP_CHOICES_FILE)
        try:
            shutil.copy2(choices_path, backup)
        except FileNotFoundError:
            backup = None
        atomic_write_json(choices_path, choices_data)
        try:
            _write_presets(data_dir, items)
        except Exception:
            if backup is None:
                os.unlink(choices_path)
            else:
                os.replace(backup, choices_path)
            raise


def import_sanitized_bundle(data_dir: str, payload: object) -> dict:
    if (not isinstance(payload, dict) or type(payload.get("schema_version")) is not int
            or payload["schema_version"] != SCHEMA_VERSION):
        raise ValueError("行程备份格式或版本无效。")
    with PREFERENCES_LOCK:
        current_items = _read_presets(data_dir)
        current_choices = load_trip_choices(data_dir)
        items = _merged_presets(current_items, payload.get("presets", []))
        choices = _merged_choices(current_choices, payload)
        _write_import(data_dir, items, choices, presets_changed=items != current_items,
                      choices_changed=choices != current_choices)
        return {"items": items, **choices}
