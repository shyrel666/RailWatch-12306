"""Read-only rehearsal checks; classifications are independently testable."""
from __future__ import annotations

import datetime as dt
import time
from dataclasses import replace
from urllib.parse import urlparse
from railwatch_config_contract import automation_config_issue, parse_codes, parse_passenger_names
from railwatch_dates import beijing_now, PRESALE_WINDOW_DAYS
from railwatch_rehearsal import background, await_diagnostic
from railwatch_sale_times import official_sale_at
from railwatch_task import TaskCancelled

PASSENGERS_URL = "https://kyfw.12306.cn/otn/view/passengers.html"


def result(status, summary, *, details=None, fix=None):
    return {"status": status, "summary": summary, "details": details or [], **({"fix": fix} if fix else {})}


def fix(page="行程设置", section="trip-basics", label="修改行程", **extra):
    return {"page": page, "section": section, "label": label, **extra}


def check_config(config):
    issue = automation_config_issue(config)
    return result("fail" if issue else "pass", issue or ("自动化配置完整" if config.get("auto_submit") or config.get("auto_alternate")
                  else "仅监控余票"), fix=fix())


def check_sale_time(config, official, now, checked_at=None):
    if official is None:
        return result("unknown", "官方起售时刻无法唯一确定，请人工核对", fix=fix(section="trip-timer", label="核对定时"))
    if config.get("timer_enabled"):
        from railwatch_time import resolve_sale_timestamp
        try:
            target = resolve_sale_timestamp(config)
        except ValueError:
            target = None
        if official.timestamp() <= now:
            # Released already: only a future timer delays the first query.
            if target is not None and target <= now:
                return result("pass", "目标日期已开售，启动后会立即查询")
            return result("warn", "目标日期已开售，定时会推迟首次查询，建议改为立即开始",
                          fix=fix(section="trip-timer", label="改为立即开始"))
        matches = target == official.timestamp()
        return result("pass" if matches else "fail", "起售时刻与官方一致" if matches else f"官方起售时刻为 {official:%Y-%m-%d %H:%M:%S}",
                      fix=fix(section="trip-timer", label="改为官方时刻", sale_at=official.isoformat(),
                              **({"checked_at": checked_at} if checked_at is not None else {})))
    return result("warn" if official.timestamp() > now else "pass",
                  "目标日期尚未起售，建议启用定时" if official.timestamp() > now else "目标日期已到起售时刻",
                  fix=fix(section="trip-timer", label="设置定时"))


def check_passengers(config, book):
    repair = fix(label="修改乘车人")
    if not book.get("complete"):
        return result("unknown", "名单未完整读取，无法确认唯一性；下单页仍按原规则核对", fix=repair)
    details, statuses = [], []
    selections = {p["name"]: p for p in config.get("passenger_selections", [])}
    for name in parse_passenger_names(config.get("passengers", "")):
        label = (name[:1] if len(name) > 1 else "") + "*"
        matches = [p for p in book.get("items", []) if p["name"] == name]
        status, message = "pass", "唯一匹配，成人，身份核验通过"
        if not matches:
            status, message = "fail", "常用乘车人中没有该完整姓名"
        elif len(matches) != 1:
            status, message = "fail", "存在同名记录，自动勾选会被拒绝，请在官方页面处理"
        else:
            person = matches[0]
            kind, verification = person.get("ticket_type"), person.get("verification")
            if kind in ("student", "child") or person.get("unsupported_ticket_type"):
                status, message = "fail", "自动交易仅支持成人票"
            elif verification == "failed":
                status, message = "fail", "身份核验未通过，请在官方页面处理"
            elif kind != "adult" and person.get("type_source") != "unavailable":
                status = "fail" if config.get("auto_alternate") else "warn"
                message = "列表未明确成人票种；普通订单将在下单页回读，候补无法预先确认"
            elif verification != "passed":
                status, message = "warn", "身份状态需按证件情况人工核对，未认定为官方拒绝购票"
            elif kind != "adult":
                # The account holder's row never exposes a ticket type on the
                # official page; that is a known display gap, not a risk. The
                # order page still re-reads the type before submitting.
                message = "本人行官方页面不显示票种，视为成人；下单页或候补页仍会按原规则核对"
            saved = selections.get(name, {}).get("identity_hint")
            actual = person.get("identity_hint")
            if saved and actual and saved != actual:
                if status == "pass":
                    status = "warn"
                message += "；证件摘要与导入记录不一致"
        details.append(f"{label}：{message}")
        statuses.append(status)
    status = "fail" if "fail" in statuses else "warn" if "warn" in statuses else "pass"
    return result(status, "乘车人核对完成" if status == "pass" else "乘车人存在待处理问题", details=details, fix=repair)


