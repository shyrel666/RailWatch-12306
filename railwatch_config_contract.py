"""Unified configuration contract shared by Python runtime and Electron renderer."""

from __future__ import annotations

import datetime as dt
import re
from copy import deepcopy
from typing import Any, Dict, List, Mapping, MutableMapping, Optional

CONFIG_VERSION = 1

DEFAULT_BURST_WINDOW_SECONDS = 45.0
DEFAULT_PREWARM_LEAD_SECONDS = 120.0
TRIP_FIELD_KEYS = (
    "from_station_cn",
    "to_station_cn",
    "date",
    "train_code",
    "seat_keyword",
    "interval",
    "query_timeout",
    "auto_submit",
    "seat_prefer",
    "passenger_count",
    "prepare_time",
    "keep_alive",
    "passengers",
    "auto_alternate",
    "alternate_deadline",
    "date_range",
    "smart_rate",
    "timer_enabled",
    "target_time",
    "burst_window_seconds",
    "prewarm_lead_seconds",
)

# Route A (default): compliance-first strong alerts; no captcha bypass.
# Route B (opt-in, not implemented): would require explicit user consent for auto-captcha.
AUTOMATION_ROUTE = "compliance_alerts"


def default_config(
    today: Optional[dt.date] = None,
    now: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    selected_today = today or dt.date.today()
    selected_now = now or dt.datetime.now()
    target_time = (selected_now + dt.timedelta(seconds=120)).strftime("%H:%M:%S")
    trip = {
        "from_station_cn": "北京",
        "to_station_cn": "上海",
        "date": (selected_today + dt.timedelta(days=1)).isoformat(),
        "train_code": "",
        "seat_keyword": "",
        "interval": 5,
        "query_timeout": 40,
        "auto_submit": False,
        "seat_prefer": "无偏好",
        "passenger_count": 1,
        "prepare_time": 2,
        "keep_alive": True,
        "passengers": "",
        "auto_alternate": False,
        "alternate_deadline": "18:00",
        "date_range": "±1天",
        "smart_rate": True,
        "timer_enabled": False,
        "target_time": target_time,
        "burst_window_seconds": DEFAULT_BURST_WINDOW_SECONDS,
        "prewarm_lead_seconds": DEFAULT_PREWARM_LEAD_SECONDS,
    }
    return {
        "config_version": CONFIG_VERSION,
        "automation_route": AUTOMATION_ROUTE,
        "query_jobs": [trip],
        **trip,
    }


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "y"}
    return bool(value)


