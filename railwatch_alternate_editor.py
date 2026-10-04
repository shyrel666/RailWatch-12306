"""Select exact alternatives through the official, visible waitlist editor."""
from dataclasses import replace
import time
from urllib.parse import urlparse

from railwatch_alternate_plan import AlternateChoice, AlternatePlan
from railwatch_policies import rate_bounds
from railwatch_selectors import ACTION_READY_JS


EDITOR_JS = ACTION_READY_JS + r"""
const root=document.querySelector('#popup');
const shown=e=>!!(e && e.getClientRects().length && getComputedStyle(e).visibility==='visible');
const text=e=>(e?.innerText||'').replace(/\s+/g,' ').trim();
if(!shown(root)) return {url:location.href,open:false};
const dateNodes=[...root.querySelectorAll('.date-list .date-item,.date-list .date-item-disable')];
const dates=dateNodes.map(e=>({date:e.getAttribute('data-val'),active:e.classList.contains('is-active'),
  count:Number(text(e.querySelector('.date-info')).match(/已选\((\d+)\)/)?.[1]||0),
  button:e,enabled:rwActionReady(e)&&!e.classList.contains('date-item-disable')}));
const current=dates.filter(e=>e.active);
const date=current.length===1?current[0].date:'';
const station=e=>{if(!e)return '';const copy=e.cloneNode(true);
  copy.querySelectorAll('.label-shi,.label-guo,.label-zhong,i').forEach(n=>n.remove());return copy.textContent.trim();};
const rows=[];
for(const item of root.querySelectorAll('.ticket-result-item')){
  if(!shown(item))continue;
  const train=text(item.querySelector('.ticket-number-num'));
  const stations=[...item.querySelectorAll('.ticket-item-info .ticket-time-info')].map(station);
  for(const group of item.querySelectorAll('.ticket-item-buy-item')){
    const seat=text(group.querySelector('.ticket-price-seat'));
    for(const button of group.querySelectorAll('.ticket-btn a')){
      if(text(button)!=='候补'||!shown(button))continue;
      // These DOM fields provide identity only. Never return the opaque secret.
      const parts=(button.getAttribute('data-info')||'').split('#');
      // The normal editor has 11 fields; its last field is a train flag,
      // not a date. A dated recommendation has 12 fields instead.
      const dated=parts.length===12?parts[10]:date;
      const ownDate=/^\d{8}$/.test(dated)?dated.slice(0,4)+'-'+dated.slice(4,6)+'-'+dated.slice(6):dated;
      rows.push({train,date:parts.length>1?ownDate:date,from:parts.length>1?parts[8]:stations[0],
        to:parts.length>1?parts[9]:stations[1],seat,button,
        selected:button.classList.contains('is-active'),
        enabled:rwActionReady(button)&&button.classList.contains('hbbtn')&&!button.classList.contains('btn-disabled'),
        identity_ok:parts.length===1||([11,12].includes(parts.length)&&parts[2]===train
          &&parts[8]===stations[0]&&parts[9]===stations[1]&&(seat!=='二等座'||parts[4]==='O'))});
    }
  }
}
const alerts=[...document.querySelectorAll('.dhtmlx_window_active,.layui-layer,.modal,[role="dialog"],.up-box')]
  .filter(e=>e!==root&&!root.contains(e)&&shown(e)).map(text).filter(Boolean);
return {url:location.href,open:true,date,dates,rows,alerts,
  resultRoot:root.querySelector('.ticket-result-bd'),
  all:!!root.querySelector('#oneTouch:checked'),
  verification:[...document.querySelectorAll('#nc_1_n1z,.nc_scale,.slide-verify,#randCode,#J-loginImg')].some(shown)};
"""


