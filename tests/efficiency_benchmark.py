"""Offline browser microbenchmarks; compare two source roots with the same fixtures.

Example: python -X utf8 tests/efficiency_benchmark.py --output build/qa/efficiency.json
No latency assertions: timings depend on the host. Railway requests are blocked.
"""
import argparse
from dataclasses import replace
import json
import math
from pathlib import Path
import statistics
import sys
import time


WORKSPACE = Path(__file__).resolve().parents[1]


def measure(driver, action):
    original, commands = driver.execute, []

    def counted(command, params=None):
        commands.append(command)
        return original(command, params)

    driver.execute = counted
    started = time.perf_counter()
    try:
        result = action()
        elapsed = (time.perf_counter() - started) * 1000
    finally:
        driver.execute = original
    return result, {"ms": elapsed, "commands": len(commands)}


def summarize(samples):
    values = sorted(sample["ms"] for sample in samples)
    return {"samples": len(values), "median_ms": round(statistics.median(values), 2),
            "p95_ms": round(values[math.ceil(len(values) * .95) - 1], 2),
            "commands_min": min(sample["commands"] for sample in samples),
            "commands_max": max(sample["commands"] for sample in samples)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=WORKSPACE)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be positive")
    source = args.source_root.resolve()
    sys.path[:0] = [str(source / "tests"), str(source)]
    import browser_smoke
    import order_browser_smoke
    from gui_12306_0 import TicketMonitor
    from railwatch_bridge import CHROMEDRIVER_PATH

    # Copied source roots need not contain the local browser driver binary.
    driver_path = Path(CHROMEDRIVER_PATH)
    if not driver_path.is_file():
        driver_path = WORKSPACE / "chromedriver.exe"
    browser_smoke.CHROMEDRIVER_PATH = str(driver_path)
    order_browser_smoke.CHROMEDRIVER_PATH = str(driver_path)
    report = {"source_root": str(source), "samples_per_case": args.samples,
              "scope": "Local fixtures only; no service latency, journal, IPC, or real orders.", "cases": {}}

    query_case = browser_smoke.BrowserQueryTests()
    query_case.setUpClass()
    try:
        driver = query_case.driver
        driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": ["*12306.cn*", "https://*"]})
        report["browser"] = driver.capabilities.get("browserVersion")
        samples = []
        for index in range(args.samples + 1):
            query_case.setUp()
            result, sample = measure(driver, lambda: query_case.query.execute(query_case.click, 3))
            assert result["status"] == "ok", result
            if index:
                samples.append(sample)
        report["cases"]["query_response_50ms"] = summarize(samples)
        for count in (1, 5, 20, 100):
            samples = []
            for index in range(args.samples + 1):
                query_case.setUp()
                driver.execute_script("""document.getElementById('queryLeftTable').innerHTML=
                  Array.from({length:arguments[0]},(_,i)=>'<tr id="ticket_'+i+'"><td>G'+(i+1)+'</td>'+
                    '<td id="ZE_'+i+'">'+(i===arguments[0]-1?'<a>候补</a>':'无')+'</td><td id="ZY_'+i+'">无</td></tr>').join('');""", count)
                monitor = TicketMonitor(driver, {"seat_keyword": "二等座,一等座", "auto_alternate": True},
                                        log_callback=lambda _: None)

                def scan():
                    monitor._row_snapshot = monitor.row_parser.snapshot_rows(monitor.target_seats)
                    return monitor._find_hit_row()

                hit, sample = measure(driver, scan)
                assert (hit[0], hit[-1]) == (f"G{count}", "alternate")
                if index:
                    samples.append(sample)
            report["cases"][f"waitlist_scan_{count}_trains"] = summarize(samples)
    finally:
        query_case.tearDownClass()

    order_case = order_browser_smoke.OrderBrowserTests()
    order_case.setUpClass()
    try:
        driver = order_case.driver
        driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": ["*12306.cn*", "https://*"]})
        for kind, element_id in (("regular", "book"), ("alternate", "candidate")):
            samples = []
            for index in range(args.samples + 1):
                order_case.setUp()
                button = driver.find_element("id", element_id)
                intent = replace(order_case.intent, kind=kind)
                result, sample = measure(driver, lambda: getattr(order_case.page, kind)(button, intent))
                assert result.status == "pending_payment", result
                if index:
                    samples.append(sample)
            report["cases"][f"{kind}_order"] = summarize(samples)
    finally:
        order_case.tearDownClass()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
