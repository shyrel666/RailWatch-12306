"""Attach to the app's LIVE logged-in Chrome via its DevTools port and reproduce
the confirm-order page readback, field by field. Never clicks 提交订单."""
from __future__ import annotations

import json
import os
import sys
import time
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import websocket
from railwatch_row_parser import BATCH_ROWS_JS, RowParser
from railwatch_config_contract import parse_passenger_names
from railwatch_selectors import BOOK_BUTTON_SELECTORS
import railwatch_order_page as op

DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/AppData/Local"), "railwatch-12306")

EXPECTED = {
    "train_code": "G1307",
    "date": "2026-09-12",
    "from_station": "北京丰台",
    "to_station": "成都东",
    "seat": "二等座",
}
QUERY_URL = ("https://kyfw.12306.cn/otn/leftTicket/init?linktypeid=dc"
             "&fs={fs},FTP&ts={ts},ICW&date={date}&flag=N,N").format(
    fs=quote(EXPECTED["from_station"]), ts=quote(EXPECTED["to_station"]), date=EXPECTED["date"])


def mask(text):
    for name in NAMES:
        if name:
            text = str(text).replace(name, "＜乘客＞")
    return text


def load_names():
    import sqlite3
    try:
        db = sqlite3.connect("file:" + os.path.join(DATA_DIR, "orders.sqlite3") + "?mode=ro", uri=True)
        row = db.execute("SELECT intent FROM orders WHERE unresolved=1 ORDER BY updated_at DESC LIMIT 1").fetchone()
        names = json.loads(row[0]).get("passengers", []) if row else []
        if names:
            return names
    except Exception:
        pass
    config_path = os.path.join(DATA_DIR, "user_config.json")
    if os.path.exists(config_path):
        with open(config_path, encoding="utf-8") as handle:
            passengers = json.load(handle).get("passengers", "")
        return parse_passenger_names(passengers) if isinstance(passengers, str) else passengers
    return []


NAMES = load_names()

CENSUS_JS = r"""
const visible = e => !!(e && e.getClientRects().length);
const txt = e => (e?.innerText || '').replace(/\s+/g,' ').trim();
const all = (s,r=document) => [...r.querySelectorAll(s)].filter(visible);
const labelName = e => {const l=e.closest('label')||document.querySelector('label[for="'+e.id+'"]');
  return (l?.getAttribute('title') || (l?.innerText||'').replace(/（(?:学生|儿童|成人)）/g,'')).trim();};
return {
  url: location.href,
  ticket_info_exists: !!document.querySelector('#ticket_info'),
  regular_text: txt(document.querySelector('#ticket_info')),
  sel_strong: all('.passenger-name strong[title]').map(e=>e.getAttribute('title')),
  sel_yichu: all('.name-yichu[title]').map(e=>e.getAttribute('title')),
  sel_passenger_info: all('.passenger-info .name[title]').map(e=>e.getAttribute('title')),
  sel_inputs: all('input[id^="passenger_name_"],input.name-input').map(e=>e.value.trim()).filter(Boolean),
  checked_labels: all('#normal_passenger_id input[type="checkbox"],#passenge_list input.chose-pass-dom')
    .filter(e=>e.checked).map(labelName),
  seat_selects_visible: all('select[id^="seatType_"]').length,
  seat_values: all('select[id^="seatType_"]').map(e=>e.selectedOptions[0]?.textContent.trim()||''),
  formReady: visible(document.querySelector('#normal_passenger_id')) || visible(document.querySelector('#passenge_list')),
  confirmation_visible: visible(document.querySelector('#qr_submit_id')),
  passenger_panel_html_len: (document.querySelector('#normal_passenger_id')?.outerHTML || document.querySelector('#passenge_list')?.outerHTML || '').length,
  selected_area_text: txt(document.querySelector('#passenge_table') || document.querySelector('#passenger-list') || ''),
  dialogs: all('.dhtmlx_window_active,.layui-layer,.modal,[role="dialog"]').map(txt).filter(Boolean),
};
"""


