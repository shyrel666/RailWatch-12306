"""Pure, explicitly incomplete timing reviews and source-labelled predictions."""
import math
from statistics import median

LABELS = {"wake": "唤醒迟到", "first_query": "首次查询", "query": "查询往返", "decision": "决策",
          "readback": "下单页与核对", "confirm": "确认弹窗", "official": "官方处理",
          "alternate_open": "候补路径准备", "alternate_submit": "候补核对", "alternate_official": "候补处理"}

ORDER_STEP_LABELS = {"page_load": "打开并等待下单页", "passengers": "选择乘车人",
                     "seats": "选择席别", "deadline": "选择候补截止时间", "readback": "提交前核对",
                     "submit": "提交操作", "confirmation_wait": "等待确认弹窗",
                     "confirmation_action": "操作确认弹窗", "result_wait": "等待并核对订单结果"}


def order_timing_details(events):
    groups = []
    for event in events:
        if event["stage"] != "order_timing":
            continue
        detail = event["detail"]
        if detail.get("kind") not in ("regular", "alternate"):
            continue
        segments = []
        for step in detail.get("steps", []):
            if not isinstance(step, dict) or step.get("id") not in ORDER_STEP_LABELS:
                continue
            if any(type(step.get(key)) not in (int, float) or not math.isfinite(step[key]) or step[key] < 0
                   for key in ("start_ms", "duration_ms")):
                continue
            segments.append({**step, "label": ORDER_STEP_LABELS[step["id"]], "source": "本机观察"})
        if segments:
            groups.append({"kind": detail["kind"], "segments": segments})
    return groups


def duration(start, end):
    if not start or not end or end["sequence"] <= start["sequence"]:
        return None
    mono = end["monotonic"] - start["monotonic"]
    wall = end["at"] - start["at"]
    if mono < 0 or abs(wall - mono) > 2:
        return None  # Resume across process/clock discontinuity cannot establish duration.
    return round(mono * 1000, 3)


CONCLUSION_STAGES = ("order_result", "inventory_found", "no_inventory", "alternate_first_action",
                     "verification", "unknown", "sold_out", "not_submitted", "confirmed_failure",
                     "regular_submit", "regular_confirm_dispatched", "alternate_submit", "submitting",
                     "task_finished")


def run_conclusion(events):
    """Needs only CONCLUSION_STAGES events, so list views can skip full reviews."""
    ordered = sorted((event for event in events if event["stage"] in CONCLUSION_STAGES), key=lambda e: e["sequence"])
    hit = next((e for e in ordered if e["stage"] in ("inventory_found", "no_inventory")), None)
    alt = next((e for e in ordered if e["stage"] == "alternate_first_action"
                and (hit is None or e["sequence"] > hit["sequence"])), None)
    # Dismissing local review does not resolve an uncertain official outcome.
    # Prefer the latest recorded result, including later cancellation/expiry.
    for event in reversed(ordered):
        stage, detail = event["stage"], event["detail"]
        status = detail.get("status") if stage == "order_result" else stage
        if stage == "order_result" and detail.get("official"):
            official = {"pending_payment": "候补待支付" if alt else "待支付", "fulfilled": "购票成功",
                        "active": "候补已生效", "cancelled": "订单已取消", "expired": "订单已过期",
                        "failed": "候补兑现失败"}
            if status in official:
                return official[status]
        if status == "verification":
            return "需要核验"
        if status in ("unknown", "pending_payment", "active", "fulfilled", "cancelled", "expired", "failed"):
            return "结果待核对"
        if status in ("sold_out", "not_submitted", "confirmed_failure"):
            return {"sold_out": "已确认售罄", "not_submitted": "未提交", "confirmed_failure": "提交未成功"}[status]
        if stage in ("regular_submit", "regular_confirm_dispatched", "alternate_submit", "submitting"):
            return "结果待核对"
    finished = next((event for event in reversed(ordered) if event["stage"] == "task_finished"), None)
    if finished:
        return {"stopped": "已停止", "error": "运行异常", "hit": "已命中",
                "human_action": "需要人工处理", "verification": "需要核验",
                "unknown": "结果待核对"}.get(finished["detail"].get("status"), "记录不完整")
    return "记录不完整"


