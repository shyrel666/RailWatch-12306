"""Unified configuration contract shared by Python runtime and Electron renderer."""

from __future__ import annotations

import datetime as dt
import math
import re
from railwatch_dates import validate_travel_date, beijing_now
from railwatch_policies import DATE_STRATEGIES, ORDER_POLICIES, normalize_strategy, priority_defaults
from copy import deepcopy
from typing import Any, Dict, List, Mapping, MutableMapping, Optional

CONFIG_VERSION = 2
TRAIN_CODE_BODY = r"(?:[GDCZTKYSL]\d{1,5}|\d{4,5})"
TRAIN_CODE_VALUE_PATTERN = re.compile(TRAIN_CODE_BODY, re.IGNORECASE)
TRIP_DRAFT_VERSION = 1
MAX_SAFE_REVISION = 2 ** 53 - 1

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
    "query_priority",
    "request_mode",
    "auto_submit",
    "seat_prefer",
    "passenger_count",
    "prepare_time",
    "keep_alive",
    "passengers",
    "passenger_selections",
    "auto_alternate",
    "alternate_deadline",
    "alternate_mode",
    "alternate_max_combinations",
    "order_watch_enabled",
    "order_watch_interval_seconds",
    "date_range",
    "date_strategy",
    "date_scan_budget_seconds",
    "smart_rate",
    "timer_enabled",
    "target_time",
    "sale_at",
    "sale_time_source",
    "sale_time_checked_at",
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
    selected_now = now or beijing_now()
    selected_today = today or selected_now.date()
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
        "passenger_selections": [],
        "auto_alternate": False,
        "alternate_deadline": "开车前60分钟",
        **{key: ORDER_POLICIES[key] for key in ("alternate_mode", "alternate_max_combinations",
                                               "order_watch_enabled", "order_watch_interval_seconds")},
        "date_range": "±1天",
        "date_strategy": DATE_STRATEGIES["default"],
        "date_scan_budget_seconds": DATE_STRATEGIES["scan_budget_seconds"],
        "smart_rate": True,
        "timer_enabled": False,
        "target_time": target_time,
        "sale_at": "",
        "sale_time_source": "manual",
        "sale_time_checked_at": "",
        "burst_window_seconds": DEFAULT_BURST_WINDOW_SECONDS,
        "prewarm_lead_seconds": DEFAULT_PREWARM_LEAD_SECONDS,
    }
    trip.update(priority_defaults())
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


def normalize_passenger_selections(selections: object) -> list[dict]:
    if not isinstance(selections, list) or len(selections) > 20:
        raise ValueError("乘客选择记录无效。")
    cleaned_selections = []
    for item in selections:
        if (not isinstance(item, dict) or not isinstance(item.get("name"), str) or
                item.get("ticket_type") not in ("adult", "student", "child", "unknown") or
                not isinstance(item.get("identity_hint", ""), str)):
            raise ValueError("乘客选择记录无效。")
        name = item["name"].strip()
        if not name or len(name) > 40 or len(item.get("identity_hint", "")) > 20:
            raise ValueError("乘客选择记录无效。")
        cleaned_selections.append({"name": name, "ticket_type": item["ticket_type"],
                                   "identity_hint": item.get("identity_hint", "")})
    return cleaned_selections


