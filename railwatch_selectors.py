"""Centralized 12306 page selectors for easier maintenance."""

from __future__ import annotations

BOOK_BUTTON_SELECTORS = (
    "a.btn72",
    "a[onclick*='getSelected']",
    ".//a[contains(text(),'预订')]",
)

ALTERNATE_BUTTON_SELECTORS = (
    "a.btn-houbu",
    "a[onclick*='houbu']",
    ".//a[contains(text(),'候补')]",
    "a.btn72.btn-houbu",
)

CONFIRM_ALTERNATE_SELECTORS = (
    "#confirmHB_id",
    "#houbu_qr_id",
    "#sureClick_id",
    "a.btn-confirm-houbu",
    ".//a[contains(text(),'确认')]",
    ".//a[contains(text(),'确定')]",
)

SUBMIT_ALTERNATE_SELECTORS = (
    "#submitHoubu_id",
    "a.btn-submit-houbu",
    ".//a[contains(text(),'提交候补')]",
    "#submit_candidate_id",
)

PASSENGER_LABEL_SELECTORS = (
    "#normal_passenger_id label",
    ".passenger-list label",
    "label[for^='normalPassenger']",
    ".normal_passenger label",
)

PASSENGER_CHECKBOX_SELECTORS = (
    'input[type="checkbox"][name^="normalPassenger"]',
    'input[type="checkbox"][id^="normalPassenger"]',
    "#normal_passenger_id input[type='checkbox']",
    ".passenger-list input[type='checkbox']",
)

CANDIDATE_PASSENGER_SELECTORS = (
    "#candidate_passenger_id label",
    ".candidate-list label",
    "input[name^='candidate_passenger']",
)

TABLE_HEADER_SELECTORS = (
    "#queryLeftTable thead th",
    "table thead th",
    ".t-list thead th",
    "thead th",
)

QUERY_BUTTON_ID = "query_ticket"
QUERY_TABLE_ID = "queryLeftTable"
QUERY_ROW_SELECTOR = "tr[id^='ticket_']"
SUBMIT_ORDER_ID = "submitOrder_id"
CONFIRM_PURCHASE_ID = "qr_submit_id"
