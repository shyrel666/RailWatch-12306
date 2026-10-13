"""Expand the native read-only waitlist details, scoped to one identified card."""
from urllib.parse import urlparse

from railwatch_alternate_plan import AlternateChoice
from railwatch_alternate_options import new_train_summary_matches
from railwatch_task import TaskCancelled


DETAILS_JS = r"""
const visible=e=>!!(e&&e.getClientRects().length&&getComputedStyle(e).visibility==='visible');
const text=e=>(e?.innerText||'').replace(/\s+/g,' ').trim();
const dialogs=[...document.querySelectorAll('.modal,[role="dialog"],.up-box,.dhtmlx_window_active,.layui-layer')].filter(visible);
const matches=dialogs.filter(e=>text(e.querySelector('.modal-tit'))==='候补明细');
if(matches.length!==1)return null;
const root=matches[0];
if(dialogs.some(e=>e!==root&&!root.contains(e)&&!e.contains(root)))return {error:true};
const groups=[...root.querySelectorAll('.hb-selected-group .selected-main .group-item')].filter(visible);
const choices=[];
let error=!groups.length;
for(const group of groups){
  const title=text(group.querySelector('.group-tit'));
  const match=title.match(/^(\d{4}-\d{1,2}-\d{1,2}|\d{8})\s*[（(]已选(\d+)[）)]$/);
  const rows=[...group.querySelectorAll('.group-ticket')].filter(visible);
  if(!match||rows.length!==Number(match[2])){error=true;continue;}
  const date=match[1].includes('-')?match[1]:match[1].slice(0,4)+'-'+match[1].slice(4,6)+'-'+match[1].slice(6);
  for(const row of rows){
    const stations=[...row.querySelectorAll('.ticket-station .ticket-station-name')].filter(visible).map(text);
    const trains=[...row.querySelectorAll('.ticket-number')].filter(visible).map(text);
    const seats=[...row.querySelectorAll('.ticket-seat')].filter(visible).map(text);
    if(stations.length!==2||trains.length!==1||!seats.length){error=true;continue;}
    for(const seat of seats)choices.push({train:trains[0],date,from:stations[0],to:stations[1],seat});
  }
}
const close=[...root.querySelectorAll('.modal-close')].filter(visible);
return {url:location.href,error,choices,close:close.length===1?close[0]:null};
"""


def read_details(page, snap, intent, known_id):
    origin = urlparse(snap.get("url", ""))
    trusted = (origin.scheme == "https" and origin.hostname == "kyfw.12306.cn"
               and origin.path == "/otn/view/lineUp_order.html") or (page.allow_fixture and origin.scheme == "file")
    if not trusted or snap.get("dialogs") or snap.get("verification") or snap.get("processing"):
        return snap
    expected = set(intent.combinations)

    def eligible(record):
        if (record.get("kind") != "alternate" or not record.get("order_id") or not record.get("detail_button")
                or record.get("new_train_fulfilled")
                or sorted(record.get("passengers", [])) != sorted(intent.passengers)):
            return False
        if known_id:
            if record["order_id"] != known_id:
                return False
        elif not (record.get("payment") or "待支付" in record.get("state", "")):
            return False  # Never bind an old paid/history order to a new submission.
        try:
            preview = [AlternateChoice.from_detail(item) for item in record.get("choices", [])]
        except (KeyError, TypeError, ValueError):
            return False
        return bool(preview and len(set(preview)) == len(preview) and set(preview) <= expected)

    records = [record for record in snap.get("orders", []) if eligible(record)]
    if len(records) != 1:
        return snap
    record = records[0]
    if page.stop():
        raise TaskCancelled()
    record["detail_button"].click()
    details = page.poll(lambda: page.driver.execute_script(DETAILS_JS), 3)
    if not details or not details.get("close"):
        raise ValueError("候补明细未能完整打开，请核对原订单")
    if page.stop():
        raise TaskCancelled()
    details["close"].click()
    if not page.poll(lambda: not page.driver.execute_script(DETAILS_JS), 2):
        raise ValueError("候补明细窗口尚未关闭，请核对原订单")
    if details.get("error") or details.get("url") != snap.get("url"):
        raise ValueError("候补明细结构或页面身份已变化，请核对原订单")
    try:
        actual = [AlternateChoice.from_detail(item) for item in details["choices"]]
    except (KeyError, TypeError, ValueError):
        raise ValueError("候补明细组合无法完整读取") from None
    if len(set(actual)) != len(actual):
        raise ValueError("官方候补明细与已保存组合不一致，请核对原订单")
    fresh = page.snapshot()
    matches = [item for item in fresh.get("orders", []) if item.get("order_id") == record["order_id"] and eligible(item)]
    if fresh.get("url") != snap.get("url") or len(matches) != 1 or fresh.get("dialogs") or fresh.get("verification"):
        raise ValueError("读取候补明细后订单身份已变化，请重新核对")
    verified = {**matches[0], "choices": details["choices"], "details_verified": True}
    if set(actual) != expected:
        # Apply the expanded-card rule to the freshly rechecked state: only a
        # bound, explicitly fulfilled multi-choice order may keep one winner.
        from railwatch_order_page import record_matches
        if len(intent.combinations) <= 1 or not record_matches(
                {**verified, "new_train_verified": bool(intent.new_train_windows)}, intent, known_id=known_id):
            raise ValueError("官方候补明细与已保存组合不一致，请核对原订单")
    return {**fresh, "orders": [verified if item is matches[0] else item for item in fresh["orders"]]}


