"""Native controls for the official added-train conditions dialog (2026-10-10)."""
from railwatch_alternate_options import new_train_summary_matches
from railwatch_selectors import ACTION_READY_JS
from railwatch_task import TaskCancelled


EDITOR_JS = ACTION_READY_JS + r"""
const text=e=>(e?.innerText||'').replace(/\s+/g,' ').trim();
const dialogs=[...document.querySelectorAll('.modal,.up-box,[role="dialog"]')].filter(rwActionReady);
const roots=dialogs.filter(e=>e.matches('.dzp-confirm > .modal')&&text(e.querySelector('.modal-tit'))==='新增列车兑现条件设置');
if(roots.length!==1)return null;
const root=roots[0];
if(dialogs.some(e=>e!==root&&!e.contains(root)&&!root.contains(e)))return null;
const rules=[...root.querySelectorAll('.mt-sm.clearfix .pull-left')].map(text).join(' ');
const rows=[...root.querySelectorAll('[data-date]')].filter(e=>e.querySelector('.linkeTime')).map(row=>{
 const input=row.querySelector('.linkeTime');
 const controls=['Time1','Time2'].map(name=>{
   const list=row.querySelector('.'+name), box=list?.closest('.sel');
   return {value:text(box?.querySelector('.sel-inner')),button:box?.querySelector('.sel-hd'),
     options:list?[...list.querySelectorAll('li')].filter(e=>rwActionReady(e)&&!e.matches('.disabled,.disable,[aria-disabled="true"]'))
       .map(e=>({label:text(e),button:e})):[]};
 });
 return {date:row.getAttribute('data-date'),checked:input.checked,enabled:!input.disabled,
   toggle:input.closest('label'),controls};
});
const saves=[...root.querySelectorAll('#saveTime')].filter(rwActionReady);
const closes=[...root.querySelectorAll('.modal-close')].filter(rwActionReady);
return {rules,rows,save:saves.length===1&&text(saves[0])==='保存设置'?saves[0]:null,
 close:closes.length===1?closes[0]:null};
"""


def set_new_trains(page, intent):
    def click(button):
        if page.stop():
            raise TaskCancelled()
        if button is None:
            raise ValueError("新增列车控件不可操作")
        button.click()

    snap = page.snapshot()
    if not intent.new_train_windows:
        if snap.get("addedTrain"):
            click(page.button(("#addTrainInput", "label[for='contact_train']")))
        if page.snapshot().get("addedTrain"):
            raise ValueError("未能关闭接受新增列车")
        return
    if snap.get("addedTrain"):
        if new_train_summary_matches(page.alternate_options().get("new_train_summary", ""), intent):
            return
        click(page.button(("#contact_train_time_content .linKeEdit",)))
    else:
        click(page.button(("#addTrainInput", "label[for='contact_train']")))

    data = page.poll(lambda: page.driver.execute_script(EDITOR_JS), 5)
    if not data:
        raise ValueError("新增列车兑现条件设置未打开")
    # The official dialog derives route/seats from the candidate choices.
    # Append only the explicit authorized windows to reuse exact rules parsing.
    dates_text = ' '.join(f'{int(w.date[5:7])}月{int(w.date[8:10])}日：{w.start_hour}点-{w.end_hour}点'
                          for w in intent.new_train_windows)
    if not new_train_summary_matches(data["rules"] + ' ' + dates_text, intent):
        raise ValueError("新增列车区间或席别与候补方案不一致")
    wanted = {w.date.replace('-', ''): w for w in intent.new_train_windows}
    dates = [r["date"] for r in data["rows"]]
    if len(set(dates)) != len(dates) or not set(wanted) <= set(dates):
        raise ValueError("官网未提供所选新增列车日期")
    for row in data["rows"]:
        selected = row["date"] in wanted
        # A date the order neither uses nor has checked may stay disabled.
        if (selected or row["checked"]) and not row["enabled"]:
            raise ValueError("官网新增列车日期暂不可选")
        if row["checked"] != selected:
            click(row["toggle"])
    for key, window in wanted.items():
        # The official menu disables starts at/after the current end. Expand
        # that end first when moving the whole interval later in the day.
        current = page.driver.execute_script(EDITOR_JS)
        row = next((r for r in (current or {}).get("rows", []) if r["date"] == key), None)
        if not row:
            raise ValueError("新增列车日期控件已变化")
        try:
            old_end = int(row["controls"][1]["value"].removesuffix("点"))
        except (ValueError, KeyError, IndexError):
            raise ValueError("新增列车时段控件无法读取") from None
        indices = (1, 0) if window.start_hour >= old_end else (0, 1)
        for index in indices:
            hour = (window.start_hour, window.end_hour)[index]
            current = page.driver.execute_script(EDITOR_JS)
            row = next((r for r in (current or {}).get("rows", []) if r["date"] == key), None)
            if not row:
                raise ValueError("新增列车日期控件已变化")
            control = row["controls"][index]
            if control["value"] != f"{hour}点":
                click(control["button"])
                current = page.driver.execute_script(EDITOR_JS)
                rows = [r for r in (current or {}).get("rows", []) if r["date"] == key]
                options = [o for o in rows[0]["controls"][index]["options"] if o["label"] == f"{hour}点"] if len(rows) == 1 else []
                if len(options) != 1:
                    raise ValueError("官网未提供所选新增列车时段")
                click(options[0]["button"])
    data = page.driver.execute_script(EDITOR_JS)
    selected = [r for r in (data or {}).get("rows", []) if r["checked"]]
    if ({r["date"] for r in selected} != set(wanted) or any(
            [c["value"] for c in r["controls"]] != [f"{wanted[r['date']].start_hour}点", f"{wanted[r['date']].end_hour}点"]
            for r in selected)):
        raise ValueError("新增列车日期或时段回读不一致")
    click(data["save"])
    if not page.poll(lambda: new_train_summary_matches(page.alternate_options().get("new_train_summary", ""), intent), 5):
        raise ValueError("新增列车条件保存后未能回读")
    # Saving may replace the dialog with recommendations; close its native X.
    # The suggested trains are never selected here.
    data = page.driver.execute_script(EDITOR_JS)
    if data:
        click(data["close"])
    if not page.poll(lambda: not page.driver.execute_script(EDITOR_JS), 3):
        raise ValueError("新增列车条件弹窗未关闭")
    if not page.snapshot().get("addedTrain") or not new_train_summary_matches(
            page.alternate_options().get("new_train_summary", ""), intent):
        raise ValueError("新增列车条件在关闭弹窗后发生变化")
