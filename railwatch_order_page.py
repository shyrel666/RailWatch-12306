"""Conservative adapters for page-visible 12306 order forms and order records.

No order APIs, page globals, payment clicks, or generic success-message detection.
Unknown layouts fail closed and retain the durable intent for reconciliation.
"""
from __future__ import annotations

import re
import time
from urllib.parse import urlparse
from selenium.webdriver.common.by import By
from railwatch_orders import OrderResult


SNAPSHOT_JS = r"""
const visible = e => !!(e && e.getClientRects().length);
const txt = e => (e?.innerText || '').replace(/\s+/g,' ').trim();
const all = (s,r=document) => [...r.querySelectorAll(s)].filter(visible);
const val = (s,r=document) => {const e=r.querySelector(s);return e?.value || txt(e);};
function passengers(root) {
  const named=all('.passenger-name strong[title],.name-yichu[title],.passenger-info .name[title]',root).map(e=>e.getAttribute('title').trim());
  if(named.length) return named;
  const fields=all('input[id^="passenger_name_"],input.name-input',root).map(e=>e.value.trim()).filter(Boolean);
  if(fields.length) return fields;
  const names=[];
  for(const table of all('table',root)) {
    const headers=[...table.querySelectorAll('th')].map(txt);
    const i=headers.findIndex(h=>h==='姓名'||h==='乘车人');
    if(i<0) continue;
    for(const row of all('tr',table)) {
      const cells=row.querySelectorAll('td');
      if(cells.length>i) {const name=val('input',cells[i])||txt(cells[i]); if(name) names.push(name);}
    }
  }
  return names;
}
const cards=all('#ticket_card_list .ticket-card');
const details=cards.map(c=>({train:txt(c.querySelector('.ticket-number')),
 date:txt(c.querySelector('.ticket-date')),
 from:c.querySelector('.ticket-station-start .ticket-station-name')?.getAttribute('title')||'',
 to:c.querySelector('.ticket-station-end .ticket-station-name')?.getAttribute('title')||'',
 seat:txt(c.querySelector('.ticket-info-txt span'))}));
const orders=all('.order-item').map(root=>{
 const header=txt(root.querySelector('.order-item-hd'));
 const orderId=header.match(/(?:候补单号|订单号|订单号码)\s*[：:]\s*([A-Za-z0-9]+)/)?.[1]||'';
 const state=all('.order-item-hd .pull-right,.order-item-hd .txt-second,.order-status',root).map(txt).join(' ');
 const payment=all('a,button',root).some(e=>/^(去支付|立即支付|网上支付|继续支付|支付)$/.test(txt(e)));
 const body=[];
 const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
 while(walker.nextNode()) {
   const node=walker.currentNode;
   if(visible(node.parentElement) && !node.parentElement.closest('.order-item-hd,.order-item-ft')) body.push(node.textContent);
 }
 return {order_id:orderId,kind:header.includes('候补单号')?'alternate':'regular',
   text:body.join(' ').replace(/\s+/g,' ').trim(),state,payment,passengers:passengers(root)};
});
const dialogs=all('.dhtmlx_window_active,.layui-layer,.modal,[role="dialog"],.up-box').map(txt).filter(Boolean);
const regularRoot=document.querySelector('#ticket_info');
return {url:location.href, orders, dialogs, details,
 regular:txt(regularRoot), passengers:passengers(document),
 seats:all('select[id^="seatType_"]').map(e=>e.selectedOptions[0]?.textContent.trim()||''),
 deadline:val('#dafaultTime')||val('#deadline_time')||val('input.deadline-time'),
 extra:all('#planList .group-ticket').length,
 addedTrain:!!document.querySelector('#addTrainInput:checked'),
 standing:txt(document.querySelector('#is_open')),
 pendingEmpty:all('#J-order-payment,#not_complete').some(e=>/您没有待支付|没有未完成|暂无待支付/.test(txt(e))) && orders.length===0 && !all('.loading,.loading-box,#J-loading').length,
 formReady:visible(document.querySelector('#normal_passenger_id')) || visible(document.querySelector('#passenge_list')),
 confirmation:visible(document.querySelector('#qr_submit_id')),
 verification:all('#nc_1_n1z,.nc_scale,.slide-verify,#randCode,#J-loginImg').length>0,
 processing:all('.order-queue').some(e=>/排队|处理中/.test(txt(e))) };
"""

