"""Conservative adapters for page-visible 12306 order forms and order records.

No order APIs, page globals, payment clicks, or generic success-message detection.
Unknown layouts fail closed and retain the durable intent for reconciliation.
"""
from __future__ import annotations

import re
import time
import uuid
import hashlib
import json
from dataclasses import replace
from enum import Enum
from urllib.parse import urlparse
from selenium.common.exceptions import ElementClickInterceptedException, StaleElementReferenceException
from selenium.webdriver.common.by import By
from railwatch_orders import OrderResult
from railwatch_policies import ORDER_POLICIES
from railwatch_task import TaskCancelled
from railwatch_alternate_options import FORM_OPTIONS_JS, canonical_deadline, deadline_minutes, form_review, new_train_summary_matches


class ConfirmationOutcome(Enum):
    REJECTED = "rejected_before_dispatch"
    DISPATCHED = "dispatched"
    UNKNOWN = "unknown"


class _OrderTiming:
    """In-memory checkpoints; no browser calls or writes on the submit path."""

    def __init__(self):
        self.started = self.last = time.monotonic()
        self.current = None
        self.steps = []

    def step(self, name=None):
        now = time.monotonic()
        if self.current is not None:
            self.steps.append({"id": self.current,
                               "start_ms": round((self.last - self.started) * 1000, 3),
                               "duration_ms": round((now - self.last) * 1000, 3)})
        self.current, self.last = name, now


SNAPSHOT_JS = r"""
const visible = e => !!(e && e.getClientRects().length && getComputedStyle(e).visibility === 'visible');
const txt = e => (e?.innerText || '').replace(/\s+/g,' ').trim();
const all = (s,r=document) => [...r.querySelectorAll(s)].filter(visible);
const val = (s,r=document) => {const e=r.querySelector(s);return e?.value || txt(e);};
function trainCodes(root) {
  // Keep every visible structured value, including conflicting attributes and
  // labels. Free text is checked separately in record_matches, never promoted
  // to a single authoritative train code here.
  const sources=all('[data-train-code],.train-num,.train-number,.ticket-number',root)
    .flatMap(node=>[node.getAttribute('data-train-code')||'',txt(node)]);
  return [...new Set(sources.flatMap(source=>[...source.matchAll(
    /(?:^|[^0-9A-Za-z])([GDCZTKYSL]\d{1,5}|\d{1,5})(?![0-9A-Za-z])/gi
  )].map(match=>match[1].toUpperCase())))];
}
function passengers(root) {
  const named=all('.passenger-name strong[title],.name-yichu[title],.passenger-info .name[title]',root).map(e=>e.getAttribute('title').trim());
  if(named.length) return named;
  // Refunded waitlist cards keep this order's passenger list collapsed behind
  // the official 展开 toggle. Read only that list of a waitlist card, without
  // expanding it; other hidden names stay ignored.
  if(root.matches?.('.order-item') && txt(root.querySelector('.order-item-hd')).includes('候补单号')) {
    const collapsed=[...root.querySelectorAll('.passenger-card-list.tuipiaoHide .passenger-name strong[title]')].map(e=>e.getAttribute('title').trim());
    if(collapsed.length) return collapsed;
  }
  const fields=all('input[id^="passenger_name_"],input.name-input',root).map(e=>e.value.trim()).filter(Boolean);
  if(fields.length) return fields;
  const names=[];
  for(const table of (root.matches?.('table') ? [root] : all('table',root))) {
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
const cardDetail=c=>({train:txt(c.querySelector('.ticket-number')),
 date:txt(c.querySelector('.ticket-date')),
 from:c.querySelector('.ticket-station-start .ticket-station-name')?.getAttribute('title')||'',
 to:c.querySelector('.ticket-station-end .ticket-station-name')?.getAttribute('title')||'',
 departure:txt(c.querySelector('.ticket-station-start .ticket-station-time')),
 fulfilled:c.classList.contains('success'),
 seat:txt(c.querySelector('.ticket-info-txt span'))});
const details=all('#ticket_card_list .ticket-card').map(cardDetail);
const orders=all('.order-item').map(root=>{
 const header=txt(root.querySelector('.order-item-hd'));
 const ids=[...header.matchAll(/(?:候补单号|订单号码?)\s*[：:]\s*([A-Za-z0-9]+)/g)].map(m=>m[1]);
 // The regular unpaid card shows only its booking date in the header. Its
 // visible payment/cancel controls carry the order identity in data-sequence.
 // Read only this card's DOM attributes; conflicting identities fail closed.
 if(root.id==='not_complete'&&!header.includes('候补单号')) {
   ids.push(...all('.order-item-ft a[data-sequence],.order-item-ft button[data-sequence]',root)
     .filter(e=>/^(去支付|立即支付|继续支付|取消订单)$/.test(txt(e)))
     .map(e=>(e.getAttribute('data-sequence')||'').trim()));
 }
 const orderId=ids.length&&ids.every(id=>/^[A-Za-z0-9]+$/.test(id))&&new Set(ids).size===1?ids[0]:'';
 const ticketStates=all('.ticket-status-name',root).map(txt);
 const state=ticketStates.length?ticketStates.join(' '):all('.order-item-hd .pull-right,.order-item-hd .txt-second,.order-status',root).map(txt).join(' ');
 const payment=all('a,button',root).some(e=>{
   if (/^(去支付|立即支付|网上支付|继续支付|支付)$/.test(txt(e))) return true;
   // The official waitlist control includes a countdown. Scope this exception
   // to its own order card and control; never match arbitrary payment text.
   if (!header.includes('候补单号') || !e.matches('a.pay_order')) return false;
   const clocks=all('#J-payment-showTime',e);
   if (clocks.length!==1 || !/^\d+分\d{1,2}秒$/.test(txt(clocks[0]))) return false;
   return /^继续支付\s*[(（]\s*\d+分\d{1,2}秒\s*[)）]$/.test(txt(e));
 });
 const body=[];
 const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
 while(walker.nextNode()) {
   const node=walker.currentNode;
   if(visible(node.parentElement) && !node.parentElement.closest('.order-item-hd,.order-item-ft')) body.push(node.textContent);
 }
 return {order_id:orderId,kind:header.includes('候补单号')?'alternate':'regular',
   text:body.join(' ').replace(/\s+/g,' ').trim(),state,state_conflict:new Set(ticketStates).size>1,payment,passengers:passengers(root),
   train_codes:trainCodes(root), choices:all('.ticket-card-list .ticket-card,.ticket-card-list .ticket-card-queue',root).map(cardDetail),
   new_train_fulfilled:all('.success-temporary-train',root).some(e=>/临客.*兑现成功/.test(txt(e))),
   new_train_button:all('a.hb-add-train,a.hb-add-train2,a.hb-add-train3',root).filter(e=>txt(e)==='详情').length===1?
     all('a.hb-add-train,a.hb-add-train2,a.hb-add-train3',root).filter(e=>txt(e)==='详情')[0]:null,
   new_train_accepted:all('a.hb-add-train,a.hb-add-train2,a.hb-add-train3',root).length>0,
   success_rate:all('.success-rate',root).length===1?txt(root.querySelector('.success-rate strong')):'',
   prepay_amount:all('.order-item-ft-houbu .pull-left',root).filter(e=>/^待支付金额/.test(txt(e)))
      .map(e=>txt(e.querySelector('.txt-price .txt-mlg'))).join('|'),
   detail_button:all('a.hb-detail,a.hb-detail2,a.hb-detail3',root).filter(e=>txt(e)==='详情')[0]||null};
});
// The immediate payment page uses a legacy ticket table, not .order-item cards.
const paymentTitle = document.querySelector('#show_title_ticket');
const paymentRows = document.querySelector('#show_ticket_message');
const paymentTable = paymentRows?.closest('table');
if (!orders.length && visible(paymentTitle) && visible(paymentRows) && visible(document.querySelector('#payButton')) &&
    !visible(document.querySelector('#show_title_ticket_fc'))) {
  const ids = [...new Set([...txt(document.body).matchAll(/订单号(?:码)?\s*[：:]\s*([A-Za-z0-9]+)/g)].map(m=>m[1]))];
  const headers = [...(paymentTable?.querySelectorAll('th') || [])].map(txt);
  const seatIndex = headers.findIndex(h=>h==='席别');
  const seats = seatIndex < 0 ? [] : all('tr',paymentRows).map(row=>txt(row.querySelectorAll('td')[seatIndex])).filter(Boolean);
  if (ids.length === 1 && paymentTable && seats.length) orders.push({
    order_id:ids[0], kind:'regular', checkout:true, text:txt(paymentTitle),
    state:'待支付', payment:true, passengers:passengers(paymentTable), seat_names:seats,
    train_codes:trainCodes(paymentTable),
  });
}
const dialogs=all('.dhtmlx_window_active,.layui-layer,.modal,[role="dialog"],.up-box').map(txt).filter(Boolean);
// The official post-confirmation progress dialog is not an .order-queue.
const officialProgress = all('#orderResultInfo_id .tit').some(e =>
 /^(?:正在处理[，,]请稍候[。.]?|订单已经提交[，,](?:系统正在处理中[，,]请稍等[。.]?|(?:预计等待时间超过30分钟|最新预估等待时间.+)[，,]请耐心等待[。.]?))$/.test(txt(e))) &&
 all('#iamge_status_id.i-work,#iamge_status_id.i-queue').length > 0;
return {url:location.href, orders, dialogs, details,
 alternateCheckout:/(?:^|\/)lineUp_payConfirm\.html$/.test(location.pathname) &&
   visible(document.querySelector('#J-payConfirm')) && visible(document.querySelector('#J-lineUp-toPay')) &&
   visible(document.querySelector('#J-lineUp-cancel')) &&
   /^\d+分\d{1,2}秒$/.test(txt(document.querySelector('#J-lineUp-showTime'))),
 alternateCart:visible(document.querySelector('#hbSubmit')),
 quietCar:visible(document.querySelector('#content_defaultwarningAlert_id')) &&
   /静音车厢/.test(txt(document.querySelector('#content_defaultwarningAlert_id'))),
 regular:txt(document.querySelector('#ticket_info')||document.querySelector('#ticket_tit_id')), passengers:passengers(document),
 seats:all('select[id^="seatType_"]').map(e=>e.selectedOptions[0]?.textContent.trim()||''),
 ticketTypes:all('select[id^="ticketType_"]').filter(visible).map(e=>e.selectedOptions[0]?.textContent.trim()||''),
 deadline:val('#dafaultTime')||val('#deadline_time')||val('input.deadline-time'),
 extra:all('#planList .group-ticket,#planList .list-item').length,
 planText:txt(document.querySelector('#planList')),
 alternatePopup:visible(document.querySelector('#popup')),
 addedTrain:!!document.querySelector('#addTrainInput:checked,#addTrainInput input:checked,#contact_train:checked'),
 standing:txt(document.querySelector('#is_open')),
 pendingEmpty:all('#J-order-payment,#not_complete').some(e=>/您没有待支付|没有未完成|暂无待支付/.test(txt(e))) && orders.length===0 && !all('.loading,.loading-box,#J-loading').length,
 formReady:visible(document.querySelector('#normal_passenger_id')) || visible(document.querySelector('#passenge_list')),
 confirmation:visible(document.querySelector('#qr_submit_id')),
 verification:all('#nc_1_n1z,.nc_scale,.slide-verify,#randCode,#J-loginImg').length>0,
 processing:officialProgress || all('.order-queue').some(e=>/排队|处理中/.test(txt(e))) };
"""