class AlternateEditor:
    def __init__(self, page, config=None):
        self.page, self.config = page, config or {}
        self.interval = max(3.0, rate_bounds(self.config)[0], float(self.config.get("interval", 3)))
        self.last_query = None

    def read(self):
        data = self.page.driver.execute_script(EDITOR_JS)
        origin = urlparse(data.get("url", ""))
        trusted = (origin.scheme == "https" and origin.hostname == "kyfw.12306.cn"
                   and origin.path == "/otn/view/lineUp_toPay.html") or (self.page.allow_fixture and origin.scheme == "file")
        if not trusted:
            raise ValueError("候补备选页面身份无法确认")
        if data.get("alerts") or data.get("verification") or data.get("all"):
            raise ValueError("请处理候补提示或关闭一键候补后重新核对")
        return data

    def _click(self, button):
        if self.page.stop():
            from railwatch_task import TaskCancelled
            raise TaskCancelled()
        button.click()

    def open(self):
        if self.read().get("open"):
            raise ValueError("候补备选编辑器已打开，请先完成当前编辑")
        # At three selected dates the add-more control may disappear. The
        # existing plan's edit control still opens the same native editor.
        button = self.page.button(("#init_add", "#continue_add", "#planList .editPlan"))
        if button is None:
            raise ValueError("未找到可核对的添加备选方案入口")
        self._wait_query()
        self._click(button)
        self.last_query = time.monotonic()
        if not self.page.poll(lambda: self.read().get("open")):
            raise ValueError("候补备选方案未加载")

    def _wait_query(self):
        remaining = self.interval - (time.monotonic() - self.last_query) if self.last_query is not None else 0
        if remaining > 0:
            self.page.wait(remaining)

    def select_date(self, travel_date):
        current = self.read()
        previous_root = None
        if current.get("date") != travel_date:
            choices = [item for item in current.get("dates", []) if item["date"] == travel_date and item["enabled"]]
            if len(choices) != 1:
                raise ValueError("候补日期不可用或存在歧义")
            previous_root = current.get("resultRoot")
            if previous_root is None:
                raise ValueError("候补结果区域无法确认")
            self._wait_query()
            # Changing the date requests official inventory. Use the page's own
            # control and normal cadence; never call its private request helpers.
            self._click(choices[0]["button"])
            self.last_query = time.monotonic()
        def ready():
            data = self.read()
            return (data.get("date") == travel_date and data.get("resultRoot") is not None
                    and (previous_root is None or data["resultRoot"] != previous_root))
        if not self.page.poll(ready):
            raise ValueError("候补日期切换未确认")
        return self.read()

    @staticmethod
    def entries(data):
        entries = []
        for row in data.get("rows", []):
            try:
                choice = AlternateChoice.from_detail(row)
            except (KeyError, TypeError, ValueError):
                if row.get("selected"):
                    raise ValueError("已选候补组合无法完整读取") from None
                continue
            if not row.get("identity_ok") or choice.date != data.get("date"):
                raise ValueError("候补备选结果日期或车次已经变化")
            entries.append((choice, row))
        return entries

    def verify_open(self, choices):
        expected = set(choices)
        for travel_date in dict.fromkeys(choice.date for choice in choices):
            data = self.select_date(travel_date)
            selected = [choice for choice, row in self.entries(data) if row["selected"]]
            if len(selected) != len(set(selected)) or set(selected) != {c for c in expected if c.date == travel_date}:
                raise ValueError("已选候补清单与保存的组合不一致")
            counts = {item["date"]: item["count"] for item in data.get("dates", []) if item["count"]}
            expected_counts = {value: len({(c.train_code, c.from_station, c.to_station) for c in choices if c.date == value})
                               for value in {c.date for c in choices}}
            if counts != expected_counts:
                raise ValueError("候补清单包含未授权日期或遗漏组合")

    def confirm(self):
        button = self.page.button(("#popup .submitTicket",))
        if button is None:
            raise ValueError("候补备选清单确认入口不可用")
        self._click(button)
        if not self.page.poll(lambda: not self.read().get("open")):
            raise ValueError("候补备选清单尚未确认")

    def populate(self, intent):
        plan = AlternatePlan(intent, self.config)
        initial = self.page.snapshot()
        if initial.get("extra") or initial.get("addedTrain"):
            raise ValueError("页面已有额外候补需求，请先核对原清单")
        if tuple(AlternateChoice.from_detail(value) for value in initial.get("details", [])) != (plan.primary,):
            raise ValueError("候补首个组合与当前订单不一致")
        chosen = [plan.primary]
        self.open()
        started = time.monotonic()
        for travel_date in plan.dates:
            if len(chosen) >= plan.limit or time.monotonic() - started >= self.config.get("date_scan_budget_seconds", 30):
                break
            data = self.select_date(travel_date)
            rows = self.entries(data)
            selected = [choice for choice, row in rows if row["selected"]]
            if selected != [choice for choice in chosen if choice.date == travel_date]:
                raise ValueError("候补编辑器包含未核对的已有选择")
            candidates = sorted({choice for choice, row in rows if row["enabled"] and plan.allows(choice)
                                 and choice not in chosen}, key=plan.rank)
            for candidate in candidates:
                if len(chosen) >= plan.limit:
                    break
                current = [(choice, row) for choice, row in self.entries(self.read()) if choice == candidate]
                if len(current) != 1 or not current[0][1]["enabled"] or current[0][1]["selected"]:
                    raise ValueError("候补组合在添加前已改变")
                self._click(current[0][1]["button"])
                if not self.page.poll(lambda: any(choice == candidate and row["selected"]
                                                  for choice, row in self.entries(self.read()))):
                    raise ValueError("候补组合添加后未能回读确认")
                chosen.append(candidate)
        if not plan.validate(chosen):
            raise ValueError("候补组合超出配置范围")
        self.verify_open(chosen)
        self.confirm()
        return replace(intent, choices=tuple(chosen))

    def verify(self, intent):
        self.open()
        self.verify_open(intent.combinations)
        self.confirm()
        return True
