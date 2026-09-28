"""Small, route-scoped UI choices; never an execution authorization."""

from __future__ import annotations

import json
import os

from railwatch_preferences import PREFERENCES_LOCK, atomic_write_json
from railwatch_config_contract import TRAIN_CODE_VALUE_PATTERN

FILE_NAME = "trip_choices.json"
TRAIN_CODE = TRAIN_CODE_VALUE_PATTERN
MAX_ROUTES = 8
MAX_FAVORITES = 20


def _route(from_station: object, to_station: object) -> dict:
    if not all(isinstance(value, str) and 1 <= len(value.strip()) <= 40
               for value in (from_station, to_station)):
        raise ValueError("路线站名无效。")
    origin, destination = from_station.strip(), to_station.strip()
    if origin == destination:
        raise ValueError("出发站和到达站不能相同。")
    return {"from_station": origin, "to_station": destination}


def _read(data_dir: str) -> dict:
    try:
        with open(os.path.join(data_dir, FILE_NAME), encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict) and payload.get("schema_version") == 1:
            return payload
    except (OSError, ValueError, TypeError):
        pass
    return {"schema_version": 1, "recent_routes": [], "favorites": []}


def load_trip_choices(data_dir: str) -> dict:
    with PREFERENCES_LOCK:
        data = _read(data_dir)
        routes = []
        for item in data.get("recent_routes", []):
            try:
                if isinstance(item, dict):
                    route = _route(item.get("from_station"), item.get("to_station"))
                    if route not in routes:
                        routes.append(route)
            except ValueError:
                continue
        favorites = []
        for item in data.get("favorites", []):
            try:
                if not isinstance(item, dict):
                    continue
                route = _route(item.get("from_station"), item.get("to_station"))
                codes = item.get("trains")
                if not isinstance(codes, list):
                    continue
                valid = [code.upper() for code in codes if isinstance(code, str) and TRAIN_CODE.fullmatch(code)]
                favorites.append({**route, "trains": list(dict.fromkeys(valid))[:MAX_FAVORITES]})
            except ValueError:
                continue
        return {"recent_routes": routes[:MAX_ROUTES], "favorites": favorites[:MAX_ROUTES]}


def remember_route(data_dir: str, from_station: object, to_station: object) -> dict:
    route = _route(from_station, to_station)
    with PREFERENCES_LOCK:
        current = load_trip_choices(data_dir)
        routes = [route, *[item for item in current["recent_routes"] if item != route]][:MAX_ROUTES]
        data = {"schema_version": 1, "recent_routes": routes, "favorites": current["favorites"]}
        atomic_write_json(os.path.join(data_dir, FILE_NAME), data)
        return load_trip_choices(data_dir)


def save_train_favorites(data_dir: str, from_station: object, to_station: object, trains: object) -> dict:
    route = _route(from_station, to_station)
    if not isinstance(trains, list) or len(trains) > MAX_FAVORITES or any(
        not isinstance(code, str) or not TRAIN_CODE.fullmatch(code) for code in trains
    ):
        raise ValueError("收藏车次无效或超过上限。")
    unique = list(dict.fromkeys(code.upper() for code in trains))
    with PREFERENCES_LOCK:
        current = load_trip_choices(data_dir)
        favorites = [item for item in current["favorites"] if
                     (item["from_station"], item["to_station"]) !=
                     (route["from_station"], route["to_station"])]
        if unique:
            favorites.insert(0, {**route, "trains": unique})
        data = {"schema_version": 1, "recent_routes": current["recent_routes"],
                "favorites": favorites[:MAX_ROUTES]}
        atomic_write_json(os.path.join(data_dir, FILE_NAME), data)
        return load_trip_choices(data_dir)
