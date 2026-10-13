"""Waitlist settings read from official controls, never inferred from inventory."""
from dataclasses import dataclass, asdict
from datetime import date
import re
import time


def deadline_minutes(value):
    match = re.fullmatch(r"开车前\s*(\d+)\s*(分钟|小时|天)", str(value).strip())
    return int(match[1]) * {"分钟": 1, "小时": 60, "天": 1440}[match[2]] if match else None


def canonical_deadline(value):
    minutes = deadline_minutes(value)
    if minutes is None or minutes <= 0:
        return str(value).strip()  # Preserve invalid legacy values for explicit correction.
    if minutes % 1440 == 0:
        return f"开车前{minutes // 1440}天"
    if minutes % 60 == 0:
        return f"开车前{minutes // 60}小时"
    return f"开车前{minutes}分钟"


@dataclass(frozen=True, order=True)
class NewTrainWindow:
    date: str
    start_hour: int
    end_hour: int

    def __post_init__(self):
        if not isinstance(self.date, str) or date.fromisoformat(self.date).isoformat() != self.date:
            raise ValueError("新增列车乘车日期无效")
        if (type(self.start_hour) is not int or type(self.end_hour) is not int
                or not 0 <= self.start_hour < self.end_hour <= 24):
            raise ValueError("新增列车时段须为0至24点内的整点，开始早于结束")


def normalize_windows(values):
    if not isinstance(values, (list, tuple)) or len(values) > 3:
        raise ValueError("新增列车最多设置3个日期")
    try:
        windows = tuple(NewTrainWindow(**item) if isinstance(item, dict) else item for item in values)
        if any(not isinstance(item, NewTrainWindow) for item in windows):
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError("新增列车日期或出发时段无效") from None
    if len({item.date for item in windows}) != len(windows):
        raise ValueError("新增列车日期不能重复")
    return tuple(sorted(windows))


def read_new_train_summary(text, windows):
    """Map official month/day labels only to explicitly saved full dates."""
    matches = re.findall(r"(\d{1,2})月(\d{1,2})日\s*[：:]\s*(\d{1,2})点\s*[-—]\s*(\d{1,2})点", text)
    if len(matches) != len(re.findall(r"\d{1,2}月\d{1,2}日", text)):
        return None
    result = []
    for month, day, start, end in matches:
        dates = [item.date for item in windows if int(item.date[5:7]) == int(month) and int(item.date[8:10]) == int(day)]
        if len(dates) != 1:
            return None
        try:
            result.append(NewTrainWindow(dates[0], int(start), int(end)))
        except ValueError:
            return None
    return tuple(sorted(result)) if result and len({item.date for item in result}) == len(result) else None


def new_train_summary_matches(text, intent):
    if not intent.new_train_windows:
        return not text
    route = re.search(r"乘车区间\s*[：:]\s*(\S+?)\s*[-—]\s*(\S+?)(?=\s|席别)", text)
    seats = re.search(r"席别(?:类型)?\s*[：:]\s*(.+?)(?=\d{1,2}月|期望出行时间|$)", text)
    if not route or not seats or route.groups() != (intent.from_station, intent.to_station):
        return False
    labels = set(filter(None, re.split(r"[,，、\s]+", seats[1].strip())))
    return (labels == {choice.seat for choice in intent.combinations}
            and read_new_train_summary(text, intent.new_train_windows) == intent.new_train_windows)


FORM_OPTIONS_JS = r"""
const visible=e=>!!(e&&e.getClientRects().length&&getComputedStyle(e).visibility==='visible');
const txt=e=>(e?.innerText||'').replace(/\s+/g,' ').trim();
const form=visible(document.querySelector('#ticket_card_list'))&&visible(document.querySelector('#dafaultTime'));
const list=document.querySelector('#date_box');
// The menu may be collapsed. Read labels only from its own non-disabled options.
const options=form&&list?[...list.querySelectorAll('li')].filter(e=>
  !e.matches('.disabled,.disable,[aria-disabled="true"]')&&!e.closest('[hidden]')&&getComputedStyle(e).display!=='none')
  .map(e=>(e.textContent||'').trim()).filter(s=>/^开车前\s*\d+\s*(分钟|小时|天)$/.test(s)):[];
const button=document.querySelector('#toPayBtn');
const rate=form&&visible(button)&&!button.querySelector('img')?txt(button).match(/^提交订单\s*预估成功率\s*[(（]\s*(\d+(?:\.\d+)?)%\s*[)）]$/):null;
const raw=rate?Number(rate[1]):null;
const summaries=[...document.querySelectorAll('#contact_train_time_content')].filter(visible).map(txt).filter(Boolean);
return {available:form,url:location.href,deadline:txt(document.querySelector('#dafaultTime')),
  deadline_options:[...new Set(options)],success_rate:raw!==null&&raw>=0&&raw<=100?raw:null,
  success_rate_status:button?.querySelector('img')?'loading':raw!==null&&raw>=0&&raw<=100?'available':'unavailable',
  new_train_summary:summaries.length===1?summaries[0]:summaries.length?'AMBIGUOUS':'',
  quiet_car:[...document.querySelectorAll('#ticket_card_list .ticket-info-txt')].some(e=>visible(e)&&/[（(]静[）)]/.test(txt(e)))};
"""


