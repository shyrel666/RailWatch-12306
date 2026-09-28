"""Parse 12306 query result rows."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException

from railwatch_selectors import QUERY_ROW_SELECTOR, QUERY_TABLE_ID, TABLE_HEADER_SELECTORS
from railwatch_seats import SEAT_CAPABILITIES
from railwatch_config_contract import TRAIN_CODE_BODY

TRAIN_CODE_PATTERN = re.compile(r"^\s*(" + TRAIN_CODE_BODY + r")(?=\s|$)", re.IGNORECASE)
DISPLAY_SEATS = tuple(seat.name for seat in SEAT_CAPABILITIES if seat.query)

BATCH_ROWS_JS = r"""
const table = document.getElementById('queryLeftTable');
if (!table) return [];
const seatPrefixes = arguments[0];
const headers = [...(table.closest('table')?.querySelectorAll('thead th') || [])]
  .map(h => h.innerText.replace(/\s+/g,'').trim());
return [...table.querySelectorAll('tr[id^="ticket_"]')].filter(row => row.getClientRects().length).map(row => {
  const field = row.querySelector('a.number,.train-number,.train-code') || row.cells[0];
  const train = (field?.innerText || '').trim().split(/\s+/)[0];
  const seats = {};
  const seat_indices = {};
  for (const [name,prefix] of Object.entries(seatPrefixes)) {
    const index = headers.indexOf(name);
    if (index >= 0) seat_indices[name] = index;
    const cell = (prefix && row.querySelector('td[id^="'+prefix+'_"]')) || (index >= 0 ? row.cells[index] : null);
    seats[name] = cell ? cell.innerText.trim().replace(/\n/g,'') : null;
  }
  const texts = selector => [...row.querySelectorAll(selector)].filter(el => el.getClientRects().length)
    .map(el => el.innerText.trim());
  const stations = texts('.cdz strong');
  const times = texts('.cds strong').filter(value => /^\d{2}:\d{2}$/.test(value));
  const arrival = texts('.ls span');
  const dayLabels = {'当日到达':0, '次日到达':1, '第三日到达':2, '第四日到达':3};
  const days = arrival.filter(value => Object.hasOwn(dayLabels, value));
  return {element:row, train, raw:row.innerText.trim(), seats, seat_indices,
    from_station:stations.length === 2 ? stations[0] : null,
    to_station:stations.length === 2 ? stations[1] : null,
    departure_time:times.length === 2 ? times[0] : null,
    arrival_time:times.length === 2 ? times[1] : null,
    arrival_day_offset:days.length === 1 ? dayLabels[days[0]] : null};
});
"""


class RowParser:
  def __init__(self, driver, seat_type_get_prefix):
    self.driver = driver
    self.seat_type_get_prefix = seat_type_get_prefix

  @staticmethod
  def extract_train_code(text: str) -> Optional[str]:
    match = TRAIN_CODE_PATTERN.search(text or "")
    return match.group(1).upper() if match else None

  def snapshot_rows(self, seats=None) -> List[dict]:
    seats = DISPLAY_SEATS if seats is None else seats
    values = self.driver.execute_script(BATCH_ROWS_JS, {seat: self.seat_type_get_prefix(seat) for seat in seats})
    if not isinstance(values, list):
      raise RuntimeError("无法读取查询结果快照")
    result = []
    for value in values:
      train = self.extract_train_code(value.get("train", ""))
      if train:
        result.append({**value, "train": train})
    return result

  @staticmethod
  def display_rows(snapshot) -> List[dict]:
    return [{"train": row["train"], "raw": row["raw"]} for row in snapshot]

  @staticmethod
  def seat_availability(value) -> dict:
    raw = value.strip() if isinstance(value, str) else ""
    state, count = "unknown", None
    if raw == "有":
      state = "available"
    elif re.fullmatch(r"[0-9]{1,8}", raw):
      count = int(raw)
      state = "available" if count else "unavailable"
    elif raw == "无":
      state, count = "unavailable", 0
    elif raw == "候补":
      state = "alternate"
    elif raw == "不适用":
      state = "not_applicable"
    # '--', '*', absent cells and unrecognized text provide no inventory proof.
    return {"status": state, "count": count, "raw": raw}

  @classmethod
  def structured_rows(cls, snapshot, travel_date) -> List[dict]:
    """Serialize the same DOM snapshot without WebElements or guessed inventory."""
    rows = []
    for row in snapshot:
      result = {"train": row["train"], "date": travel_date, "raw": row.get("raw", ""),
                "seats": {name: cls.seat_availability(value) for name, value in row.get("seats", {}).items()}}
      for field in ("from_station", "to_station", "departure_time", "arrival_time", "arrival_day_offset"):
        result[field] = row.get(field)
      rows.append(result)
    return rows

  @staticmethod
  def is_seat_available(value: Optional[str]) -> bool:
    if value is None:
      return False
    value = value.strip()
    if value in ("", "--", "无", "0", "*"):
      return False
    if value == "有":
      return True
    if re.fullmatch(r"\d+", value):
      try:
        return int(value) > 0
      except ValueError:
        return False
    return False

  def parse_rows(self) -> List[dict]:
    return self.structured_rows(self.snapshot_rows(), "")

  @staticmethod
  def selected_route(row):
    """Bind the booking to the actual stations displayed on the selected row."""
    try:
      stations = [element.text.strip() for element in row.find_elements(By.CSS_SELECTOR, '.cdz strong')
                  if element.is_displayed()]
      if len(stations) == 2 and all(stations):
        return tuple(stations)
    except Exception:
      pass
    return None

  def get_seat_col_index(self, seat_keyword: str) -> Optional[int]:
    for selector in TABLE_HEADER_SELECTORS:
      try:
        headers = self.driver.find_elements(By.CSS_SELECTOR, selector)
        if headers:
          for index, header in enumerate(headers):
            header_text = header.text.strip().replace("\n", "")
            if header_text == seat_keyword or seat_keyword in header_text:
              return index
          break
      except (NoSuchElementException, StaleElementReferenceException):
        continue
    return None

  def get_seat_value_by_prefix(self, row_element, seat_keyword: str) -> Optional[str]:
    prefix = self.seat_type_get_prefix(seat_keyword)
    if not prefix:
      return None
    try:
      cell = row_element.find_element(By.CSS_SELECTOR, f"td[id^='{prefix}_']")
      return cell.text.strip().replace("\n", "")
    except NoSuchElementException:
      return None
    except StaleElementReferenceException:
      raise
    except Exception:
      return None

  def get_seat_value(self, row, seat_keyword: str, col_index: Optional[int]) -> Optional[str]:
    value = self.get_seat_value_by_prefix(row, seat_keyword)
    if value is not None:
      return value
    if col_index is not None:
      try:
        cells = row.find_elements(By.CSS_SELECTOR, "td")
        if col_index < len(cells):
          return cells[col_index].text.strip().replace("\n", "")
      except NoSuchElementException:
        pass
    return None

  def find_button(self, row, selectors: tuple[str, ...]) -> Optional[Any]:
    for selector in selectors:
      try:
        if selector.startswith(".//"):
          button = row.find_element(By.XPATH, selector)
        else:
          button = row.find_element(By.CSS_SELECTOR, selector)
        if button and button.is_displayed() and button.is_enabled() and button.get_attribute("aria-disabled") != "true":
          return button
      except NoSuchElementException:
        continue
    return None
