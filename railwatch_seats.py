"""Query visibility and transaction support verified against browser fixtures."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SeatCapability:
    name: str
    prefix: str | None
    query: bool = True
    regular: bool = False
    alternate: bool = False


# A prefix only identifies a query cell. Transaction flags require a browser
# fixture proving option selection and readback before the submit click.
SEAT_CAPABILITIES = (
    SeatCapability("二等座", "ZE", regular=True, alternate=True),
    SeatCapability("一等座", "ZY", regular=True),
    SeatCapability("商务座", "SWZ"),
    SeatCapability("特等座", "TZ"),
    SeatCapability("无座", "WZ"),
    SeatCapability("硬座", "YZ", regular=True),
    SeatCapability("软座", "RZ", regular=True),
    SeatCapability("硬卧", "YW", regular=True),
    SeatCapability("软卧", "RW", regular=True),
    SeatCapability("高级软卧", "GR"),
    SeatCapability("动卧", "SRRB"),
)
CAPABILITIES_BY_NAME = {seat.name: seat for seat in SEAT_CAPABILITIES}


def seat_prefix(name: str) -> str | None:
    seat = CAPABILITIES_BY_NAME.get(name)
    return seat.prefix if seat else None


def public_seat_capabilities() -> list[dict]:
    return [{"name": seat.name, "query": seat.query, "regular": seat.regular,
             "alternate": seat.alternate} for seat in SEAT_CAPABILITIES]


def validate_automation_seats(value: str, *, regular: bool, alternate: bool) -> list[str]:
    import re

    seats = list(dict.fromkeys(item for item in re.split(r"[,，、;；\s]+", str(value or "").strip()) if item))
    if not seats:
        raise ValueError("自动交易必须选择明确席别，不能使用“不限”。")
    for name in seats:
        seat = CAPABILITIES_BY_NAME.get(name)
        if seat is None or regular and not seat.regular or alternate and not seat.alternate:
            raise ValueError(f"席别 {name} 尚未通过当前自动交易路径验证，请关闭自动化并在官方页面处理。")
    return seats
