"""Auto-submit flow for regular ticket booking."""

from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional, Tuple

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import (
  ElementClickInterceptedException,
  NoSuchElementException,
  StaleElementReferenceException,
  TimeoutException,
)

from railwatch_config_contract import parse_passenger_names, redact_sensitive_text
from railwatch_selectors import CONFIRM_PURCHASE_ID, PASSENGER_CHECKBOX_SELECTORS, PASSENGER_LABEL_SELECTORS, SUBMIT_ORDER_ID


class SubmitFlow:
  def __init__(
    self,
    driver,
    cfg: dict,
    log_callback: Optional[Callable[[str], None]] = None,
    popup_handler: Optional[Callable[[], bool]] = None,
    seat_preference_handler: Optional[Callable[[str], None]] = None,
  ):
    self.driver = driver
    self.cfg = cfg
    self.log = log_callback or (lambda _message: None)
    self.handle_popups = popup_handler or (lambda: False)
    self.select_seat_preference = seat_preference_handler or (lambda _preference: None)

  @staticmethod
  def _parse_passenger_selection_result(result, target_passengers: List[str]) -> Tuple[int, List[str]]:
    if isinstance(result, dict):
      selected_count = int(result.get("selectedCount") or 0)
      missing_names = [str(name) for name in result.get("missingNames") or []]
      return selected_count, missing_names
    try:
      selected_count = int(result or 0)
    except (TypeError, ValueError):
      selected_count = 0
    if target_passengers:
      return selected_count, list(target_passengers)
    return selected_count, []

  @staticmethod
  def _passenger_selection_sufficient(
    selected_count: int,
    missing_names: List[str],
    target_passengers: List[str],
    target_count: int,
  ) -> bool:
    if missing_names:
      return False
    required_count = len(target_passengers) if target_passengers else max(1, int(target_count or 1))
    return selected_count >= required_count

  def _wait_clickable(self, by, locator, timeout: float = 8.0):
    return WebDriverWait(self.driver, timeout).until(EC.element_to_be_clickable((by, locator)))

  def try_auto_submit(self, book_btn, seat_type_name: str = "", intent=None):
    from railwatch_order_page import OrderPage
    from railwatch_orders import OrderIntent
    intent = intent or OrderIntent.from_config(self.cfg, self.cfg.get("train_code", ""), seat_type_name, "regular")
    page = getattr(self, "order_page", None) or OrderPage(self.driver)
    return page.regular(book_btn, intent)

  def _select_seat_type(self, seat_type_name: str) -> None:
    self.log(f"💺 尝试选择席别: {seat_type_name}")
    js_select_seat_type = """
    const targetSeatName = arguments[0];
    const selects = document.querySelectorAll('select[id^="seatType_"]');
    let count = 0;
    for (let s of selects) {
      if (s.offsetParent === null) continue;
      for (let opt of s.options) {
        if (opt.text.includes(targetSeatName)) {
          s.value = opt.value;
          s.dispatchEvent(new Event('change', {bubbles: true}));
          count++;
          break;
        }
      }
    }
    return count;
    """
    try:
      num_selected = self.driver.execute_script(js_select_seat_type, seat_type_name)
      if num_selected > 0:
        self.log(f"✅ 已成功为 {num_selected} 位乘车人选择席别: {seat_type_name}")
    except Exception as exc:
      self.log(f"⚠️ 选择席别过程出错: {exc}")

  def _select_passengers_with_selenium(self, target_passengers: List[str], target_count: int) -> Tuple[int, List[str]]:
    if target_passengers:
      labels = []
      for selector in PASSENGER_LABEL_SELECTORS:
        labels = self.driver.find_elements(By.CSS_SELECTOR, selector)
        if labels:
          break
      selected_names = []
      for target_name in target_passengers:
        matched_label = None
        for label in labels:
          label_text = (getattr(label, "text", "") or "").strip()
          if label_text == target_name or target_name in label_text:
            matched_label = label
            break
        if not matched_label:
          continue
        checkbox = self._find_checkbox_for_label(matched_label)
        if checkbox and not checkbox.is_selected():
          checkbox.click()
        if checkbox and checkbox.is_selected():
          selected_names.append(target_name)
      missing_names = [name for name in target_passengers if name not in selected_names]
      return len(selected_names), missing_names

    checkboxes = []
    for selector in PASSENGER_CHECKBOX_SELECTORS:
      checkboxes = self.driver.find_elements(By.CSS_SELECTOR, selector)
      if checkboxes:
        break
    selected_count = 0
    for checkbox in checkboxes[:target_count]:
      if checkbox.is_displayed() and not checkbox.is_selected():
        checkbox.click()
      if checkbox.is_selected():
        selected_count += 1
    return selected_count, []

  def _find_checkbox_for_label(self, label):
    try:
      return label.find_element(By.CSS_SELECTOR, 'input[type="checkbox"]')
    except Exception:
      pass
    try:
      for_id = label.get_attribute("for")
      if for_id:
        return self.driver.find_element(By.ID, for_id)
    except Exception:
      pass
    return None
