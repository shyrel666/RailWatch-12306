"""Query policy data shared with the renderer and included in runtime builds."""
import json
from importlib.resources import files

QUERY_STRATEGIES = json.loads(files(__package__).joinpath("query_strategies.json").read_text(encoding="utf-8"))
DATE_STRATEGIES = json.loads(files(__package__).joinpath("date_strategies.json").read_text(encoding="utf-8"))
ORDER_POLICIES = json.loads(files(__package__).joinpath("order_policies.json").read_text(encoding="utf-8"))


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


validate_order_policies(ORDER_POLICIES)
validate_query_strategies(QUERY_STRATEGIES)


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
