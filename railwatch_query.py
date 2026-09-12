"""Page-visible query transactions. No direct ticket API requests."""
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
import math
import time
import uuid


@dataclass(frozen=True)
class FillResult:
    status: str
    reason: str = ""

    def __bool__(self):
        return self.status == "success"


def fill_result(value):
    if isinstance(value, FillResult):
        return value
    return FillResult("success" if value is True else "retry", "查询参数未写入")


def parse_retry_after(value, response_date=None):
    """Read delta-seconds or HTTP-date; use the response clock when available."""
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        return None
    value = value.strip()
    try:
        if value.isascii() and value.isdigit():
            seconds = float(value)
        else:
            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                return None
            reference = time.time()
            if isinstance(response_date, str) and response_date:
                try:
                    server_date = parsedate_to_datetime(response_date)
                    if server_date.tzinfo is not None:
                        reference = server_date.timestamp()
                except (TypeError, ValueError, OverflowError):
                    pass
            seconds = max(0.0, target.timestamp() - reference)
        return seconds if math.isfinite(seconds) else None
    except (TypeError, ValueError, OverflowError):
        return None


FILL_QUERY_FORM_JS = r"""
const ids = ['fromStationText','fromStation','toStationText','toStation','train_date'];
const values = [arguments[0],arguments[1],arguments[2],arguments[3],arguments[4]];
const elements = ids.map(id => document.getElementById(id));
if (elements.some(el => !el)) return false;
elements.forEach((el,i) => {
  el.removeAttribute('readonly'); el.value = values[i];
  el.dispatchEvent(new Event('input',{bubbles:true}));
  el.dispatchEvent(new Event('change',{bubbles:true}));
});
return elements.every((el,i) => el.value === values[i]);
"""

FORM_SNAPSHOT_JS = r"""
if (!window.__railwatchPageId) window.__railwatchPageId = arguments[0];
const ids = ['fromStationText','fromStation','toStationText','toStation','train_date'];
const values = ids.map(id => document.getElementById(id)?.value ?? null);
return {page:window.__railwatchPageId, values};
"""

DIALOG_INSPECT_JS = r"""
const visible = el => !!(el && el.getClientRects().length);
const dialogs = [...document.querySelectorAll('.dhtmlx_window_active,.layui-layer,.modal,[role="dialog"]')].filter(visible);
let safe = null;
for (const dialog of dialogs) {
  const text = (dialog.innerText || dialog.textContent || '').replace(/\s+/g,' ').trim();
  const sensitive = /登录|核验|验证|订单|提交|支付|频繁|操作过快|稍后再试/.test(text);
  const allowed = /未到起售时间|尚未起售/.test(text) && !sensitive;
  const result = {kind: sensitive ? 'human_action' : allowed ? 'not_on_sale' : 'unknown', text};
  if (!allowed) return result;
  safe = result;
}
const verification = document.querySelector('#nc_1_n1z,.nc_scale,.nc-container,.slide-verify,#J-loginImg,#randCode');
if (visible(verification) || /login\.html|\/otn\/login\/init/.test(location.href))
  return {kind:'human_action',text:'请在浏览器中完成登录或核验'};
return safe || {kind:'none',text:''};
"""

DISMISS_DIALOG_JS = r"""
const expected = arguments[0];
const visible = el => !!(el && el.getClientRects().length);
for (const dialog of document.querySelectorAll('.dhtmlx_window_active,.layui-layer,.modal,[role="dialog"]')) {
  if (!visible(dialog)) continue;
  const text = (dialog.innerText || dialog.textContent || '').replace(/\s+/g,' ').trim();
  if (text !== expected || !/未到起售时间|尚未起售/.test(text) || /登录|核验|验证|订单|提交|支付|频繁|操作过快|稍后再试/.test(text)) continue;
  for (const button of dialog.querySelectorAll('a,button,input[type="button"]')) {
    if (visible(button) && !button.disabled && button.getAttribute('aria-disabled') !== 'true'
        && /^(确定|确认|知道了|好|关闭)$/.test((button.innerText || button.textContent || button.value || '').trim())) {
      button.click(); return true;
    }
  }
}
return false;
"""

