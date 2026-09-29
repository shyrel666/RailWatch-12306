"""Read-only rehearsal orchestration. No transaction actions or account persistence."""
from __future__ import annotations

import math
import threading
import time
import uuid
from concurrent.futures import Future
from railwatch_config_contract import parse_codes, parse_passenger_names
from railwatch_task import TaskCancelled

CHECKS = (("config", "自动化配置"), ("sale_time", "起售时刻"), ("browser", "受控浏览器"),
          ("login", "登录会话"), ("passengers", "乘车人"), ("train_seat", "车次与席别"),
          ("drill", "交易路径演练"), ("clock", "系统时钟"), ("scheduler", "定时唤醒"), ("alerts", "提醒渠道"))
DEPENDENCIES = {"login": ("browser",), "passengers": ("browser", "login", "config"),
                "train_seat": ("browser", "login"), "drill": ("browser", "config", "train_seat")}


def public_trip(config):
    return {"from_station": config.get("from_station_cn", ""), "to_station": config.get("to_station_cn", ""),
            "date": config.get("date", ""), "train_codes": parse_codes(config.get("train_code"), upper=True),
            "seat_types": parse_codes(config.get("seat_keyword")),
            "passenger_count": len(parse_passenger_names(config.get("passengers", ""))),
            "auto_submit": bool(config.get("auto_submit")), "auto_alternate": bool(config.get("auto_alternate")),
            "sale_at": config.get("sale_at", "")}


def verdict(checks, cancelled=False):
    if cancelled:
        return "cancelled"
    if any(c["critical"] and c["status"] == "fail" for c in checks):
        return "blocked"
    if any(c["status"] in ("warn", "fail") or (c["critical"] or c.get("required_evidence"))
           and c["status"] in ("unknown", "skipped") for c in checks):
        return "risky"
    return "ready"


def background(function):
    """Only for bounded, read-only local/HTTP diagnostics; never for browser calls."""
    future = Future()
    def worker():
        try:
            future.set_result(function())
        except BaseException as exc:
            future.set_exception(exc)
    threading.Thread(target=worker, daemon=True, name="rehearsal-diagnostic").start()
    return future


def await_diagnostic(future, cancel):
    while not future.done():
        if cancel.wait(0.02):
            raise TaskCancelled()
    if cancel.is_set():
        raise TaskCancelled()
    return future.result()


def sample_scheduler_lateness(samples=24, lead=0.25, cancel=None):
    cancel = cancel or threading.Event()
    values, drift = [], []
    for _ in range(samples):
        wall, mono = time.time(), time.monotonic()
        target = mono + lead
        while time.monotonic() < target:
            if cancel.wait(min(0.02, max(0, target - time.monotonic()))):
                raise TaskCancelled()
        elapsed = time.monotonic() - mono
        values.append(max(0, (elapsed - lead) * 1000))
        drift.append(abs(time.time() - wall - elapsed) * 1000)
    ordered = sorted(values)
    return {"p50": ordered[max(0, math.ceil(samples * .5) - 1)],
            "p95": ordered[max(0, math.ceil(samples * .95) - 1)], "max": max(values),
            "clock_drift_ms": max(drift)}


class RehearsalRunner:
    def __init__(self, config, checks, *, emit=lambda *_: None, save=lambda _: None,
                 log=lambda *_: None, session_lost=lambda _: False, release=lambda: None, history=lambda: []):
        from copy import deepcopy
        self.config, self.checks, self.emit, self.save = deepcopy(config), checks, emit, save
        self.log, self.session_lost, self.release = log, session_lost, release
        self.history = history

    def run(self, *, trigger="manual", cancel=None, run_id=None):
        cancel = cancel or threading.Event()
        auto = bool(self.config.get("auto_submit") or self.config.get("auto_alternate"))
        definitions = [{"id": key, "title": title, "critical": key in ("browser", "login")
                       or key == "sale_time" and bool(self.config.get("timer_enabled"))
                       or key in ("config", "passengers", "train_seat", "drill") and auto,
                        "required_evidence": key == "clock" and bool(self.config.get("timer_enabled"))}
                       for key, title in CHECKS]
        report = {"schema_version": 1, "rehearsal_id": uuid.uuid4().hex, "trigger": trigger,
                  "started_at": time.time(), "trip": public_trip(self.config), "checks": [], "measurements": {}}
        if run_id:
            report["run_id"] = run_id
        self.emit("rehearsalStarted", {"rehearsal_id": report["rehearsal_id"], "trigger": trigger,
                                      "checks": definitions})
        scheduler = background(lambda: sample_scheduler_lateness(cancel=cancel))
        completed, lost = {}, False
        for definition in definitions:
            key, started = definition["id"], time.monotonic()
            result = {"status": "skipped", "summary": "彩排已取消", "details": []}
            try:
                if not cancel.is_set():
                    if lost and key in ("login", "passengers", "train_seat", "drill"):
                        result["summary"] = "浏览器会话已失效"
                    elif any(completed.get(dep) in ("fail", "unknown", "skipped") for dep in DEPENDENCIES.get(key, ())):
                        result["summary"] = "前置检查未通过，无法验证此步骤"
                    elif not auto and key in ("passengers", "drill"):
                        result = {"status": "pass", "summary": "仅监控余票，无需交易检查"}
                    else:
                        argument = await_diagnostic(scheduler, cancel) if key == "scheduler" else None
                        result = self.checks[key](report, cancel, argument)
            except TaskCancelled:
                cancel.set()
            except Exception as exc:
                result = {"status": "unknown", "summary": f"检查未完成（{type(exc).__name__}）"}
                if self.session_lost(exc):
                    lost = True
                    try:
                        self.release()
                    except Exception:
                        pass
            result = {**definition, **result, "duration_ms": round((time.monotonic() - started) * 1000),
                      "details": result.get("details", [])}
            completed[key] = result["status"]
            report["checks"].append(result)
            self.emit("rehearsalStep", {"rehearsal_id": report["rehearsal_id"], "check": result})
        report.update(finished_at=time.time(), verdict=verdict(report["checks"], cancel.is_set()))
        from railwatch_run_review import build_prediction
        try:
            history = self.history()
        except Exception:
            history = []
        report["prediction"] = build_prediction(report, history)
        try:
            self.save(report)
        except Exception:
            self.log("彩排报告未能保存，本次结论仍可查看。", "WARN")
        self.emit("rehearsalFinished", {"report": report})
        return report
