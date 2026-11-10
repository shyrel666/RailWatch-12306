"""Official 12306 PC pre-fill (购票信息预填) adapter.

Pure DOM interaction only: no private API calls, no XHR body interception,
no captcha/slider bypass, and no deletion of unrelated user pre-fill entries.
Every submission preserves single-choice OrderIntent ownership in OrderJournal.
"""
from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import re
import time
from typing import Callable, Optional, Sequence
from urllib.parse import urlparse
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
    StaleElementReferenceException,
)

from railwatch_config_contract import parse_codes, parse_passenger_names
from railwatch_order_page import (
    ConfirmationOutcome,
    OrderPage,
    contains_token,
    form_token,
    needs_person,
    normalized_date,
    seat_label,
    train_token,
)
from railwatch_orders import OrderIntent, OrderJournal, OrderResult
from railwatch_policies import ORDER_POLICIES
from railwatch_query import QueryExecutor
from railwatch_row_parser import RowParser
from railwatch_seats import CAPABILITIES_BY_NAME
from railwatch_selectors import (
    ACTION_READY_JS,
    CONFIRM_DIALOG_HELPER_JS,
    PREFILL_EDITOR_CONFIRM_SELECTOR,
    PREFILL_ENTRY_LINK_ID,
    PREFILL_SAVE_BTN_ID,
)
from railwatch_task import TaskCancelled

BEIJING_TZ = dt.timezone(dt.timedelta(hours=8))
QUERY_INIT_URL = "https://kyfw.12306.cn/otn/leftTicket/init?linktypeid=dc"
PREFILL_REMAINING_URL = "https://kyfw.12306.cn/otn/view/prefill_remaining.html"
PREFILL_LIST_URL = "https://kyfw.12306.cn/otn/view/prefill_list.html"
PREFILL_ORDER_URL = "https://kyfw.12306.cn/otn/view/prefill_order.html"

FALLBACK_MESSAGES = {
    "unlock_timeout": "预填购票按钮未在限定时间内显示，已回退常规余票查询。",
    "countdown_behind": "官方预填页倒计时仍明显早于起售时刻，未等待解锁，已回退常规余票查询。",
    "detail_unavailable": "官方预填详情页暂不可用，已回退常规余票查询。",
    "dialog_open": "官方预填详情页仍有弹窗未关闭，已回退常规余票查询。",
    "trip_changed": "官方预填行程日期或区间已变化，已回退常规余票查询。",
    "passengers_changed": "官方预填乘车人信息缺失或已变化，已回退常规余票查询。",
    "click_rejected": "预填购票点击未送达官方页面，已回退常规余票查询。",
    "not_on_sale": "官方仍提示未到起售时间，已回退常规余票查询。",
}


class PrefillFallback(Exception):
    """Raised during preparation when pre-fill must safely fall open to query mode."""

    def __init__(self, reason: str, *, stage: str = "prepare", query_result: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.stage = stage
        self.query_result = query_result


@dataclass(frozen=True)
class PrefillCandidate:
    train_code: str
    date: str
    from_station: str
    to_station: str
    seat: str
    sale_label: str = ""


@dataclass(frozen=True)
class ArmedPrefillPlan:
    date: str
    passengers: tuple[str, ...]
    candidates: tuple[PrefillCandidate, ...]
    target_timestamp: float


@dataclass(frozen=True)
class PrefillExecutionOutcome:
    action: str  # "handled" | "sold_out_all" | "fallback_to_query"
    sold_out_candidates: tuple[PrefillCandidate, ...] = ()
    last_intent: Optional[OrderIntent] = None
    last_result: Optional[OrderResult] = None


def regular_target_seats(config: dict) -> list[str]:
    """Return configured seats that are verified for regular order transactions."""
    seats = parse_codes(config.get("seat_keyword", ""))
    return [seat for seat in seats if (cap := CAPABILITIES_BY_NAME.get(seat)) and cap.regular]


def prefill_eligible_reason(config: dict, target_timestamp: Optional[float], *, now: Optional[float] = None) -> Optional[str]:
    """Return None when pre-fill preparation may be attempted, else a skip reason."""
    if not (config.get("timer_enabled") and config.get("auto_submit") and target_timestamp is not None):
        return "未同时启用定时抢票与自动提交"
    if config.get("prefill_enabled", True) is False:
        return "已关闭官方购票信息预填，直接采用常规查询准备"
    current = time.time() if now is None else now
    min_lead = ORDER_POLICIES["prefill_min_lead_seconds"]
    if target_timestamp - current < min_lead:
        return f"距起售不足 {min_lead} 秒，直接采用常规查询准备"
    travel_date = str(config.get("date", "")).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", travel_date):
        return "乘车日期格式无效"
    if not parse_codes(config.get("train_code", ""), upper=True):
        return "未指定明确目标车次"
    if not regular_target_seats(config):
        return "未包含支持常规自动提交的目标席别"
    passengers = parse_passenger_names(config.get("passengers", ""))
    if not passengers or len(passengers) != len(set(passengers)):
        return "乘车人名单为空或存在重复姓名"
    return None


def parse_sale_label_timestamp(label: str, *, reference_timestamp: float) -> Optional[float]:
    """Parse Chinese sale text (e.g. '11月7日16点起售', '11月7日12点45分起售') to UTC+8 timestamp."""
    compact = re.sub(r"\s+", "", str(label or ""))
    if not compact:
        return None
    match = re.search(
        r"(?:(?P<year>\d{4})年)?(?:(?P<month>\d{1,2})月(?P<day>\d{1,2})日)?(?P<hour>\d{1,2})(?:点|时|:)(?:(?P<minute>\d{1,2})分?)?起售",
        compact,
    )
    if not match:
        return None
    ref = dt.datetime.fromtimestamp(reference_timestamp, tz=BEIJING_TZ)
    hour = int(match.group("hour"))
    minute = int(match.group("minute") or 0)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    if match.group("year"):
        year = int(match.group("year"))
        month = int(match.group("month") or ref.month)
        day = int(match.group("day") or ref.day)
        try:
            return dt.datetime(year, month, day, hour, minute, 0, tzinfo=BEIJING_TZ).timestamp()
        except ValueError:
            return None
    if match.group("month") and match.group("day"):
        month = int(match.group("month"))
        day = int(match.group("day"))
        candidates = []
        for candidate_year in (ref.year - 1, ref.year, ref.year + 1):
            try:
                built = dt.datetime(candidate_year, month, day, hour, minute, 0, tzinfo=BEIJING_TZ)
            except ValueError:
                continue
            candidates.append((abs((built - ref).total_seconds()), built))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1].timestamp()
    try:
        return dt.datetime(ref.year, ref.month, ref.day, hour, minute, 0, tzinfo=BEIJING_TZ).timestamp()
    except ValueError:
        return None


def parse_countdown_seconds(value) -> Optional[int]:
    """Parse countdown text or the official editor's visible units (h, m, s)."""
    if isinstance(value, (list, tuple)):
        if not 1 <= len(value) <= 3 or not all(str(part).strip().isdecimal() for part in value):
            return None
        # The editor omits leading zero units below one hour and one minute.
        hours, minutes, seconds = [0] * (3 - len(value)) + [int(part) for part in value]
        return hours * 3600 + minutes * 60 + seconds if 0 <= minutes < 60 and 0 <= seconds < 60 else None
    compact = re.sub(r"\s+", "", str(value or ""))
    if not compact:
        return None
    match = re.fullmatch(
        r"(?:(?P<h>\d+)小时)?(?:(?P<m>\d+)分(?:钟)?)?(?:(?P<s>\d+)秒)?",
        compact,
    )
    if not match or not any(match.group(key) is not None for key in ("h", "m", "s")):
        return None
    hours = int(match.group("h") or 0)
    minutes = int(match.group("m") or 0)
    seconds = int(match.group("s") or 0)
    if minutes >= 60 or seconds >= 60:
        return None
    return hours * 3600 + minutes * 60 + seconds


