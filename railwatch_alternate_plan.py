"""Explicit, serializable waitlist choices; no browser elements or order secrets."""
from dataclasses import dataclass
from datetime import date
import re

from railwatch_dates import expand_travel_dates
from railwatch_policies import ORDER_POLICIES


@dataclass(frozen=True)
class AlternateChoice:
    train_code: str
    date: str
    from_station: str
    to_station: str
    seat: str

    def __post_init__(self):
        if not all(isinstance(value, str) and value.strip() == value and value
                   for value in (self.train_code, self.date, self.from_station, self.to_station, self.seat)):
            raise ValueError("候补组合字段不完整")
        date.fromisoformat(self.date)
        if not re.fullmatch(r"(?:[GDCZTKYSL]\d{1,5}|\d{4,5})", self.train_code):
            raise ValueError("候补车次无效")
        if self.from_station == self.to_station:
            raise ValueError("候补出发站与到达站不能相同")

    @classmethod
    def from_intent(cls, intent):
        return cls(intent.train_code, intent.date, intent.from_station, intent.to_station, intent.seat)

    @classmethod
    def from_detail(cls, value):
        from railwatch_order_page import normalized_date
        return cls(value["train"], normalized_date(value["date"]), value["from"], value["to"], value["seat"])


class AlternatePlan:
    def __init__(self, intent, config):
        self.primary = AlternateChoice.from_intent(intent)
        split = lambda value: list(dict.fromkeys(re.split(r"[,，、;；\s]+", value.strip())))
        self.trains = split(config.get("train_code", intent.train_code))
        self.seats = split(config.get("seat_keyword", intent.seat))
        self.limit = int(config.get("alternate_max_combinations", ORDER_POLICIES["alternate_max_combinations"]))
        if not 1 <= self.limit <= ORDER_POLICIES["max_combinations"]:
            raise ValueError("候补组合上限无效")
        dates = config.get("_alternate_dates")
        if dates is None:
            dates = expand_travel_dates(config.get("date", intent.date), config.get("date_range", "单日"))
        ordered = [intent.date, *dates]
        self.dates = list(dict.fromkeys(ordered))[:ORDER_POLICIES["max_dates"]]
        if not self.allows(self.primary):
            raise ValueError("首个候补组合不在已授权范围内")

    def allows(self, choice):
        return (choice.date in self.dates and choice.train_code in self.trains and choice.seat in self.seats
                and (choice.from_station, choice.to_station) == (self.primary.from_station, self.primary.to_station))

    def rank(self, choice):
        return (choice != self.primary, self.dates.index(choice.date), self.trains.index(choice.train_code),
                self.seats.index(choice.seat))

    def validate(self, choices):
        return (0 < len(choices) <= self.limit and choices[0] == self.primary
                and len(set(choices)) == len(choices) and all(self.allows(choice) for choice in choices))