ADDED_DETAILS_JS = r"""
const visible=e=>!!(e&&e.getClientRects().length&&getComputedStyle(e).visibility==='visible');
const text=e=>(e?.innerText||'').replace(/\s+/g,' ').trim();
const dialogs=[...document.querySelectorAll('.modal,[role="dialog"],.up-box,.dhtmlx_window_active,.layui-layer')].filter(visible);
const roots=dialogs.filter(e=>e.matches('.dzp-confirm > .modal')&&text(e.querySelector('.modal-tit'))==='已接受新增列车');
if(roots.length!==1)return null;
const root=roots[0];
if(dialogs.some(e=>e!==root&&!root.contains(e)&&!e.contains(root)))return null;
const closes=[...root.querySelectorAll('.modal-close')].filter(visible);
return {text:text(root.querySelector('.modal-bd')),url:location.href,close:closes.length===1?closes[0]:null};
"""


def read_added_conditions(page, snap, intent, known_id):
    """Bind the visible added-train details to the same unchanged official card."""
    from railwatch_order_page import record_matches
    origin = urlparse(snap.get("url", ""))
    trusted = (origin.scheme == "https" and origin.hostname == "kyfw.12306.cn"
               and origin.path == "/otn/view/lineUp_order.html") or (page.allow_fixture and origin.scheme == "file")
    if not trusted or snap.get("dialogs") or snap.get("verification") or snap.get("processing"):
        return snap
    records = [record for record in snap.get("orders", []) if record.get("new_train_button")
               and record.get("order_id") and (record["order_id"] == known_id if known_id else
                   record.get("payment") or "待支付" in record.get("state", ""))
               and record_matches({**record, "new_train_verified": True}, intent, known_id=known_id)]
    if len(records) != 1:
        return snap
    record = records[0]
    before = page.snapshot()

    def anchor(snapshot):
        items = [item for item in snapshot.get("orders", []) if item.get("order_id") == record["order_id"]]
        return ({key: items[0].get(key) for key in ("kind", "state", "passengers", "choices", "train_codes",
                    "new_train_accepted", "new_train_fulfilled")} if len(items) == 1 else None)

    if page.stop():
        raise TaskCancelled()
    record["new_train_button"].click()
    details = page.poll(lambda: page.driver.execute_script(ADDED_DETAILS_JS), 3)
    if not details or not details.get("close"):
        raise ValueError("已接受新增列车详情未能打开，请核对原订单")
    if page.stop():
        raise TaskCancelled()
    details["close"].click()
    if not page.poll(lambda: not page.driver.execute_script(ADDED_DETAILS_JS), 2):
        raise ValueError("新增列车详情尚未关闭，请核对原订单")
    fresh = page.snapshot()
    if (details.get("url") != snap.get("url") or fresh.get("url") != snap.get("url")
            or fresh.get("dialogs") or fresh.get("verification") or fresh.get("processing")
            or not anchor(before) or anchor(before) != anchor(fresh)
            or not new_train_summary_matches(details.get("text", ""), intent)):
        raise ValueError("官方新增列车条件或订单身份与已保存意图不一致，请核对原订单")
    return {**fresh, "orders": [{**item, "choices": record.get("choices", []),
              "details_verified": record.get("details_verified", False), "new_train_verified": True}
              if item.get("order_id") == record["order_id"] else item for item in fresh["orders"]]}
