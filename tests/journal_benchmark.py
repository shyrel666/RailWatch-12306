"""Offline journal write benchmark for the hit → order path (SALE_SPEED_PLAN W4).

Example: python -X utf8 tests/journal_benchmark.py --output build/qa/journal.json
Compare a baseline checkout with --source-root. Temporary databases only.
Gates (rollback journal, no concurrent reader): begin() plus the hit marker
p95 <= 15ms, and mark() with one buffered telemetry event p95 <= 15ms.
WAL rows are a reference column only; the journal keeps rollback mode.
"""
import argparse
import inspect
import json
import math
from pathlib import Path
import sqlite3
import statistics
import sys
import tempfile
import threading
import time


WORKSPACE = Path(__file__).resolve().parents[1]
SEEDED_EVENTS = 20_000
GATE_MS = 15.0
DETAIL = {"query_id": "0" * 32, "date": "2026-10-20", "status": "ok", "hit": False, "revisit_ms": 3000.0,
          "steps": [{"id": name, "start_ms": 0.0, "duration_ms": 10.0}
                    for name in ("prepare", "query", "snapshot", "decision", "publish")]}


def summarize(values):
    ordered = sorted(values)
    return {"samples": len(values), "p50_ms": round(statistics.median(ordered), 2),
            "p95_ms": round(ordered[math.ceil(len(ordered) * .95) - 1], 2)}


class Reader(threading.Thread):
    """Dashboard-like short read transactions, much more often than the real 5s poll."""

    def __init__(self, path):
        super().__init__(daemon=True)
        self.path, self.stopped = path, threading.Event()

    def run(self):
        while not self.stopped.is_set():
            db = sqlite3.connect(self.path, timeout=3)
            try:
                db.execute("SELECT at,monotonic,detail FROM order_events WHERE run_id='bench' AND stage='query_timing' "
                           "ORDER BY sequence DESC LIMIT 60").fetchall()
                db.execute("SELECT count(*) FROM order_events WHERE run_id='bench' AND stage='query_timing'").fetchone()
            finally:
                db.close()
            self.stopped.wait(.02)


def run_case(modules, journal_mode, reader, samples):
    OrderJournal, OrderIntent = modules
    found_in_begin = "found" in inspect.signature(OrderJournal.begin).parameters
    results = {}
    with tempfile.TemporaryDirectory(prefix="railwatch-journal-bench-") as directory:
        path = str(Path(directory) / "orders.sqlite3")
        journal = OrderJournal(path)
        detail = json.dumps(DETAIL)
        with journal.connection() as db:
            db.executemany("INSERT INTO order_events(run_id,intent_id,stage,at,monotonic,detail) VALUES(?,?,?,?,?,?)",
                           [("bench", "", "query_timing", time.time(), time.monotonic(), detail)] * SEEDED_EVENTS)
        if journal_mode == "wal":
            with journal.connection() as db:
                db.execute("PRAGMA journal_mode=WAL")
        background = Reader(path) if reader else None
        if background:
            background.start()
        try:
            def buffered(count):
                for _ in range(count):
                    journal.record_telemetry("bench", "query_timing", detail=DETAIL)

            for count in (0, 60):
                values = []
                for index in range(samples + 1):
                    buffered(count)
                    intent = OrderIntent("regular", "G101", "2026-10-20", "北京", "上海", "二等座", ("张三",))
                    started = time.perf_counter()
                    if found_in_begin:
                        journal.begin("bench", intent, {}, "inventory_found")
                    else:
                        journal.begin("bench", intent, {})
                        journal.mark("bench", "inventory_found", intent.intent_id)
                    elapsed = (time.perf_counter() - started) * 1000
                    with journal.connection() as db:
                        db.execute("UPDATE orders SET unresolved=0 WHERE unresolved=1")
                    if index:
                        values.append(elapsed)
                results[f"begin_hit_buffered_{count}"] = summarize(values)
            for count in (0, 1, 60):
                values = []
                for index in range(samples + 1):
                    buffered(count)
                    started = time.perf_counter()
                    journal.mark("bench", "order_timing", detail={"kind": "regular", "steps": DETAIL["steps"]})
                    elapsed = (time.perf_counter() - started) * 1000
                    if index:
                        values.append(elapsed)
                results[f"mark_buffered_{count}"] = summarize(values)
        finally:
            if background:
                background.stopped.set()
                background.join()
            journal.flush_telemetry()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-root", type=Path, default=WORKSPACE)
    parser.add_argument("--samples", type=int, default=60)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be positive")
    source = args.source_root.resolve()
    sys.path.insert(0, str(source))
    from railwatch_orders import OrderIntent, OrderJournal
    report = {"source_root": str(source), "samples_per_case": args.samples, "seeded_events": SEEDED_EVENTS,
              "python": sys.version.split()[0], "platform": sys.platform, "cases": {}}
    for journal_mode in ("delete", "wal"):
        for reader in (False, True):
            name = f"{journal_mode}_{'reader' if reader else 'idle'}"
            report["cases"][name] = run_case((OrderJournal, OrderIntent), journal_mode, reader, args.samples)
    idle = report["cases"]["delete_idle"]
    report["gates"] = {key: {"p95_ms": idle[key]["p95_ms"], "limit_ms": GATE_MS, "passed": idle[key]["p95_ms"] <= GATE_MS}
                       for key in ("begin_hit_buffered_0", "begin_hit_buffered_60", "mark_buffered_1")}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, cases in report["cases"].items():
        print(name, {key: (value["p50_ms"], value["p95_ms"]) for key, value in cases.items()})
    print("gates", {key: value["passed"] for key, value in report["gates"].items()})


if __name__ == "__main__":
    main()