def build_run_review(events, report=None):
    ordered = sorted(events, key=lambda e: e["sequence"])
    def first(stage, after=None):
        return next((e for e in ordered if e["stage"] in stage.split("|") and (after is None or e["sequence"] > after["sequence"])), None)
    target = first("target_sale")
    wake = first("scheduler_wake")
    hit = first("inventory_found|no_inventory")
    click = first("query_click", wake or target)
    pairs = []
    pending = None
    for event in ordered:
        if event["stage"] == "query_click":
            pending = event
        elif event["stage"] == "query_result" and pending:
            pairs.append((pending, event))
            pending = None
    hit_pair = next((pair for pair in reversed(pairs) if hit and pair[1]["sequence"] < hit["sequence"]), None)
    chosen = hit_pair or (pairs[0] if pairs else (None, None))
    submit = first("regular_submit", hit)
    confirm = first("regular_confirm_dispatched", submit)
    official = first("pending_payment|order_result", confirm) if confirm else None
    alt = first("alternate_first_action", hit)
    alt_submit = first("alternate_submit", alt) if alt else None
    alt_done = first("pending_payment|active|order_result", alt_submit) if alt_submit else None
    values = {"wake": (wake or {}).get("detail", {}).get("late_ms"), "first_query": duration(wake, click),
              "query": duration(*chosen), "decision": duration(chosen[1], hit), "readback": duration(hit, submit),
              "confirm": duration(submit, confirm), "official": duration(confirm, official)}
    first_known = (wake or {}).get("detail", {}).get("first_query_known", True)
    if not first_known:
        values["first_query"] = None
    if alt or alt_submit:
        values.update(alternate_open=duration(hit, alt), alternate_submit=duration(alt, alt_submit), alternate_official=duration(alt_submit, alt_done))
    target_at = (target or {}).get("detail", {}).get("target_at")
    starts = {"first_query": wake, "query": chosen[0], "decision": chosen[1], "readback": hit,
              "confirm": submit, "official": confirm, "alternate_open": hit, "alternate_submit": alt, "alternate_official": alt_submit}
    def offset(key):
        if key == "wake":
            return 0
        start = starts.get(key)
        return max(0, (start["at"] - target_at) * 1000) if start and target_at is not None else None
    segments = [{"id": key, "label": LABELS[key], "duration_ms": value, "start_ms": offset(key),
                 "source": "本机观察" if value is not None else "未记录"} for key, value in values.items()]
    known = [s for s in segments if s["duration_ms"] is not None]
    prepared = first("prepared")
    margin = (target_at - prepared["at"]) * 1000 if target_at is not None and prepared else None
    rounds = [duration(a, b) for a, b in pairs if wake is None or a["sequence"] > wake["sequence"]][:5]
    rounds = [v for v in rounds if v is not None]
    conclusion = run_conclusion(ordered)
    return {"run_id": (target or (ordered[0] if ordered else {})).get("run_id", ""), "target_at": target_at,
            "trip": (target or {}).get("detail", {}).get("trip", (report or {}).get("trip", {})), "conclusion": conclusion,
            "segments": segments, "slowest": max(known, key=lambda s: s["duration_ms"])["label"] if known else None,
            "order_timings": order_timing_details(ordered),
            "preparation_margin_ms": margin, "query_median_ms": median(rounds) if rounds and first_known else None,
            "history_complete": all(s["duration_ms"] is not None for s in segments),
            "note": "未记录的阶段不推测补齐；可能未命中、未执行对应路径，或查询遥测已按 20,000 条上限清理。官方处理为本机观察时间。",
            "prediction": report.get("prediction", build_prediction(report, [])) if report else []}


def build_prediction(report, history):
    measurements = (report or {}).get("measurements", {})
    measured = {"wake": measurements.get("scheduler_late_ms", {}).get("p95"),
                "query": measurements.get("query_round_trip_ms")}
    predictions = []
    for key in ("wake", "query", "readback", "confirm", "official"):
        values = [segment["duration_ms"] for review in history for segment in review.get("segments", [])
                  if segment["id"] == key and isinstance(segment.get("duration_ms"), (float, int))
                  and math.isfinite(segment["duration_ms"]) and segment["duration_ms"] >= 0]
        value, source = measured.get(key), "本机实测"
        if value is None and values:
            value, source = median(values), "历史中位数"
        if value is None and key == "readback":
            drill = measurements.get("drill_ms", {})
            # Only the regular path matches this segment; "readback" is the pre-split key.
            value = drill.get("regular_readback", drill.get("readback"))
            source = "本地脚本，不含官方页面加载"
        predictions.append({"id": key, "label": LABELS[key], "duration_ms": value, "source": source if value is not None else "未知"})
    return predictions
