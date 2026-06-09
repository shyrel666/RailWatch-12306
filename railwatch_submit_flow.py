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

from railwatch_config_contract import redact_sensitive_text
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

  def try_auto_submit(self, book_btn, seat_type_name: str = "") -> None:
    try:
      self.log("🤖 尝试自动点击【预订】...")
      try:
        book_btn.click()
      except Exception:
        self.driver.execute_script("arguments[0].click();", book_btn)

      try:
        self._wait_clickable(By.ID, "normal_passenger_id", timeout=10)
        self.log("✅ 已进入乘车人选择页面")
      except TimeoutException:
        self.log("⚠️ 等待乘车人页面超时，尝试继续...")

      target_passengers = [p.strip() for p in self.cfg.get("passengers", "").split(",") if p.strip()]
      target_count = self.cfg.get("passenger_count", 1)
      if target_passengers:
        redacted = ", ".join(redact_sensitive_text(name) for name in target_passengers)
        self.log(f"👥 正在尝试勾选：{redacted}")
      else:
        self.log(f"👥 未指定姓名，将尝试勾选前 {target_count} 位乘车人")

      js_select_passengers = """
      const targetNames = arguments[0];
      const targetCount = arguments[1];
      const requiredCount = targetNames.length > 0 ? targetNames.length : targetCount;
      let selectedCount = 0;
      let selectedNames = [];
      const selectors = [
        '#normal_passenger_id label',
        '.passenger-list label',
        'label[for^="normalPassenger"]',
        '.normal_passenger label',
        'input[name="normalPassenger_"]'
      ];
      let labels = [];
      for (let selector of selectors) {
        labels = document.querySelectorAll(selector);
        if (labels.length > 0) break;
      }
      if (labels.length === 0) return {selectedCount: 0, selectedNames: [], missingNames: targetNames};
      for (let label of labels) {
        if (selectedCount >= requiredCount && requiredCount > 0) break;
        let name = label.innerText ? label.innerText.trim() : '';
        let checkbox = label.querySelector('input[type="checkbox"]');
        if (!checkbox && label.tagName === 'INPUT') checkbox = label;
        if (!checkbox) continue;
        let shouldSelect = targetNames.length === 0 || targetNames.includes(name) || targetNames.some(n => name.includes(n));
        if (shouldSelect && !checkbox.checked) {
          checkbox.click();
          selectedCount++;
          selectedNames.push(name);
        } else if (shouldSelect && checkbox.checked) {
          selectedCount++;
          selectedNames.push(name);
        }
      }
      const missingNames = targetNames.filter(target => !selectedNames.some(name => name === target || name.includes(target)));
      return {selectedCount, selectedNames, missingNames};
      """
      selection_result = self.driver.execute_script(js_select_passengers, target_passengers, target_count)
      passengers_selected, missing_names = self._parse_passenger_selection_result(selection_result, target_passengers)

      if not self._passenger_selection_sufficient(passengers_selected, missing_names, target_passengers, target_count):
        passengers_selected, missing_names = self._select_passengers_with_selenium(target_passengers, target_count)

      if not self._passenger_selection_sufficient(passengers_selected, missing_names, target_passengers, target_count):
        if missing_names:
          self.log(f"❌ 未能匹配到指定乘车人，已停止自动提交")
        else:
          self.log("❌ 未能勾选足够的乘车人，已停止自动提交")
        return

      self.log(f"✅ 成功勾选了 {passengers_selected} 位乘车人")
      self.handle_popups()

      if seat_type_name:
        self._select_seat_type(seat_type_name)

      seat_prefer = self.cfg.get("seat_prefer", "无偏好")
      if seat_prefer != "无偏好":
        self.select_seat_preference(seat_prefer)

      self.handle_popups()

      try:
        submit_btn = self._wait_clickable(By.ID, SUBMIT_ORDER_ID, timeout=10)
        submit_btn.click()
        self.log("✅ 已点击【提交订单】")
      except TimeoutException:
        self.log("⚠️ 未找到提交订单按钮，请手动操作")
        return

      self.handle_popups()

      confirm_clicked = False
      for attempt in range(5):
        try:
          confirm_btn = self._wait_clickable(By.ID, CONFIRM_PURCHASE_ID, timeout=8)
          confirm_btn.click()
          confirm_clicked = True
          self.log(f"✅ 已点击【确认购买】(第 {attempt + 1} 次)")
          try:
            if not self.driver.find_element(By.ID, CONFIRM_PURCHASE_ID).is_displayed():
              break
          except (NoSuchElementException, StaleElementReferenceException):
            break
        except TimeoutException:
          if not confirm_clicked:
            self.log("⚠️ 未找到确认购买按钮")
          break
        except ElementClickInterceptedException:
          self.log("⚠️ 确认按钮被遮挡，重试中...")
          time.sleep(0.3)
        except Exception as exc:
          self.log(f"⚠️ 点击确认购买异常: {exc}")
          break

      if confirm_clicked:
        self.log("🎉 订单已提交！请尽快完成支付！")
      else:
        self.log("⚠️ 自动确认失败，请手动确认订单")
    except Exception as exc:
      self.log(f"⚠️ 自动提交过程异常：{exc}")

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