def passengers_span_matches(span_text: str, expected: Sequence[str]) -> bool:
    """Compare .passsengers-span text against configured adult passenger names."""
    expected_list = [name.strip() for name in expected if name.strip()]
    raw = str(span_text or "").strip()
    if not expected_list or not raw:
        return False
    parts = [part.strip() for part in re.split(r"[,，、;；/]+", raw) if part.strip()]
    if (len(parts) == 1 and len(expected_list) > 1 and re.search(r"\s", raw)
            and not any(re.search(r"\s", name) for name in expected_list)):
        parts = [part.strip() for part in raw.split() if part.strip()]
    return len(parts) == len(expected_list) and len(set(parts)) == len(parts) and set(parts) == set(expected_list)


def month_day_matches(info_text: str, iso_date: str) -> bool:
    """Verify '（11月21日 星期五）' matches the month and day of YYYY-MM-DD."""
    date_match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", str(iso_date or "").strip())
    info_match = re.search(r"(\d{1,2})月(\d{1,2})日", str(info_text or ""))
    if not date_match or not info_match:
        return False
    return (int(info_match.group(1)), int(info_match.group(2))) == (int(date_match.group(2)), int(date_match.group(3)))


def explicit_rejection(snap: dict) -> Optional[str]:
    """Accept only one unambiguous entry rejection with no order evidence."""
    dialogs = set(snap.get("dialogs", []))
    if len(dialogs) != 1 or any(snap.get(field) for field in
                               ("orders", "processing", "confirmation", "formReady", "verification", "quietCar")):
        return None
    text = next(iter(dialogs))
    if re.search(r"登录|核验|验证|滑块|频繁|操作过快|稍后再试|订单|提交|支付|排队", text):
        return None
    sold_out = bool(re.search(r"余票不足|车票已售罄|没有足够的余票|席位已售完|票已售完|已售完|已售罄|无余票", text))
    not_on_sale = bool(re.search(r"未到?起售时间|尚未起售", text))
    if sold_out == not_on_sale:
        return None
    return "sold_out" if sold_out else "not_on_sale"


TIMEZONE_OFFSET_JS = "return new Date().getTimezoneOffset();"

REMAINING_LIST_JS = ACTION_READY_JS + r"""
const txt = e => (e?.innerText || '').replace(/\s+/g, ' ').trim();
const cleanStation = e => {
  if (!e) return '';
  const clone = e.cloneNode(true);
  clone.querySelectorAll('span').forEach(node => node.remove());
  return (clone.textContent || '').replace(/\s+/g, '').trim();
};
const items = [...document.querySelectorAll('#trainList > .ticket-result-item')].map(item => {
  const times = [...item.querySelectorAll('.ticket-item-info .ticket-time')];
  const saleNode = [...item.querySelectorAll('.ticket-state .txt-lighter')].find(n => txt(n));
  // Restrict strictly to direct children of .ticket-item-buy-item-drop to ignore sleeper berth rows.
  const seatRows = [...item.querySelectorAll(':scope .ticket-item-buy-item-drop > .ticket-item-buy-item')];
  return {
    train_code: txt(item.querySelector('.ticket-number-num')).toUpperCase(),
    from_station: cleanStation(times[0]?.querySelector('.ticket-time-info')),
    to_station: cleanStation(times[1]?.querySelector('.ticket-time-info')),
    sale_label: txt(saleNode),
    seats: seatRows.map(row => {
      const btn = row.querySelector('.ticket-btn > a.btn.btn-hollow.btn-sm');
      return {
        seat: txt(row.querySelector('.ticket-price-seat')),
        active: !!btn && btn.classList.contains('is-active'),
        ready: rwActionReady(btn),
      };
    }),
  };
});
const saveBtn = document.getElementById('saveBtn');
return {
  url: location.href,
  has_list: !!document.getElementById('trainList'),
  items,
  save_ready: !!(rwActionReady(saveBtn) && !saveBtn.classList.contains('btn-disabled') && !saveBtn.hasAttribute('disabled')),
};
"""

FIND_REMAINING_SEAT_BTN_JS = ACTION_READY_JS + r"""
const [wantTrain, wantFrom, wantTo, wantSeat] = arguments;
const txt = e => (e?.innerText || '').replace(/\s+/g, ' ').trim();
const cleanStation = e => {
  if (!e) return '';
  const clone = e.cloneNode(true);
  clone.querySelectorAll('span').forEach(node => node.remove());
  return (clone.textContent || '').replace(/\s+/g, '').trim();
};
for (const item of document.querySelectorAll('#trainList > .ticket-result-item')) {
  const code = txt(item.querySelector('.ticket-number-num')).toUpperCase();
  const times = [...item.querySelectorAll('.ticket-item-info .ticket-time')];
  const from = cleanStation(times[0]?.querySelector('.ticket-time-info'));
  const to = cleanStation(times[1]?.querySelector('.ticket-time-info'));
  if (code !== wantTrain || from !== wantFrom || to !== wantTo) continue;
  for (const row of item.querySelectorAll(':scope .ticket-item-buy-item-drop > .ticket-item-buy-item')) {
    if (txt(row.querySelector('.ticket-price-seat')) !== wantSeat) continue;
    const btn = row.querySelector('.ticket-btn > a.btn.btn-hollow.btn-sm');
    return {
      found: !!btn,
      active: !!btn && btn.classList.contains('is-active'),
      button: rwActionReady(btn) ? btn : null,
    };
  }
}
return {found: false, active: false, button: null};
"""

EDITOR_SNAPSHOT_JS = ACTION_READY_JS + r"""
const visible = e => !!(e && e.getClientRects().length && getComputedStyle(e).visibility === 'visible');
const txt = e => (e?.innerText || '').replace(/\s+/g, ' ').trim();
const tables = [...document.querySelectorAll('table.ticket-fill-advance-table')].filter(visible);
const rows = tables.map(table => {
  const stations = [...table.querySelectorAll('.td-station')];
  const readStation = cell => txt(cell?.querySelector('div > strong') || cell);
  return {
    train_code: txt(table.querySelector('.td-train-number strong')).toUpperCase(),
    from_station: readStation(stations[0]),
    to_station: readStation(stations[1]),
    sale_label: txt(table.querySelector('.td-state .txt-lighter')),
    seats: [...table.querySelectorAll('.td-seat .seat-item.is-active .seat-name')].map(txt).filter(Boolean),
  };
});
const checkedNames = [...document.querySelectorAll('#passenge_list input.chose-pass-dom:checked')].map(input => {
  const label = input.closest('label') || [...(input.labels || [])][0];
  return (label?.getAttribute('title') || label?.innerText || '').replace(/[（(](?:学生|儿童|成人)[）)]/g, '').trim();
}).filter(Boolean);
const selectedRows = [];
for (const tr of document.querySelectorAll('#on_chick_passenger .list-table tr')) {
  const nameInput = tr.querySelector('input.name-input');
  if (!nameInput || !visible(tr)) continue;
  selectedRows.push({
    name: (nameInput.value || '').trim(),
    ticket_type: txt(tr.querySelector('.sel-hd .typetext')),
  });
}
const confirmBtn = document.querySelector('.order-detail-ft > .btn-primary');
return {
  url: location.href,
  ready: visible(document.getElementById('panel-order-con')) && visible(document.getElementById('passenge_list')),
  header_dates: [...document.querySelectorAll('#panel-order-con .panel-order-hd > strong')].filter(visible).map(txt),
  countdown: [...document.querySelectorAll('.sail-time0 .txt-num')].filter(visible).map(txt),
  rows,
  checked_names: checkedNames,
  selected_rows: selectedRows,
  confirm_ready: rwActionReady(confirmBtn) && txt(confirmBtn) === '确定',
};
"""

