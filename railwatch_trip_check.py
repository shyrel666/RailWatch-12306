"""Before automated buying starts: does the account already hold this trip?

The journal only knows orders this tool submitted. A ticket bought in the 12306
App or on the website is invisible to it, and outside the Spring Festival period
the official waitlist still fulfils a ticket that conflicts with one already held.

Read-only: official orders are read in a temporary tab and nothing on them is
clicked. A missed conflict is acceptable, a wrong stop is not. Only an
identified, active order of a configured passenger on a task date counts, and
only for a target train or one of the task's exact station pairs.
"""
from __future__ import annotations

import re
import time

from railwatch_config_contract import parse_codes, parse_passenger_names
from railwatch_order_page import form_token, normalized_date, train_token
from railwatch_task import TaskCancelled, browser_tab_lifecycle

ORDER_URL = "https://kyfw.12306.cn/otn/view/train_order.html"
UNFINISHED_TAB, UNTRAVELED_TAB = "未完成订单", "未出行订单"
# States seen on real cards (2026-11-10). An unknown state is not evidence of a held ticket.
ACTIVE_STATE = re.compile("已支付|待支付|等待支付")

TAB_STATE_JS = r"""
const visible = e => !!(e && e.getClientRects().length && getComputedStyle(e).visibility === 'visible');
const text = e => (e?.innerText || '').replace(/\s+/g, ' ').trim();
return {active: [...document.querySelectorAll('.panel-tab .tab-hd-list li.active')].map(text),
        loading: [...document.querySelectorAll('.loading,.loading-box,#J-loading')].filter(visible).length};
"""


def _route_in(text, route):
    start, end = route
    return (form_token(text, start, "站") and form_token(text, end, "站")
            and text.index(start) < text.index(end))


def trip_conflicts(orders, config, dates, known_routes=()):
    """Trips among ``orders`` that the task would buy again, without passenger or order identity.

    ``orders`` are OrderPage snapshot records; ``dates`` the task's travel dates;
    ``known_routes`` the station pairs its target trains were last seen with.
    """
    passengers = set(parse_passenger_names(config.get("passengers", "")))
    trains = parse_codes(config.get("train_code", ""), upper=True)
    configured = (str(config.get("from_station_cn", "")).strip(), str(config.get("to_station_cn", "")).strip())
    routes = [route for route in dict.fromkeys([configured, *(tuple(route) for route in known_routes)])
              if len(route) == 2 and all(route)]
    dates = set(dates)
    found = []
    for record in orders or []:
        if not isinstance(record, dict) or not record.get("order_id") or record.get("kind") != "regular":
            continue
        # Tickets of one order in different states cannot be told apart per passenger.
        if record.get("state_conflict") or not (record.get("payment") or ACTIVE_STATE.search(str(record.get("state", "")))):
            continue
        if not passengers & set(record.get("passengers", [])):
            continue
        text = str(record.get("text", ""))
        # The booking date sits in the card header, which the snapshot keeps out of the text.
        travel = {normalized_date(match[0]) for match in re.finditer(r"\d{4}[-年/]\d{1,2}[-月/]\d{1,2}", text)}
        if len(travel) != 1 or not travel <= dates:
            continue
        codes = {str(code).upper() for code in record.get("train_codes", [])}
        train = next((code for code in trains if code in codes or train_token(text, code)), "")
        route = next((route for route in routes if _route_in(text, route)), None)
        if not train and route is None:
            continue
        trip = {"train": train or (next(iter(codes)) if len(codes) == 1 else ""), "date": next(iter(travel)),
                "from_station": route[0] if route else "", "to_station": route[1] if route else ""}
        if trip not in found:
            found.append(trip)
    return found


def describe_trip(trip):
    route = f"{trip['from_station']} → {trip['to_station']}" if trip.get("from_station") else ""
    return " ".join(part for part in (trip.get("train", ""), trip.get("date", ""), route) if part)


