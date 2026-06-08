from __future__ import annotations

from datetime import date, timedelta


def expand_travel_dates(travel_date: str, date_range: str) -> list[str]:
    try:
        base = date.fromisoformat(str(travel_date))
    except ValueError:
        return [str(travel_date)]

    radius_by_range = {
        "单日": 0,
        "±1天": 1,
        "±2天": 2,
    }
    radius = radius_by_range.get(str(date_range).strip(), 0)
    return [(base + timedelta(days=offset)).isoformat() for offset in range(-radius, radius + 1)]
