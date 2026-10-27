"""Sale-start reminders for a route and travel date. A reminder never starts a task or opens a page."""

from __future__ import annotations

import json
import os
import threading
import uuid

from railwatch_dates import validate_travel_date
from railwatch_preferences import atomic_write_json

FILE_NAME = "sale_reminders.json"


def _station(value: object) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 40:
        raise ValueError("提醒的站名无效。")
    return value.strip()


def _entry(item) -> dict | None:
    try:
        entry = {"id": item["id"], "from_station": _station(item["from_station"]), "to_station": _station(item["to_station"]),
                 "date": validate_travel_date(item["date"]).isoformat(), "sale_at": item["sale_at"],
                 "notified_at": item.get("notified_at")}
    except (KeyError, TypeError, ValueError):
        return None
    if (not isinstance(entry["id"], str) or not 1 <= len(entry["id"]) <= 64 or type(entry["sale_at"]) not in (int, float)
            or entry["notified_at"] is not None and type(entry["notified_at"]) not in (int, float)):
        return None
    return entry


class SaleReminders:
    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, FILE_NAME)
        self._lock = threading.Lock()

    def _read(self) -> list:
        try:
            with open(self.path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError, TypeError):
            return []
        items = payload.get("items") if isinstance(payload, dict) and payload.get("schema_version") == 1 else None
        return [entry for entry in map(_entry, items if isinstance(items, list) else []) if entry is not None]

    def _write(self, items: list) -> None:
        atomic_write_json(self.path, {"schema_version": 1, "items": sorted(items, key=lambda entry: entry["sale_at"])})

    def items(self, now: float) -> list:
        """Reminders whose sale has not started; past ones are dropped on the next change."""
        with self._lock:
            return sorted((entry for entry in self._read() if entry["sale_at"] > now), key=lambda entry: entry["sale_at"])

    def add(self, from_station, to_station, travel_date, sale_at: float, now: float, limit: int) -> list:
        origin, destination = _station(from_station), _station(to_station)
        if origin == destination:
            raise ValueError("出发站和到达站不能相同。")
        date = validate_travel_date(travel_date).isoformat()
        if sale_at <= now:
            raise ValueError("该日期已经开售，无需提醒。")
        with self._lock:
            items = [entry for entry in self._read() if entry["sale_at"] > now]
            # One reminder per route and date: adding it again refreshes the official sale time.
            items = [entry for entry in items if (entry["from_station"], entry["to_station"], entry["date"]) != (origin, destination, date)]
            if len(items) >= limit:
                raise ValueError(f"最多设置 {limit} 个起售提醒，请先删除不需要的提醒。")
            items.append({"id": uuid.uuid4().hex, "from_station": origin, "to_station": destination, "date": date,
                          "sale_at": sale_at, "notified_at": None})
            self._write(items)
        return self.items(now)

    def remove(self, reminder_id, now: float) -> list:
        if not isinstance(reminder_id, str):
            raise ValueError("提醒标识无效。")
        with self._lock:
            items = self._read()
            remaining = [entry for entry in items if entry["id"] != reminder_id and entry["sale_at"] > now]
            if len(remaining) != len(items):
                self._write(remaining)
        return self.items(now)

    def due(self, now: float, lead_seconds: float) -> list:
        """Not yet sent and inside the lead window. A sale that already started is never announced late."""
        return [entry for entry in self.items(now) if entry["notified_at"] is None and now >= entry["sale_at"] - lead_seconds]

    def update(self, reminder_id: str, now: float, **changes) -> None:
        with self._lock:
            items = self._read()
            self._write([{**entry, **changes} if entry["id"] == reminder_id else entry
                         for entry in items if entry["sale_at"] > now or entry["id"] == reminder_id])
