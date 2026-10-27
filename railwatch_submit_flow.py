"""Auto-submit flow for regular ticket booking."""

from __future__ import annotations

from typing import Callable, Optional


class SubmitFlow:
  def __init__(
    self,
    driver,
    cfg: dict,
    log_callback: Optional[Callable[[str], None]] = None,
  ):
    self.driver = driver
    self.cfg = cfg
    self.log = log_callback or (lambda _message: None)

  def try_auto_submit(self, book_btn, seat_type_name: str = "", intent=None):
    from railwatch_order_page import OrderPage
    from railwatch_orders import OrderIntent
    intent = intent or OrderIntent.from_config(self.cfg, self.cfg.get("train_code", ""), seat_type_name, "regular")
    page = getattr(self, "order_page", None) or OrderPage(self.driver, log=self.log)
    return page.regular(book_btn, intent, seat_preference=self.cfg.get("seat_prefer", "无偏好"))
