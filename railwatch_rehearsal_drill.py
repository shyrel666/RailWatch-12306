"""Local-only transaction fixture with tab-scoped offline and navigation guards."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import time
from urllib.parse import urlparse
from railwatch_task import TaskCancelled
from selenium.webdriver.remote.command import Command


class DrillIsolationError(RuntimeError):
    pass


@contextmanager
def cancellable_browser(driver, cancel):
    if driver is None:
        yield
        return
    original_execute, original_get = driver.execute, driver.get
    def execute(command, params=None):
        if cancel.is_set():
            raise TaskCancelled()
        return original_execute(command, params)
    def navigate(url):
        parsed = urlparse(url)
        if parsed.scheme != "file" and url not in (
                "https://kyfw.12306.cn/otn/view/passengers.html",
                "https://kyfw.12306.cn/otn/leftTicket/init?linktypeid=dc"):
            raise ValueError("彩排导航地址不在白名单")
        token = str(time.monotonic_ns())
        driver.execute_script("window.__railwatch_navigation=arguments[0]", token)
        driver.execute_cdp_cmd("Page.navigate", {"url": url})
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if cancel.wait(.05):
                raise TaskCancelled()
            state = driver.execute_script("return {old:window.__railwatch_navigation,ready:document.readyState}")
            if state.get("old") != token and state.get("ready") == "complete":
                return
        raise TimeoutError("彩排页面加载超时")
    driver._rehearsal_raw_execute = original_execute
    driver.execute, driver.get = execute, navigate
    try:
        yield
    finally:
        driver.execute, driver.get = original_execute, original_get
        del driver._rehearsal_raw_execute


@contextmanager
def isolated_drill_tab(driver, path, cancel):
    original = driver.current_window_handle
    original_url = driver.current_url
    active_execute, active_get = driver.execute, driver.get
    raw = getattr(driver, "_rehearsal_raw_execute", active_execute)
    handle = None
    try:
        if cancel.is_set():
            raise TaskCancelled()
        # Keep the handle even if cancellation arrives during tab creation.
        handle = raw("newWindow", {"type": "tab"})["value"]["handle"]
        driver.switch_to.window(handle)
        driver.execute_cdp_cmd("Network.enable", {})
        driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": ["http://*", "https://*", "ws://*", "wss://*"]})
        driver.execute_cdp_cmd("Network.emulateNetworkConditions", {
            "offline": True, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1})
        driver.execute_cdp_cmd("Network.setBypassServiceWorker", {"bypass": True})
        driver.execute_cdp_cmd("Network.setCacheDisabled", {"cacheDisabled": True})
        uri = Path(path).resolve().as_uri()
        active_get(uri)
        def assert_local():
            if driver.current_window_handle != handle or driver.current_url != uri:
                raise RuntimeError("离线演练上下文已改变")
        assert_local()
        def get(url):
            assert_local()
            if url != uri:
                raise RuntimeError("离线演练禁止外部导航")
            active_get(uri)
        verified_at = float("-inf")
        def execute(command, params=None):
            nonlocal verified_at
            if cancel.is_set():
                raise TaskCancelled()
            # Prevent OrderPage fallback navigations, even if it bypasses get().
            if command in ("get", "newWindow", "switchToWindow"):
                raise RuntimeError("离线演练禁止更换页面")
            # Clicks are always preceded by a context check; read-only polling is
            # sampled, since the offline tab already stops network access.
            if command == Command.CLICK_ELEMENT or time.monotonic() - verified_at >= .25:
                if (raw(Command.W3C_GET_CURRENT_WINDOW_HANDLE)["value"] != handle
                        or raw(Command.GET_CURRENT_URL)["value"] != uri):
                    raise DrillIsolationError("离线演练上下文已改变")
                verified_at = time.monotonic()
            return active_execute(command, params)
        driver.get, driver.execute = get, execute
        yield assert_local
    finally:
        driver.get = active_get
        driver.execute = raw  # Cleanup must work even after cancellation.
        try:
            if handle is not None and handle in driver.window_handles:
                driver.switch_to.window(handle)
                driver.close()
            driver.switch_to.window(original)
            if driver.current_url != original_url:
                raise DrillIsolationError("原标签页已改变，请重新打开登录页")
        except Exception as exc:
            raise DrillIsolationError("无法恢复原标签页，请重新打开登录页") from exc
        finally:
            driver.execute = active_execute


TEMPLATE = r'''<!doctype html><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'; form-action 'none'; base-uri 'none'">
<title>RailWatch 离线核对演练</title>
<style>.hidden{display:none}label,button,a,select{display:inline-block}td{padding:3px}</style>
<button id="book">本地普通路径</button><button id="candidate">本地候补路径</button>
<div id="regular" class="hidden"><div id="ticket_info"></div><div id="normal_passenger_id"></div><div id="normal-selected"></div><button id="submitOrder_id">本地提交</button></div>
<div id="candidate-form" class="hidden"><div id="ticket_card_list"><div class="ticket-card">
<div class="ticket-date"></div><div class="ticket-number"></div>
<div class="ticket-station-start"><div class="ticket-station-name"></div></div><div class="ticket-station-end"><div class="ticket-station-name"></div></div>
<div class="ticket-info-txt"><span></span></div></div></div><div id="passenge_list"></div><div id="candidate-selected"></div>
<div id="dafaultTime"></div><ul id="date_box" class="hidden"></ul><div id="is_open">已关闭</div><input id="addTrainInput" type="checkbox"><div id="planList"></div><a id="toPayBtn" href="#">本地候补提交</a></div>
<div class="modal hidden" id="dialog"></div><div id="records"></div>
<script>
const data=__DATA__;
const fixture={regularClicks:0,confirmClicks:0,alternateClicks:0,kind:'regular'};
const el=id=>document.getElementById(id), show=id=>el(id).classList.remove('hidden');
const make=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
const date=data.date.replace(/-/g,'/');
el('ticket_info').textContent=`${data.train_code}次 ${data.date} ${data.from_station}站 → ${data.to_station}站`;
document.querySelector('.ticket-date').textContent=data.date;
document.querySelector('.ticket-number').textContent=data.train_code;
for(const [selector,value] of [['.ticket-station-start .ticket-station-name',data.from_station],['.ticket-station-end .ticket-station-name',data.to_station],['.ticket-info-txt span',data.seat]]){
 const e=document.querySelector(selector);e.textContent=value;e.title=value;
}
el('dafaultTime').textContent=data.deadline||'开车前60分钟';
function selected(area,target,regular){
 const names=[...el(area).querySelectorAll('input:checked')].map(e=>e.parentElement.title);el(target).replaceChildren();
 names.forEach((name,i)=>{const input=make('input');input.value=name;input.readOnly=true;if(regular)input.id='passenger_name_'+i;else input.className='name-input';el(target).append(input);
 if(regular){const seat=make('select');seat.id='seatType_'+i;seat.append(make('option',data.seat+'（1.00元）'));const type=make('select');type.id='ticketType_'+i;type.append(make('option','成人票'));el(target).append(seat,type);}});
}
for(const [area,target,regular] of [['normal_passenger_id','normal-selected',true],['passenge_list','candidate-selected',false]]){
 for(const name of data.passengers){const l=make('label',name+'（成人）');l.title=name;const input=make('input');input.type='checkbox';if(!regular)input.className='chose-pass-dom';l.prepend(input);input.onchange=()=>selected(area,target,regular);el(area).append(l);}
}
el('book').onclick=()=>show('regular');el('candidate').onclick=()=>{fixture.kind='alternate';show('candidate-form');};
function record(){
 for(const id of ['regular','candidate-form','dialog'])el(id).classList.add('hidden');
 const item=make('div',undefined,'order-item');const heading=make('div',(fixture.kind==='alternate'?'候补单号':'订单号')+'：E123456 ','order-item-hd');heading.append(make('span','待支付','order-status'));item.append(heading,make('p',`${data.train_code} ${data.date} ${data.from_station} ${data.to_station} ${data.seat}`));
 for(const name of data.passengers){const p=make('div',undefined,'passenger-name'),n=make('strong',name);n.title=name;p.append(n);item.append(p);}el('records').replaceChildren(item);
}
el('submitOrder_id').onclick=()=>{fixture.regularClicks++;el('dialog').replaceChildren();const a=make('a','本地确认','btn92s');a.id='qr_submit_id';a.href='javascript:;';
 const preferences=data.passengers.map((_,i)=>{const p=make('select');p.id='seat_preference_'+i;for(const v of ['B','A','C','F'])p.append(make('option',v));el('dialog').append(p);return p;});
 el('dialog').append(a);show('dialog');a.onclick=()=>{fixture.confirmClicks++;fixture.seatPreferences=preferences.map(p=>p.value);record();};};
el('toPayBtn').onclick=e=>{e.preventDefault();fixture.alternateClicks++;fixture.deadline=el('dafaultTime').textContent;record();};
</script>'''


def run_drill(driver, config, rows, data_dir, cancel, measurements):
    from railwatch_orders import OrderIntent
    from railwatch_order_page import OrderPage
    from railwatch_rehearsal import public_trip
    trip = public_trip(config)
    row = next((r for r in rows if r.get("train") in trip["train_codes"]
                and r.get("from_station") and r.get("to_station")), None)
    if row is None or not trip["seat_types"]:
        return {"status": "unknown", "summary": "缺少实际发到站证据，无法构造离线演练"}
    details, durations = [], {}
    statuses = []
    for kind, enabled in (("regular", config.get("auto_submit")), ("alternate", config.get("auto_alternate"))):
        if not enabled:
            continue
        if cancel.is_set():
            raise TaskCancelled()
        intent = OrderIntent.from_config(config, row["train"], trip["seat_types"][0], kind)
        intent = replace(intent, from_station=row["from_station"], to_station=row["to_station"])
        payload = {key: getattr(intent, key) for key in ("train_code", "date", "from_station", "to_station", "seat", "passengers", "deadline")}
        with tempfile.TemporaryDirectory(prefix="rehearsal-", dir=data_dir) as directory:
            path = Path(directory) / "drill.html"
            path.write_text(TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")), encoding="utf-8")
            with isolated_drill_tab(driver, path, cancel) as assert_local:
                started = time.monotonic()
                page = OrderPage(driver, stop=cancel.is_set, wait=cancel.wait, allow_fixture=True)
                marks = {}
                page.mark = lambda stage, detail=None: marks.setdefault(stage, time.monotonic())
                assert_local()
                if kind == "regular":
                    outcome = page.regular(driver.find_element("id", "book"), intent, seat_preference=config.get("seat_prefer", "无偏好"))
                else:
                    outcome = page.alternate(driver.find_element("id", "candidate"), intent)
                assert_local()
                counters = driver.execute_script("return fixture")
                valid = outcome.status == "pending_payment" and (counters["regularClicks"] == counters["confirmClicks"] == 1 if kind == "regular"
                        else counters["alternateClicks"] == 1 and page.deadline_matches(counters.get("deadline", ""), intent.deadline, intent.date))
                preference = config.get("seat_prefer")
                if kind == "regular" and preference in ("靠窗优先", "靠过道优先"):
                    wanted = ("A", "F") if preference == "靠窗优先" else ("C", "D")
                    actual = counters.get("seatPreferences", [])
                    valid = valid and len(actual) == len(intent.passengers) and all(value in wanted for value in actual)
                statuses.append(valid)
                reason = outcome.reason if not valid else "本地核对通过"
                if not valid:
                    reason += "；" + page.form_mismatch_report(intent)
                for name in intent.passengers:
                    reason = reason.replace(name, "＜乘客＞")
                details.append(("普通订单" if kind == "regular" else "候补") + "：" + reason)
                durations[kind] = round((time.monotonic() - started) * 1000, 3)
                submit = marks.get(f"{kind}_submit")
                if submit:
                    durations[f"{kind}_readback"] = round((submit - started) * 1000, 3)
    measurements["drill_ms"] = durations
    return {"status": "pass" if all(statuses) and statuses else "fail", "summary": "离线演练，仅验证 RailWatch 自身的核对逻辑",
            "details": details, "fix": {"page": "行程设置", "section": "trip-basics", "label": "核对行程"}}