PASSENGER_FIELDS_JS = r"""
const visible=e=>!!(e&&e.getClientRects().length&&getComputedStyle(e).visibility==='visible');
const allInputs=[...document.querySelectorAll('#normal_passenger_id input[type="checkbox"],#passenge_list input.chose-pass-dom')]
 .filter(e=>visible(e.closest('#normal_passenger_id,#passenge_list')));
const inputs=allInputs.filter(visible);
const label=e=>e.closest('label')||[...(e.labels||[])][0];
const name=e=> {const l=label(e);
 return (l?.getAttribute('title') || l?.innerText || '').replace(/[（(](?:学生|儿童|成人)[）)]/g,'').trim();};
const ticketType=e=> {
 const l=label(e), text=[e.dataset.ticketType,l?.dataset.ticketType,l?.innerText].filter(Boolean).join(' ');
 const kinds=[[/学生|\bstudent\b/i,'student'],[/儿童|\bchild\b/i,'child'],[/成人|\badult\b/i,'adult']]
   .filter(([pattern])=>pattern.test(text)).map(([,kind])=>kind);
 if (e.matches('#passenge_list input.chose-pass-dom') && e.hasAttribute('passengerInfo')) {
   // Official adult labels omit the type. Read only the type/name prefix of
   // this DOM attribute; never transport its document/token fields to Python.
   const prefix=/^([123])#([^#]+)#[^#]+#/.exec(e.getAttribute('passengerInfo')||'');
   const kind=prefix && ({'1':'adult','2':'child','3':'student'})[prefix[1]];
   if (!kind || prefix[2]!==name(e)) return 'unknown';
   kinds.push(kind);
 }
 return kinds.length && new Set(kinds).size===1 ? kinds[0] : 'unknown';
};
"""

SELECT_PASSENGERS_JS = PASSENGER_FIELDS_JS + r"""
const wanted=arguments[0], regular=arguments[1]===true;
if(!wanted.length || new Set(wanted).size!==wanted.length) return '乘车人名单为空或姓名重复，请核对行程设置';
// Collapsed rows are hidden, not absent: uniqueness must cover the whole list.
if(allInputs.some(e=>e.checked&&!inputs.includes(e))) return '官方乘客列表折叠区存在已勾选乘客，请展开核对';
for(const n of wanted) {
 if(allInputs.filter(e=>name(e)===n).length>1) return '官方乘客列表存在同名记录，无法唯一选择，请人工核对';
 const matches=inputs.filter(e=>name(e)===n);
 if(!matches.length) return '官方乘客列表未找到完整姓名匹配项，请检查列表是否已加载或展开';
 const type=ticketType(matches[0]);
 if(type==='student'||type==='child') return '目标乘客标记为学生或儿童，当前自动交易仅支持成人票';
 // Regular checkout provides a passenger-specific ticket selector after selection.
 // Unknown list labels are not adult evidence; verify_form must confirm every row.
 if(type!=='adult'&&!regular) return '候补乘客列表未明确票种，请在官方页面核对';
}
const changes=inputs.filter(e=>e.checked!==wanted.includes(name(e)));
if(changes.some(e=>e.disabled)) return '乘客勾选项不可操作，请检查官方页面';
// iCheck cancels native input clicks; its visible label is the user control.
// A normal HTML label also toggles its associated checkbox exactly once.
for(const input of changes) if(input.checked!==wanted.includes(name(input))) (label(input)||input).click();
const actual=inputs.filter(e=>e.checked).map(name);
return actual.length===wanted.length && wanted.every(n=>actual.includes(n)) || '乘客勾选结果与目标名单不一致';
"""