def _normalize_trip(raw_trip: Mapping[str, Any], defaults: Mapping[str, Any]) -> Dict[str, Any]:
    merged = {**defaults, **dict(raw_trip or {})}
    trip = {key: merged[key] for key in TRIP_FIELD_KEYS if key in merged}
    trip["from_station_cn"] = str(trip.get("from_station_cn", "")).strip()
    trip["to_station_cn"] = str(trip.get("to_station_cn", "")).strip()
    trip["date"] = str(trip.get("date", "")).strip()
    trip["train_code"] = str(trip.get("train_code", "")).strip().upper()
    trip["seat_keyword"] = str(trip.get("seat_keyword", "")).strip()
    trip["seat_prefer"] = str(trip.get("seat_prefer", "无偏好")).strip() or "无偏好"
    trip["passengers"] = str(trip.get("passengers", "")).strip()
    trip["passenger_selections"] = normalize_passenger_selections(trip.get("passenger_selections", []))
    trip["alternate_deadline"] = str(trip.get("alternate_deadline", "开车前60分钟")).strip() or "开车前60分钟"
    trip["target_time"] = str(trip.get("target_time", "00:00:00")).strip() or "00:00:00"
    for key in ("sale_at", "sale_time_source", "sale_time_checked_at"):
        trip[key] = str(trip.get(key, "")).strip()
    if trip["sale_at"]:
        from railwatch_time import resolve_sale_timestamp
        resolve_sale_timestamp(trip)
    trip["date_range"] = str(trip.get("date_range", "±1天")).strip() or "±1天"
    trip["date_strategy"] = str(trip.get("date_strategy", DATE_STRATEGIES["default"]))
    if trip["date_strategy"] not in DATE_STRATEGIES["strategies"]:
        raise ValueError("不支持的多日期策略")
    try:
        budget = float(trip.get("date_scan_budget_seconds", DATE_STRATEGIES["scan_budget_seconds"]))
    except (TypeError, ValueError, OverflowError):
        raise ValueError("跨日期扫描预算须为10至120秒") from None
    if not math.isfinite(budget) or not DATE_STRATEGIES["min_budget_seconds"] <= budget <= DATE_STRATEGIES["max_budget_seconds"]:
        raise ValueError("跨日期扫描预算须为10至120秒")
    trip["date_scan_budget_seconds"] = budget
    trip["alternate_mode"] = str(trip.get("alternate_mode", ORDER_POLICIES["alternate_mode"]))
    if trip["alternate_mode"] not in ("single", "multiple"):
        raise ValueError("候补组合模式无效")
    for key, low, high in (("alternate_max_combinations", 1, ORDER_POLICIES["max_combinations"]),
                           ("order_watch_interval_seconds", ORDER_POLICIES["min_watch_interval_seconds"],
                            ORDER_POLICIES["max_watch_interval_seconds"])):
        value = trip.get(key, ORDER_POLICIES[key])
        if type(value) not in (int, float) or not math.isfinite(value) or int(value) != value or not low <= value <= high:
            raise ValueError(f"{'候补组合上限' if key == 'alternate_max_combinations' else '订单核对间隔'}须为{low}至{high}的整数")
        trip[key] = int(value)
    trip["order_watch_enabled"] = _to_bool(trip.get("order_watch_enabled", ORDER_POLICIES["order_watch_enabled"]))
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
    normalize_strategy(trip, raw_trip)
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
    if base["from_station_cn"] == base["to_station_cn"]:
        raise ValueError("出发站和到达站不能相同。")
    if not base["date"]:
        raise ValueError("出行日期为必填项。")
    validate_travel_date(base["date"])
    return base


