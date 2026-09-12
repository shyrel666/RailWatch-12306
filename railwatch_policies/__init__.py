"""Query policy data shared with the renderer and included in runtime builds."""
import json
from importlib.resources import files

QUERY_STRATEGIES = json.loads(files(__package__).joinpath("query_strategies.json").read_text(encoding="utf-8"))


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
