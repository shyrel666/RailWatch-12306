"""Centralized 12306 page selectors for easier maintenance."""

from __future__ import annotations

import json

# Exact observed messages only. Query recovery and submitted-order recovery
# share wording, but retain their own page and transaction guards.
TRANSIENT_ERROR_PATTERN = (
    r"^(?:温馨提示|提示)?(?:系统忙[，,]?请稍后再试|网络超时[，,]?请(?:稍后)?(?:再试|重试))"
    r"[！!。.]?(?:确定|确认|关闭)?$"
)
TRANSIENT_ERROR_TEXT_JS = (
    "const rwTransientPattern = new RegExp(" + json.dumps(TRANSIENT_ERROR_PATTERN) + ");\n"
    r"const rwTransientError = text => rwTransientPattern.test(String(text || '').replace(/\s+/g, ''));"
)

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

CONFIRM_ALTERNATE_SELECTORS = ()
SUBMIT_ALTERNATE_SELECTORS = ("#toPayBtn",)

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

PREFILL_ENTRY_ID = "preFilled1"
PREFILL_ENTRY_LINK_ID = "preFilled1href"
PREFILL_SAVE_BTN_ID = "saveBtn"
PREFILL_TRAIN_ITEM_SELECTOR = "#trainList > .ticket-result-item"
PREFILL_SEAT_ITEM_SELECTOR = ".ticket-item-buy-item-drop > .ticket-item-buy-item"
PREFILL_SELECT_BTN_SELECTOR = ".ticket-btn > a.btn.btn-hollow.btn-sm"
PREFILL_EDITOR_TABLE_SELECTOR = "table.ticket-fill-advance-table"
PREFILL_EDITOR_CONFIRM_SELECTOR = ".order-detail-ft > .btn-primary"
PREFILL_LINES_ITEM_SELECTOR = ".ticket-fill-advance-lines .lines-item"
PREFILL_DETAIL_CARD_SELECTOR = ".ticket-result-bd > .ticket-result-item"
PREFILL_BUY_BUTTON_SELECTOR = ".ticket-item-buy-item-drop > .ticket-item-buy-item a.buy-ticket-button"

# Read-only readiness shared by batch scans and final control lookup. A later
# native click and the order form readback remain authoritative.
ACTION_READY_JS = r"""
const rwActionReady = el => {
  if (!el || !el.isConnected || !el.getClientRects().length || el.matches(':disabled') ||
      el.getAttribute('aria-disabled') === 'true') return false;
  for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
    const style = getComputedStyle(node);
    if (style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse' ||
        Number(style.opacity) === 0) return false;
  }
  return true;
};
"""

# Shared confirmation dialog discovery for both regular (#qr_submit_id) and
# M1-verified official pre-fill (.modal + a.btn.btn-primary.ok "提交订单").
CONFIRM_DIALOG_HELPER_JS = ACTION_READY_JS + r"""
const rwDialogSelector = '.dhtmlx_window_active,.layui-layer,.modal,[role="dialog"],.up-box';
const rwConfirmBtnSelector = 'a.btn.btn-primary.ok,.modal-ft a.ok,.modal-ft a.btn-primary,a.ok,a.btn-primary,button';
const rwTxt = e => (e?.innerText || '').replace(/\s+/g, ' ').trim();
const rwVisible = e => !!(e && e.getClientRects().length && getComputedStyle(e).visibility === 'visible');
const rwInnerDialogs = () => {
  const raw = [...document.querySelectorAll(rwDialogSelector)].filter(rwVisible);
  return raw.filter(node => !raw.some(other => other !== node && node.contains(other)));
};
const rwPrefillSubmitReady = el => (
  rwActionReady(el) && !el.classList.contains('btn-disabled') &&
  !el.hasAttribute('disabled') && rwTxt(el) === '提交订单'
);
const rwPrefillConfirmModal = () => {
  if (!/(?:^|\/)prefill_order\.html$|(?:^|\/)prefill-order\.html$/.test(location.pathname)) return null;
  const matches = [];
  for (const dialog of rwInnerDialogs()) {
    if (!/购票信息确认/.test(rwTxt(dialog)) || !dialog.querySelector('table')) continue;
    const submits = [...dialog.querySelectorAll(rwConfirmBtnSelector)].filter(rwPrefillSubmitReady);
    if (submits.length === 1) matches.push({root: dialog, button: submits[0]});
  }
  return matches.length === 1 ? matches[0] : null;
};
const rwQrConfirm = () => {
  const btn = document.querySelector('#qr_submit_id');
  if (!rwVisible(btn)) return null;
  const ready = rwActionReady(btn) && btn.classList.contains('btn92s') && !btn.classList.contains('btn92');
  return {root: btn.closest(rwDialogSelector), button: ready ? btn : null, visible: true};
};
"""

# The live query page also makes the seat cell itself the waitlist control.
# Read only its structural markers; hbdata contains opaque official data.
ALTERNATE_ACTION_JS = ACTION_READY_JS + r"""
const rwAlternateAction = cell => {
  if (!cell || !rwActionReady(cell)) return null;
  const controls = [...cell.querySelectorAll('a,button,div')]
    .filter(el => el.innerText.trim() === '候补');
  if (controls.length) return controls.find(rwActionReady) || null;
  if (cell.innerText.trim() === '候补' &&
      cell.matches('td[role="button"][onclick][hbdata][hbid]') &&
      cell.getAttribute('onclick')?.trim() && cell.getAttribute('hbdata')?.trim() &&
      cell.getAttribute('hbid')?.trim()) return cell;
  return null;
};
"""