def read_existing_orders(page, *, url=ORDER_URL, budget=10.0, settle=3.0, timing=None):
    """Identified records on the untraveled and unfinished tabs, or None when they cannot be read.

    Runs in a temporary tab and restores the original one. The official order
    page alone took about five to eight seconds to load in the live runs of
    2026-11-08 and 2026-11-10, so the paid tickets on the untraveled tab are read
    first and are what the result depends on. The unfinished tab is only sampled
    as it stands on arrival: after a refused purchase it shows a failure panel
    with neither an order nor the official "none" statement, and waiting there
    used up the whole budget of the first live check.

    ``settle`` bounds the wait for the untraveled list. An empty untraveled tab
    shows no statement at all, so only its being active, idle and still empty
    after that wait means "none". ``timing`` receives how long each part took
    and, for None, why; numbers and fixed words only.
    """
    driver = page.driver
    timing = {} if timing is None else timing
    started = time.monotonic()
    deadline = started + budget

    def spent(since):
        return round((time.monotonic() - since) * 1000)

    def unreadable(reason):
        timing["reason"] = reason
        return None

    def identified(snap):
        return [record for record in snap.get("orders", []) if record.get("order_id")]

    def open_untraveled():
        """The untraveled tab control, with the unfinished orders visible while waiting for it."""
        until = min(deadline, time.monotonic() + settle)
        unfinished = []
        while not page.stop():
            snap = page.snapshot()
            if not snap:
                return unreadable("not_official_page"), unfinished  # Login redirect or error page.
            state = driver.execute_script(TAB_STATE_JS)
            if isinstance(state, dict) and state.get("active") == [UNFINISHED_TAB]:
                unfinished = identified(snap)
            tab = page._recovery_tab(UNTRAVELED_TAB, url)
            if tab is not None:
                return tab, unfinished
            left = until - time.monotonic()
            if left <= 0:
                return unreadable("budget" if until >= deadline else "tab_control_missing"), unfinished
            page.wait(min(page.poll_interval, left))
        raise TaskCancelled()

    def untraveled_records():
        until = time.monotonic() + settle
        # A wait cut short by the overall budget has not shown the list to be empty.
        full = until <= deadline
        until = min(until, deadline)
        seen = None
        while not page.stop():
            snap = page.snapshot()
            if not snap:
                return unreadable("not_official_page")
            state = driver.execute_script(TAB_STATE_JS)
            active = isinstance(state, dict) and state.get("active") == [UNTRAVELED_TAB]
            records = identified(snap) if active else []
            # Cards may be added one after another: accept a list once two reads agree.
            if records and seen is not None and len(records) == seen:
                return records
            seen = len(records) if records else None
            left = until - time.monotonic()
            if left <= 0:
                if records:
                    return records
                if not active:
                    return unreadable("tab_not_active")
                if state.get("loading"):
                    return unreadable("loading")
                return [] if full else unreadable("budget")
            page.wait(min(page.poll_interval, left))
        raise TaskCancelled()

    if page.stop():
        raise TaskCancelled()
    original = driver.current_window_handle
    page_timeout = driver.timeouts.page_load
    temporary = None
    try:
        # Capture our handle before cancellation can unwind the operation.
        with browser_tab_lifecycle(driver):
            driver.switch_to.new_window("tab")
            temporary = driver.current_window_handle
        if page.stop():
            raise TaskCancelled()
        driver.set_page_load_timeout(budget)
        try:
            driver.get(url)
        finally:
            timing["navigation_ms"] = spent(started)
        opened = time.monotonic()
        tab, unfinished = open_untraveled()
        timing["tabs_ms"] = spent(opened)
        if tab is None:
            return None
        tab.click()
        clicked = time.monotonic()
        untraveled = untraveled_records()
        timing["untraveled_ms"] = spent(clicked)
        return None if untraveled is None else unfinished + untraveled
    finally:
        with browser_tab_lifecycle(driver):
            try:
                driver.set_page_load_timeout(page_timeout)
            except Exception:
                pass  # The caller applies its own timeout again after the check.
            if temporary and temporary != original and temporary in driver.window_handles:
                driver.switch_to.window(temporary)
                driver.close()
            if original in driver.window_handles:
                driver.switch_to.window(original)
