"""Read-only station sale schedules from the source used by the official sale page."""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.request

from railwatch_dates import validate_travel_date

SOURCE_URL = "https://kyfw.12306.cn/index/view/infos/sale_time.html"
DATA_URL = "https://kyfw.12306.cn/otn/index12306/queryAllCacheSaleTime"
CACHE_SECONDS = 3600
RETRY_SECONDS = 60


def parse_schedules(payload: object) -> list[dict]:
    if not isinstance(payload, dict) or payload.get("status") is not True or not isinstance(payload.get("data"), list):
        raise ValueError("官方起售数据格式异常")
    schedules = []
    for item in payload["data"]:
        if not isinstance(item, dict):
            continue
        name, code, sale = (item.get(key) for key in ("station_name", "station_telecode", "sale_time"))
        start, stop = item.get("start_date"), item.get("stop_date")
        if not (isinstance(name, str) and 1 <= len(name.strip()) <= 40
                and isinstance(code, str) and re.fullmatch(r"[A-Z]{3}", code)
                and isinstance(sale, str) and re.fullmatch(r"(?:[01]\d|2[0-3])[0-5]\d", sale)):
            continue
        try:
            if not all(isinstance(value, str) and re.fullmatch(r"\d{8}", value) for value in (start, stop)):
                continue
            dates = [f"{value[:4]}-{value[4:6]}-{value[6:]}" for value in (start, stop)]
            if validate_travel_date(dates[0]) >= validate_travel_date(dates[1]):
                continue
        except ValueError:
            continue
        record = {"station_name": name.strip(), "station_code": code, "sale_time": f"{sale[:2]}:{sale[2:]}",
                  "start_date": dates[0], "stop_date": dates[1]}
        if record not in schedules:
            schedules.append(record)
    if not schedules:
        raise ValueError("官方起售数据为空或无法识别")
    return schedules


def fetch_schedules() -> list[dict]:
    request = urllib.request.Request(DATA_URL, data=b"", headers={
        "Referer": SOURCE_URL, "User-Agent": "RailWatch/1.0", "Cache-Control": "no-cache",
    })
    with urllib.request.urlopen(request, timeout=10) as response:
        data = response.read(2_000_001)
    if len(data) > 2_000_000:
        raise ValueError("官方起售数据超出大小限制")
    return parse_schedules(json.loads(data.decode("utf-8")))


class SaleTimeService:
    """Shared in-memory cache; no browser, login, task or config side effects."""

    def __init__(self, fetch=fetch_schedules, clock=time.time):
        self._fetch, self._clock = fetch, clock
        self._lock = threading.Lock()
        self._schedules: list[dict] = []
        self._checked_at = None
        self._attempted_at = None
        self._error = None

    def query(self, station: object, force: object = False) -> dict:
        if not isinstance(station, str) or not 1 <= len(station.strip()) <= 40:
            raise ValueError("请输入完整出发站名称。")
        if not isinstance(force, bool):
            raise ValueError("刷新参数无效。")
        station = station.strip()
        with self._lock:
            now = self._clock()
            fresh = self._checked_at is not None and 0 <= now - self._checked_at < CACHE_SECONDS
            retry = self._attempted_at is None or now - self._attempted_at >= RETRY_SECONDS or now < self._attempted_at
            if (force or not fresh) and retry:
                self._attempted_at = now
                try:
                    self._schedules = self._fetch()
                    self._checked_at = self._clock()
                    self._error = None
                except (OSError, ValueError):
                    self._error = "无法更新官方起售时间，请稍后刷新或前往官方核对。"
            now = self._clock()
            fresh = self._checked_at is not None and 0 <= now - self._checked_at < CACHE_SECONDS
            # Exact name only: a city or similarly named station cannot supply this station's time.
            matches = [dict(item) for item in self._schedules if item["station_name"] == station]
            status = "available" if fresh and matches else "not_found" if fresh else "stale" if matches else "unavailable"
            return {"station": station, "status": status, "schedules": matches,
                    "checked_at": self._checked_at,
                    "expires_at": self._checked_at + CACHE_SECONDS if self._checked_at is not None else None,
                    "retry_at": (self._attempted_at or now) + RETRY_SECONDS,
                    "source_url": SOURCE_URL,
                    "warning": self._error or ("未找到该站的起售时间，请核对完整站名。" if status == "not_found" else None)}


sale_time_service = SaleTimeService()


def official_sale_at(station, travel_date, now, window_days=15, *, info=None):
    """saleDay's exact station, open boundaries and freshness rules."""
    import datetime as dt
    from railwatch_dates import BEIJING_TZ
    travel = validate_travel_date(travel_date)
    days = window_days if type(window_days) is int and 0 < window_days <= 366 else 15
    release = (travel - dt.timedelta(days=days - 1)).isoformat()
    timestamp = now.timestamp() if isinstance(now, dt.datetime) else float(now)
    info = sale_time_service.query(station) if info is None else info
    if (info.get("status") != "available" or info.get("checked_at") is None
            or info.get("expires_at") is None
            or not info["checked_at"] <= timestamp < info["expires_at"]):
        return None
    choices = {(item["station_code"], item["sale_time"]) for item in info.get("schedules", [])
               if item["station_name"] == station and item["start_date"] < release < item["stop_date"]
               and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", item["sale_time"])}
    if len(choices) != 1:
        return None
    return dt.datetime.fromisoformat(f"{release}T{next(iter(choices))[1]}:00").replace(tzinfo=BEIJING_TZ)
