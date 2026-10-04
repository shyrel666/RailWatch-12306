"""Date ordering and bounded cash-first scans; never retain browser elements."""
from datetime import date

from railwatch_policies import DATE_STRATEGIES


class DatePlan:
    def __init__(self, preferred, strategy="round_robin", budget=30):
        self.preferred = preferred
        if strategy not in DATE_STRATEGIES["strategies"]:
            raise ValueError("不支持的多日期策略")
        self.strategy, self.budget = strategy, float(budget)
        self.dates = ()
        self.reset()

    def reset(self):
        self.started = None
        self.first_loop = None
        self.checked = set()
        self.offers = set()
        self.recheck = None

    def sync(self, dates):
        ordered = list(dates)
        if self.strategy != "round_robin":
            preferred = date.fromisoformat(self.preferred)
            ordered.sort(key=lambda value: (abs((date.fromisoformat(value) - preferred).days), value))
        if tuple(ordered) != self.dates:
            self.dates = tuple(ordered)
            self.reset()

    def select(self, loop, now):
        if not self.dates:
            raise ValueError("没有可查询的出行日期")
        if self.first_loop is None:
            self.first_loop = loop
        if self.strategy == "inventory_first":
            if self.started is None:
                self.started = now
            if self.offers and now - self.started >= self.budget:
                self.recheck = next(value for value in self.dates if value in self.offers)
            if self.recheck:
                return self.recheck
        index = loop - 1 if self.strategy == "round_robin" else loop - self.first_loop
        return self.dates[index % len(self.dates)]

    def allow_alternate(self, travel_date, available, now):
        """Call only after a fresh, valid query and a complete cash inventory scan.

        A remembered date merely selects the next query. Only a newly read
        candidate from that query can authorize entering the waitlist form.
        """
        if self.strategy != "inventory_first" or len(self.dates) <= 1:
            return available
        if self.recheck == travel_date:
            self.reset()
            return available
        self.checked.add(travel_date)
        self.offers.discard(travel_date)
        if available:
            self.offers.add(travel_date)
        if self.started is None:
            self.started = now
        if set(self.dates) <= self.checked or now - self.started >= self.budget:
            chosen = next((value for value in self.dates if value in self.offers), None)
            if chosen == travel_date and available:
                self.reset()
                return True  # The selected date is already the current fresh query.
            if chosen:
                self.recheck = chosen
            elif set(self.dates) <= self.checked:
                self.reset()
        return False
