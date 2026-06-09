"""Auto-submit flow for waitlist (候补) orders."""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import NoSuchElementException, TimeoutException

from railwatch_selectors import (
  ALTERNATE_BUTTON_SELECTORS,
  CANDIDATE_PASSENGER_SELECTORS,
  CONFIRM_ALTERNATE_SELECTORS,
  SUBMIT_ALTERNATE_SELECTORS,
)
from railwatch_config_contract import parse_passenger_names
from railwatch_submit_flow import SubmitFlow
from railwatch_verification import VerificationDetector


class AlternateFlow:
  def __init__(
    self,
    driver,
    cfg: dict,
    verification: VerificationDetector,
    log_callback: Optional[Callable[[str], None]] = None,
    human_action_callback: Optional[Callable[[dict], None]] = None,
    find_alternate_button: Optional[Callable] = None,
  ):
    self.driver = driver
    self.cfg = cfg
    self.verification = verification
    self.log = log_callback or (lambda _message: None)
    self.human_action = human_action_callback
    self.find_alternate_button = find_alternate_button

  def _signal_human_action(self, train_code: str, message: str) -> None:
    self.log(f"🙋 需要人工操作：{message}")
    if self.human_action:
      try:
        self.human_action({"train_code": train_code, "title": "需要人工操作", "message": message})
      except Exception:
        pass

  def _click_confirm_alternate(self) -> None:
    for selector in CONFIRM_ALTERNATE_SELECTORS:
      try:
        if selector.startswith(".//"):
          button = self.driver.find_element(By.XPATH, selector)
        else:
          button = self.driver.find_element(By.CSS_SELECTOR, selector)
        if button and button.is_displayed():
          button.click()
          self.log("✅ 已自动确认候补对话框")
          return
      except NoSuchElementException:
        continue
      except Exception:
        continue

  def _find_button(self, selectors: tuple[str, ...]):
    for selector in selectors:
      try:
        if selector.startswith(".//"):
          button = self.driver.find_element(By.XPATH, selector)
        else:
          button = self.driver.find_element(By.CSS_SELECTOR, selector)
        if button and button.is_displayed():
          return button
      except NoSuchElementException:
        continue
    return None

  def try_alternate_order(self, row, train_code: str, seat_name: str) -> str:
    try:
      self.log(f"🔄 尝试为 {train_code} {seat_name} 提交候补订单...")
      alternate_btn = self.find_alternate_button(row) if self.find_alternate_button else self._find_button(ALTERNATE_BUTTON_SELECTORS)
      if not alternate_btn:
        self.log("↻ 候补按钮暂不可点，继续监控")
        return "retry"

      try:
        alternate_btn.click()
      except Exception:
        self.driver.execute_script("arguments[0].click();", alternate_btn)

      try:
        WebDriverWait(self.driver, 10).until(
          EC.presence_of_element_located(
            (By.CSS_SELECTOR, ".candidate-list, #candidate_passenger_id, #normal_passenger_id")
          )
        )
        self.log("✅ 已进入候补订单页面")
      except TimeoutException:
        if self.verification.verification_present():
          self._signal_human_action(train_code, "候补需要人工核验（人脸/验证码/滑块），请在浏览器中完成。")
          return "human"
        self.log("⚠️ 等待候补页面超时")
        return "failed"

      if self.verification.verification_present():
        self._signal_human_action(train_code, "候补需要人工核验（人脸/验证码/滑块），请在浏览器中完成。")
        return "human"

      target_passengers = parse_passenger_names(self.cfg.get("passengers", ""))
      try:
        target_count = max(1, int(self.cfg.get("passenger_count", 1) or 1))
      except (TypeError, ValueError):
        target_count = 1

      passengers_selected = self._select_candidate_passengers(target_passengers, target_count)
      if not SubmitFlow._passenger_selection_sufficient(passengers_selected, [], target_passengers, target_count):
        self.log("❌ 未能勾选足够的候补乘车人，已停止候补提交")
        return "failed"

      self.log(f"✅ 已为候补选择 {passengers_selected} 位乘车人")
      self._set_deadline_if_configured()

      submit_btn = self._find_button(SUBMIT_ALTERNATE_SELECTORS)
      if not submit_btn:
        if self.verification.verification_present():
          self._signal_human_action(train_code, "候补需要人工核验，请在浏览器中完成。")
          return "human"
        self.log("⚠️ 未找到候补提交按钮，请手动提交")
        return "failed"

      try:
        submit_btn.click()
      except Exception:
        self.driver.execute_script("arguments[0].click();", submit_btn)
      self.log("✅ 已点击提交候补")

      if self.verification.verification_present():
        self._signal_human_action(train_code, "候补提交需要人工核验，请在浏览器中完成。")
        return "human"

      self._click_confirm_alternate()

      if self.verification.verification_present():
        self._signal_human_action(train_code, "候补确认需要人工核验，请在浏览器中完成。")
        return "human"

      if self.verification.alternate_success_present():
        self.log("✅ 候补订单已提交")
        return "success"

      self._signal_human_action(
        train_code,
        "候补已尝试提交，但未能自动确认结果，请在浏览器中核对候补订单状态。",
      )
      return "human"
    except Exception as exc:
      self.log(f"⚠️ 候补订单处理异常: {exc}")
      return "failed"

  def _select_candidate_passengers(self, target_passengers: List[str], target_count: int) -> int:
    js_select_candidates = """
    const targetNames = arguments[0];
    const targetCount = arguments[1];
    let selectedCount = 0;
    const selectors = [
      '#candidate_passenger_id label',
      '.candidate-list label',
      'input[name^="candidate_passenger"]'
    ];
    let labels = [];
    for (let selector of selectors) {
      labels = document.querySelectorAll(selector);
      if (labels.length > 0) break;
    }
    for (let label of labels) {
      if (selectedCount >= targetCount && targetCount > 0) break;
      let name = label.innerText ? label.innerText.trim() : '';
      let checkbox = label.querySelector('input[type="checkbox"]');
      if (!checkbox && label.tagName === 'INPUT') checkbox = label;
      if (!checkbox) continue;
      let shouldSelect = targetNames.length === 0
        || targetNames.includes(name)
        || targetNames.some(n => name.includes(n));
      if (shouldSelect && !checkbox.checked) {
        checkbox.click();
        selectedCount++;
      } else if (shouldSelect && checkbox.checked) {
        selectedCount++;
      }
    }
    return selectedCount;
    """
    passengers_selected = self.driver.execute_script(js_select_candidates, target_passengers, target_count)
    try:
      return int(passengers_selected or 0)
    except (TypeError, ValueError):
      return 0

  def _set_deadline_if_configured(self) -> None:
    alternate_deadline = self.cfg.get("alternate_deadline", "")
    if not alternate_deadline:
      return
    js_set_deadline = """
    const deadline = arguments[0];
    const timeInputs = document.querySelectorAll('input[type="time"], input.deadline-time, #deadline_time');
    for (let input of timeInputs) {
      if (input.offsetParent !== null) {
        input.value = deadline;
        input.dispatchEvent(new Event('change', {bubbles: true}));
        return true;
      }
    }
    return false;
    """
    try:
      if self.driver.execute_script(js_set_deadline, alternate_deadline):
        self.log(f"✅ 已设置候补截止时间: {alternate_deadline}")
    except Exception:
      pass