SELECT_PASSENGERS_JS = r"""
const wanted=arguments[0];
const visible=e=>!!(e&&e.getClientRects().length);
const inputs=[...document.querySelectorAll('#normal_passenger_id input[type="checkbox"],#passenge_list input.chose-pass-dom')].filter(visible);
const name=e=> {const l=e.closest('label')||document.querySelector('label[for="'+e.id+'"]');
 return (l?.getAttribute('title') || (l?.innerText||'').replace(/（(?:学生|儿童|成人)）/g,'')).trim();};
if(!wanted.length || wanted.some(n=>inputs.filter(e=>name(e)===n).length!==1)) return false;
for(const input of inputs) {
 const select=wanted.includes(name(input));
 if(input.checked!==select) {if(input.disabled)return false;input.click();}
}
const actual=inputs.filter(e=>e.checked).map(name);
return actual.length===wanted.length && wanted.every(n=>actual.includes(n));
"""


def normalized_date(value):
    match = re.search(r"(\d{4})[-年/](\d{1,2})[-月/](\d{1,2})", str(value))
    return "{}-{:02d}-{:02d}".format(match[1], int(match[2]), int(match[3])) if match else ""


def contains_token(text, token):
    # Avoid matching G1 inside G101, or a passenger name inside a longer name.
    return bool(token and re.search(r"(?<![\w])" + re.escape(token) + r"(?![\w])", text))


def record_matches(record, intent):
    text = record.get("text", "")
    dates = {normalized_date(m[0]) for m in re.finditer(r"\d{4}[-年/]\d{1,2}[-月/]\d{1,2}", text)}
    trains = set(re.findall(r"(?<![\w])[GDCZTKYSL]?\d{1,5}(?![\w])", re.sub(r"\d{4}[-年/]\d{1,2}[-月/]\d{1,2}(?:日)?|\d{1,2}:\d{2}", "", text)))
    # Prefixed train codes must form one combination. Plain numbers elsewhere in
    # an order (fares, coach numbers) are not additional train codes.
    trains = {value for value in trains if value[0].isalpha() or value == intent.train_code}
    seats = {value for value in ("二等座", "一等座", "商务座", "特等座", "无座", "硬座", "软座", "硬卧", "软卧", "高级软卧", "动卧") if contains_token(text, value)}
    return (record.get("kind") == intent.kind and contains_token(text, intent.train_code)
            and trains == {intent.train_code} and dates == {intent.date} and seats == {intent.seat}
            and all(contains_token(text, item) for item in (intent.from_station, intent.to_station, intent.seat))
            and text.index(intent.from_station) < text.index(intent.to_station)
            and sorted(record.get("passengers", [])) == sorted(intent.passengers))


