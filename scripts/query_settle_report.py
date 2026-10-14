"""Summarize query-completion timing and pre-sale evidence from local telemetry.

Reads query_timing events from orders.sqlite3 read-only. Never opens a browser,
sends a request or writes the journal. Output is aggregate numbers only.

    python -X utf8 scripts/query_settle_report.py [--db PATH] [--run RUN_ID] [--json]
"""
import argparse
import json
import math
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MIN_SAMPLES = 200
CURRENT_QUIET_MS = 300
SALE_WINDOW_MS = 45_000  # Default burst_window_seconds after the sale time.
SEQUENCE_FROM_MS = -10_000


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def distribution(values):
    if not values:
        return {"samples": 0}
    return {"samples": len(values), "p50_ms": percentile(values, .5), "p95_ms": percentile(values, .95),
            "p99_ms": percentile(values, .99), "max_ms": max(values)}


def load_details(path, run_id=None):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"找不到本地记录：{path}")
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        query = "SELECT detail FROM order_events WHERE stage='query_timing'"
        rows = db.execute(query + " AND run_id=? ORDER BY sequence" if run_id else query + " ORDER BY sequence",
                          (run_id,) if run_id else ()).fetchall()
    finally:
        db.close()
    details = []
    for (raw,) in rows:
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            details.append(value)
    return details


def settle_stats(details):
    """Distributions over completed queries that carry page timing."""
    late_counts, late_max, gap_max, query_step = [], [], [], []
    spans = {"network": [], "render": [], "detect": [], "settle": []}
    for detail in details:
        page = detail.get("page")
        if detail.get("status") not in ("ok", "empty"):
            continue
        # The query step baseline also covers records written before page timing existed.
        step = next((s.get("duration_ms") for s in detail.get("steps", [])
                     if isinstance(s, dict) and s.get("id") == "query"), None)
        if number(step) and step >= 0:
            query_step.append(step)
        if not isinstance(page, dict) or not all(number(page.get(key)) and page[key] >= 0
                                                 for key in ("late_count", "late_max_ms", "gap_max_ms")):
            continue
        late_counts.append(page["late_count"])
        late_max.append(page["late_max_ms"])
        gap_max.append(page["gap_max_ms"])
        for name, start, end in (("network", "sent_ms", "response_ms"), ("render", "response_ms", "last_change_ms"),
                                 ("detect", "last_change_ms", "completed_ms"), ("settle", "response_ms", "completed_ms")):
            if number(page.get(start)) and number(page.get(end)) and page[end] >= page[start]:
                spans[name].append(round(page[end] - page[start], 1))
    samples = len(late_counts)
    return {"samples": samples,
            "late_zero_share": round(late_counts.count(0) / samples, 4) if samples else None,
            "late_max": distribution(late_max), "gap_max": distribution(gap_max),
            "network": distribution(spans["network"]), "render": distribution(spans["render"]),
            "detect": distribution(spans["detect"]), "settle": distribution(spans["settle"]),
            "query_step": distribution(query_step)}


def quiet_decision(stats):
    """SALE_SPEED_PLAN W2 rule; M3 decides whether to adopt it."""
    if not stats["samples"]:
        return {"eligible": False, "enough_samples": False, "quiet_ms": CURRENT_QUIET_MS}
    late_p99, gap_p99 = stats["late_max"]["p99_ms"], stats["gap_max"]["p99_ms"]
    eligible = stats["late_zero_share"] >= .99 or late_p99 <= 150
    quiet = min(CURRENT_QUIET_MS, max(50, math.ceil(max(late_p99, gap_p99) + 30))) if eligible else CURRENT_QUIET_MS
    return {"eligible": eligible, "enough_samples": stats["samples"] >= MIN_SAMPLES, "quiet_ms": quiet}


def build_report(details):
    statuses = {}
    for detail in details:
        status = str(detail.get("status") or "unconfirmed")
        statuses[status] = statuses.get(status, 0) + 1
    # Completed by the heuristic, then rejected by a later ownership check.
    completed = [d for d in details if isinstance(d.get("page"), dict)
                 and d.get("status") in ("ok", "empty", "invalid")]
    stale = sum(d.get("status") == "invalid" for d in completed)
    not_on_sale = [d for d in details if d.get("status") == "not_on_sale"]
    presale = [d["presale"] for d in details if isinstance(d.get("presale"), dict)]
    labels = sorted({label for p in presale for label in p.get("labels", []) if isinstance(label, str)})
    sale = [d for d in details if number(d.get("sale_offset_ms")) and 0 <= d["sale_offset_ms"] <= SALE_WINDOW_MS]
    stats = settle_stats(details)
    resettles = [item for d in details if isinstance(d.get("resettle"), list)
                 for item in d["resettle"] if isinstance(item, dict)]
    sequence = sorted((d for d in details if number(d.get("sale_offset_ms"))
                       and SEQUENCE_FROM_MS <= d["sale_offset_ms"] <= SALE_WINDOW_MS),
                      key=lambda d: d["sale_offset_ms"])
    return {
        "recorded": len(details), "statuses": dict(sorted(statuses.items())),
        "settle": stats, "decision": quiet_decision(stats),
        "stale_after_completion": {"completed": len(completed), "stale": stale,
                                   "rate": round(stale / len(completed), 4) if completed else None},
        # Late re-renders that W2b waited out instead of discarding the round.
        "resettle": {"attempts": len(resettles), "accepted": sum(item.get("ok") is True for item in resettles)},
        "not_on_sale": {"total": len(not_on_sale),
                        "request_sent": sum(number(d.get("requests")) and d["requests"] >= 1 for d in not_on_sale),
                        "no_request": sum(d.get("requests") == 0 for d in not_on_sale),
                        "unknown": sum(not number(d.get("requests")) for d in not_on_sale)},
        "presale_rows": {"queries": len(presale),
                         "with_sale_text": sum(number(p.get("sale_text_rows")) and p["sale_text_rows"] > 0
                                               for p in presale),
                         "all_rows_star": sum(number(p.get("rows")) and p["rows"] > 0
                                              and p.get("all_star_rows") == p["rows"] for p in presale),
                         "labels": labels[:10]},
        "sale_window": {"queries": len(sale), "settle": settle_stats(sale)},
        "sale_sequence": [{"offset_ms": d["sale_offset_ms"], "status": d.get("status"), "requests": d.get("requests"),
                           "presale": d.get("presale"), "sale_retry": d.get("sale_retry")} for d in sequence],
    }