# The official list is rendered asynchronously after the form shell. Return
# only a count and whether every target name is present, never the names.
PASSENGER_LIST_READY_JS = PASSENGER_FIELDS_JS + r"""
const wanted=arguments[0], names=new Set(allInputs.map(name));
return {count:allInputs.length, complete:wanted.length>0 && wanted.every(n=>names.has(n))};
"""

READ_PASSENGER_BOOK_JS = r"""
// Personal-centre list, verified 2026-09-28. Read-only; never return data-val,
// checkbox values, phone numbers, tokens or full document numbers.
const visible=e=>!!(e&&e.getClientRects().length&&getComputedStyle(e).visibility==='visible');
const text=e=>(e?.innerText||'').trim();
const root=document.querySelector('#content_list');
const headers=[...(root?.querySelectorAll('.order-panel-head th')||[])].map(text);
const expected=['序号','姓名','证件类型','证件号码','手机／电话','核验状态','操作'];
const table=root?.querySelector('.order-item-table');
const unknown={recognized:false,items:[],page:0,total_pages:null,has_next:false,complete:false};
if(!visible(root)||!visible(table)||JSON.stringify(headers)!==JSON.stringify(expected)) return unknown;
const search=document.querySelector('#_search_name');
if(search?.value.trim() && search.value.trim()!=='请输入乘客姓名') return unknown;
const rows=[...table.querySelectorAll('tr')].filter(visible);
if(rows.length>10 || rows.length!==table.querySelectorAll('tr').length) return unknown;
const items=[];
for(const row of rows){
  const cells=[...row.cells];
  const nameNode=cells[1]?.querySelector('.name-yichu[title]');
  if(cells.length!==7||!visible(nameNode)||!nameNode.title.trim()||nameNode.title.trim()!==text(nameNode)) return unknown;
  const identity=cells[5].querySelector('.verification-status-user[title]');
  const label=visible(identity)?identity.title.trim():'';
  let verification='unknown';
  // Preserve pre-pass as a distinct state; it is not an official rejection.
  if(label==='已通过'&&identity.classList.contains('user-check-success')) verification='passed';
  else if(label==='预通过') verification='prepassed';
  else if(identity?.classList.contains('user-check-error')) {
    if(/未经核验|待核验/.test(label)) verification='pending';
    else if(/未通过|不再支持|重复/.test(label)) verification='failed';
  }
  const edit=cells[6].querySelector('.one-edit[data-val]');
  const self=!!cells[0].querySelector('input.UserSelf');
  // Non-self rows embed the profile type in the edit link; never click it.
  // For self there is no edit link, so the type must remain unknown.
  const fields=!self&&visible(edit)?edit.getAttribute('data-val').split('#'):[];
  const code=fields.length===7&&fields[0]===nameNode.title.trim()?fields[3]:'';
  const ticket_type=({'1':'adult','2':'child','3':'student'})[code]||'unknown';
  const documentText=text(cells[3]);
  const hint=documentText.length>5 ? documentText.slice(0,2)+'***'+documentText.slice(-2):'';
  items.push({name:nameNode.title.trim(),ticket_type,unsupported_ticket_type:code==='4',
    type_source:code?'profile_metadata':'unavailable',verification,
    identity_hint:/^[^*＊\s]{1,2}\*{3}[^*＊\s]{1,2}$/.test(hint)?hint:''});
}
const pager=document.querySelector('.pagination');
const totalText=text(pager?.querySelector('.page-all strong'));
const currentText=text(pager?.querySelector('.page-num .active'));
const total=/^\d+$/.test(totalText)?Number(totalText):null;
const page=/^\d+$/.test(currentText)?Number(currentText):0;
const next=pager?.querySelector('a.next');
const has_next=visible(next)&&!next.classList.contains('disabled')&&next.getAttribute('aria-disabled')!=='true';
const coherent=total!==null&&total>=1&&page>=1&&page<=total&&has_next===(page<total);
return {recognized:true,items,page,total_pages:total,has_next,complete:coherent&&page===total,
  pagination_valid:coherent};
"""


READ_PASSENGER_CANDIDATES_JS = PASSENGER_FIELDS_JS + r"""
const mask=value=>{const text=(value||'').trim();return text.length>5?text.slice(0,2)+'***'+text.slice(-2):'';};
return inputs.slice(0,100).map(input=>{
 const identity=mask(label(input)?.dataset.identity||input.dataset.identity||'');
 return {name:name(input),ticket_type:ticketType(input),identity_hint:identity};
});
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

# Observe the DOM event, independently of WebDriver's command acknowledgement.
# The marker belongs to RailWatch, never to 12306's private application state.
CONFIRM_RECEIPT_JS = r"""
const button = document.querySelector('#qr_submit_id');
const token = arguments[0], action = arguments[1];
if (!button) return null;
if (action === 'observe') {
  const receipt = {token, delivered:false};
  button.__railwatchClickReceipt = receipt;
  button.addEventListener('click', () => { receipt.delivered = true; }, {capture:true, once:true});
  return true;
}
const receipt = button.__railwatchClickReceipt;
if (!receipt || receipt.token !== token) return null;
if (action === 'read') return receipt.delivered;
if (action === 'dispatch' && !receipt.delivered && button.isConnected &&
    button.getClientRects().length && getComputedStyle(button).visibility === 'visible' &&
    button.classList.contains('btn92s') && !button.classList.contains('btn92') &&
    !button.disabled && button.getAttribute('aria-disabled') !== 'true') {
  HTMLElement.prototype.click.call(button);
  return receipt.delivered;
}
return null;
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


def record_matches(record, intent, *, known_id=""):
    if intent.kind == "alternate":
        if bool(record.get("new_train_accepted")) != bool(intent.new_train_windows):
            return False
        if intent.new_train_windows and not record.get("new_train_verified"):
            return False
        if record.get("new_train_fulfilled"):
            from railwatch_alternate_options import added_fulfillment_matches
            return added_fulfillment_matches(record, intent, known_id)
    if record.get("detail_button") and not record.get("details_verified"):
        # A collapsed official card is only a preview, not the full choice set.
        return False
    if intent.kind == "alternate" and len(intent.combinations) > 1:
        from railwatch_alternate_plan import AlternateChoice
        try:
            actual = tuple(AlternateChoice.from_detail(item) for item in record.get("choices", []))
        except (KeyError, TypeError, ValueError):
            return False
        if (record.get("kind") != "alternate" or not actual or len(set(actual)) != len(actual)
                or sorted(record.get("passengers", [])) != sorted(intent.passengers)):
            return False
        expected = set(intent.combinations)
        if set(actual) == expected:
            return True
        # A fulfilled card may retain just the winning choice. Only the bound
        # waitlist ID and an explicit fulfilled state can authorize that subset.
        return bool(known_id and record.get("order_id") == known_id and len(actual) == 1
                    and set(actual) <= expected and re.search("兑现成功|已兑现", record.get("state", "")))
    text = record.get("text", "")
    dates = {normalized_date(m[0]) for m in re.finditer(r"\d{4}[-年/]\d{1,2}[-月/]\d{1,2}", text)}
    clean_text = re.sub(r"\d{4}[-年/]\d{1,2}[-月/]\d{1,2}(?:日)?|\d{1,2}:\d{2}", "", text)
    structured = {str(value).strip().upper()
                  for value in [record.get("train_code", ""), *record.get("train_codes", [])]
                  if str(value).strip()}
    suffixed = {value.upper() for value in re.findall(
        r"(?<![0-9A-Za-z])([GDCZTKYSL]\d{1,5}|\d{1,5})\s*次(?![0-9A-Za-z])", clean_text, re.I
    )}
    # Combine independent evidence instead of letting one field hide a second
    # train. Bare numbers outside dedicated train fields may still be fares.
    prefixed = {value.upper() for value in re.findall(
        r"(?<![0-9A-Za-z])([GDCZTKYSL]\d{1,5})(?![0-9A-Za-z])", clean_text, re.I
    )}
    trains = structured | suffixed | prefixed
    if record.get("checkout"):
        return (record.get("kind") == intent.kind == "regular" and train_token(text, intent.train_code)
                and trains == {intent.train_code} and dates == {intent.date}
                and all(form_token(text, station, "站") for station in (intent.from_station, intent.to_station))
                and text.index(intent.from_station) < text.index(intent.to_station)
                and sorted(record.get("passengers", [])) == sorted(intent.passengers)
                and [seat_label(value) for value in record.get("seat_names", [])] == [intent.seat] * len(intent.passengers))
    seats = {value for value in ("二等座", "一等座", "商务座", "特等座", "无座", "硬座", "软座", "硬卧", "软卧", "高级软卧", "动卧") if contains_token(text, value)}
    return (record.get("kind") == intent.kind and train_token(text, intent.train_code)
            and trains == {intent.train_code} and dates == {intent.date} and seats == {intent.seat}
            and all(contains_token(text, item) for item in (intent.from_station, intent.to_station, intent.seat))
            and text.index(intent.from_station) < text.index(intent.to_station)
            and sorted(record.get("passengers", [])) == sorted(intent.passengers))