class OrderPage:
    def __init__(self, driver, stop=lambda: False, wait=None, mark=None, *, allow_fixture=False):
        self.driver, self.stop = driver, stop
        self.allow_fixture = allow_fixture
        self.wait = wait or time.sleep
        self.mark = mark or (lambda stage, detail=None: None)

    def snapshot(self):
        try:
            value = self.driver.execute_script(SNAPSHOT_JS)
            if isinstance(value, dict):
                origin = urlparse(value.get("url", ""))
                if (origin.hostname == "kyfw.12306.cn" and origin.scheme == "https") or (self.allow_fixture and origin.scheme == "file"):
                    return value
            return {}
        except Exception:
            return {}

    def result(self, intent, *, submitted=False, known_id="", allow_empty=False):
        snap = self.snapshot()
        if not snap:
            return OrderResult("unknown", "无法读取订单页面")
        # Only an identified, matching order can establish payment or fulfillment.
        matching = [r for r in snap.get("orders", []) if r.get("order_id")
                    and record_matches(r, intent) and (not known_id or r["order_id"] == known_id)]
        if len(matching) == 1:
            record = matching[0]
            state = record.get("state", "")
            stage = None
            if re.search("兑现失败", state): stage = "failed"
            elif re.search("已取消|已退单", state): stage = "cancelled"
            elif re.search("已过期|支付超时", state): stage = "expired"
            elif re.search("兑现成功|已兑现|交易成功", state): stage = "fulfilled"
            elif re.search("已支付", state): stage = "active" if intent.kind == "alternate" else "fulfilled"
            elif re.search("待兑现|候补中", state) and intent.kind == "alternate": stage = "active"
            elif record.get("payment") or re.search("待支付|等待支付", state): stage = "pending_payment"
            if stage:
                return OrderResult(stage, order_id=record["order_id"], evidence={
                    "matched": True, "url": snap.get("url", "").split("?")[0],
                    "observed_at": time.time(), "state": state[:100]})
        dialogs = " ".join(snap.get("dialogs", []))
        if snap.get("verification") or re.search(r"登录|核验|验证码|滑块|频繁|操作过快|稍后再试|候补.*(?:上限|限额)", dialogs) or re.search(r"login\.html|/login/init", snap.get("url", "")):
            return OrderResult("verification", "请在官方页面完成登录、核验或处理限制")
        if snap.get("processing"):
            return OrderResult("unknown", "官方仍在处理订单，请勿重复提交")
        # An explicit rejection before final submission cannot have created an order.
        if re.search(r"余票不足|车票已售罄|没有足够的余票|席位已售完", dialogs):
            return OrderResult("sold_out" if not submitted else "unknown", "官方提示余票不足",
                               no_order=not submitted)
        if dialogs and not snap.get("confirmation"):
            return OrderResult("verification", "存在未识别的订单提示，请在官方页面检查")
        if snap.get("pendingEmpty") and not known_id and (not submitted or allow_empty):
            return OrderResult("not_submitted", "官方待支付订单列表明确为空", no_order=True)
        return OrderResult("unknown", "未获得匹配的订单证据，请打开官方订单详情核对")

    def poll(self, predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while not self.stop():
            value = predicate()
            if value:
                return value
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            self.wait(min(0.1, remaining))
        return None

    def button(self, selectors):
        for selector in selectors:
            try:
                for element in self.driver.find_elements(By.CSS_SELECTOR, selector):
                    if element.is_displayed() and element.is_enabled() and element.get_attribute("aria-disabled") != "true":
                        return element
            except Exception:
                continue
        return None

    def verify_form(self, intent):
        snap = self.snapshot()
        if not intent.passengers or sorted(snap.get("passengers", [])) != sorted(intent.passengers):
            return False
        if intent.kind == "alternate":
            details = snap.get("details", [])
            if len(details) != 1 or snap.get("extra") or snap.get("addedTrain"):
                return False
            card = details[0]
            return (card.get("train") == intent.train_code and normalized_date(card.get("date")) == intent.date
                    and card.get("from") == intent.from_station and card.get("to") == intent.to_station
                    and card.get("seat") == intent.seat and intent.deadline
                    and self.deadline_matches(snap.get("deadline", ""), intent.deadline, intent.date)
                    and snap.get("standing", "").replace(" ", "") == "已关闭")
        text = snap.get("regular", "")
        return (contains_token(text, intent.train_code) and normalized_date(text) == intent.date
                and contains_token(text, intent.from_station) and contains_token(text, intent.to_station)
                and snap.get("seats") == [intent.seat] * len(intent.passengers))

    def prepare_people(self, intent):
        selected = self.driver.execute_script(SELECT_PASSENGERS_JS, list(intent.passengers)) is True
        if not selected:
            expand = self.button(("#order_toggle",))
            if expand and expand.text.strip() == "展开":
                expand.click()
                selected = self.driver.execute_script(SELECT_PASSENGERS_JS, list(intent.passengers)) is True
        return selected

    @staticmethod
    def deadline_matches(actual, expected, travel_date):
        if not actual or not expected:
            return False
        def relative_minutes(value):
            match = re.fullmatch(r"开车前\s*(\d+)\s*(分钟|小时)", value.strip())
            return int(match[1]) * (60 if match[2] == "小时" else 1) if match else None
        expected_relative = relative_minutes(expected)
        if expected_relative is not None:
            return relative_minutes(actual) == expected_relative
        expected_date = normalized_date(expected) or travel_date
        expected_time = re.search(r"\d{2}:\d{2}", expected)
        actual_time = re.search(r"\d{2}:\d{2}", actual)
        return bool(expected_time and actual_time and expected_time[0] == actual_time[0]
                    and normalized_date(actual) == expected_date)

    def set_deadline(self, deadline, travel_date):
        if not deadline:
            return False
        # Select an existing official option; never synthesize unsupported values.
        current = self.snapshot().get("deadline", "").strip()
        if self.deadline_matches(current, deadline, travel_date):
            return True
        selector = self.button(("#dafaultTime",))
        if selector:
            selector.click()
            options = [option for option in self.driver.find_elements(By.CSS_SELECTOR, "#date_box li")
                       if option.is_displayed() and self.deadline_matches(option.text, deadline, travel_date)]
            if len(options) == 1:
                options[0].click()
                return bool(self.poll(lambda: self.deadline_matches(self.snapshot().get("deadline", ""), deadline, travel_date), 2))
        return False

    def wait_result(self, intent, submitted=True):
        def terminal():
            result = self.result(intent, submitted=submitted)
            return result if result.status != "unknown" else None
        return self.poll(terminal) or self.result(intent, submitted=submitted)

    def reconcile(self, intent, known_id="", navigate=False, allow_empty=False):
        result = self.result(intent, submitted=True, known_id=known_id, allow_empty=allow_empty)
        if result.status not in ("unknown", "verification") or not navigate:
            return result
        # Explicit recovery action only: normal payment observation never navigates away.
        if self.stop():
            return result
        url = "https://kyfw.12306.cn/otn/view/" + ("lineUp_order.html" if intent.kind == "alternate" else "train_order.html")
        try:
            self.driver.get(url)
            return self.poll(lambda: self._resolved(intent, known_id, allow_empty)) or self.result(intent, submitted=True, known_id=known_id, allow_empty=allow_empty)
        except Exception:
            return OrderResult("unknown", "订单核对失败，请保留当前订单并在官方页面核查", order_id=known_id)

    def _resolved(self, intent, known_id, allow_empty=False):
        result = self.result(intent, submitted=True, known_id=known_id, allow_empty=allow_empty)
        return result if result.status != "unknown" else None

    def regular(self, button, intent):
        submitted = False
        try:
            if button is not None:
                button.click()
            def ready():
                result = self.result(intent)
                return result if result.status in ("sold_out", "verification", "pending_payment", "fulfilled") else self.snapshot().get("formReady")
            ready_result = self.poll(ready)
            if isinstance(ready_result, OrderResult): return ready_result
            if not ready_result or not self.prepare_people(intent):
                return OrderResult("verification", "乘车人未能唯一匹配，请检查官方页面")
            selects = self.driver.find_elements(By.CSS_SELECTOR, 'select[id^="seatType_"]')
            from selenium.webdriver.support.ui import Select
            for select in selects:
                if select.is_displayed(): Select(select).select_by_visible_text(intent.seat)
            if not self.poll(lambda: self.verify_form(intent), 2):
                return OrderResult("verification", "车次、日期、区间、乘客或席别回读不一致")
            submit = self.button(("#submitOrder_id",))
            if not submit: return OrderResult("not_submitted", "提交按钮不可用", no_order=True)
            if self.stop(): return OrderResult("not_submitted", "提交前已停止", no_order=True)
            self.mark("regular_submit")
            submitted = True  # Set before click: a transport error may follow a successful action.
            submit.click()
            def confirm_or_result():
                result = self.result(intent, submitted=True)
                return result if result.status != "unknown" else self.button(("#qr_submit_id",))
            confirm = self.poll(confirm_or_result)
            if isinstance(confirm, OrderResult): return confirm
            if confirm and not self.stop():
                if not self.verify_form(intent):
                    return OrderResult("verification", "确认购买前订单信息发生变化")
                confirm.click()  # Never repeat an ambiguous confirmation click.
            return self.wait_result(intent)
        except Exception:
            return self.result(intent, submitted=submitted)

    def alternate(self, button, intent):
        submitted = False
        try:
            # One seat-specific button has already been chosen by the query adapter.
            if button is not None:
                self.mark("alternate_first_action")
                button.click()
            def order_page():
                result = self.result(intent)
                if result.status == "verification": return result
                if self.snapshot().get("details"): return True
                return self.button(("#hbSubmit",))
            next_step = self.poll(order_page)
            if isinstance(next_step, OrderResult): return next_step
            if next_step is not True and next_step is not None:
                next_step.click()
            if not self.poll(lambda: self.snapshot().get("details")):
                return OrderResult("verification", "请检查候补需求清单并进入候补订单页")
            if not self.prepare_people(intent) or not self.set_deadline(intent.deadline, intent.date):
                return OrderResult("verification", "乘客或截止兑现时间未能回读确认")
            if not self.verify_form(intent):
                return OrderResult("verification", "候补组合不匹配，或包含额外车次、席别、无座设置")
            submit = self.button(("#toPayBtn",))
            if not submit: return OrderResult("not_submitted", "候补提交按钮不可用", no_order=True)
            if self.stop(): return OrderResult("not_submitted", "提交前已停止", no_order=True)
            self.mark("alternate_submit")
            submitted = True
            submit.click()
            return self.wait_result(intent)
        except Exception:
            return self.result(intent, submitted=submitted)
