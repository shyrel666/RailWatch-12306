"""Last-seen stations and times of listed trains, to match a saved number to its 2026 renumbering.

12306's 2026 renumbering keeps each service's stations and times and changes only the number,
so a saved train that stops appearing can be matched to a listed train with the same timetable.
Suggestions only: nothing here changes which trains a task matches or books.
"""
from __future__ import annotations

import json
import os
import threading
import time

from railwatch_preferences import atomic_write_json

FILE_NAME = "train_schedules.json"
MAX_ENTRIES = 600
FIELDS = ("from_station", "to_station", "departure_time", "arrival_time", "arrival_day_offset")


def _schedule(row) -> dict | None:
    """A row's timetable, or None unless every field was read: a partial match proves nothing."""
    if not isinstance(row, dict) or not isinstance(row.get("train"), str) or not row["train"]:
        return None
    values = {field: row.get(field) for field in FIELDS}
    if not all(isinstance(values[field], str) and values[field] for field in FIELDS[:4]):
        return None
    offset = values["arrival_day_offset"]
    if type(offset) is not int or not 0 <= offset <= 3:
        return None
    return values


class TrainSchedules:
    """In-memory between flushes, so recording a query round never writes to disk."""

    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, FILE_NAME)
        self._lock = threading.Lock()
        self._flush_lock = threading.Lock()
        self._items: dict[tuple, dict] = {}
        self._dirty = False
        # Read once here: the first monitor round must not wait on a file.
        try:
            with open(self.path, encoding="utf-8") as handle:
                payload = json.load(handle)
            entries = payload.get("items", []) if isinstance(payload, dict) and payload.get("schema_version") == 1 else []
        except (OSError, ValueError, TypeError):
            entries = []
        for entry in entries if isinstance(entries, list) else []:
            schedule = _schedule(entry)
            if schedule is None or not isinstance(entry.get("seen_date"), str) or type(entry.get("seen_at")) not in (int, float):
                continue
            self._items[(entry["train"], schedule["from_station"], schedule["to_station"])] = {
                "train": entry["train"], **schedule, "seen_date": entry["seen_date"], "seen_at": entry["seen_at"]}

    def observe(self, rows, travel_date: str) -> None:
        """Remember the timetable of every fully read row of one complete result."""
        now = time.time()
        with self._lock:
            for row in rows or []:
                schedule = _schedule(row)
                if schedule is None:
                    continue
                key = (row["train"], schedule["from_station"], schedule["to_station"])
                previous = self._items.get(key)
                entry = {"train": row["train"], **schedule, "seen_date": travel_date, "seen_at": now}
                self._items[key] = entry
                if previous is None or any(previous[field] != entry[field] for field in (*FIELDS, "seen_date")):
                    self._dirty = True

    def candidates(self, train: str, rows) -> list:
        """Other listed trains whose stations and times equal those last seen for ``train``."""
        with self._lock:
            known = [entry for (code, _, _), entry in self._items.items() if code == train]
        found = {}
        for entry in known:
            for row in rows or []:
                schedule = _schedule(row)
                if (schedule is not None and row["train"] != train and row["train"] not in found
                        and all(schedule[field] == entry[field] for field in FIELDS)):
                    found[row["train"]] = {"train": row["train"], **schedule, "seen_date": entry["seen_date"]}
        return list(found.values())

    def flush(self) -> None:
        # The write runs outside the item lock, so a monitor round never waits on fsync.
        # Entries are replaced, never mutated, so the snapshot stays consistent.
        with self._flush_lock:
            with self._lock:
                if not self._dirty:
                    return
                newest = sorted(self._items.values(), key=lambda entry: entry["seen_at"], reverse=True)[:MAX_ENTRIES]
                self._items = {(entry["train"], entry["from_station"], entry["to_station"]): entry for entry in newest}
                self._dirty = False
            try:
                atomic_write_json(self.path, {"schema_version": 1, "items": newest})
            except BaseException:
                with self._lock:
                    self._dirty = True
                raise
