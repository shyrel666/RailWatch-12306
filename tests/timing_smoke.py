"""Local scheduler exercise only. No browser/network, no ticket-speed claims."""
import argparse
import json
import math
import platform
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from railwatch_bridge import RailWatchBridge
from railwatch_task import MonitorTask


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=1000)
    parser.add_argument("--output", default="build/qa/timing.json")
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("samples must be positive")
    returned = []
    with tempfile.TemporaryDirectory(prefix="railwatch-timing-") as directory:
        bridge = RailWatchBridge(directory)
        started = time.time()
        for _ in range(args.samples):
            target = time.time() + 0.015
            task = MonitorTask({}, target)
            bridge._task = task
            if not bridge._wait_for_target_timestamp(target, {}):
                raise RuntimeError("Scheduler cancelled; sample run invalid")
            returned.append(max(0, (time.time() - target) * 1000))
            task.done.set()
        with bridge.order_journal.connection() as db:
            wakes = [json.loads(row[0])["late_ms"] for row in db.execute("SELECT detail FROM order_events WHERE stage='scheduler_wake' ORDER BY sequence")]
    def stats(values):
        ordered = sorted(values)
        return {"p95_ms": round(ordered[math.ceil(len(values) * .95) - 1], 3),
                "p99_ms": round(ordered[math.ceil(len(values) * .99) - 1], 3), "max_ms": round(max(values), 3)}
    result = {"samples": args.samples, "started_at": started, "duration_seconds": round(time.time() - started, 3),
              "platform": platform.platform(), "python": platform.python_version(),
              "conditions": "Local awake machine; 15ms deadlines; no browser or network; real bridge scheduler and SQLite writes.",
              "scheduler_wake": stats(wakes), "return_after_journal_commit": stats(returned)}
    result["target_met"] = result["scheduler_wake"]["p95_ms"] <= 100 and result["scheduler_wake"]["p99_ms"] <= 250
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["target_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