def merge_notification_settings(raw: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    events = ("hit", "verification", "payment", "alternate_active", "alternate_fulfilled", "purchase_success")
    channels = ("server_chan", "email", "wecom_webhook")
    defaults = {
        "desktop_urgent": True,
        "sound_loop": True,
        "window_attention": True,
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
        "event_channels": {event: list(channels) for event in events},
    }
    if not raw:
        return defaults
    merged = {**defaults, **dict(raw)}
    merged["desktop_urgent"] = _to_bool(merged.get("desktop_urgent"))
    merged["sound_loop"] = _to_bool(merged.get("sound_loop"))
    merged["window_attention"] = _to_bool(merged.get("window_attention"))
    merged["server_chan_enabled"] = _to_bool(merged.get("server_chan_enabled"))
    merged["email_enabled"] = _to_bool(merged.get("email_enabled"))
    merged["wecom_webhook_enabled"] = _to_bool(merged.get("wecom_webhook_enabled"))
    selected = merged.get("event_channels")
    merged["event_channels"] = {event: list(selected[event]) if isinstance(selected, dict) and
                                 isinstance(selected.get(event), list) else list(channels)
                                 for event in events}
    return merged


def validate_notification_patch(patch: object) -> dict:
    """Validate M3 UI input without changing M0's partial-update semantics."""
    if not isinstance(patch, dict):
        raise ValueError("通知设置必须为对象。")
    bool_fields = {"desktop_urgent", "sound_loop", "window_attention", "server_chan_enabled", "email_enabled", "wecom_webhook_enabled"}
    text_fields = {"server_chan_key", "email_smtp_host", "email_user", "email_password", "email_to", "wecom_webhook_url"}
    known = bool_fields | text_fields | {"email_smtp_port", "event_channels"}
    events = set(merge_notification_settings()["event_channels"])
    channels = {"server_chan", "email", "wecom_webhook"}
    cleaned = {}
    for key, value in patch.items():
        if key.endswith("_configured"):
            continue  # Read-only metadata from older clients.
        if key not in known:
            raise ValueError(f"未知通知设置字段：{key}")
        if key in bool_fields and type(value) is not bool:
            raise ValueError(f"通知开关必须为布尔值：{key}")
        if key in text_fields and not (isinstance(value, str) and len(value) <= 512 or value is None and key in ("server_chan_key", "email_password", "wecom_webhook_url")):
            raise ValueError(f"通知字段无效：{key}")
        if key in ("email_smtp_host", "email_user", "email_to", "server_chan_key") and isinstance(value, str) and any(char in value for char in "\r\n"):
            raise ValueError(f"通知字段包含非法换行：{key}")
        if key == "email_smtp_port" and (type(value) is not int or not 1 <= value <= 65535):
            raise ValueError("SMTP 端口必须在 1 至 65535 之间。")
        if key == "event_channels":
            if not isinstance(value, dict) or set(value) - events:
                raise ValueError("通知事件选择无效。")
            for event, selected in value.items():
                if not isinstance(selected, list) or not all(isinstance(item, str) for item in selected) or len(selected) != len(set(selected)) or set(selected) - channels:
                    raise ValueError(f"通知渠道选择无效：{event}")
        cleaned[key] = value
    return cleaned


def validate_trip_draft(payload: object) -> dict:
    """Validate an incomplete draft without normalizing dates or enabling a task.

    Config schema stays at v2. Draft schema/revisions are independent of the app
    version. Unknown JSON fields are retained for non-destructive round trips.
    """
    def finite_number(value):
        # Bound before math.isfinite: very large JSON integers can overflow the
        # conversion to float and cannot round-trip through JavaScript numbers.
        return (type(value) in (int, float) and
                -MAX_SAFE_REVISION <= value <= MAX_SAFE_REVISION and math.isfinite(value))

    if (not isinstance(payload, dict) or type(payload.get("schema_version")) is not int or
            payload["schema_version"] != TRIP_DRAFT_VERSION):
        raise ValueError("草稿版本不受支持。")
    revision = payload.get("revision")
    if type(revision) is not int or not 0 <= revision <= MAX_SAFE_REVISION:
        raise ValueError("草稿修订号无效。")
    saved_at = payload.get("saved_at")
    if not finite_number(saved_at) or saved_at < 0:
        raise ValueError("草稿保存时间无效。")
    config = payload.get("config")
    if not isinstance(config, dict):
        raise ValueError("草稿配置必须为对象。")
    # Incomplete/expired dates are valid draft values, not executable configs.
    defaults = default_config()
    for key in TRIP_FIELD_KEYS:
        if key not in config:
            continue
        value, default = config[key], defaults[key]
        if isinstance(default, bool):
            valid = isinstance(value, bool)
        elif isinstance(default, (int, float)):
            valid = finite_number(value)
        elif isinstance(default, list):
            valid = isinstance(value, list)
        else:
            valid = isinstance(value, str)
        if not valid:
            raise ValueError(f"草稿字段类型无效：{key}")
    if "config_version" in config and (type(config["config_version"]) is not int or
                                       config["config_version"] != CONFIG_VERSION):
        raise ValueError("草稿配置版本不受支持。")
    if "passenger_selections" in config:
        normalize_passenger_selections(config["passenger_selections"])
    return deepcopy(payload)


def parse_passenger_names(value: str) -> List[str]:
    return [name.strip() for name in re.split(r"[,，、]+", str(value or "")) if name.strip()]


def parse_codes(value: str, *, upper: bool = False) -> List[str]:
    """Train or seat targets, split identically for monitoring and rehearsal."""
    items = (item.strip() for item in re.split(r"[,，、;；\s]+", str(value or "")))
    return list(dict.fromkeys(item.upper() if upper else item for item in items if item))


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


def automation_config_issue(config) -> Optional[str]:
    """Return the same automation admission issue for monitor and rehearsal."""
    if not (config.get("auto_submit") or config.get("auto_alternate")):
        return None
    from railwatch_seats import validate_automation_seats
    names = parse_passenger_names(config.get("passengers", ""))
    try:
        # Keep this order identical to src/lib/automationReadiness.ts; the
        # shared cases in tests/fixtures/automation-readiness-cases.json pin it.
        if not config.get("train_code", "").strip():
            raise ValueError("自动化需要明确的目标车次，请在行程设置中选择车次。")
        if not names:
            raise ValueError("自动化需要乘车人姓名，请在行程设置中添加乘客。")
        if len(names) != len(set(names)):
            raise ValueError("乘车人姓名重复，请在行程设置中删除重复乘客。")
        selections = config.get("passenger_selections", [])
        if any(item["name"] not in names or item["ticket_type"] != "adult" for item in selections):
            raise ValueError("自动交易仅支持已核对为成人的乘客；学生、儿童和未知票种请在官方页面处理。")
        if config.get("auto_alternate") and len(names) > 19:
            raise ValueError("候补单最多支持19名乘车人。")
        validate_automation_seats(config.get("seat_keyword", ""),
                                  regular=bool(config.get("auto_submit")),
                                  alternate=bool(config.get("auto_alternate")))
    except ValueError as exc:
        return str(exc)
    return None