ORDER_DETAIL_SNAPSHOT_JS = ACTION_READY_JS + r"""
const visible = e => !!(e && e.getClientRects().length && getComputedStyle(e).visibility === 'visible');
const txt = e => (e?.innerText || '').replace(/\s+/g, ' ').trim();
const cleanStation = e => {
  if (!e) return '';
  const clone = e.cloneNode(true);
  clone.querySelectorAll('span').forEach(node => node.remove());
  return (clone.textContent || '').replace(/\s+/g, '').trim();
};
const tabNodes = [...document.querySelectorAll('.ticket-fill-advance-lines .lines-item')].filter(visible);
const tabs = tabNodes.map((node, index) => {
  const names = [...node.querySelectorAll('strong.lines-name')].map(txt);
  return {
    index,
    active: node.classList.contains('is-active'),
    from_station: names[0] || '',
    to_station: names[1] || '',
    info: txt(node.querySelector('span.lines-info')),
  };
});
const cards = [...document.querySelectorAll('.ticket-result-bd > .ticket-result-item')].filter(visible).map(item => {
  const times = [...item.querySelectorAll('.ticket-item-info .ticket-time')];
  const saleNode = [...item.querySelectorAll('.qishou-text')].find(n => txt(n));
  const seatRows = [...item.querySelectorAll(':scope .ticket-item-buy-item-drop > .ticket-item-buy-item')];
  return {
    train_code: txt(item.querySelector('.ticket-number-num')).toUpperCase(),
    from_station: cleanStation(times[0]?.querySelector('.ticket-time-info')),
    to_station: cleanStation(times[1]?.querySelector('.ticket-time-info')),
    sale_label: txt(saleNode),
    seats: seatRows.map(row => {
      const btn = row.querySelector('a.buy-ticket-button');
      return {
        seat: txt(row.querySelector('.ticket-price-seat')),
        has_buy_button: !!btn,
        buy_ready: rwActionReady(btn),
      };
    }),
  };
});
const unonsale = document.querySelector('.tips-box .unOnsale-span');
const onsale = document.querySelector('.tips-box .onsale-span');
const editBtn = document.getElementById('edit-button');
return {
  url: location.href,
  tabs,
  dialogs: [...document.querySelectorAll('.dhtmlx_window_active,.layui-layer,.modal,[role="dialog"],.up-box')]
    .filter(visible).map(txt).filter(Boolean),
  passengers_text: txt(document.querySelector('.tips-box .passsengers-span')),
  unonsale_visible: visible(unonsale),
  onsale_visible: visible(onsale),
  countdown_text: visible(unonsale?.querySelector('.count-down-text')) ? txt(unonsale.querySelector('.count-down-text')) : '',
  edit_ready: rwActionReady(editBtn),
  cards,
};
"""

CLICK_TAB_AT_INDEX_JS = ACTION_READY_JS + r"""
const visible = e => !!(e && e.getClientRects().length && getComputedStyle(e).visibility === 'visible');
const tabs = [...document.querySelectorAll('.ticket-fill-advance-lines .lines-item')].filter(visible);
const target = tabs[arguments[0]];
return rwActionReady(target) ? target : null;
"""

FIND_BUY_BUTTON_JS = ACTION_READY_JS + r"""
const [wantTrain, wantFrom, wantTo, wantSeat] = arguments;
const visible = e => !!(e && e.getClientRects().length && getComputedStyle(e).visibility === 'visible');
const txt = e => (e?.innerText || '').replace(/\s+/g, ' ').trim();
const cleanStation = e => {
  if (!e) return '';
  const clone = e.cloneNode(true);
  clone.querySelectorAll('span').forEach(node => node.remove());
  return (clone.textContent || '').replace(/\s+/g, '').trim();
};
for (const item of document.querySelectorAll('.ticket-result-bd > .ticket-result-item')) {
  if (!visible(item)) continue;
  const code = txt(item.querySelector('.ticket-number-num')).toUpperCase();
  const times = [...item.querySelectorAll('.ticket-item-info .ticket-time')];
  const from = cleanStation(times[0]?.querySelector('.ticket-time-info'));
  const to = cleanStation(times[1]?.querySelector('.ticket-time-info'));
  if (code !== wantTrain || from !== wantFrom || to !== wantTo) continue;
  for (const row of item.querySelectorAll(':scope .ticket-item-buy-item-drop > .ticket-item-buy-item')) {
    if (txt(row.querySelector('.ticket-price-seat')) !== wantSeat) continue;
    const btn = row.querySelector('a.buy-ticket-button');
    if (rwActionReady(btn) && txt(btn) === '按预填信息购票') return btn;
    return null;
  }
}
return null;
"""

CONFIRMATION_SNAPSHOT_JS = CONFIRM_DIALOG_HELPER_JS + r"""
const qr = rwQrConfirm();
const prefill = rwPrefillConfirmModal();
if (qr && prefill && qr.root !== prefill.root) {
  return {text: '', names: [], seats: [], ticket_types: [], no_seat_preference: false};
}
const root = qr?.root || prefill?.root || null;
if (!root) return {text: '', names: [], seats: [], ticket_types: [], no_seat_preference: false};
const names = [];
const seats = [];
const ticketTypes = [];
for (const table of root.querySelectorAll('table')) {
  const headers = [...table.querySelectorAll('th')].map(rwTxt);
  const nameIdx = headers.findIndex(text => /姓名|乘车人/.test(text));
  if (nameIdx < 0) continue;
  const seatIdx = headers.findIndex(text => text === '席别');
  const typeIdx = headers.findIndex(text => text === '票种');
  for (const row of [...table.querySelectorAll('tr')].filter(rwVisible)) {
    const cells = row.querySelectorAll('td');
    if (cells.length <= nameIdx) continue;
    const name = (cells[nameIdx].querySelector('input')?.value || rwTxt(cells[nameIdx])).trim();
    if (!name) continue;
    names.push(name);
    if (seatIdx >= 0 && cells.length > seatIdx) seats.push(rwTxt(cells[seatIdx]));
    if (typeIdx >= 0 && cells.length > typeIdx) ticketTypes.push(rwTxt(cells[typeIdx]));
  }
}
const dialogText = rwTxt(root);
return {
  text: dialogText,
  names,
  seats,
  ticket_types: ticketTypes,
  no_seat_preference: !!prefill && /暂不支持自选席位/.test(dialogText),
};
"""

DISMISS_PREFILL_ALERT_JS = CONFIRM_DIALOG_HELPER_JS + r"""
if (rwQrConfirm() || rwPrefillConfirmModal()) return false;
const dialogs = rwInnerDialogs();
if (dialogs.some(d => /购票信息确认|提交订单/.test(rwTxt(d)))) return false;
for (const dialog of dialogs) {
  const text = rwTxt(dialog);
  if (/登录|核验|验证|滑块|支付|排队|订单/.test(text)) continue;
  if (!/余票不足|车票已售罄|没有足够的余票|席位已售完|票已售完|已售完|已售罄|无余票|未到?起售时间|尚未起售/.test(text)) continue;
  const controls = [...dialog.querySelectorAll(
    '.modal-ft a.ok,.modal-ft a.btn-primary,a.ok,a.btn-primary,button,.layui-layer-btn0,.modal-close,a.close'
  )].filter(el => {
    if (!rwActionReady(el)) return false;
    const label = rwTxt(el);
    if (el.matches('.modal-close,a.close') && !label) return true;
    return /^(确定|确认|我知道了|知道了|关闭|返回)$/.test(label);
  });
  if (controls.length) {
    controls[0].click();
    return true;
  }
}
return false;
"""