def read_passenger_book(driver, cancel):
    from railwatch_order_page import READ_PASSENGER_BOOK_JS
    if urlparse(driver.current_url).path != "/otn/view/passengers.html":
        driver.get(PASSENGERS_URL)
    items = []
    total_pages = None
    for expected in range(1, 11):
        deadline = time.monotonic() + 5
        while True:
            if cancel.is_set():
                raise TaskCancelled()
            book = driver.execute_script(READ_PASSENGER_BOOK_JS)
            if book.get("recognized") and book.get("page") == expected:
                break
            if time.monotonic() >= deadline:
                return {"complete": False, "items": items}
            cancel.wait(.05)
        if not book.get("pagination_valid") or total_pages is not None and total_pages != book.get("total_pages"):
            return {"complete": False, "items": items}
        total_pages = book.get("total_pages")
        items.extend(book["items"])
        if book.get("complete"):
            return {"complete": True, "items": items}
        if len(items) >= 100 or expected == 10 or not book.get("has_next"):
            break
        # Sole click in this module: the official passenger list's next-page control.
        controls = driver.find_elements("css selector", ".pagination a.next")
        controls = [e for e in controls if e.is_displayed() and e.is_enabled()]
        if len(controls) != 1:
            break
        controls[0].click()
    return {"complete": False, "items": items}


def check_train_seat(config, rows, query):
    repair = fix(label="修改车次与席别")
    if query.get("status") in ("rate_limited", "server_backoff"):
        delay = query.get("retry_after_seconds")
        return result("warn", f"查询被限流，未重试；建议等待 {delay if delay is not None else '官方建议的'} 秒", fix=repair)
    if query.get("status") not in ("ok", "empty"):
        return result("unknown", "查询未完成，无法确认车次与席别", fix=repair)
    trains = parse_codes(config.get("train_code", ""), upper=True)
    seats = parse_codes(config.get("seat_keyword", ""))
    if not trains or not seats:
        return result("pass", "已完成一次查询，未限定交易车次或席别")
    details, usable, uncertain = [], 0, False
    for train in trains:
        matches = [r for r in rows if r.get("train") == train]
        if len(matches) != 1:
            details.append(f"{train}：本次运行图未找到唯一车次")
            continue
        for seat in seats:
            cell = matches[0].get("seats", {}).get(seat)
            value = cell.get("raw") if isinstance(cell, dict) else cell
            if value in ("--", "不适用"):
                details.append(f"{train} · {seat}：不开行此席别")
            elif value in (None, "", "*"):
                uncertain = True
                details.append(f"{train} · {seat}：页面无法确认")
            else:
                usable += 1
    status = "warn" if uncertain else "fail" if not usable else "warn" if details else "pass"
    return result(status, "车次与席别核对完成（不预测余票）", details=details, fix=repair)


def probe_date(target, today, last_released):
    """Latest released date no later than the target; last_released covers today's sale time."""
    last = today + dt.timedelta(days=PRESALE_WINDOW_DAYS - (1 if last_released else 2))
    return max(today, min(target, last))


def check_clock(offset, uncertainty, error=""):
    if error or uncertainty is None:
        return result("unknown", "HTTP 时间辅助检查不可用；定时仍使用系统时钟")
    status = "pass" if abs(offset) <= 1 else "warn" if abs(offset) <= 3 else "fail"
    return result(status, f"系统时钟偏差约 {offset:+.2f}s，不确定度 ±{uncertainty:.2f}s；请开启系统自动对时")


def check_scheduler(sample):
    p95 = sample["p95"]
    status = "pass" if p95 <= 100 else "warn" if p95 <= 250 else "fail"
    if sample.get("clock_drift_ms", 0) > 100:
        status = "warn" if status == "pass" else status
    return result(status, f"本机唤醒迟到 P95 {p95:.1f}ms；不代表开售时官方响应速度")


def check_alerts(settings, statuses):
    required = {"server_chan": ("server_chan_key",), "email": ("email_smtp_host", "email_user", "email_password", "email_to"),
                "wecom_webhook": ("wecom_webhook_url",)}
    warnings = [key for key, fields in required.items() if settings.get(f"{key}_enabled") and
                (not all(settings.get(field) for field in fields) or statuses.get(key, {}).get("status") in ("failed", "not_configured", "queue_full"))]
    enabled = any(settings.get(f"{key}_enabled") for key in required)
    return result("warn" if warnings else "pass", "提醒渠道配置不完整或最近发送失败" if warnings else
                  "提醒渠道已配置（未代表本次发送成功）" if enabled else "仅桌面提醒",
                  details=warnings, fix=fix("系统设置", "settings-notifications", "检查提醒设置"))


