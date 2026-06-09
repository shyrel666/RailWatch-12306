"""Parse 12306 query result rows."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException

from railwatch_selectors import QUERY_ROW_SELECTOR, QUERY_TABLE_ID, TABLE_HEADER_SELECTORS

TRAIN_CODE_PATTERN = re.compile(r"\b([GDKTZCS]\d{1,4})\b")


class RowParser:
  def __init__(self, driver, seat_type_get_prefix):
    self.driver = driver
    self.seat_type_get_prefix = seat_type_get_prefix

  @staticmethod
  def extract_train_code(text: str) -> Optional[str]:
    match = TRAIN_CODE_PATTERN.search(text or "")
    return match.group(1) if match else None

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
    try:
      table = self.driver.find_element(By.ID, QUERY_TABLE_ID)
      rows = table.find_elements(By.CSS_SELECTOR, QUERY_ROW_SELECTOR)
      results = []
      for row in rows:
        text = row.text.strip()
        if not text:
          continue
        train_code = self.extract_train_code(text)
        if not train_code:
          continue
        results.append({"train": train_code, "raw": text})
      return results
    except (NoSuchElementException, StaleElementReferenceException):
      return []

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
        if button and button.is_displayed():
          return button
      except NoSuchElementException:
        continue
    return None