QUERY_BEGIN_JS = r"""
// Observe the page's own requests without issuing requests or reading ticket data.
// A DOM mutation alone (e.g. opening train details) is not query completion.
if (!window.__railwatchTransport) {
  const urls = new WeakMap();
  const begin = input => {
    let url;
    try { url = new URL(input, location.href); } catch { return null; }
    if (url.origin !== location.origin || !/^\/otn\/leftTicket\/query[A-Za-z]*$/.test(url.pathname)) return null;
    const state = window.__railwatchQuery;
    if (!state) return null;
    const expected = state.conditions;
    const fields = ['leftTicketDTO.from_station','leftTicketDTO.to_station','leftTicketDTO.train_date'];
    if (fields.some((key,i) => url.searchParams.get(key) !== expected[i])) {
      state.invalidated = true;
      return null;
    }
    state.requests++;
    if (state.requests !== 1) state.invalidated = true;
    return (status, retryAfter=null, responseDate=null) => {
      if (window.__railwatchQuery !== state) {
        if (window.__railwatchQuery) window.__railwatchQuery.invalidated = true;
        return;
      }
      state.responseFinished = status >= 200 && status < 300;
      if (!state.responseFinished) {
        state.invalidated = true;
        // Keep explicit throttling evidence even if another response interferes.
        if (!state.failure || status === 429) state.failure = {
          http_status:status, retry_after:retryAfter, response_date:responseDate
        };
      }
    };
  };
  const open = XMLHttpRequest.prototype.open;
  const send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(method, url, ...rest) {
    urls.set(this, url);
    return open.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.send = function(...args) {
    const finish = begin(urls.get(this));
    if (finish) this.addEventListener('loadend', () => finish(this.status,
      this.getResponseHeader('Retry-After'), this.getResponseHeader('Date')), {once:true});
    return send.apply(this, args);
  };
  if (window.fetch) {
    const fetch = window.fetch;
    window.fetch = function(input, ...args) {
      const finish = begin(typeof input === 'string' || input instanceof URL ? input : input.url);
      const result = fetch.call(this, input, ...args);
      if (finish) result.then(response => finish(response.status,
        response.headers.get('Retry-After'), response.headers.get('Date')), () => finish(0));
      return result;
    };
  }
  window.__railwatchTransport = true;
}
window.__railwatchQuery?.observer?.disconnect();
const token = arguments[0];
const state = {token, changed:false, last:performance.now(), revision:0,
  requests:0, responseFinished:false, invalidated:false,
  conditions:['fromStation','toStation','train_date'].map(id => document.getElementById(id)?.value)};
state.observer = new MutationObserver(records => {
  const table = document.getElementById('queryLeftTable');
  const relevant = records.some(r => {
    if (r.type === 'attributes') return false;
    const element = r.target.nodeType === 1 ? r.target : r.target.parentElement;
    const cell = element?.closest('td[id]');
    if (table?.contains(cell) && /^(ZE|ZY|SWZ|TZ|WZ|YZ|RZ|YW|RW|GR|SRRB)_/.test(cell.id)) return true;
    if (element?.closest('#no_filter_ticket,#no_filter_ticket_6,[data-query-empty]')) return true;
    if (r.target === table) return true;
    return [...r.addedNodes,...r.removedNodes].some(n => n.nodeType === 1 &&
      (n.id === 'queryLeftTable' || n.querySelector?.('#queryLeftTable') ||
       (table?.contains(r.target) && (n.matches('tr[id^="ticket_"]') || n.querySelector('tr[id^="ticket_"]')))));
  });
  if (relevant) { state.changed=true; state.last=performance.now(); state.revision++; }
});
state.observer.observe(document.body,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['disabled','aria-busy']});
window.__railwatchQuery = state;
return true;
"""

QUERY_STATUS_JS = r"""
const state = window.__railwatchQuery;
if (!state || state.token !== arguments[0]) return {status:'invalid'};
if (state.invalidated) return {status:'invalid', ...state.failure};
const button = document.getElementById('query_ticket');
const loading = !!(button && (button.disabled || button.getAttribute('aria-busy') === 'true'));
const table = document.getElementById('queryLeftTable');
const rows = table ? [...table.querySelectorAll('tr[id^="ticket_"]')] : [];
const emptyBox = document.querySelector('#no_filter_ticket,#no_filter_ticket_6,[data-query-empty]');
const empty = (emptyBox && emptyBox.getClientRects().length && /没有|未查询到|暂无/.test(emptyBox.textContent || ''))
 || (table && /没有符合条件|没有查询到|未查询到|暂无.*车次/.test(table.textContent || ''));
const completed = state.responseFinished && state.changed && !loading && performance.now()-state.last >= 300;
return {status:completed && rows.length ? 'ok' : completed && empty ? 'empty' : 'pending', revision:state.revision};
"""