def _to_int(value: object, fallback: int, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _to_float(
    value: object,
    fallback: float,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = fallback
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _normalize_trip(raw_trip: Mapping[str, Any], defaults: Mapping[str, Any]) -> Dict[str, Any]:
    trip = {**defaults, **dict(raw_trip or {})}
    trip["from_station_cn"] = str(trip.get("from_station_cn", "")).strip()
    trip["to_station_cn"] = str(trip.get("to_station_cn", "")).strip()
    trip["date"] = str(trip.get("date", "")).strip()
    trip["train_code"] = str(trip.get("train_code", "")).strip().upper()
    trip["seat_keyword"] = str(trip.get("seat_keyword", "")).strip()
    trip["seat_prefer"] = str(trip.get("seat_prefer", "无偏好")).strip() or "无偏好"
    trip["passengers"] = str(trip.get("passengers", "")).strip()
    trip["alternate_deadline"] = str(trip.get("alternate_deadline", "18:00")).strip() or "18:00"
    trip["target_time"] = str(trip.get("target_time", "00:00:00")).strip() or "00:00:00"
    trip["date_range"] = str(trip.get("date_range", "±1天")).strip() or "±1天"
    trip["interval"] = _to_float(trip.get("interval"), 5.0, minimum=1.0, maximum=60.0)
    trip["query_timeout"] = _to_int(trip.get("query_timeout"), 40, minimum=5, maximum=120)
    trip["passenger_count"] = _to_int(trip.get("passenger_count"), 1, minimum=1, maximum=20)
    trip["prepare_time"] = _to_int(trip.get("prepare_time"), 2, minimum=0, maximum=30)
    trip["burst_window_seconds"] = _to_float(
        trip.get("burst_window_seconds"),
        DEFAULT_BURST_WINDOW_SECONDS,
        minimum=5.0,
        maximum=180.0,
    )
    trip["prewarm_lead_seconds"] = _to_float(
        trip.get("prewarm_lead_seconds"),
        DEFAULT_PREWARM_LEAD_SECONDS,
        minimum=0.0,
        maximum=600.0,
    )
    trip["auto_submit"] = _to_bool(trip.get("auto_submit"))
    trip["auto_alternate"] = _to_bool(trip.get("auto_alternate"))
    trip["keep_alive"] = _to_bool(trip.get("keep_alive"))
    trip["smart_rate"] = _to_bool(trip.get("smart_rate"))
    trip["timer_enabled"] = _to_bool(trip.get("timer_enabled"))
    return trip


def normalize_query_jobs(raw_config: Mapping[str, Any], defaults: Mapping[str, Any]) -> List[Dict[str, Any]]:
    jobs = raw_config.get("query_jobs")
    top_level_trip = {key: raw_config[key] for key in TRIP_FIELD_KEYS if key in raw_config}
    if isinstance(jobs, list) and jobs:
        normalized = []
        for index, job in enumerate(jobs):
            if not isinstance(job, Mapping):
                continue
            job_payload = {**dict(job), **top_level_trip} if index == 0 else job
            normalized.append(_normalize_trip(job_payload, defaults))
        if normalized:
            return normalized
    return [_normalize_trip(raw_config, defaults)]


def validate_config(raw_config: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    base = default_config()
    incoming = dict(raw_config or {})
    base.update(incoming)
    jobs = normalize_query_jobs(incoming, base)
    primary = jobs[0]
    for key, value in primary.items():
        base[key] = value
    base["query_jobs"] = jobs
    base["config_version"] = CONFIG_VERSION
    base["automation_route"] = str(incoming.get("automation_route") or AUTOMATION_ROUTE)

    if not base["from_station_cn"]:
        raise ValueError("出发站为必填项。")
    if not base["to_station_cn"]:
        raise ValueError("到达站为必填项。")
    if not base["date"]:
        raise ValueError("出行日期为必填项。")
    return base


def merge_notification_settings(raw: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    defaults = {
        "desktop_urgent": True,
        "sound_loop": True,
        "server_chan_enabled": False,
        "server_chan_key": "",
        "email_enabled": False,
        "email_smtp_host": "",
        "email_smtp_port": 465,
        "email_user": "",
        "email_password": "",
        "email_to": "",
        "wecom_webhook_enabled": False,
        "wecom_webhook_url": "",
    }
    if not raw:
        return defaults
    merged = {**defaults, **dict(raw)}
    merged["desktop_urgent"] = _to_bool(merged.get("desktop_urgent"))
    merged["sound_loop"] = _to_bool(merged.get("sound_loop"))
    merged["server_chan_enabled"] = _to_bool(merged.get("server_chan_enabled"))
    merged["email_enabled"] = _to_bool(merged.get("email_enabled"))
    merged["wecom_webhook_enabled"] = _to_bool(merged.get("wecom_webhook_enabled"))
    return merged


def parse_passenger_names(value: str) -> List[str]:
    return [name.strip() for name in re.split(r"[,，、]+", str(value or "")) if name.strip()]


def redact_sensitive_text(value: str, keep_start: int = 2, keep_end: int = 1) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) < keep_start + keep_end:
        return "*" * len(text)
    return f"{text[:keep_start]}***{text[-keep_end:]}"


def redact_proxy_url(proxy_url: str) -> str:
    text = str(proxy_url or "").strip()
    if not text:
        return ""
    if "@" in text:
        scheme, rest = text.split("://", 1) if "://" in text else ("", text)
        creds, host = rest.rsplit("@", 1)
        if ":" in creds:
            user = creds.split(":", 1)[0]
            return f"{scheme}://{redact_sensitive_text(user)}@{host}" if scheme else f"{redact_sensitive_text(user)}@{host}"
        return f"{scheme}://***@{host}" if scheme else f"***@{host}"
    return text


def config_for_persistence(config: Mapping[str, Any]) -> Dict[str, Any]:
    validated = validate_config(config)
    payload = deepcopy(validated)
    payload.pop("query_jobs", None)
    return payload
