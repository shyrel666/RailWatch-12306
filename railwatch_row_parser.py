"""Parse 12306 query result rows."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException

from railwatch_selectors import QUERY_ROW_SELECTOR, QUERY_TABLE_ID, TABLE_HEADER_SELECTORS

TRAIN_CODE_PATTERN = re.compile(r"^\s*([GDCZTKYSL]\d{1,5}|\d{4,5})(?=\s|$)", re.IGNORECASE)

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
  return {element:row, train, raw:row.innerText.trim(), seats, seat_indices};
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

  def snapshot_rows(self, seats=()) -> List[dict]:
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
    return self.display_rows(self.snapshot_rows())

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
      except (NoSuchElementException, StaleElementReferenceException):
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