class PrefillAdapter:
    """Orchestrates official 12306 pre-fill preparation, readback, and timed submission."""

    UNLOCK_POLL_SECONDS = 0.025
    TRANSITION_POLL_SECONDS = 0.04
    TRANSITION_TIMEOUT_SECONDS = 10.0
    DIALOG_CLEAR_SECONDS = 0.3
    BUY_CLICK_ATTEMPTS = 3
    # Time kept before the sale for the fallback to navigate and refill the query page.
    PREPARE_RESERVE_SECONDS = 30.0

    def __init__(
        self,
        driver,
        *,
        stop: Callable[[], bool] = lambda: False,
        wait: Optional[Callable[[float], None]] = None,
        log: Optional[Callable[[str], None]] = None,
        now: Callable[[], float] = time.time,
        allow_fixture: bool = False,
        query_init_url: str = QUERY_INIT_URL,
        prefill_order_url: str = PREFILL_ORDER_URL,
    ):
        self.driver = driver
        self.stop = stop
        self.wait = wait or time.sleep
        self.log = log or (lambda message: None)
        self.now = now
        self.allow_fixture = allow_fixture
        self.query_init_url = query_init_url
        self.prefill_order_url = prefill_order_url
        self._prepare_deadline: Optional[float] = None

    def _trusted_url(self, url: str, expected_path: Optional[str] = None) -> bool:
        parsed = urlparse(str(url or ""))
        if self.allow_fixture and parsed.scheme == "file":
            return True
        if parsed.scheme != "https" or parsed.hostname != "kyfw.12306.cn":
            return False
        return expected_path is None or parsed.path == expected_path

    def _poll(self, predicate, timeout: float, interval: float = 0.05):
        deadline = time.monotonic() + timeout
        while not self.stop():
            self._check_prepare_budget()
            value = predicate()
            if value:
                return value
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            self.wait(min(interval, remaining))
        if self.stop():
            raise TaskCancelled()
        return None

    def check_browser_clock(self) -> None:
        """Require browser local timezone UTC+8 because 12306 computes prefill countdown locally."""
        try:
            offset = self.driver.execute_script(TIMEZONE_OFFSET_JS)
        except Exception as exc:
            raise PrefillFallback(f"无法读取浏览器时区（{type(exc).__name__}）", stage="timezone_check") from exc
        if offset != -480:
            raise PrefillFallback(
                "浏览器时区非北京时间（UTC+8），官网预填倒计时与购票按钮解锁会失准，已自动回退常规余票查询",
                stage="timezone_mismatch",
            )

    def _check_countdown_tolerance(self, countdown_seconds: Optional[int], target_timestamp: float, *, stage: str) -> None:
        if countdown_seconds is None:
            raise PrefillFallback("无法解析官方预填页倒计时，已自动回退常规余票查询", stage=stage)
        expected_remaining = target_timestamp - self.now()
        tolerance = ORDER_POLICIES["prefill_countdown_tolerance_seconds"]
        drift = abs(countdown_seconds - expected_remaining)
        if drift > tolerance:
            raise PrefillFallback(
                f"官方预填倒计时与目标起售时刻偏差 {drift:.1f}s（上限 {tolerance}s），已自动回退常规余票查询",
                stage="countdown_mismatch",
            )

    def _editor_snapshot(self) -> dict:
        value = self.driver.execute_script(EDITOR_SNAPSHOT_JS)
        if not isinstance(value, dict) or not self._trusted_url(value.get("url", ""), "/otn/view/prefill_list.html"):
            return {}
        return value

    def _detail_snapshot(self) -> dict:
        value = self.driver.execute_script(ORDER_DETAIL_SNAPSHOT_JS)
        if not isinstance(value, dict) or not self._trusted_url(value.get("url", ""), "/otn/view/prefill_order.html"):
            return {}
        return value

    def _remaining_snapshot(self) -> dict:
        value = self.driver.execute_script(REMAINING_LIST_JS)
        if not isinstance(value, dict) or not self._trusted_url(value.get("url", ""), "/otn/view/prefill_remaining.html"):
            return {}
        return value

    def _wait_editor_ready(self, timeout: float) -> Optional[dict]:
        def check():
            snap = self._editor_snapshot()
            return snap if snap.get("ready") else None

        return self._poll(check, timeout)

    def _wait_detail_tabs(self, timeout: float) -> Optional[dict]:
        def check():
            snap = self._detail_snapshot()
            return snap if snap.get("tabs") else None

        return self._poll(check, timeout)

    def _wait_remaining_ready(self, timeout: float) -> Optional[dict]:
        def check():
            snap = self._remaining_snapshot()
            return snap if snap.get("has_list") and snap.get("items") else None

        return self._poll(check, timeout)

    def _activate_detail_tab(self, index: int, expected_from: str, expected_to: str, timeout: float = 3.0) -> dict:
        snap = self._detail_snapshot()
        tabs = snap.get("tabs", [])
        if index < 0 or index >= len(tabs):
            raise PrefillFallback("官方预填详情页行程标签索引无效", stage="detail_tab")
        if not tabs[index].get("active"):
            tab_el = self.driver.execute_script(CLICK_TAB_AT_INDEX_JS, index)
            if tab_el is None:
                raise PrefillFallback("官方预填详情页行程标签不可点击", stage="detail_tab")
            tab_el.click()

        def settled():
            current = self._detail_snapshot()
            active = next((t for t in current.get("tabs", []) if t.get("active")), None)
            if not active or active.get("from_station") != expected_from or active.get("to_station") != expected_to:
                return None
            cards = current.get("cards", [])
            if not cards or any(c.get("from_station") != expected_from or c.get("to_station") != expected_to for c in cards):
                return None
            return current

        result = self._poll(settled, timeout, interval=0.04)
        if not result:
            raise PrefillFallback("切换官方预填行程标签后列表未就绪", stage="detail_tab")
        return result

    def _collect_saved_detail(self, travel_date: str, target_timestamp: float) -> tuple[str, list[PrefillCandidate]]:
        snap = self._detail_snapshot()
        tabs = snap.get("tabs", [])
        if not tabs:
            return "", []
        passengers_text = snap.get("passengers_text", "")
        collected: list[PrefillCandidate] = []
        for tab in tabs:
            tab_snap = self._activate_detail_tab(tab["index"], tab["from_station"], tab["to_station"])
            if not month_day_matches(tab.get("info", ""), travel_date):
                continue
            for card in tab_snap.get("cards", []):
                sale_label = card.get("sale_label", "")
                sale_ts = parse_sale_label_timestamp(sale_label, reference_timestamp=target_timestamp) if sale_label else target_timestamp
                if sale_ts != target_timestamp:
                    continue
                for seat_info in card.get("seats", []):
                    if seat_info.get("has_buy_button") and seat_info.get("seat"):
                        collected.append(
                            PrefillCandidate(
                                train_code=card["train_code"],
                                date=travel_date,
                                from_station=card["from_station"],
                                to_station=card["to_station"],
                                seat=seat_info["seat"],
                                sale_label=sale_label,
                            )
                        )
        return passengers_text, collected

    def _rank_candidates(self, candidates: Sequence[PrefillCandidate], trains: Sequence[str], seats: Sequence[str]) -> list[PrefillCandidate]:
        train_rank = {code: idx for idx, code in enumerate(trains)}
        seat_rank = {seat: idx for idx, seat in enumerate(seats)}
        filtered = [c for c in candidates if c.train_code in train_rank and c.seat in seat_rank]
        seen = set()
        unique = []
        for item in sorted(filtered, key=lambda c: (train_rank[c.train_code], seat_rank[c.seat])):
            key = (item.train_code, item.date, item.from_station, item.to_station, item.seat)
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique

    def _inspect_existing(
        self,
        *,
        travel_date: str,
        passengers: tuple[str, ...],
        target_timestamp: float,
    ) -> list[PrefillCandidate]:
        """Read saved candidates without opening the editor or changing data."""
        self.driver.get(self.prefill_order_url)

        def loaded():
            url = str(self.driver.current_url or "")
            if not self._trusted_url(url):
                return "untrusted"
            snap = self._detail_snapshot()
            if snap.get("tabs"):
                return snap
            if "/otn/leftTicket/" in url or "login" in url.lower():
                return "empty"
            return None

        initial = self._poll(loaded, 3.0, interval=0.05)
        if not isinstance(initial, dict):
            return []
        passengers_text = initial.get("passengers_text", "")
        if not passengers_text.strip():
            # Selecting seats can persist a partial draft before passengers are
            # confirmed. Resume through the selection/editor flow to fill them.
            return []
        if not passengers_span_matches(passengers_text, passengers):
            raise PrefillFallback(
                "账号内已存在其他乘车人的预填单，为保护既有预填未自动覆盖，已回退常规余票查询",
                stage="account_conflict",
            )
        _, saved = self._collect_saved_detail(travel_date, target_timestamp)
        return saved

    def _try_reuse_existing(
        self,
        *,
        saved: Sequence[PrefillCandidate],
        allowed: set[tuple[str, str, str]],
        travel_date: str,
        trains: list[str],
        seats: list[str],
        passengers: tuple[str, ...],
        target_timestamp: float,
        order_page: OrderPage,
    ) -> Optional[ArmedPrefillPlan]:
        """Match saved entries to this query's actual routes before reuse."""
        ranked = self._rank_candidates(
            [c for c in saved if (c.train_code, c.from_station, c.to_station) in allowed], trains, seats)
        wanted_pairs = {(t, s) for t in trains for s in seats}
        saved_pairs = {(c.train_code, c.seat) for c in ranked}
        if not ranked or saved_pairs != wanted_pairs:
            return None

        try:
            self.driver.get(self.prefill_order_url)
            if not self._wait_detail_tabs(3.0):
                raise PrefillFallback("既有预填详情页未就绪", stage="detail_load")
            # Read back the full year and adult ticket type in the editor.
            edit_btn = order_page.button(("#edit-button",))
            if edit_btn is None:
                raise PrefillFallback("预填详情页编辑按钮不可用", stage="editor_load")
            edit_btn.click()
            editor = self._wait_editor_ready(6.0)
            if not editor:
                raise PrefillFallback("预填编辑页未就绪", stage="editor_load")
            self._verify_editor_readback(editor, travel_date, ranked, passengers, target_timestamp)
            confirm = order_page.button((PREFILL_EDITOR_CONFIRM_SELECTOR,))
            if confirm is None:
                raise PrefillFallback("预填编辑页确定按钮不可用", stage="editor_confirm")
            confirm.click()
            return self._verify_and_arm_detail(travel_date, ranked, passengers, target_timestamp)
        except (TaskCancelled, PrefillFallback):
            raise
        except Exception:
            raise PrefillFallback("既有预填回读失败，已回退常规查询", stage="reuse_readback") from None

    def _verify_no_editor_conflict(self, editor: dict, passengers: tuple[str, ...]) -> None:
        """Never replace passengers that an earlier pre-fill already saved.

        The editor shares one passenger selection across every saved trip, so a
        different checked set belongs to an existing pre-fill whatever its date
        or train. This is the last guard before the selection is changed, and
        must hold even when the read-only detail inspection found nothing.
        """
        checked = tuple(editor.get("checked_names", []))
        if checked and set(checked) != set(passengers):
            raise PrefillFallback(
                "编辑页已勾选其他乘车人，为保护既有预填未自动修改，已回退常规余票查询",
                stage="account_conflict",
            )

    def _verify_editor_readback(
        self,
        editor: dict,
        travel_date: str,
        expected_candidates: Sequence[PrefillCandidate],
        passengers: tuple[str, ...],
        target_timestamp: float,
    ) -> None:
        header_dates = [normalized_date(text) for text in editor.get("header_dates", []) if normalized_date(text)]
        if travel_date not in header_dates:
            raise PrefillFallback("预填编辑页乘车日期与目标日期不一致", stage="editor_readback")
        selected_rows = editor.get("selected_rows", [])
        actual_names = [row.get("name", "") for row in selected_rows if row.get("name")]
        if len(selected_rows) != len(passengers) or sorted(actual_names) != sorted(passengers):
            raise PrefillFallback("预填编辑页已选乘车人与目标名单不一致", stage="editor_readback")
        if any(row.get("ticket_type") != "成人票" for row in selected_rows):
            raise PrefillFallback("预填编辑页包含非成人票种，自动交易仅支持成人票", stage="editor_readback")

        actual_keys = set()
        panel_sale_timestamps = set()
        for row in editor.get("rows", []):
            sale_ts = parse_sale_label_timestamp(row.get("sale_label", ""), reference_timestamp=target_timestamp)
            if sale_ts is not None:
                panel_sale_timestamps.add(sale_ts)
            for seat in row.get("seats", []):
                actual_keys.add((row.get("train_code"), row.get("from_station"), row.get("to_station"), seat))
        for cand in expected_candidates:
            if (cand.train_code, cand.from_station, cand.to_station, cand.seat) not in actual_keys:
                raise PrefillFallback(f"预填编辑页缺少目标候选：{cand.train_code} {cand.seat}", stage="editor_readback")

        if panel_sale_timestamps == {target_timestamp} and editor.get("countdown"):
            self._check_countdown_tolerance(
                parse_countdown_seconds(editor.get("countdown")),
                target_timestamp,
                stage="editor_countdown",
            )

    def _verify_and_arm_detail(
        self,
        travel_date: str,
        expected_candidates: Sequence[PrefillCandidate],
        passengers: tuple[str, ...],
        target_timestamp: float,
    ) -> ArmedPrefillPlan:
        initial = self._wait_detail_tabs(8.0)
        if not initial:
            raise PrefillFallback("未进入官方预填保存详情页", stage="detail_load")
        if not passengers_span_matches(initial.get("passengers_text", ""), passengers):
            raise PrefillFallback("预填详情页乘车人回读与目标名单不一致", stage="detail_readback")
        _, saved = self._collect_saved_detail(travel_date, target_timestamp)
        saved_keys = {(c.train_code, c.date, c.from_station, c.to_station, c.seat) for c in saved}
        for cand in expected_candidates:
            if (cand.train_code, cand.date, cand.from_station, cand.to_station, cand.seat) not in saved_keys:
                raise PrefillFallback(f"预填详情页回读缺少候选：{cand.train_code} {cand.seat}", stage="detail_readback")

        first = expected_candidates[0]
        latest = self._detail_snapshot()
        first_tab = next(
            (
                t for t in latest.get("tabs", [])
                if t.get("from_station") == first.from_station
                and t.get("to_station") == first.to_station
                and month_day_matches(t.get("info", ""), first.date)
            ),
            None,
        )
        if first_tab is None:
            raise PrefillFallback("预填详情页未找到首选候选对应的行程标签", stage="detail_tab")
        armed_snap = self._activate_detail_tab(first_tab["index"], first.from_station, first.to_station)
        if armed_snap.get("dialogs"):
            raise PrefillFallback("官方预填详情页有弹窗未关闭，已回退常规查询", stage="detail_dialog")
        if not armed_snap.get("unonsale_visible"):
            raise PrefillFallback("官方预填页未显示起售倒计时，已回退常规查询", stage="detail_countdown")
        self._check_countdown_tolerance(
            parse_countdown_seconds(armed_snap.get("countdown_text", "")),
            target_timestamp,
            stage="detail_countdown",
        )
        return ArmedPrefillPlan(
            date=travel_date,
            passengers=passengers,
            candidates=tuple(expected_candidates),
            target_timestamp=target_timestamp,
        )

    def _check_prepare_budget(self) -> None:
        """Stop preparing while the regular query page can still be ready on time."""
        deadline = self._prepare_deadline
        if deadline is not None and self.now() > deadline:
            raise PrefillFallback(
                "官方预填准备超出时间预算，为保证常规查询准点已自动回退常规余票查询",
                stage="prepare_deadline",
            )

    def prepare(
        self,
        config: dict,
        target_timestamp: float,
        *,
        param_filler: Optional[Callable[[str, str, str], object]] = None,
        check_existing: bool = True,
    ) -> ArmedPrefillPlan:
        """Prepare or reuse an official pre-fill plan and park on prefill_order.html.

        Each step has its own timeout, but slow successes add up. The whole
        preparation must end early enough for the fallback to refill the query
        page before the sale; the budget does not apply to execute_armed.
        """
        reason = prefill_eligible_reason(config, target_timestamp, now=self.now())
        if reason:
            raise PrefillFallback(reason, stage="ineligible")
        reserve = min(self.PREPARE_RESERVE_SECONDS, ORDER_POLICIES["prefill_min_lead_seconds"] / 3)
        self._prepare_deadline = target_timestamp - reserve
        try:
            return self._prepare_plan(config, target_timestamp, param_filler=param_filler,
                                      check_existing=check_existing)
        finally:
            self._prepare_deadline = None

    def _prepare_plan(
        self,
        config: dict,
        target_timestamp: float,
        *,
        param_filler: Optional[Callable[[str, str, str], object]],
        check_existing: bool,
    ) -> ArmedPrefillPlan:
        self.check_browser_clock()

        travel_date = str(config["date"]).strip()
        trains = parse_codes(config.get("train_code", ""), upper=True)
        seats = regular_target_seats(config)
        passengers = tuple(parse_passenger_names(config.get("passengers", "")))
        order_page = OrderPage(
            self.driver,
            self.stop,
            self.wait,
            allow_fixture=self.allow_fixture,
            log=self.log,
            poll_interval=0.05,
        )

        saved = []
        if check_existing:
            saved = self._inspect_existing(
                travel_date=travel_date,
                passengers=passengers,
                target_timestamp=target_timestamp,
            )

        # Navigate to /otn/leftTicket/init, execute one query for the target date, and enter prefill_remaining.html.
        current_url = str(self.driver.current_url or "")
        on_query_page = (current_url.split("?")[0] == self.query_init_url.split("?")[0]
                         if self.allow_fixture else "/otn/leftTicket/" in urlparse(current_url).path)
        if not on_query_page:
            self.driver.get(self.query_init_url)
        if param_filler is not None:
            fill_ok = param_filler(
                str(config.get("from_station_cn", "")),
                str(config.get("to_station_cn", "")),
                travel_date,
            )
            if not fill_ok:
                raise PrefillFallback("查询页参数填充未完成，无法打开官方预填入口", stage="query_prepare")

        query_btn = order_page.button(("#query_ticket",))
        if query_btn is None:
            raise PrefillFallback("查询页查询按钮不可用，无法刷新预填横幅", stage="query_prepare")
        if self.allow_fixture and str(self.driver.current_url or "").startswith("file:"):
            query_btn.click()
        else:
            executor = QueryExecutor(self.driver, self.stop, self.wait)
            q_res = executor.execute(lambda: (query_btn.click() or True), min(15.0, float(config.get("query_timeout", 15))))
            if q_res.get("status") == "cancelled":
                raise TaskCancelled()
            if q_res.get("status") not in ("ok", "empty"):
                raise PrefillFallback("预填入口查询未完成，已转交查询监控处理", stage="query_prepare", query_result=q_res)

        if saved:
            allowed = {(row["train"], row["from_station"], row["to_station"])
                       for row in RowParser(self.driver, lambda seat: None).snapshot_rows(())
                       if row.get("from_station") and row.get("to_station")}
            reused = self._try_reuse_existing(
                saved=saved, allowed=allowed, travel_date=travel_date, trains=trains, seats=seats,
                passengers=passengers, target_timestamp=target_timestamp, order_page=order_page)
            if reused is not None:
                self.log(f"已复用账号既有官方预填单（{len(reused.candidates)} 个候选），已切至首选行程待命。")
                return reused

        entry_btn = self._poll(lambda: order_page.button((f"#{PREFILL_ENTRY_LINK_ID}",)), 5.0, interval=0.05)
        if entry_btn is None:
            raise PrefillFallback("当前余票页未显示官方购票信息预填入口", stage="entry_unavailable")
        entry_btn.click()

        # With an earlier browser prefill, “去填写” can open the editor first.
        # Follow its official add-train control to the selection page.
        if urlparse(self.driver.current_url).path.endswith("/prefill_list.html") and self._trusted_url(
            self.driver.current_url, "/otn/view/prefill_list.html"
        ):
            editor = self._wait_editor_ready(6.0)
            if not editor:
                raise PrefillFallback("官方预填编辑页未就绪", stage="editor_load")
            self._verify_no_editor_conflict(editor, passengers)
            add_train = order_page.button(("a.btn-addpassenger.list-add",))
            if add_train is None:
                raise PrefillFallback("官方预填编辑页的添加车次入口不可用", stage="remaining_load")
            add_train.click()

        rem_snap = self._wait_remaining_ready(10.0)
        if not rem_snap:
            raise PrefillFallback("官方预填选车页未加载出可选车次", stage="remaining_load")

        discovered: list[PrefillCandidate] = []
        for item in rem_snap.get("items", []):
            sale_ts = parse_sale_label_timestamp(item.get("sale_label", ""), reference_timestamp=target_timestamp)
            if sale_ts != target_timestamp or item.get("train_code") not in trains:
                continue
            for seat_info in item.get("seats", []):
                seat_name = seat_info.get("seat", "")
                if seat_name in seats:
                    discovered.append(
                        PrefillCandidate(
                            train_code=item["train_code"],
                            date=travel_date,
                            from_station=item["from_station"],
                            to_station=item["to_station"],
                            seat=seat_name,
                            sale_label=item.get("sale_label", ""),
                        )
                    )
        selected_plan = self._rank_candidates(discovered, trains, seats)
        if not selected_plan:
            raise PrefillFallback("官方预填选车页没有与目标起售时刻匹配的目标车次席别", stage="no_matching_candidates")

        for cand in selected_plan:
            info = self.driver.execute_script(
                FIND_REMAINING_SEAT_BTN_JS, cand.train_code, cand.from_station, cand.to_station, cand.seat
            )
            if not isinstance(info, dict) or not info.get("found"):
                raise PrefillFallback(f"预填选车页未找到候选按钮：{cand.train_code} {cand.seat}", stage="remaining_select")
            if info.get("active"):
                continue
            btn = info.get("button")
            if btn is None:
                raise PrefillFallback(f"预填选车按钮不可操作：{cand.train_code} {cand.seat}", stage="remaining_select")
            btn.click()
            activated = self._poll(
                lambda c=cand: (
                    res := self.driver.execute_script(
                        FIND_REMAINING_SEAT_BTN_JS, c.train_code, c.from_station, c.to_station, c.seat
                    )
                )
                and res.get("active") is True,
                3.0,
                interval=0.04,
            )
            if not activated:
                raise PrefillFallback(f"预填选车点击后未进入激活态：{cand.train_code} {cand.seat}", stage="remaining_select")

        save_ready = self._poll(lambda: self._remaining_snapshot().get("save_ready") is True, 3.0, interval=0.04)
        save_btn = order_page.button((f"#{PREFILL_SAVE_BTN_ID}",)) if save_ready else None
        if save_btn is None:
            raise PrefillFallback("预填选车页提交按钮未激活", stage="remaining_save")
        save_btn.click()

        editor = self._wait_editor_ready(10.0)
        if not editor:
            raise PrefillFallback("未进入官方预填编辑与乘车人页面", stage="editor_load")

        probe_intent = OrderIntent(
            "regular",
            selected_plan[0].train_code,
            travel_date,
            selected_plan[0].from_station,
            selected_plan[0].to_station,
            selected_plan[0].seat,
            passengers,
        )
        people_ready = order_page.wait_people(probe_intent)
        if people_ready is not True:
            raise PrefillFallback("预填编辑页乘车人列表加载未完成", stage="passenger_wait")

        self._check_prepare_budget()
        editor = self._editor_snapshot()
        self._verify_no_editor_conflict(editor, passengers)
        if not order_page.prepare_people(probe_intent):
            raise PrefillFallback(f"预填编辑页乘车人勾选未通过：{order_page._people_error}", stage="passenger_select")

        def editor_selected_synced():
            snap = self._editor_snapshot()
            return snap if len(snap.get("selected_rows", [])) == len(passengers) else None

        verified_editor = self._poll(editor_selected_synced, 4.0, interval=0.05)
        if not verified_editor:
            raise PrefillFallback("预填编辑页已选乘车人表未同步", stage="editor_readback")
        self._verify_editor_readback(verified_editor, travel_date, selected_plan, passengers, target_timestamp)

        confirm_btn = order_page.button((PREFILL_EDITOR_CONFIRM_SELECTOR,))
        if confirm_btn is None:
            raise PrefillFallback("预填编辑页确定按钮不可点击", stage="editor_confirm")
        confirm_btn.click()

        armed = self._verify_and_arm_detail(travel_date, selected_plan, passengers, target_timestamp)
        self.log(f"官方购票信息预填已完成核对（共 {len(armed.candidates)} 个候选），已驻留详情页待命。")
        return armed

    def _ensure_candidate_tab(self, cand: PrefillCandidate) -> bool:
        snap = self._detail_snapshot()
        if not snap.get("tabs"):
            return False
        target_tab = next(
            (
                t for t in snap["tabs"]
                if t.get("from_station") == cand.from_station
                and t.get("to_station") == cand.to_station
                and month_day_matches(t.get("info", ""), cand.date)
            ),
            None,
        )
        if target_tab is None:
            return False
        if target_tab.get("active"):
            return True
        try:
            self._activate_detail_tab(target_tab["index"], cand.from_station, cand.to_station, timeout=1.5)
            return True
        except PrefillFallback:
            return False

    def _wait_buy_button(self, cand: PrefillCandidate, timeout_seconds: float):
        return self._poll(
            lambda: self.driver.execute_script(
                FIND_BUY_BUTTON_JS, cand.train_code, cand.from_station, cand.to_station, cand.seat
            ),
            timeout_seconds,
            interval=self.UNLOCK_POLL_SECONDS,
        )

    @staticmethod
    def _countdown_behind(detail: dict, plan: ArmedPrefillPlan, cand: PrefillCandidate) -> bool:
        """True when the page itself says this candidate's sale is still seconds away.

        Waiting costs less than falling back only while unlocking is imminent.
        Judged from the snapshot already taken, and only when it is unambiguous:
        the candidate's own tab is active and no train on it sells later, since
        the countdown may then already point at that later sale. An empty
        countdown is the normal state in the last moments before unlocking.
        """
        active = [tab for tab in detail.get("tabs", []) if tab.get("active")]
        if (len(active) != 1 or active[0].get("from_station") != cand.from_station
                or active[0].get("to_station") != cand.to_station
                or not month_day_matches(active[0].get("info", ""), cand.date)):
            return False
        if not detail.get("unonsale_visible"):
            return False
        for card in detail.get("cards", []):
            label = card.get("sale_label", "")
            if not label:
                continue
            sale_at = parse_sale_label_timestamp(label, reference_timestamp=plan.target_timestamp)
            if sale_at is None or sale_at > plan.target_timestamp:
                return False
        remaining = parse_countdown_seconds(detail.get("countdown_text", ""))
        return remaining is not None and remaining > ORDER_POLICIES["prefill_unlock_abort_countdown_seconds"]

    def _prepare_candidate_button(self, plan: ArmedPrefillPlan, cand: PrefillCandidate, wait_budget: float):
        """Load, select and recheck the detail page before claiming an intent."""
        try:
            detail = self._detail_snapshot()
            if not detail.get("tabs"):
                self.driver.get(self.prefill_order_url)
                detail = self._wait_detail_tabs(3.0) or {}
            if not detail.get("tabs") or not self._ensure_candidate_tab(cand):
                return None, "detail_unavailable"
            if self._countdown_behind(detail, plan, cand):
                return None, "countdown_behind"
            button = self._wait_buy_button(cand, wait_budget)
            if button is None:
                return None, "unlock_timeout"

            def clear_dialogs():
                snap = self._detail_snapshot()
                return snap if snap and not snap.get("dialogs") else None

            checked = self._poll(clear_dialogs, self.DIALOG_CLEAR_SECONDS)
            if not checked:
                return None, "dialog_open"
            active = [tab for tab in checked.get("tabs", []) if tab.get("active")]
            if (len(active) != 1 or active[0].get("from_station") != cand.from_station
                    or active[0].get("to_station") != cand.to_station
                    or not month_day_matches(active[0].get("info", ""), cand.date)):
                return None, "trip_changed"
            if not passengers_span_matches(checked.get("passengers_text", ""), plan.passengers):
                return None, "passengers_changed"
            return button, ""
        except TaskCancelled:
            raise
        except Exception:
            return None, "detail_unavailable"

    def _deliver_buy_click(self, button, plan: ArmedPrefillPlan, cand: PrefillCandidate, order_page: OrderPage,
                           unlock_wait_ms: Optional[float] = None) -> bool:
        """Retry only input rejected by WebDriver before dispatch."""
        detail = {"train": cand.train_code, "seat": cand.seat}
        if unlock_wait_ms is not None:
            # Review evidence only; it rides on the marker this click already writes.
            detail["unlock_wait_ms"] = unlock_wait_ms
        for attempt in range(self.BUY_CLICK_ATTEMPTS):
            if self.stop():
                return False
            try:
                order_page.mark("prefill_submit", detail)
                button.click()
                return True
            except (StaleElementReferenceException, ElementClickInterceptedException, ElementNotInteractableException) as exc:
                order_page.mark("prefill_click_rejected", {"kind": type(exc).__name__})
            try:
                button, _ = self._prepare_candidate_button(plan, cand, 0.3)
            except TaskCancelled:
                return False
            if button is None:
                return False
        return False

    def _confirmation_matches(self, intent: OrderIntent) -> bool:
        self._last_confirmation_no_seat_pref = False
        try:
            value = self.driver.execute_script(CONFIRMATION_SNAPSHOT_JS)
            if not isinstance(value, dict):
                return False
            self._last_confirmation_no_seat_pref = bool(value.get("no_seat_preference"))
            text, names = value.get("text", ""), value.get("names", [])
            seats = value.get("seats") or []
            ticket_types = value.get("ticket_types") or []
            if (not train_token(text, intent.train_code) or normalized_date(text) != intent.date
                    or not form_token(text, intent.from_station, "站")
                    or not form_token(text, intent.to_station, "站")
                    or text.find(intent.from_station) >= text.find(intent.to_station)
                    or not contains_token(text, intent.seat)):
                return False
            if seats and [seat_label(s) for s in seats] != [intent.seat] * len(intent.passengers):
                return False
            if ticket_types and (
                len(ticket_types) != len(intent.passengers)
                or any("成人" not in t or "学生" in t or "儿童" in t for t in ticket_types)
            ):
                return False
            return (sorted(names) == sorted(intent.passengers) if names
                    else all(contains_token(text, name) for name in intent.passengers))
        except Exception:
            return False

    def _resolve_after_buy_click(
        self,
        intent: OrderIntent,
        order_page: OrderPage,
        *,
        seat_preference: str = "无偏好",
        preference_handler=None,
    ) -> OrderResult:
        """Observe the post-click transition on prefill_order.html and unify with OrderPage."""
        deadline = time.monotonic() + self.TRANSITION_TIMEOUT_SECONDS
        while not self.stop():
            snap = order_page.snapshot()
            if snap:
                direct = order_page._result_from_snapshot(snap, intent, submitted=True)
                if snap.get("processing") or direct.status in ("pending_payment", "fulfilled"):
                    order_page.mark("regular_submit")
                    return order_page._post_submit(intent, False)
                if snap.get("quietCar") or needs_person(snap):
                    return direct
                if snap.get("confirmation"):
                    confirm = order_page.confirmation_button()
                    if confirm is not None:
                        if not self._confirmation_matches(intent):
                            return OrderResult("verification", "官方确认弹窗与本次订单不一致或无法核对，尚未确认提交，请在官方页面核对")
                        order_page.mark("regular_submit")
                        if seat_preference != "无偏好":
                            if preference_handler is None and getattr(self, "_last_confirmation_no_seat_pref", False):
                                self.log(f"官方预填直连确认暂不支持自选席位（{seat_preference}），将按官方分配继续。")
                            else:
                                try:
                                    applied = (
                                        preference_handler(seat_preference)
                                        if preference_handler
                                        else order_page.apply_seat_preference(seat_preference, len(intent.passengers))
                                    ) is True
                                except Exception:
                                    applied = False
                                self.log(
                                    f"座位偏好已回读确认：{seat_preference}"
                                    if applied
                                    else f"未能应用座位偏好（{seat_preference}），将按官方分配继续。"
                                )
                        if self.stop():
                            return OrderResult("unknown", "确认提交前任务已停止，请核对官方订单")
                        outcome = order_page._click_regular_confirmation(confirm, intent)
                        if isinstance(outcome, OrderResult):
                            return outcome
                        return order_page._post_submit(intent, outcome is ConfirmationOutcome.DISPATCHED)
                elif snap.get("formReady"):
                    order_page.mark("prefill_form_opened")
                    return order_page.regular(
                        None, intent, seat_preference=seat_preference, preference_handler=preference_handler)
                else:
                    rejection = explicit_rejection(snap)
                    if rejection:
                        order_page.mark("prefill_official_rejected", {"kind": rejection})
                        try:
                            self.driver.execute_script(DISMISS_PREFILL_ALERT_JS)
                        except Exception:
                            pass
                        if rejection == "not_on_sale":
                            return OrderResult("not_submitted", "官方提示未到起售时间", no_order=True,
                                               evidence={"not_on_sale": True})
                        return OrderResult("sold_out", "官方提示余票不足", no_order=True)
                    if direct.status == "verification":
                        return direct

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            self.wait(min(self.TRANSITION_POLL_SECONDS, remaining))

        return order_page.result(intent, submitted=True)

    def execute_armed(
        self,
        plan: ArmedPrefillPlan,
        order_journal: OrderJournal,
        run_id: str,
        cfg: dict,
        *,
        on_order: Optional[Callable[[OrderIntent, OrderResult], None]] = None,
        on_stage=None,
        seat_preference: str = "无偏好",
        preference_handler=None,
    ) -> PrefillExecutionOutcome:
        """Execute armed pre-fill candidates at sale_at while preserving OrderJournal invariants."""
        sold_out_list: list[PrefillCandidate] = []
        last_intent: Optional[OrderIntent] = None
        last_result: Optional[OrderResult] = None
        unlock_timeout = ORDER_POLICIES["prefill_unlock_timeout_ms"] / 1000.0
        # One budget for the whole task: every retry is another official request.
        retry_delays = [ms / 1000.0 for ms in ORDER_POLICIES["prefill_presale_retry_delays_ms"]]
        presale_retries = 0

        def fallback(cand, stage):
            message = FALLBACK_MESSAGES.get(stage, "官方预填暂不可用，已回退常规余票查询。")
            self.log(f"{cand.train_code} {cand.seat}：{message}")
            order_journal.mark(run_id, "prefill_fallback",
                               detail={"stage": stage, "train": cand.train_code, "seat": cand.seat})
            return PrefillExecutionOutcome("fallback_to_query", tuple(sold_out_list), last_intent, last_result)

        for idx, cand in enumerate(plan.candidates):
            if self.stop():
                return PrefillExecutionOutcome("handled", tuple(sold_out_list), last_intent, last_result)

            while True:
                if self.stop():
                    return PrefillExecutionOutcome("handled", tuple(sold_out_list), last_intent, last_result)

                wait_budget = unlock_timeout if idx == 0 and presale_retries == 0 else min(0.5, unlock_timeout)
                wait_started = time.monotonic()
                button, stage = self._prepare_candidate_button(plan, cand, wait_budget)
                if button is None:
                    return fallback(cand, stage)
                unlock_wait_ms = round((time.monotonic() - wait_started) * 1000, 3)

                intent = OrderIntent(
                    "regular",
                    cand.train_code,
                    cand.date,
                    cand.from_station,
                    cand.to_station,
                    cand.seat,
                    plan.passengers,
                )
                last_intent = intent
                try:
                    order_journal.begin(run_id, intent, dict(cfg), "inventory_found")
                except Exception:
                    err_res = OrderResult("unknown", "无法取得订单提交权限，请先核对未完成订单和本地存储")
                    return PrefillExecutionOutcome("handled", tuple(sold_out_list), intent, err_res)

                if on_order:
                    on_order(intent, OrderResult("submitting"))

                def mark(stage, detail_payload=None, iid=intent.intent_id):
                    order_journal.mark(run_id, stage, iid, detail_payload)
                    if on_stage and stage in ("regular_confirm_dispatched", "regular_auto_reconcile"):
                        try:
                            on_stage(stage)
                        except Exception:
                            self.log("预填进度显示暂未更新，订单处理继续。")

                order_page = OrderPage(
                    self.driver,
                    self.stop,
                    self.wait,
                    mark,
                    allow_fixture=self.allow_fixture,
                    log=self.log,
                    poll_interval=0.05,
                    trip_route=(cfg.get("from_station_cn", ""), cfg.get("to_station_cn", "")),
                )
                try:
                    if self._deliver_buy_click(button, plan, cand, order_page, unlock_wait_ms):
                        result = self._resolve_after_buy_click(
                            intent,
                            order_page,
                            seat_preference=seat_preference,
                            preference_handler=preference_handler,
                        )
                    else:
                        result = OrderResult("not_submitted", "预填购票点击未送达官方页面，尚未提交", no_order=True,
                                             evidence={"click_rejected": True})
                except TaskCancelled:
                    result = OrderResult("unknown", "提交过程中任务已停止，请核对官方订单")
                except Exception as exc:
                    self.log(f"预填自动提交中断（{type(exc).__name__}），将核对订单状态。")
                    result = order_page.result(intent, submitted=True)

                if result.status == "unknown" and result.reason == "官方提示余票不足":
                    result = order_page.reconcile(intent, navigate=False)

                try:
                    result = order_journal.record(intent, result)
                    marker_stage = (
                        "confirmed_failure"
                        if (result.can_fallback or (result.status == "not_submitted" and result.no_order))
                        else result.status
                    )
                    order_journal.mark(run_id, marker_stage, intent.intent_id)
                except Exception:
                    err_res = OrderResult("unknown", "订单结果无法保存，请保留当前页面并核对订单，禁止重新提交")
                    return PrefillExecutionOutcome("handled", tuple(sold_out_list), intent, err_res)
                last_result = result
                if on_order:
                    on_order(intent, result)

                if (result.status == "not_submitted" and result.no_order
                        and result.evidence.get("click_rejected") is True):
                    return fallback(cand, "click_rejected")

                not_on_sale = (result.status == "not_submitted" and result.no_order
                               and result.evidence.get("not_on_sale") is True)
                if not_on_sale:
                    if presale_retries < len(retry_delays) and not self.stop():
                        delay = retry_delays[presale_retries]
                        presale_retries += 1
                        self.log(f"{cand.train_code} {cand.seat} 官方仍提示未到起售时间，{delay:g} 秒后重试"
                                 f"（{presale_retries}/{len(retry_delays)}）。")
                        self.wait(delay)
                        continue
                    return fallback(cand, "not_on_sale")

                if result.can_fallback:
                    sold_out_list.append(cand)
                    self.log(f"{cand.train_code} {cand.seat} 预填提交确认售罄，继续检查下一候选。")
                    break

                return PrefillExecutionOutcome("handled", tuple(sold_out_list), intent, result)

        return PrefillExecutionOutcome("sold_out_all", tuple(sold_out_list), last_intent, last_result)