def format_distribution(name, value):
    if not value.get("samples"):
        return f"  {name}：无样本"
    return (f"  {name}：p50 {value['p50_ms']:g} / p95 {value['p95_ms']:g} / p99 {value['p99_ms']:g} / "
            f"最大 {value['max_ms']:g} ms（{value['samples']} 条）")


def format_report(report):
    settle, decision = report["settle"], report["decision"]
    lines = [f"query_timing 记录：{report['recorded']} 条；按状态：" +
             ("、".join(f"{key} {value}" for key, value in report["statuses"].items()) or "无"),
             f"带页面计时的有效查询：{settle['samples']} 条（目标 ≥{MIN_SAMPLES}）"]
    if settle["samples"]:
        lines.append(f"  loadend 之后无相关变化的比例：{settle['late_zero_share']:.2%}")
    for key, label in (("late_max", "late_max_ms（loadend 后最晚变化）"), ("gap_max", "gap_max_ms（响应后相邻变化最大间隔）"),
                       ("network", "请求发出 → 响应"), ("render", "响应 → 最后一次相关变化"),
                       ("detect", "最后一次变化 → 判定完成"), ("settle", "响应 → 判定完成"), ("query_step", "query 步")):
        lines.append(format_distribution(label, settle[key]))
    verdict = ("暂无样本，保留" if not settle["samples"] else "满足缩短条件" if decision["eligible"]
               else "不满足缩短条件，保留") + f"：quiet_ms = {decision['quiet_ms']}"
    lines.append(f"静默窗口建议：{verdict}" + ("" if decision["enough_samples"] else "（样本不足，仅供参考）"))
    stale = report["stale_after_completion"]
    if stale["completed"]:
        lines.append(f"判定完成后又失效：{stale['stale']}/{stale['completed']}（{stale['rate']:.2%}）")
    resettle = report["resettle"]
    if resettle["attempts"]:
        lines.append(f"判定后页面又变化、重新等稳定：{resettle['accepted']}/{resettle['attempts']} 次成功")
    nos = report["not_on_sale"]
    lines.append(f"未起售提示：{nos['total']} 次；已发出查询 {nos['request_sent']}，未发出 {nos['no_request']}，"
                 f"未知 {nos['unknown']}")
    pre = report["presale_rows"]
    lines.append(f"目标行起售候选标志：{pre['queries']} 轮中 {pre['with_sale_text']} 轮出现“起售”文字，"
                 f"{pre['all_rows_star']} 轮全部席位为 *；文字样例：{'、'.join(pre['labels']) or '无'}")
    window = report["sale_window"]
    lines.append(f"起售后 {SALE_WINDOW_MS // 1000} 秒内查询：{window['queries']} 条")
    lines.append(format_distribution("起售窗口 query 步", window["settle"]["query_step"]))
    if report["sale_sequence"]:
        lines.append("起售前后查询序列（相对起售时刻）：")
        for item in report["sale_sequence"][:30]:
            presale = item["presale"] or {}
            retry = item["sale_retry"] if isinstance(item["sale_retry"], dict) else {}
            lines.append(f"  {item['offset_ms'] / 1000:+.1f}s {item['status']} requests={item['requests']} "
                         f"起售文字 {presale.get('sale_text_rows', '-')}/{presale.get('rows', '-')}"
                         + (f" 未开售证据={retry.get('evidence')} 快速重查={retry.get('retry') or '否'}"
                            if retry.get("evidence") else ""))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", help="orders.sqlite3 路径，默认使用本机数据目录")
    parser.add_argument("--run", help="只统计指定 run_id")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)
    if args.db:
        path = args.db
    else:
        from railwatch_bridge import get_data_path
        path = get_data_path("orders.sqlite3")
    report = build_report(load_details(path, args.run))
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else format_report(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
