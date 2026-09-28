"""Offline synthetic history benchmark; timings are reports, not CI assertions.

python -X utf8 tests/history_paging_benchmark.py --baseline path/to/old_orders.py
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sqlite3
import statistics
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from railwatch_orders import OrderJournal
from test_p3_paging import measured_reads, seed_history


def measure(journal, kwargs):
    with measured_reads(journal) as stats:
        page = journal.history_page(**kwargs)
    timings = []
    for _ in range(7):
        started = time.perf_counter()
        assert journal.history_page(**kwargs) == page
        timings.append((time.perf_counter() - started) * 1000)
    return page, {"selects": len(stats["selects"]), "vm_steps_approx": stats["steps"],
                  "median_ms": round(statistics.median(timings), 3),
                  "plans": list(dict.fromkeys(stats["plans"]))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    baseline = None
    if args.baseline:
        spec = importlib.util.spec_from_file_location("paging_baseline", args.baseline.resolve())
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        baseline = module.OrderJournal
    report = {"sqlite": sqlite3.sqlite_version, "runs_per_median": 7, "datasets": []}
    for count in (10_000, 100_000):
        with tempfile.TemporaryDirectory(prefix="railwatch-paging-") as directory:
            path = Path(directory) / "history.sqlite3"
            journal = (baseline or OrderJournal)(path)
            seed_history(journal, count)
            cases = {"first": {}, "deep": {"cursor": journal._cursor_encode(100, "order-00000700")},
                     "filtered_first": {"status": "fulfilled"},
                     "filtered_deep": {"status": "fulfilled", "cursor": journal._cursor_encode(100, "order-00000700")}}
            dataset = {"orders": count, "order_events": count, "before": {}, "after": {}}
            expected = {}
            if baseline:
                for name, kwargs in cases.items():
                    expected[name], dataset["before"][name] = measure(journal, kwargs)
            old_size = path.stat().st_size
            started = time.perf_counter()
            journal = OrderJournal(path)
            dataset["initialization_ms"] = round((time.perf_counter() - started) * 1000, 3)
            dataset["database_growth_bytes"] = path.stat().st_size - old_size
            for name, kwargs in cases.items():
                page, dataset["after"][name] = measure(journal, kwargs)
                if baseline:
                    assert page == expected[name], f"Summary/cursor changed: {count}/{name}"
            report["datasets"].append(dataset)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