def trip_route_fields(trip_route):
    """The configured stations a snapshot was read for; a lookup key for trip settings only."""
    if not trip_route or len(trip_route) != 2:
        return {}
    from_station, to_station = (str(value or "").strip() for value in trip_route)
    return {"trip_from_station": from_station, "trip_to_station": to_station} if from_station and to_station else {}


def form_review(intent, data, snap, trip_route=None):
    observed = time.time()
    return {"source": "official_page", "observed_at": observed, "success_rate_observed_at": observed,
            "from_station": intent.from_station, "to_station": intent.to_station, **trip_route_fields(trip_route),
            "dates": list(dict.fromkeys(choice.date for choice in intent.combinations)),
            "choices": [asdict(choice) for choice in intent.combinations],
            "passenger_count": len(intent.passengers), "deadline": canonical_deadline(data.get("deadline", "")),
            "deadline_options": list(dict.fromkeys(canonical_deadline(value) for value in data.get("deadline_options", []))),
            "success_rate": data.get("success_rate"), "success_rate_status": data.get("success_rate_status", "unavailable"),
            "standing": snap.get("standing", ""), "quiet_car": data.get("quiet_car", False),
            "new_train_windows": [asdict(item) for item in intent.new_train_windows],
            "new_train_same_city": bool(intent.new_train_windows)}


def record_review(record):
    """Optional presentation fields are never evidence of order identity."""
    now = time.time()
    result = {"source": "official_page", "observed_at": now,
              "success_rate": None, "success_rate_status": "unavailable", "success_rate_observed_at": None}
    rate = str(record.get("success_rate", "")).strip()
    if re.fullmatch(r"\d+(?:\.\d+)?%", rate) and 0 <= float(rate[:-1]) <= 100:
        result.update(success_rate=float(rate[:-1]), success_rate_status="available", success_rate_observed_at=now)
    amount = str(record.get("prepay_amount", "")).strip()
    if re.fullmatch(r"\d+(?:\.\d{1,2})?", amount):
        result.update(prepay_amount=amount, amount_observed_at=now)
    return result


def added_fulfillment_matches(record, intent, known_id):
    # An added train can have a different code and same-city stations. That
    # identity comes from the bound official order and its explicit new-train
    # fulfillment marker, never from a guessed station-name/city relationship.
    if (not known_id or record.get("order_id") != known_id or record.get("kind") != "alternate"
            or not intent.new_train_windows or not record.get("new_train_verified")
            or not record.get("new_train_fulfilled") or not re.search("兑现成功|已兑现", record.get("state", ""))
            or sorted(record.get("passengers", [])) != sorted(intent.passengers)):
        return False
    winners = [item for item in record.get("choices", []) if item.get("fulfilled")]
    if len(winners) != 1:
        return False
    item = winners[0]
    from railwatch_order_page import normalized_date
    windows = [w for w in intent.new_train_windows if w.date == normalized_date(item.get("date", ""))]
    departure = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", item.get("departure", ""))
    if (len(windows) != 1 or not departure or not item.get("from") or not item.get("to")
            or not re.fullmatch(r"(?:[GDCZTKYSL]\d{1,5}|\d{4,5})", item.get("train", ""))
            or item.get("seat") not in {choice.seat for choice in intent.combinations}):
        return False
    minutes = int(departure[1]) * 60 + int(departure[2])
    # Boundary semantics have no observed fulfilled sample; use the unambiguous
    # interior until the official record supplies enough evidence at an endpoint.
    return windows[0].start_hour * 60 < minutes < windows[0].end_hour * 60