class OrderPage:
    RESULT_UNKNOWN_TIMEOUT = 60.0
    RESULT_POLL_INTERVAL = 0.5
    # A listed dialog may still be fading in or covered; wait this long for the
    # official waitlist confirmation to become clickable before reporting it.
    ALTERNATE_CONFIRMATION_GRACE = 3.0

    def __init__(self, driver, stop=lambda: False, wait=None, mark=None, *, allow_fixture=False, log=None,
                 poll_interval=0.1, trip_route=None):
        self.driver, self.stop = driver, stop
        self.allow_fixture = allow_fixture
        self.wait = wait or time.sleep
        self.mark = mark or (lambda stage, detail=None: None)
        self.log = log or (lambda message: None)
        self.poll_interval = poll_interval
        # The configured (possibly city-level) stations, recorded with official
        # options so trip settings can find them; never order evidence.
        self.trip_route = trip_route
        self._people_error = ""
        self.bind_intent = None
        self.alternate_editor = None
        self.verified_alternate_signature = ""

    def _save_timing(self, intent, timing):
        timing.step()
        try:
            self.mark("order_timing", {"kind": intent.kind, "steps": timing.steps})
        except Exception:
            # Timing evidence is optional and cannot change an order's outcome.
            pass

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
        return self._result_from_snapshot(self.snapshot(), intent, submitted=submitted,
                                          known_id=known_id, allow_empty=allow_empty)

    def _result_with_alternate_details(self, snap, intent, *, submitted=True, known_id="", allow_empty=False):
        # A single saved choice can also be displayed as a collapsed order card.
        if intent.kind == "alternate":
            from railwatch_alternate_records import read_details
            try:
                snap = read_details(self, snap, intent, known_id)
                if intent.new_train_windows:
                    from railwatch_alternate_records import read_added_conditions
                    snap = read_added_conditions(self, snap, intent, known_id)
            except ValueError as exc:
                return OrderResult("verification", str(exc), order_id=known_id)
        return self._result_from_snapshot(snap, intent, submitted=submitted, known_id=known_id, allow_empty=allow_empty)

    def _result_from_snapshot(self, snap, intent, *, submitted=False, known_id="", allow_empty=False):
        if not snap:
            return OrderResult("unknown", "无法读取订单页面")
        # Only an identified, matching order can establish payment or fulfillment.
        matching = [r for r in snap.get("orders", []) if r.get("order_id")
                    and record_matches(r, intent, known_id=known_id) and (not known_id or r["order_id"] == known_id)]
        if len(matching) == 1 and not matching[0].get("state_conflict"):
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
                # A historical completed/cancelled order can have exactly the
                # same trip. It cannot establish the outcome of an unbound
                # submission, even when it is the only visible matching card.
                if stage != "pending_payment" and not known_id:
                    return OrderResult("unknown", "尚未取得本次提交的订单号，历史订单不能证明本次结果，请人工核对")
                from railwatch_alternate_options import record_review
                return OrderResult(stage, order_id=record["order_id"], review=record_review(record) if intent.kind == "alternate" else {}, evidence={
                    "matched": True, "url": snap.get("url", "").split("?")[0],
                    "observed_at": time.time(), "state": state[:100],
                    **({"fulfilled_choices": record.get("choices", [])} if stage == "fulfilled" and intent.kind == "alternate" else {})})
        if len(matching) == 1 and matching[0].get("state_conflict"):
            return OrderResult("unknown", "已匹配到订单，但订单内车票状态不一致（如部分退票或改签），请在官方订单详情人工核对",
                               order_id=known_id)
        dialogs = " ".join(snap.get("dialogs", []))
        if snap.get("quietCar"):
            return OrderResult("verification", "官网提示可能候补到静音车厢，请在官网确认是否接受；处理后继续原候补")
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
        # An empty view cannot prove that an in-flight or externally created
        # order does not exist. Only a known pre-submit failure releases ownership.
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
            self.wait(min(self.poll_interval, remaining))
        return None

    def button(self, selectors):
        from railwatch_selectors import ACTION_READY_JS
        try:
            return self.driver.execute_script(ACTION_READY_JS + r"""
              for (const selector of arguments[0]) {
                for (const el of document.querySelectorAll(selector)) {
                  if (!rwActionReady(el)) continue;
                  // Official anchors are ready only after their handler is bound.
                  if (selector === '#qr_submit_id' &&
                      (!el.classList.contains('btn92s') || el.classList.contains('btn92'))) continue;
                  return el;
                }
              }
              return null;
            """, list(selectors))
        except Exception:
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
            ("票种", "成人", "、".join(snap.get("ticketTypes", [])) or "未读到",
             len(snap.get("ticketTypes", [])) == len(intent.passengers) and
             all("成人" in value and "学生" not in value and "儿童" not in value
                 for value in snap.get("ticketTypes", []))),
        ]
        failed = "；".join(f"{name}：期望 {want}，实际 {got}" for name, want, got, matches in fields if not matches)
        if (form_token(text, intent.from_station, "站") and form_token(text, intent.to_station, "站")
                and text.index(intent.from_station) >= text.index(intent.to_station)):
            failed += "；区间：出发站与到达站顺序不一致"
        summary = f"；页面摘要：{masked[:120]}" if masked else "；页面摘要为空"
        return (failed or "各字段均已读到") + summary

    def alternate_options(self):
        data = self.driver.execute_script(FORM_OPTIONS_JS)
        if not isinstance(data, dict):
            return {}
        origin = urlparse(data.get("url", ""))
        trusted = (origin.scheme == "https" and origin.hostname == "kyfw.12306.cn"
                   and origin.path == "/otn/view/lineUp_toPay.html") or (self.allow_fixture and origin.scheme == "file")
        return data if trusted and data.get("available") else {}

    def alternate_signature(self, snap, options=None):
        fields = {key: snap.get(key) for key in ("url", "details", "passengers", "deadline", "standing", "extra", "planText", "addedTrain")}
        fields["new_train_summary"] = (self.alternate_options() if options is None else options).get("new_train_summary", "")
        return hashlib.sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def verify_form(self, intent, *, confirmation=False):
        if intent.kind == "alternate" and len(intent.combinations) > 1:
            if confirmation:
                # Do not reopen the alternatives editor behind the confirmation.
                if not self.verified_alternate_signature or self.alternate_signature(self.snapshot()) != self.verified_alternate_signature:
                    return False
            else:
                from railwatch_alternate_editor import AlternateEditor
                editor = self.alternate_editor or AlternateEditor(self)
                if not editor.verify(intent):
                    return False
        snap = self.snapshot()
        if not intent.passengers or sorted(snap.get("passengers", [])) != sorted(intent.passengers):
            return False
        if intent.kind == "alternate":
            details = snap.get("details", [])
            if any(window.date not in {choice.date for choice in intent.combinations} for window in intent.new_train_windows):
                return False
            if (len(details) != 1 or bool(snap.get("addedTrain")) != bool(intent.new_train_windows) or snap.get("alternatePopup")
                    or len(intent.combinations) == 1 and snap.get("extra")):
                return False
            if not new_train_summary_matches(self.alternate_options().get("new_train_summary", ""), intent):
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
                and len(snap.get("ticketTypes", [])) == len(intent.passengers)
                and all("成人" in value and "学生" not in value and "儿童" not in value
                        for value in snap.get("ticketTypes", []))
                and [seat_label(value) for value in snap.get("seats", [])] == [intent.seat] * len(intent.passengers))

    def select_regular_seats(self, intent):
        from railwatch_selectors import ACTION_READY_JS
        return self.driver.execute_script(ACTION_READY_JS + r"""
          const selects = [...document.querySelectorAll('select[id^="seatType_"]')].filter(rwActionReady);
          if (selects.length !== arguments[1]) return false;
          const label = value => value.replace(/\s*[（(]\s*[¥￥]?\s*\d+(?:\.\d+)?\s*元\s*[）)]\s*$/, '').trim();
          const choices = selects.map(select => [...select.options].filter(option =>
            !option.matches(':disabled') && label(option.text) === arguments[0]));
          if (choices.some(options => options.length !== 1)) return false;
          // Validate every passenger before changing any selection. The caller
          // still verifies the complete form before the native submit click.
          selects.forEach((select, i) => {
            if (select.selectedIndex !== choices[i][0].index) {
              select.selectedIndex = choices[i][0].index;
              select.dispatchEvent(new Event('change', {bubbles:true}));
            }
          });
          return true;
        """, intent.seat, len(intent.passengers)) is True

    def wait_people(self, intent):
        """True once the list holds every target name or stops growing.

        Stability is measured in time, not polls, so a short timed-mode poll
        interval cannot accept a list that is still rendering in batches.
        Returns None when stopped and False on timeout.
        """
        timeout = ORDER_POLICIES["people_ready_timeout_seconds"]
        if timeout <= 0:
            return True
        stable_seconds = ORDER_POLICIES["people_stable_ms"] / 1000
        seen = {"count": None, "since": 0.0}
        def ready():
            try:
                value = self.driver.execute_script(PASSENGER_LIST_READY_JS, list(intent.passengers))
            except Exception:
                return False  # The list may be replaced while it renders.
            if not isinstance(value, dict):
                # No readiness evidence at all: prepare_people still checks
                # every name and fails closed, as before this wait existed.
                return True
            count = value.get("count")
            if type(count) is not int or count <= 0:
                seen["count"] = None
                return False
            if value.get("complete") is True:
                return True
            now = time.monotonic()
            if count != seen["count"]:
                seen.update(count=count, since=now)
                return False
            return now - seen["since"] >= stable_seconds
        if self.poll(ready, timeout):
            return True
        return None if self.stop() else False

    def prepare_people(self, intent):
        result = self.driver.execute_script(SELECT_PASSENGERS_JS, list(intent.passengers), intent.kind == "regular")
        selected = result is True
        if not selected:
            expand = self.button(("#order_toggle",))
            if expand and expand.text.strip() == "展开":
                expand.click()
                result = self.driver.execute_script(SELECT_PASSENGERS_JS, list(intent.passengers), intent.kind == "regular")
                selected = result is True
        self._people_error = result if isinstance(result, str) else "乘车人选择未完成，请检查官方页面"
        return selected

    @staticmethod
    def deadline_matches(actual, expected, travel_date):
        if not actual or not expected:
            return False
        expected_relative = deadline_minutes(expected)
        if expected_relative is not None:
            return deadline_minutes(actual) == expected_relative
        expected_date = normalized_date(expected) or travel_date
        expected_time = re.search(r"\d{2}:\d{2}", expected)
        actual_time = re.search(r"\d{2}:\d{2}", actual)
        return bool(expected_time and actual_time and expected_time[0] == actual_time[0]
                    and normalized_date(actual) == expected_date)

    def set_deadline(self, deadline, travel_date, options=None):
        data = self.alternate_options() if options is None else options
        if (not deadline_minutes(deadline) or canonical_deadline(deadline) not in
                {canonical_deadline(value) for value in data.get("deadline_options", [])}):
            return False
        # Select an existing official option; never synthesize unsupported values.
        current = self.snapshot().get("deadline", "").strip()
        if self.deadline_matches(current, deadline, travel_date):
            return True
        # The official label may initially be blank and have zero height. Its
        # dropdown header remains the native click target in that state.
        selector = self.button((".sel-hd:has(> #dafaultTime)", "#dafaultTime"))
        if selector:
            selector.click()
            options = [option for option in self.driver.find_elements(By.CSS_SELECTOR, "#date_box li")
                       if option.is_displayed() and option.is_enabled() and option.get_attribute("aria-disabled") != "true"
                       and "disabled" not in (option.get_attribute("class") or "").split()
                       and self.deadline_matches(option.text, deadline, travel_date)]
            if len(options) == 1:
                options[0].click()
                return bool(self.poll(lambda: self.deadline_matches(self.snapshot().get("deadline", ""), deadline, travel_date), 2))
        return False

    def alternate_confirmation(self, intent, snap=None):
        """Recognize only the official deadline/terms confirmation for this form."""
        from railwatch_selectors import ACTION_READY_JS
        snap = self.snapshot() if snap is None else snap
        if (intent.kind != "alternate" or not snap.get("formReady") or snap.get("verification")
                or snap.get("processing") or snap.get("orders") or not self.verify_form(intent, confirmation=True)):
            return None
        candidate = self.driver.execute_script(ACTION_READY_JS + r"""
          const txt=e=>(e?.innerText||'').replace(/\s+/g,'').trim();
          const dialogs=[...document.querySelectorAll('.dhtmlx_window_active,.layui-layer,.modal,[role="dialog"],.up-box')]
            .filter(rwActionReady);
          if(dialogs.length!==1)return null;
          const dialog=dialogs[0];
          if(!dialog.matches('.dzp-confirm > .modal')||txt(dialog.querySelector('.modal-tit'))!=='提示')return null;
          const info=dialog.querySelector('.modal-bd .msg-info');
          const deadlines=info?.querySelectorAll('.txt-default');
          if(!deadlines||deadlines.length!==1)return null;
          const deadline=txt(deadlines[0]);
          const expected=`1、您的候补购票需求截止兑现时间为${deadline}，兑现成功车票视为已购车票，退改签按既有规则办理。`+
            '2、候补需求车次与已购其他车次时间冲突时，乘车日期在春运期间的，行程冲突车票将不予兑现；其他乘车日期仍将按您需求兑现候补车票，由此造成车票退改签时，按既有退改签规则办理。'+
            '3、请使用候补订单查询功能及时确认订单状态，交易结果以查询结果为准，合理规划出行时间，避免漏乘。';
          if(!deadline||txt(info)!==expected)return null;
          const buttons=[...dialog.querySelectorAll('.modal-ft a.ok.btn-primary')].filter(rwActionReady);
          const cancel=[...dialog.querySelectorAll('.modal-ft a.cancel')].filter(rwActionReady);
          return buttons.length===1&&txt(buttons[0])==='确定'&&cancel.length===1&&txt(cancel[0])==='取消'
            ? {deadline,button:buttons[0]} : null;
        """)
        if (isinstance(candidate, dict) and self.deadline_matches(candidate.get("deadline", ""), intent.deadline, intent.date)):
            return candidate.get("button")
        return None

    def confirm_quiet_car(self, intent):
        """Automatic waitlist authorization includes this observed official advisory."""
        from railwatch_selectors import ACTION_READY_JS
        snap = self.snapshot()
        if intent.kind != "alternate" or intent.seat != "二等座" or not snap.get("quietCar") or snap.get("verification"):
            return False
        button = self.driver.execute_script(ACTION_READY_JS + r"""
          const root=document.querySelector('#content_defaultwarningAlert_id');
          const txt=e=>(e?.innerText||'').replace(/\s+/g,'').trim();
          const expected='选择该车次二等座可能候补到“静音车厢”席位，是否继续选择？'+
            '在静音车厢内须保持安静，动作轻柔避免产生噪声；将手机等电子设备调至静音或振动状态；在接打电话或相互交谈时离开静音车厢；在使用电子设备时佩戴耳机或关闭音源外放功能；携带儿童出行的旅客照看好孩子，避免喧哗、哭闹。';
          const complete='温馨提示关闭'+expected+'记住我的选择，不再提示取消选择仍然选择';
          if(!rwActionReady(root)||txt(root)!==complete)return null;
          const dialogs=[...document.querySelectorAll('.modal,.up-box,[role="dialog"],.dhtmlx_window_active,.layui-layer')].filter(rwActionReady);
          if(dialogs.some(e=>e!==root&&!e.contains(root)&&!root.contains(e)))return null;
          const yes=[...root.querySelectorAll('#qd_closeDefaultWarningWindowDialog_id')].filter(rwActionReady);
          const no=[...root.querySelectorAll('#qd_cancelDefaultWarningWindowDialog_id')].filter(rwActionReady);
          return yes.length===1&&txt(yes[0])==='仍然选择'&&no.length===1&&txt(no[0])==='取消选择'?yes[0]:null;
        """)
        if button is None or self.stop():
            return False
        self.mark("alternate_quiet_confirm")
        if self.stop():
            return False
        button.click()
        self.log("已自动确认官网静音车厢提示，继续核对原候补行程。")
        return bool(self.poll(lambda: not self.snapshot().get("quietCar"), 3))

    def wait_result(self, intent, submitted=True, timeout=None, *, known_id="", confirm_alternate=False):
        """Observe in-flight orders; only an unrecognized page can time out.

        A visible official queue is ongoing work, not missing evidence. Keep
        watching it without navigating or submitting again, and allow a fresh
        grace period when it disappears while the payment page loads. Read the
        result and progress from the same snapshot to avoid a navigation race.
        """
        timeout = self.RESULT_UNKNOWN_TIMEOUT if timeout is None else timeout
        started = time.monotonic()
        deadline = started + timeout
        next_progress_log = started
        confirm_until = None
        while True:
            snap = self.snapshot()
            result = self._result_with_alternate_details(snap, intent, submitted=submitted, known_id=known_id)
            if (intent.kind == "alternate" and submitted and result.status == "unknown"
                    and snap.get("alternateCheckout") and not self.stop()):
                return self.probe_submitted_alternate(intent, known_id)
            if confirm_alternate and result.status in ("unknown", "verification") and not self.stop():
                confirmation = self.alternate_confirmation(intent, snap)
                if confirmation is not None:
                    # One delivered attempt only: a lost click acknowledgement must
                    # never replay a confirmation that may already have created an order.
                    self.mark("alternate_confirm_attempt")
                    if self.stop():
                        return self._stopped_result(True)
                    try:
                        confirmation.click()
                    except (ElementClickInterceptedException, StaleElementReferenceException):
                        # WebDriver refused the click before dispatch (an overlay or a
                        # re-rendered dialog), so nothing reached the official page.
                        self.mark("alternate_confirm_rejected")
                        self.log("候补确认按钮暂时无法点击，正在重新核对确认提示。")
                    else:
                        confirm_alternate = False
                        continue
                # Only on the submitted form, before any order card: re-reading order
                # details would repeat their clicks and could adopt a changed identity.
                if (result.status == "verification" and snap.get("dialogs") and snap.get("formReady")
                        and not snap.get("orders") and not snap.get("verification")):
                    now = time.monotonic()
                    confirm_until = confirm_until or now + self.ALTERNATE_CONFIRMATION_GRACE
                    if now < confirm_until:
                        self.wait(min(self.RESULT_POLL_INTERVAL, confirm_until - now))
                        continue
            if result.status != "unknown" or self.stop():
                return result
            now = time.monotonic()
            if snap.get("processing"):
                deadline = now + timeout
                if now >= next_progress_log:
                    self.log(f"官方仍在排队或处理订单，已等待 {int(now - started)} 秒，正在自动核对结果。")
                    next_progress_log = now + 30
            elif now >= deadline:
                self.log("暂未读到匹配的官方订单，已保留原订单记录，请在官方页面核对后继续处理。")
                return result
            self.wait(min(self.RESULT_POLL_INTERVAL, max(0.01, deadline - now)))

    def _click_regular_confirmation(self, confirm, intent):
        """Retry only clicks rejected before dispatch; ambiguous receipts are observed."""
        def click():
            nonlocal confirm
            if self.stop():
                return ConfirmationOutcome.REJECTED
            if confirm is None:
                result = self.result(intent, submitted=True)
                if result.status != "unknown":
                    return result
                confirm = self.button(("#qr_submit_id",))
            if confirm is None:
                return None
            token = uuid.uuid4().hex
            try:
                observed = self.driver.execute_script(CONFIRM_RECEIPT_JS, token, "observe") is True
            except Exception:
                observed = False
            if self.stop():
                return ConfirmationOutcome.REJECTED
            self.mark("regular_confirm_attempt")
            try:
                confirm.click()
            except (ElementClickInterceptedException, StaleElementReferenceException):
                # WebDriver rejected the action before it reached the button.
                # Reacquire after an overlay/DOM update instead of asking the user.
                confirm = None
                return None
            except Exception:
                self.log("确认购买点击回执异常，将等待并核对订单结果，不自动重复确认。")
                return ConfirmationOutcome.UNKNOWN
            if observed:
                try:
                    delivered = self.driver.execute_script(CONFIRM_RECEIPT_JS, token, "read")
                    if delivered is False:
                        if self.stop():
                            return ConfirmationOutcome.REJECTED
                        result = self.result(intent, submitted=True)
                        if result.status != "unknown":
                            return result
                        if self.stop():
                            return ConfirmationOutcome.REJECTED
                        self.log("浏览器点击未触发确认按钮，正在直接触发该按钮的点击事件。")
                        delivered = self.driver.execute_script(CONFIRM_RECEIPT_JS, token, "dispatch")
                    if delivered is True:
                        self.mark("regular_confirm_dispatched")
                        self.log("确认按钮点击事件已触发，正在等待官方订单结果。")
                        return ConfirmationOutcome.DISPATCHED
                except Exception:
                    self.log("确认按钮事件回读失败，将核对订单结果，不重复点击。")
            self.log("确认点击结果未知，将保留当前页面并核对订单，不重复点击。")
            return ConfirmationOutcome.UNKNOWN

        return click() or self.poll(click, timeout=5) or ConfirmationOutcome.REJECTED

    def _post_submit(self, intent, confirmed_clicked):
        """Resolve the outcome after the official submit/confirm step.

        Continue observing an official queue until it resolves or the user
        stops. An unrecognized page gets a bounded grace period, after which a
        completed confirmation can be reconciled on the official order page.
        """
        result = self.wait_result(intent, submitted=True)
        if result.status != "unknown":
            return result
        snap = self.snapshot()
        if snap.get("processing"):
            return result  # Do not navigate away while the official queue is active.
        if snap.get("confirmation"):
            return OrderResult("verification",
                               "官方确认流程尚未结束，请保留当前页面核对官方订单，再点击“继续处理”；请勿重复提交。")
        if confirmed_clicked and not self.stop():
            reconciled = self.reconcile(intent, navigate=True)
            if reconciled.status != "unknown":
                return reconciled
        return result

    def reconcile(self, intent, known_id="", navigate=False, allow_empty=False):
        snap = self.snapshot()
        result = self._result_with_alternate_details(snap, intent, known_id=known_id, allow_empty=allow_empty)
        if result.status not in ("unknown", "verification") or not navigate:
            return result
        if snap.get("quietCar"):
            return result
        if intent.kind == "alternate" and snap.get("alternateCheckout"):
            return self.probe_submitted_alternate(intent, known_id)
        if snap.get("processing") or snap.get("confirmation"):
            return OrderResult("unknown", "官方处理或确认流程尚未结束，请保留当前页面核对，请勿重复提交", order_id=known_id)
        # Explicit recovery action only: normal payment observation never navigates away.
        if self.stop():
            return result
        url = "https://kyfw.12306.cn/otn/view/" + ("lineUp_order.html" if intent.kind == "alternate" else "train_order.html")
        try:
            self.driver.get(url)
            result = self.poll(lambda: self._resolved(intent, known_id, allow_empty), self.RECOVERY_TAB_TIMEOUT)
            if result:
                return result
            # Only a previously bound identity may be sought in paid/history
            # tabs. A similar historical trip cannot establish a new order.
            if known_id:
                labels = (("待兑现订单", "已处理订单") if intent.kind == "alternate"
                          else ("未出行订单", "历史订单"))
                for label in labels:
                    if self.stop():
                        break
                    current = self.snapshot()
                    if current.get("processing") or current.get("confirmation"):
                        return OrderResult("unknown", "官方仍在处理或确认订单，请保留当前页面核对", order_id=known_id)
                    tab = self._recovery_tab(label, url)
                    if tab is None:
                        break
                    tab.click()
                    result = self.poll(lambda: self._resolved(intent, known_id, allow_empty), self.RECOVERY_TAB_TIMEOUT)
                    if result:
                        return result
            return OrderResult("unknown", "未找到匹配订单；请在官方未完成／未出行／历史订单中核对后继续处理"
                               if intent.kind == "regular" else "未找到匹配候补；请在官方待支付／待兑现／已处理订单中核对后继续处理",
                               order_id=known_id)
        except Exception:
            return OrderResult("unknown", "订单核对失败，请保留当前订单并在官方页面核查", order_id=known_id)

    def probe_known_order(self, intent, known_id):
        """Read only the bound order in a disposable tab; preserve payment tabs."""
        from railwatch_task import browser_tab_lifecycle
        if not known_id:
            return OrderResult("unknown", "缺少已绑定订单号，无法自动核对")
        return self._probe_order_tab(intent, known_id)

    def probe_submitted_alternate(self, intent, known_id=""):
        """The checkout page triggers a read; only a matched official card binds an ID."""
        snap = self.snapshot()
        if (intent.kind != "alternate" or not snap.get("alternateCheckout") or snap.get("dialogs")
                or snap.get("verification") or snap.get("processing")):
            return self._result_from_snapshot(snap, intent, submitted=True, known_id=known_id)
        checkout = self.driver.execute_script(r"""
          const text=e=>(e?.innerText||'').replace(/\s+/g,' ').trim();
          return {amount:text(document.querySelector('#J-payConfirm #detail_total')),
            rate:text(document.querySelector('#J-lineUp-toPay')).match(/预估成功率\s*[(（](\d+(?:\.\d+)?)%[)）]/)?.[1]||''};
        """)
        result = self._probe_order_tab(intent, known_id)
        if result.status == "pending_payment" and result.evidence.get("matched"):
            from railwatch_alternate_options import record_review
            review = record_review({"prepay_amount": checkout.get("amount", ""),
                                    "success_rate": checkout.get("rate", "") + "%"})
            # Prefer the matched card's rate when available; otherwise the
            # checkout observation belongs to the just-matched pending order.
            merged = {**review, **result.review}
            if result.review.get("success_rate") is None and review.get("success_rate") is not None:
                merged.update({key: review[key] for key in ("success_rate", "success_rate_status", "success_rate_observed_at")})
            return replace(result, review=merged)
        return result

    def _probe_order_tab(self, intent, known_id):
        from railwatch_task import browser_tab_lifecycle
        if self.stop():
            raise TaskCancelled()
        original = self.driver.current_window_handle
        temporary = None
        try:
            # Capture our handle before cancellation can unwind the operation.
            with browser_tab_lifecycle(self.driver):
                self.driver.switch_to.new_window("tab")
                temporary = self.driver.current_window_handle
            if self.stop():
                raise TaskCancelled()
            return self.reconcile(intent, known_id=known_id, navigate=True)
        finally:
            with browser_tab_lifecycle(self.driver):
                handles = self.driver.window_handles
                if temporary and temporary != original and temporary in handles:
                    self.driver.switch_to.window(temporary)
                    self.driver.close()
                if original in self.driver.window_handles:
                    self.driver.switch_to.window(original)

    RECOVERY_TAB_TIMEOUT = 5.0

    def _recovery_tab(self, label, url):
        current = urlparse(self.driver.current_url)
        expected = urlparse(url)
        if not ((current.scheme, current.netloc, current.path) == (expected.scheme, expected.netloc, expected.path)
                or self.allow_fixture and current.scheme == "file"):
            return None
        tabs = [element for element in self.driver.find_elements(By.CSS_SELECTOR, ".panel-tab .tab-hd-list > li > a")
                if element.is_displayed() and element.text.strip() == label and element.is_enabled()
                and element.get_attribute("aria-disabled") != "true"]
        return tabs[0] if len(tabs) == 1 else None

    def _resolved(self, intent, known_id, allow_empty=False):
        result = (self._result_with_alternate_details(self.snapshot(), intent, known_id=known_id, allow_empty=allow_empty)
                  if intent.kind == "alternate" else
                  self.result(intent, submitted=True, known_id=known_id, allow_empty=allow_empty))
        return result if result.status != "unknown" else None

    def regular(self, button, intent, *, seat_preference="无偏好", preference_handler=None):
        submitted = False
        stage = "打开乘车人页面"
        timing = _OrderTiming()
        timing.step("page_load")
        try:
            if self.stop():
                return self._stopped_result(submitted)
            if button is not None:
                button.click()
            def ready():
                snap = self.snapshot()
                result = self._result_from_snapshot(snap, intent)
                return result if result.status in ("sold_out", "verification", "pending_payment", "fulfilled") else snap.get("formReady")
            ready_result = self.poll(ready)
            if isinstance(ready_result, OrderResult): return ready_result
            stage = "等待乘车人列表"
            if not ready_result:
                return OrderResult("verification", "乘客表单尚未加载，请检查官方页面")
            people = self._wait_people_result(intent, timing)
            if people: return people
            stage = "选择乘车人"
            timing.step("passengers")
            if not self.prepare_people(intent):
                return OrderResult("verification", self._people_error)
            stage = "选择席别"
            timing.step("seats")
            if not self.select_regular_seats(intent):
                return OrderResult("verification", "尚未点击提交订单：席别选项未能唯一匹配，请检查官方页面")
            stage = "核对订单信息"
            timing.step("readback")
            if not self.poll(lambda: self.verify_form(intent), 6):
                self.log("回读核对未通过，已停止自动提交：" + self.form_mismatch_report(intent))
                return OrderResult("verification", "车次、日期、区间、乘客、成人票种或席别回读不一致，尚未提交订单")
            submit = self.button(("#submitOrder_id",))
            if not submit: return OrderResult("not_submitted", "提交按钮不可用", no_order=True)
            if self.stop(): return OrderResult("not_submitted", "提交前已停止", no_order=True)
            stage = "提交订单"
            timing.step("submit")
            self.mark("regular_submit")
            submitted = True  # Set before click: a transport error may follow a successful action.
            submit.click()
            timing.step("confirmation_wait")
            def confirm_or_result():
                result = self.result(intent, submitted=True)
                return result if result.status != "unknown" else self.button(("#qr_submit_id",))
            # Stop cancels further clicks, including confirmation. The durable
            # submit marker remains available for read-only reconciliation.
            confirm = self.poll(confirm_or_result, timeout=30)
            if self.stop():
                return self._stopped_result(submitted)
            if isinstance(confirm, OrderResult): return confirm
            confirmed_clicked = False
            if confirm is None:
                confirm = self.button(("#qr_submit_id",))
            if confirm:
                timing.step("confirmation_action")
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
                if self.stop():
                    return self._stopped_result(submitted)
                self.log("官方确认弹窗已出现，直接点击“确认”提交订单。")
                stage = "确认订单"
                confirmation = self._click_regular_confirmation(confirm, intent)
                if isinstance(confirmation, OrderResult):
                    return confirmation
                confirmed_clicked = confirmation is ConfirmationOutcome.DISPATCHED
            timing.step("result_wait")
            return self._post_submit(intent, confirmed_clicked)
        except TaskCancelled:
            return self._stopped_result(submitted)
        except Exception as exc:
            # Exception text can contain passenger data and browser internals.
            self.log(f"自动提交在{stage}阶段中断（{type(exc).__name__}）；"
                     + ("已尝试提交，需要核对官方订单。" if submitted else "尚未点击提交订单。"))
            result = self.result(intent, submitted=submitted)
            if not submitted and result.status == "unknown":
                return OrderResult("verification", f"尚未点击提交订单：{stage}失败，请检查官方页面后继续处理")
            return result
        finally:
            self._save_timing(intent, timing)

    def alternate(self, button, intent, *, plan_config=None):
        submitted = False
        stage = "打开候补页面"
        timing = _OrderTiming()
        timing.step("page_load")
        try:
            if self.stop():
                return self._stopped_result(submitted)
            # One seat-specific button has already been chosen by the query adapter.
            if button is not None:
                self.mark("alternate_first_action")
                button.click()
            def order_page():
                snap = self.snapshot()
                if snap.get("quietCar") and self.confirm_quiet_car(intent):
                    snap = self.snapshot()
                result = self._result_from_snapshot(snap, intent)
                if result.status == "verification": return result
                if snap.get("details"): return True
                return self.button(("#hbSubmit",))
            next_step = self.poll(order_page)
            if isinstance(next_step, OrderResult): return next_step
            if next_step is not True and next_step is not None:
                next_step.click()
            if not self.poll(lambda: self.snapshot().get("details")):
                return OrderResult("verification", "请检查候补需求清单并进入候补订单页")
            if plan_config is not None and plan_config.get("alternate_mode") == "multiple" and not intent.choices:
                from railwatch_alternate_editor import AlternateEditor
                if self.bind_intent is None:
                    return OrderResult("verification", "多组合候补缺少持久化通道")
                timing.step("alternatives")
                stage = "选择候补组合"
                self.alternate_editor = AlternateEditor(self, plan_config)
                intent = self.alternate_editor.populate(intent).for_choice_dates()
                self.bind_intent(intent)
            stage = "等待乘车人列表"
            people = self._wait_people_result(intent, timing)
            if people: return people
            timing.step("passengers")
            stage = "选择乘车人"
            if not self.prepare_people(intent):
                return OrderResult("verification", self._people_error)
            timing.step("deadline")
            stage = "选择截止兑现时间"
            options = self.alternate_options()
            if not self.set_deadline(intent.deadline, intent.date, options):
                review = form_review(intent, options, self.snapshot(), self.trip_route)
                if review["deadline_options"]:
                    self.mark("alternate_options", review)
                return OrderResult("verification", "所选截止时间不在当前官网选项中或未能回读，请在订单中心重选后继续原方案",
                                   review={**review, "deadline_reselection": True})
            from railwatch_new_trains import set_new_trains
            stage = "设置新增列车条件"
            set_new_trains(self, intent)
            timing.step("readback")
            stage = "核对候补信息"
            if not self.verify_form(intent):
                return OrderResult("verification", "候补组合不匹配，或包含额外车次、席别、无座设置")
            self.verified_alternate_signature = self.alternate_signature(self.snapshot())
            # Wait only for the official submit control: the success rate is a
            # display-only estimate and must never delay the submission.
            submit = self.poll(lambda: self.button(("#toPayBtn",)), 3)
            if self.stop(): return OrderResult("not_submitted", "提交前已停止", no_order=True)
            if not submit: return OrderResult("not_submitted", "候补提交按钮不可用", no_order=True)
            snap, options = self.snapshot(), self.alternate_options()
            if self.alternate_signature(snap, options) != self.verified_alternate_signature:
                return OrderResult("verification", "等待提交按钮时候补方案已变化，请核对原方案")
            review = form_review(intent, options, snap, self.trip_route)
            review["form_signature"] = self.verified_alternate_signature
            self.mark("alternate_form", review)
            if self.stop(): return OrderResult("not_submitted", "提交前已停止", no_order=True)
            timing.step("submit")
            stage = "提交候补订单"
            self.mark("alternate_submit")
            submitted = True
            submit.click()
            timing.step("result_wait")
            return self.wait_result(intent, confirm_alternate=True)
        except TaskCancelled:
            return self._stopped_result(submitted)
        except ValueError as exc:
            if self.stop():
                return self._stopped_result(submitted)
            return OrderResult("verification", str(exc))
        except Exception as exc:
            self.log(f"自动候补在{stage}阶段中断（{type(exc).__name__}）；"
                     + ("已尝试提交，需要核对官方订单。" if submitted else "尚未点击提交订单。"))
            result = self.result(intent, submitted=submitted)
            if not submitted and result.status == "unknown":
                return OrderResult("verification", f"尚未点击提交订单：{stage}失败，请在官方页面检查后继续原候补")
            return result
        finally:
            self._save_timing(intent, timing)

    def _wait_people_result(self, intent, timing):
        """None when the passenger list is ready; otherwise the pre-submit result."""
        timing.step("people_wait")
        ready = self.wait_people(intent)
        if ready:
            return None
        if ready is None or self.stop():
            return self._stopped_result(False)
        return OrderResult("verification", "尚未提交订单：官方乘客列表未加载完成，请检查官方页面")

    @staticmethod
    def _stopped_result(submitted):
        return OrderResult("unknown" if submitted else "not_submitted",
                           "已停止后续操作；已尝试提交，请在当前官方页面核对原订单，请勿重复提交"
                           if submitted else "已停止，尚未点击提交订单", no_order=not submitted)
