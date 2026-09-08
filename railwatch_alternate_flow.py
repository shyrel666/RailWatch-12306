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

  def try_alternate_order(self, row, train_code: str, seat_name: str, intent=None):
    from railwatch_order_page import OrderPage
    from railwatch_orders import OrderIntent, OrderResult
    intent = intent or OrderIntent.from_config(self.cfg, train_code, seat_name, "alternate")
    page = getattr(self, "order_page", None) or OrderPage(self.driver)
    button = self.find_alternate_button(row, seat_name) if self.find_alternate_button else None
    if button is None:
      return OrderResult("not_submitted", "目标席别候补按钮不可用", no_order=True)
    return page.alternate(button, intent)