class CDP:
    def __init__(self, port, target_id):
        self.ws = websocket.create_connection(f"ws://127.0.0.1:{port}/devtools/page/{target_id}",
                                              timeout=40, suppress_origin=True)
        self.seq = 0

    def cmd(self, method, **params):
        self.seq += 1
        self.ws.send(json.dumps({"id": self.seq, "method": method, "params": params}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") == self.seq:
                if "error" in message:
                    raise RuntimeError(message["error"])
                return message.get("result", {})

    def js(self, expression, promise=False):
        wrapped = "(function(){\n" + expression + "\n})()"
        result = self.cmd("Runtime.evaluate", expression=wrapped, returnByValue=True, awaitPromise=promise)
        value = result.get("result", {})
        if value.get("subtype") == "error" or result.get("exceptionDetails"):
            raise RuntimeError(f"JS 执行失败: {json.dumps(result, ensure_ascii=False)[:400]}")
        return value.get("value")

    def navigate(self, url):
        self.cmd("Page.navigate", url=url)

    def wait_ready(self, timeout=30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.js("return document.readyState") == "complete":
                    return
            except Exception:
                pass
            time.sleep(0.5)
        raise TimeoutError("页面加载超时")


def find_page_target(port):
    import urllib.request
    request = urllib.request.Request(f"http://127.0.0.1:{port}/json", headers={"Host": "127.0.0.1"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    targets = json.loads(opener.open(request, timeout=5).read().decode("utf-8"))
    pages = [t for t in targets if t.get("type") == "page"]
    for target in pages:
        if "kyfw.12306.cn" in target.get("url", ""):
            return target
    if pages:
        return pages[0]
    raise SystemExit("浏览器里没有可用的页面标签")


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 58804
    target = find_page_target(port)
    cdp = CDP(port, target["id"])
    print(mask(f"预期值：{EXPECTED}，乘客 {len(NAMES)} 人（已脱敏）"), flush=True)

    logged = cdp.js("""
return new Promise(resolve => {
  fetch('/otn/login/checkUser',{credentials:'include'})
    .then(r=>r.json()).then(j=>resolve(!!(j.data&&j.data.flag))).catch(()=>resolve(false));
});""", promise=True)
    if not logged:
        print("结果：当前浏览器会话仍未登录，请先在浏览器里完成登录再运行。")
        return
    print("登录态有效。正在打开查询页……", flush=True)
    cdp.navigate(QUERY_URL)
    time.sleep(4)
    cdp.wait_ready()
    time.sleep(2)
    cdp.js("""
const els=[...document.querySelectorAll('a,button,div,span')]
  .filter(e=>e.getClientRects().length && e.innerText && e.innerText.replace(/\\s+/g,'')==='查询');
if(els.length) els[0].click();
""")
    row = None
    deadline = time.time() + 30
    while time.time() < deadline and row is None:
        rows = cdp.js("const fn=new Function('arguments', " + json.dumps(BATCH_ROWS_JS) + ");"
                      "return fn([{ '二等座': 'ZE' }]);") or []
        for item in rows:
            if item.get("train") == EXPECTED["train_code"]:
                row = item
                break
        if row is None:
            time.sleep(1)
    if row is None:
        print("结果：查询结果中没有 G1307，无法复现确认页。")
        return
    seat_value = (row.get("seats") or {}).get("二等座")
    print(f"G1307 二等座 当前显示：{seat_value!r}", flush=True)
    if not RowParser.is_seat_available(seat_value):
        print("结果：二等座当前无票，无法进入确认页复现。")
        return

    clicked = cdp.js("""
const code = arguments_val;
const row = [...document.querySelectorAll('tr[id^="ticket_"]')].find(r => r.innerText.includes(code));
if (!row) return 'row-not-found';
const sels = ["a.btn72", "a[onclick*='getSelected']"];
for (const s of sels) { for (const b of row.querySelectorAll(s)) {
  if (b.getClientRects().length && b.textContent.includes('预订')) { b.click(); return 'clicked'; } } }
const link = [...row.querySelectorAll('a,button')].find(e => e.getClientRects().length && e.textContent.trim() === '预订');
if (link) { link.click(); return 'clicked'; }
return 'button-not-found';
""".replace("arguments_val", json.dumps(EXPECTED["train_code"])))
    print(f"点击预订：{clicked}", flush=True)
    if clicked != "clicked":
        print("结果：未能点击预订按钮。")
        return

    time.sleep(3)
    deadline = time.time() + 25
    while time.time() < deadline:
        state = cdp.js("""
const visible = e => !!(e && e.getClientRects().length);
return {url: location.href,
  ready: (visible(document.querySelector('#normal_passenger_id'))||visible(document.querySelector('#passenge_list')))
         && !!document.querySelector('#ticket_info')};""")
        if state.get("ready"):
            break
        time.sleep(1)
    else:
        print(f"结果：未等到确认页（当前 {mask(cdp.js('return location.href'))}）。")
        return
    time.sleep(2)

    census = cdp.js(CENSUS_JS)
    snapshot = cdp.js("const fn=new Function('return (' + " + json.dumps(op.SNAPSHOT_JS) + " + ')'); return fn();")
    text = census.get("regular_text", "")

    checks = [
        ("页面存在 #ticket_info", "存在", str(census.get("ticket_info_exists")), bool(census.get("ticket_info_exists"))),
        ("乘车人回读 == 所选乘客", str(sorted(NAMES)), str(sorted(snapshot.get("passengers", []))) + "｜勾选框：" + str(census.get("checked_labels")),
         sorted(snapshot.get("passengers", [])) == sorted(NAMES)),
        ("车次独立词(可带'次')", EXPECTED["train_code"] + "(次)", "命中" if op.form_token(text, EXPECTED["train_code"], "次") else "未命中",
         op.form_token(text, EXPECTED["train_code"], "次")),
        ("日期归一化", EXPECTED["date"], op.normalized_date(text) or "（摘要中未解析到日期）", op.normalized_date(text) == EXPECTED["date"]),
        ("出发站独立词(可带'站')", EXPECTED["from_station"] + "(站)", "命中" if op.form_token(text, EXPECTED["from_station"], "站") else "未命中",
         op.form_token(text, EXPECTED["from_station"], "站")),
        ("到达站独立词(可带'站')", EXPECTED["to_station"] + "(站)", "命中" if op.form_token(text, EXPECTED["to_station"], "站") else "未命中",
         op.form_token(text, EXPECTED["to_station"], "站")),
    ]
    try:
        order_ok = text.index(EXPECTED["from_station"]) < text.index(EXPECTED["to_station"])
    except ValueError:
        order_ok = False
    checks.append(("出发站在到达站之前", "是", "是" if order_ok else "否/缺失", order_ok))
    expected_seats = [EXPECTED["seat"]] * max(len(NAMES), 1)
    actual_seats = [op.seat_label(v) for v in snapshot.get("seats", [])]
    checks.append(("席别下拉回读", str(expected_seats),
                   str(actual_seats) + f"（可见下拉 {census.get('seat_selects_visible')} 个）", actual_seats == expected_seats))

    print("\n===== 摘要文本 #ticket_info =====")
    print(mask(text or "（空）"))
    print("\n===== 逐项核对 =====")
    failed = []
    for name, expected, actual, ok in checks:
        print(mask(("[PASS] " if ok else "[FAIL] ") + name + " | 期望: " + expected + " | 实际: " + actual))
        if not ok:
            failed.append(name)
    print("\n===== 乘客选择器命中情况 =====")
    for key in ("sel_strong", "sel_yichu", "sel_passenger_info", "sel_inputs", "checked_labels", "selected_area_text"):
        print(f"{key}: {mask(census.get(key))}")
    print("\n结论：" + ("全部通过" if not failed else "失败项 → " + "；".join(failed)))
    report = {"census": census, "snapshot": {k: snapshot.get(k) for k in ("regular", "passengers", "seats", "url")}, "failed": failed}
    with open(os.path.join(DATA_DIR, "diag_live_readback.json"), "w", encoding="utf-8") as handle:
        handle.write(mask(json.dumps(report, ensure_ascii=False, indent=1, default=str)))
    print("完整报告已写入 diag_live_readback.json（乘客名已脱敏）")


if __name__ == "__main__":
    main()
