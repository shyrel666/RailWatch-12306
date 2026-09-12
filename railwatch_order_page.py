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
return {url:location.href, orders, dialogs, details,
 regular:txt(document.querySelector('#ticket_info')||document.querySelector('#ticket_tit_id')), passengers:passengers(document),
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

SEAT_PREFERENCE_JS = r"""
const wanted = arguments[0] === '靠窗优先' ? ['A','F','靠窗','窗'] : ['C','D','靠过道','过道'];
const count = arguments[1];
const visible = e => !!(e && e.getClientRects().length);
const selects = [...document.querySelectorAll('select')].filter(e => visible(e) && !e.disabled &&
  !/^seatType_/.test(e.id) && [...e.options].some(o => wanted.includes(o.text.trim())));
if (selects.length === count) {
  for (const select of selects) {
    const option = [...select.options].find(o => !o.disabled && wanted.includes(o.text.trim()));
    if (!option) return false;
    select.value = option.value;
    select.dispatchEvent(new Event('change',{bubbles:true}));
  }
  return selects.every(e => wanted.includes(e.selectedOptions[0]?.text.trim()));
}
const choices = [...document.querySelectorAll('#erdeng1 a,#yideng1 a,#seat_select [data-seat]')]
  .filter(e => visible(e) && !e.classList.contains('disabled') && e.getAttribute('aria-disabled') !== 'true');
const label = e => (e.getAttribute('data-seat') || e.textContent).trim();
const selected = e => e.classList.contains('cur') || e.classList.contains('selected') || e.getAttribute('aria-pressed') === 'true';
const targets = choices.filter(e => wanted.includes(label(e)));
if (targets.length < count) return false;
const picked = targets.slice(0,count);
for (const choice of choices) if (selected(choice) !== picked.includes(choice)) choice.click();
const actual = choices.filter(selected);
return actual.length === count && actual.every(e => picked.includes(e));
"""


def normalized_date(value):
    match = re.search(r"(\d{4})[-年/](\d{1,2})[-月/](\d{1,2})", str(value))
    return "{}-{:02d}-{:02d}".format(match[1], int(match[2]), int(match[3])) if match else ""


_TOKEN_START = r"(?:(?<![0-9A-Za-z\u4e00-\u9fff])|(?<=次))"


def contains_token(text, token):
    # Avoid matching G1 inside G101, or a passenger name inside a longer name.
    # \w also matches CJK in Python, which would reject the packed official
    # format "G1307次北京丰台站"; a token may sit flush only behind the train
    # suffix 次, never inside a longer station or passenger name.
    return bool(token and re.search(_TOKEN_START + re.escape(token)
                                   + r"(?![0-9A-Za-z\u4e00-\u9fff])", str(text)))


def train_token(text, code):
    # The code may run flush into the next field: "G1307次北京丰台站（09:29开）".
    return bool(code and re.search(_TOKEN_START + re.escape(code)
                                   + r"(?:\s*次)?(?![0-9A-Za-z])", str(text)))


def seat_label(value):
    """Remove only a displayed fare, retaining the exact seat class."""
    return re.sub(r"\s*[（(]\s*[¥￥]?\s*\d+(?:\.\d+)?\s*元\s*[）)]\s*$", "", str(value)).strip()


def form_token(text, token, suffix):
    # The optional suffix (次/站) absorbs the official page's glued layout; the
    # CJK end boundary keeps 北京 from matching inside 北京南.
    return bool(token and re.search(_TOKEN_START + re.escape(token)
                                   + r"(?:\s*" + suffix + r")?(?![0-9A-Za-z\u4e00-\u9fff])", str(text)))


def record_matches(record, intent):
    text = record.get("text", "")
    dates = {normalized_date(m[0]) for m in re.finditer(r"\d{4}[-年/]\d{1,2}[-月/]\d{1,2}", text)}
    trains = set(re.findall(r"(?<![0-9A-Za-z])([GDCZTKYSL]\d{1,5}|\d{1,5})(?![0-9A-Za-z])",
                            re.sub(r"\d{4}[-年/]\d{1,2}[-月/]\d{1,2}(?:日)?|\d{1,2}:\d{2}", "", text)))
    # Prefixed train codes must form one combination. Plain numbers elsewhere in
    # an order (fares, coach numbers) are not additional train codes.
    trains = {value for value in trains if value[0].isalpha() or value == intent.train_code}
    seats = {value for value in ("二等座", "一等座", "商务座", "特等座", "无座", "硬座", "软座", "硬卧", "软卧", "高级软卧", "动卧") if contains_token(text, value)}
    return (record.get("kind") == intent.kind and train_token(text, intent.train_code)
            and trains == {intent.train_code} and dates == {intent.date} and seats == {intent.seat}
            and all(contains_token(text, item) for item in (intent.from_station, intent.to_station, intent.seat))
            and text.index(intent.from_station) < text.index(intent.to_station)
            and sorted(record.get("passengers", [])) == sorted(intent.passengers))


class OrderPage:
    def __init__(self, driver, stop=lambda: False, wait=None, mark=None, *, allow_fixture=False, log=None):
        self.driver, self.stop = driver, stop
        self.allow_fixture = allow_fixture
        self.wait = wait or time.sleep
        self.mark = mark or (lambda stage, detail=None: None)
        self.log = log or (lambda message: None)

    def apply_seat_preference(self, preference, passenger_count):
        if preference not in ("靠窗优先", "靠过道优先"):
            return False
        return self.driver.execute_script(SEAT_PREFERENCE_JS, preference, passenger_count) is True

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

    def poll(self, predicate, timeout=10, ignore_stop=False):
        deadline = time.monotonic() + timeout
        while ignore_stop or not self.stop():
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

    def form_mismatch_report(self, intent):
        """Expected/actual diff for the pre-submit readback, safe for the event log."""
        snap = self.snapshot()
        if not snap:
            return "无法读取订单页面"
        text = snap.get("regular", "")
        actual_passengers = snap.get("passengers", [])
        masked = str(text)
        for name in sorted(set(intent.passengers) | set(actual_passengers), key=len, reverse=True):
            if not name:
                continue
            masked = masked.replace(name, "＜乘客＞")
        fields = [
            ("车次", intent.train_code + "次", "未读到", train_token(text, intent.train_code)),
            ("日期", intent.date, normalized_date(text) or "未读到", normalized_date(text) == intent.date),
            ("出发站", intent.from_station + "站", "未读到", form_token(text, intent.from_station, "站")),
            ("到达站", intent.to_station + "站", "未读到", form_token(text, intent.to_station, "站")),
            ("乘车人", f"{len(intent.passengers)} 位指定乘客", f"{len(actual_passengers)} 位，名单不一致",
             sorted(actual_passengers) == sorted(intent.passengers)),
            ("席别", "、".join([intent.seat] * len(intent.passengers)),
             "、".join(seat_label(value) for value in snap.get("seats", [])) or "未读到",
             [seat_label(value) for value in snap.get("seats", [])] == [intent.seat] * len(intent.passengers)),
        ]
        failed = "；".join(f"{name}：期望 {want}，实际 {got}" for name, want, got, matches in fields if not matches)
        if (form_token(text, intent.from_station, "站") and form_token(text, intent.to_station, "站")
                and text.index(intent.from_station) >= text.index(intent.to_station)):
            failed += "；区间：出发站与到达站顺序不一致"
        summary = f"；页面摘要：{masked[:120]}" if masked else "；页面摘要为空"
        return (failed or "各字段均已读到") + summary

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
        return (train_token(text, intent.train_code) and normalized_date(text) == intent.date
                and form_token(text, intent.from_station, "站") and form_token(text, intent.to_station, "站")
                and text.index(intent.from_station) < text.index(intent.to_station)
                and [seat_label(value) for value in snap.get("seats", [])] == [intent.seat] * len(intent.passengers))

    def select_regular_seats(self, intent):
        from selenium.webdriver.support.ui import Select
        selects = [Select(element) for element in self.driver.find_elements(By.CSS_SELECTOR, 'select[id^="seatType_"]')
                   if element.is_displayed()]
        if len(selects) != len(intent.passengers):
            return False
        choices = [[option for option in select.options
                    if option.is_enabled() and seat_label(option.text) == intent.seat] for select in selects]
        if any(len(options) != 1 for options in choices):
            return False
        for select, options in zip(selects, choices):
            select.select_by_index(options[0].get_attribute("index"))
        return True

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

    def wait_result(self, intent, submitted=True, timeout=10):
        def terminal():
            result = self.result(intent, submitted=submitted)
            return result if result.status != "unknown" else None
        return self.poll(terminal, timeout) or self.result(intent, submitted=submitted)

    def _post_submit(self, intent, confirmed_clicked):
        """Resolve the outcome after the official submit/confirm step.

        Grab semantics: once the submission is in flight, resolving it is the
        only task left. A still-waiting official dialog is kept untouched for
        the user; a completed confirmation is reconciled on the official order
        page so a created order surfaces as pending payment, not as doubt.
        """
        result = self.wait_result(intent, submitted=True, timeout=20)
        if result.status != "unknown":
            return result
        if self.snapshot().get("confirmation"):
            return OrderResult("verification",
                               "官方确认弹窗仍在等待：请在官方页面点击“确认”，然后回到监控页点击“继续处理”核对订单")
        if confirmed_clicked and not self.stop():
            reconciled = self.reconcile(intent, navigate=True)
            if reconciled.status != "unknown":
                return reconciled
        return result

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

    def regular(self, button, intent, *, seat_preference="无偏好", preference_handler=None):
        submitted = False
        stage = "打开乘车人页面"
        try:
            if button is not None:
                button.click()
            def ready():
                result = self.result(intent)
                return result if result.status in ("sold_out", "verification", "pending_payment", "fulfilled") else self.snapshot().get("formReady")
            ready_result = self.poll(ready)
            if isinstance(ready_result, OrderResult): return ready_result
            stage = "选择乘车人"
            if not ready_result or not self.prepare_people(intent):
                return OrderResult("verification", "乘车人未能唯一匹配，请检查官方页面")
            stage = "选择席别"
            if not self.select_regular_seats(intent):
                return OrderResult("verification", "尚未点击提交订单：席别选项未能唯一匹配，请检查官方页面")
            stage = "核对订单信息"
            if not self.poll(lambda: self.verify_form(intent), 6):
                self.log("回读核对未通过，已停止自动提交：" + self.form_mismatch_report(intent))
                return OrderResult("verification", "车次、日期、区间、乘客或席别回读不一致")
            submit = self.button(("#submitOrder_id",))
            if not submit: return OrderResult("not_submitted", "提交按钮不可用", no_order=True)
            if self.stop(): return OrderResult("not_submitted", "提交前已停止", no_order=True)
            stage = "提交订单"
            self.mark("regular_submit")
            submitted = True  # Set before click: a transport error may follow a successful action.
            submit.click()
            def confirm_or_result():
                result = self.result(intent, submitted=True)
                return result if result.status != "unknown" else self.button(("#qr_submit_id",))
            # The submission is already in flight: keep waiting for the official
            # dialog even across a stop request, so the grab window is spent on
            # completing the order instead of abandoning a submitted form.
            confirm = self.poll(confirm_or_result, ignore_stop=True)
            if isinstance(confirm, OrderResult): return confirm
            confirmed_clicked = False
            if confirm is None:
                confirm = self.button(("#qr_submit_id",))
            if confirm:
                if seat_preference != "无偏好":
                    try:
                        applied = (preference_handler(seat_preference) if preference_handler else
                                   self.apply_seat_preference(seat_preference, len(intent.passengers))) is True
                    except Exception:
                        applied = False
                    self.log(f"座位偏好已回读确认：{seat_preference}" if applied else
                             f"未能应用座位偏好（{seat_preference}），当前页面不支持或可选位置不足，将按官方分配继续。")
                # 核对已在点击“提交订单”前完成。弹窗打开时再回读会把乘客在背景页
                # 和弹窗表格里各读一遍（名单必然不一致），只会白白错失抢票窗口，
                # 因此自动化模式下弹窗出现后直接确认提交。
                self.log("官方确认弹窗已出现，直接点击“确认”提交订单。")
                if self.stop():
                    self.log("已请求停止，但官方确认弹窗已出现：仍完成本次确认，之后只需人工支付。")
                confirmed_clicked = True  # An attempted click may already have reached the server.
                try:
                    confirm.click()  # Never repeat an ambiguous confirmation click.
                except Exception:
                    # A visible button does not prove rejection: the request or
                    # DOM update may still be pending. Only observe/reconcile.
                    self.log("确认购买点击回执异常，将等待并核对订单结果，不自动重复确认。")
            return self._post_submit(intent, confirmed_clicked)
        except Exception as exc:
            # Exception text can contain passenger data and browser internals.
            self.log(f"自动提交在{stage}阶段中断（{type(exc).__name__}）；"
                     + ("已尝试提交，需要核对官方订单。" if submitted else "尚未点击提交订单。"))
            result = self.result(intent, submitted=submitted)
            if not submitted and result.status == "unknown":
                return OrderResult("verification", f"尚未点击提交订单：{stage}失败，请检查官方页面后继续处理")
            return result

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
