from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

BEIJING_TZ = timezone(timedelta(hours=8))
PRESALE_WINDOW_DAYS = 15


def beijing_now(timestamp=None):
    return datetime.fromtimestamp(timestamp, BEIJING_TZ) if timestamp is not None else datetime.now(BEIJING_TZ)


def validate_travel_date(value: str) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)):
        raise ValueError("出行日期必须使用 YYYY-MM-DD 格式。")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("出行日期不是有效的日历日期。") from exc


def eligible_travel_dates(travel_date: str, date_range: str, today=None):
    today = today or beijing_now().date()
    dates, skipped = [], []
    for value in expand_travel_dates(travel_date, date_range):
        offset = (validate_travel_date(value) - today).days
        if 0 <= offset < PRESALE_WINDOW_DAYS:
            dates.append(value)
        else:
            skipped.append({"date": value, "reason": "已过期" if offset < 0 else "超出可查询窗口"})
    return dates, skipped


def expand_travel_dates(travel_date: str, date_range: str) -> list[str]:
    base = validate_travel_date(str(travel_date))

    radius_by_range = {
        "单日": 0,
        "±1天": 1,
        "±2天": 2,
    }
    radius = radius_by_range.get(str(date_range).strip(), 0)
    return [(base + timedelta(days=offset)).isoformat() for offset in range(-radius, radius + 1)]