class QueryExecutor:
    def __init__(self, driver, stop_check=lambda: False, wait=None, tick=lambda: None):
        self.driver = driver
        self.stop_check = stop_check
        self.wait = wait or time.sleep
        self.tick = tick
        self.snapshot = None
        self.token = None
        self.revision = None

    def inspect_dialog(self):
        result = self.driver.execute_script(DIALOG_INSPECT_JS)
        return result if isinstance(result, dict) else {"kind": "unknown", "text": "无法确认页面状态"}

    def snapshot_form(self):
        return self.driver.execute_script(FORM_SNAPSHOT_JS, uuid.uuid4().hex)

    def current(self):
        if self.stop_check() or self.snapshot_form() != self.snapshot:
            return False
        if self.inspect_dialog()["kind"] != "none":
            return False
        status = self.driver.execute_script(QUERY_STATUS_JS, self.token)
        return isinstance(status, dict) and status.get("status") in ("ok", "empty") and status.get("revision") == self.revision

    def execute(self, click, timeout):
        self.token = uuid.uuid4().hex
        self.snapshot = self.snapshot_form()
        self.revision = None
        if not isinstance(self.snapshot, dict) or len(self.snapshot.get("values", [])) != 5 or any(v in (None, "") for v in self.snapshot.get("values", [])):
            return {"status": "invalid", "reason": "查询字段不完整"}
        dialog = self.inspect_dialog()
        if dialog["kind"] != "none":
            return {"status": dialog["kind"], "reason": dialog["text"]}
        if self.stop_check():
            return {"status": "cancelled"}
        self.driver.execute_script(QUERY_BEGIN_JS, self.token)
        deadline = time.monotonic() + timeout
        if not click():
            dialog = self.inspect_dialog()
            return {"status": dialog["kind"] if dialog["kind"] != "none" else "timeout", "reason": dialog["text"]}
        while time.monotonic() < deadline:
            self.tick()
            if self.stop_check():
                return {"status": "cancelled"}
            if self.snapshot_form() != self.snapshot:
                return {"status": "invalid", "reason": "页面或查询条件已改变"}
            dialog = self.inspect_dialog()
            if dialog["kind"] != "none":
                return {"status": dialog["kind"], "reason": dialog["text"]}
            result = self.driver.execute_script(QUERY_STATUS_JS, self.token)
            if isinstance(result, dict) and result.get("status") == "invalid":
                http_status = result.get("http_status")
                retry_after = parse_retry_after(result.get("retry_after"), result.get("response_date"))
                if http_status == 429 or (http_status == 503 and retry_after is not None):
                    return {**result, "status": "rate_limited" if http_status == 429 else "server_backoff",
                            "reason": f"查询收到 HTTP {http_status}", "retry_after_seconds": retry_after}
                return {**result, "reason": "本轮请求失败或有其他查询响应干扰"}
            if isinstance(result, dict) and result.get("status") in ("ok", "empty"):
                self.revision = result.get("revision")
                return {**result, "query_id": self.token, "conditions": self.snapshot, "fetched_at": time.time()}
            self.wait(0.1)
        return {"status": "timeout", "reason": "未观察到本轮查询完成"}


LOGIN_CHECK_JS = r"""
const done = arguments[arguments.length-1];
if (location.hostname !== 'kyfw.12306.cn') { done('unknown'); return; }
const abort = new AbortController();
let finished = false;
const finish = value => { if (!finished) { finished=true; clearTimeout(timer); done(value); } };
const timer = setTimeout(() => { abort.abort(); finish('unknown'); }, 2800);
fetch('/otn/login/checkUser',{credentials:'include',signal:abort.signal})
 .then(r => r.ok ? r.json() : Promise.reject())
 .then(data => finish(data?.data?.flag === true ? 'ok' : data?.data?.flag === false ? 'expired' : 'unknown'))
 .catch(() => finish('unknown'));
"""