def make_checks(bridge, config):
    """Adapters keep browser effects out of the pure classifications above."""
    shared = {}
    def sale(report, cancel, _):
        from railwatch_sale_times import sale_time_service
        def read():
            info = sale_time_service.query(config["from_station_cn"])
            # Freshness is evaluated after the fetch, not against its start time.
            return info, official_sale_at(config["from_station_cn"], config["date"], time.time(), info=info)
        info, official = await_diagnostic(background(read), cancel)
        shared["info"] = info
        return check_sale_time(config, official, time.time(), checked_at=info.get("checked_at"))
    def browser(report, cancel, _):
        from railwatch_bridge import driver_session_alive, detect_chrome_version, detect_chromedriver_version
        if not bridge.driver or not driver_session_alive(bridge.driver):
            return result("fail", "受控浏览器未打开，请先登录", fix=fix("系统设置", "settings-login", "打开登录页"))
        chrome = detect_chrome_version() if detect_chrome_version else None
        driver = detect_chromedriver_version(bridge.chromedriver_path) if detect_chromedriver_version else None
        mismatch = chrome and driver and str(chrome).split('.')[0] != str(driver).split('.')[0]
        return result("warn" if mismatch else "pass", "浏览器与驱动大版本不一致" if mismatch else "受控浏览器可用",
                      fix=fix("系统设置", "settings-environment", "检查环境"))
    def login(report, cancel, _):
        # Reuse the passenger navigation, then only one checkUser request.
        bridge.driver.get(PASSENGERS_URL)
        state = bridge._verify_login_session(cancel=cancel)
        # Only definite answers update the flag; the phase belongs to the owner
        # (idle UI or a running monitor task) and must not change here.
        if state in ("ok", "expired"):
            bridge.state = replace(bridge.state, login_ready=state == "ok")
            bridge.emit_state()
        return result({"ok": "pass", "expired": "fail"}.get(state, "unknown"),
                      {"ok": "登录会话有效", "expired": "登录已失效，请重新登录"}.get(state, "登录会话无法确认"),
                      fix=fix("系统设置", "settings-login", "检查登录"))
    def passengers(report, cancel, _):
        return check_passengers(config, read_passenger_book(bridge.driver, cancel))
    def train(report, cancel, _):
        today = beijing_now().date()
        target = dt.date.fromisoformat(config["date"])
        info = shared.get("info")
        last = today + dt.timedelta(days=PRESALE_WINDOW_DAYS - 1)
        # Unknown release of the newest window day falls back to the day before.
        last_sale = official_sale_at(config["from_station_cn"], last.isoformat(), time.time(), info=info) if info else None
        probe = probe_date(target, today, last_sale is not None and last_sale.timestamp() <= time.time())
        report["trip"]["probe_date"] = probe.isoformat()
        rows, query = bridge._probe_query(bridge.driver, {**config, "date": probe.isoformat(), "query_timeout": min(15, config.get("query_timeout", 15))}, cancel)
        shared["rows"] = rows
        if query.get("round_trip_ms") is not None:
            report["measurements"]["query_round_trip_ms"] = query["round_trip_ms"]
        answer = check_train_seat(config, rows, query)
        if probe != target:
            answer["details"].append(f"基于 {probe} 的运行图，目标日期可能不同")
        return answer
    def drill(report, cancel, _):
        from railwatch_rehearsal_drill import run_drill
        return run_drill(bridge.driver, config, shared.get("rows", []), bridge.data_dir, cancel, report["measurements"])
    def clock(report, cancel, _):
        from railwatch_time import ServerTimeSync
        def sync():
            diagnostic = ServerTimeSync()
            offset = diagnostic.sync(force=True)
            return offset, diagnostic.uncertainty_seconds, diagnostic.last_error
        offset, uncertainty, error = await_diagnostic(background(sync), cancel)
        report["measurements"].update(clock_offset_s=offset, clock_uncertainty_s=uncertainty)
        return check_clock(offset, uncertainty, error)
    def scheduler(report, cancel, sample):
        report["measurements"]["scheduler_late_ms"] = sample
        return check_scheduler(sample)
    def alerts(report, cancel, _):
        if shared.get("send_test_notification"):
            await_diagnostic(background(bridge.notification_service.test_notification), cancel)
        return check_alerts(bridge.notification_service.settings, bridge.notification_service.status())
    shared["send_test_notification"] = False
    return {"config": lambda *_: check_config(config), "sale_time": sale, "browser": browser, "login": login,
            "passengers": passengers, "train_seat": train, "drill": drill, "clock": clock,
            "scheduler": scheduler, "alerts": alerts}, shared
