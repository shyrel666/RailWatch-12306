"""Query policy data shared with the renderer and included in runtime builds."""
import json
import re
from importlib.resources import files

QUERY_STRATEGIES = json.loads(files(__package__).joinpath("query_strategies.json").read_text(encoding="utf-8"))
DATE_STRATEGIES = json.loads(files(__package__).joinpath("date_strategies.json").read_text(encoding="utf-8"))
ORDER_POLICIES = json.loads(files(__package__).joinpath("order_policies.json").read_text(encoding="utf-8"))
NOTIFICATION_CHANNEL_TABLE = json.loads(files(__package__).joinpath("notification_channels.json").read_text(encoding="utf-8"))
TRAIN_CODE_TABLE = json.loads(files(__package__).joinpath("train_codes.json").read_text(encoding="utf-8"))
IDLE_POLICIES = json.loads(files(__package__).joinpath("idle_policies.json").read_text(encoding="utf-8"))


def _check_range(policies, key, low, high, types=(int, float)):
    value = policies.get(key) if isinstance(policies, dict) else None
    if type(value) not in types or not low <= value <= high:
        raise ValueError(f"策略参数 {key} 应在 {low}–{high} 之间，实际为 {value!r}")


def validate_order_policies(policies):
    """Packaged policies cannot be changed at runtime; reject bad values at load."""
    _check_range(policies, "people_ready_timeout_seconds", 0, 30)
    _check_range(policies, "people_stable_ms", 100, 2000)
    return policies


def validate_query_strategies(strategies):
    # The mode is chosen per task, so the retry must stay below every mode's floor.
    floor = min(mode["min_interval"] for mode in strategies["modes"].values())
    sale, settle = strategies.get("sale_start"), strategies.get("query_settle")
    _check_range(sale, "presale_retry_seconds", 1, floor)
    _check_range(sale, "presale_retry_limit", 0, 3, (int,))
    _check_range(sale, "presale_retry_window_seconds", 0, 30)
    _check_range(settle, "quiet_ms", 50, 300)
    _check_range(settle, "poll_ms", 10, 100)
    _check_range(settle, "sale_poll_ms", 10, 100)
    _check_range(settle, "resettle_timeout_ms", 0, 2000)
    return strategies


def validate_notification_channels(table):
    """Field names become settings keys and renderer types; reject ambiguous tables at load.

    Flags appear only when true: the renderer derives secret fields from key presence.
    Port and switch fields state their default, which also gives the renderer their value type.
    """
    seen = set()
    for channel, spec in table["channels"].items():
        if not re.fullmatch(r"[a-z][a-z0-9_]*", channel) or not spec.get("label") or not spec.get("fields"):
            raise ValueError(f"通知渠道 {channel!r} 定义无效")
        for name, field in spec["fields"].items():
            kind = field.get("type", "text")
            value_type = {"text": str, "url": str, "port": int, "switch": bool}.get(kind)
            if (not name.startswith(f"{channel}_") or name.endswith(("_enabled", "_configured")) or name in seen
                    or not field.get("label") or value_type is None
                    or any(field.get(flag, True) is not True for flag in ("secret", "required", "allow_newline"))
                    or value_type is not str and (field.get("secret") or field.get("required") or "default" not in field)
                    or field.get("allow_newline") and kind != "text"
                    or type(field.get("default", "")) is not value_type):
                raise ValueError(f"通知字段 {name!r} 定义无效")
            seen.add(name)
    return table


def validate_train_codes(table):
    """Prefixes become a regex character class here and in the renderer; reject anything else at load.

    12306 renumbers in two batches (late November and late December 2026), so the
    old prefixes stay listed beside X, N and V until it no longer shows them.
    """
    prefixes = table.get("prefixes")
    if (not isinstance(prefixes, list) or not prefixes or len(set(prefixes)) != len(prefixes)
            or not all(isinstance(prefix, str) and re.fullmatch(r"[A-Z]", prefix) for prefix in prefixes)):
        raise ValueError(f"车次字头定义无效：{prefixes!r}")
    # One missing result can be a page glitch; a saved number that has changed never comes back.
    _check_range(table, "missing_target_rounds", 2, 20, (int,))
    return table


def validate_idle_policies(policies):
    """Work done while no task runs: a login probe, never a ticket query, and route reminders."""
    _check_range(policies, "login_keep_alive_seconds", 120, 900)
    _check_range(policies, "sale_reminder_lead_minutes", 5, 120, (int,))
    _check_range(policies, "max_sale_reminders", 1, 50, (int,))
    return policies


validate_order_policies(ORDER_POLICIES)
validate_idle_policies(IDLE_POLICIES)
validate_query_strategies(QUERY_STRATEGIES)
validate_notification_channels(NOTIFICATION_CHANNEL_TABLE)
validate_train_codes(TRAIN_CODE_TABLE)

# A train number: a listed prefix and up to five digits, or a bare four- or five-digit number.
TRAIN_CODE_PREFIX = "[" + "".join(TRAIN_CODE_TABLE["prefixes"]) + "]"
TRAIN_CODE_BODY = r"(?:" + TRAIN_CODE_PREFIX + r"\d{1,5}|\d{4,5})"


def priority_defaults(priority=None):
    priority = priority or QUERY_STRATEGIES["default_priority"]
    mode = QUERY_STRATEGIES["priorities"][priority]["request_mode"]
    policy = QUERY_STRATEGIES["modes"][mode]
    return {"query_priority": priority, "request_mode": mode,
            "interval": policy["interval"], "query_timeout": policy["query_timeout"],
            "smart_rate": True, "keep_alive": True}


def rate_bounds(config):
    policy = QUERY_STRATEGIES["modes"].get(config.get("request_mode"), QUERY_STRATEGIES["modes"]["legacy"])
    return policy["min_interval"], policy["max_interval"]


def normalize_strategy(trip, raw):
    """Preserve saved tuning; presets are applied only by an explicit UI action."""
    mode = raw.get("request_mode")
    if mode is None and any(key in raw for key in ("interval", "query_timeout", "smart_rate")):
        mode = "legacy"
    mode = mode or trip.get("request_mode", "conservative")
    if mode not in QUERY_STRATEGIES["modes"]:
        raise ValueError("不支持的请求模式")
    priority = raw.get("query_priority")
    if priority is None:
        priority = "speed" if mode == "fast" or (mode == "legacy" and trip["smart_rate"] and trip["interval"] <= 4) else "reliability"
    if priority not in QUERY_STRATEGIES["priorities"]:
        raise ValueError("不支持的查询优先级")
    trip.update(query_priority=priority, request_mode=mode)
