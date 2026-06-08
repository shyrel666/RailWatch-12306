# RailWatch Frontend↔Backend Gaps and Bug Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the gaps where the RailWatch UI shows monitoring features that are not actually backed by the Python backend, and fix the functional bugs found in the login check, the JSON-lines runtime concurrency, and ChromeDriver download path.

**Architecture:** Keep the Python bridge as the single source of truth. The Selenium `TicketMonitor` becomes observable: it streams per-loop query rows and structured hits to the bridge, which forwards them as `monitorTick`/`notify` events. The JSON-lines runtime stops blocking on long Selenium/network commands by dispatching each request on a worker thread with a serialized stdout writer, and the bridge serializes driver access so commands cannot race the monitor. The renderer consumes the new telemetry instead of fabricating numbers, and unbacked UI is either wired to real data or removed.

**Tech Stack:** React 19, Ant Design 6, Zustand 5, Electron IPC, Python 3.10, Selenium, Vitest 4, unittest/pytest.

---

## Findings → Task Map

| ID | Finding | Severity | Task |
| --- | --- | --- | --- |
| B1 | `check_login` returns an un-awaited Promise from `execute_script`; login verification always fails in real browsers | High | Task 1 |
| B2 | JSON-lines runtime processes stdin synchronously; long commands (analyze/checkEnvironment/openLogin/download) freeze the whole app; concurrent stdout writes from the monitor thread can interleave | High | Task 2 |
| race | Driver commands can run concurrently with the monitor thread on the same Chrome session | High | Task 3 |
| A1/B3 | Monitor page "query count / results / hits" are stale or simulated; monitor loop never emits live data; hit detail is lossy | High | Task 4 (backend), Task 5 (renderer) |
| A2 | Dashboard shows hardcoded `00:12`, `请求次数 0`, `成功提交 0` | Medium | Task 6 |
| B4 | ChromeDriver download can target a read-only packaged dir | Medium | Task 7 |
| B5 | Background `notify` event force-navigates the user to 仪表盘 | Medium | Task 8 |
| A3 | "Pause log stream" store state exists but no control wires it | Medium | Task 9 |
| A4/A5/B8 | "常用车次" only adds one code; 优先级 not re-derived on load; event-log noise filter only matches G-trains | Low | Task 10 |
| — | Full verification | — | Task 11 |

---

## File Structure

- `railwatch_bridge.py` — login check (async), driver-access serialization + monitoring guards, monitor telemetry handlers, ChromeDriver download dir.
- `railwatch_runtime.py` — per-request worker dispatch + thread-safe stdout + graceful shutdown.
- `gui_12306_0.py` — `BaseHandler._parse_rows` (shared), `TicketMonitor` progress + structured-hit callbacks.
- `src/types.ts` — `MonitorTickPayload` and `BridgeEvent` extension.
- `src/store/railwatchStore.ts` — `monitorLoops`, `applyMonitorTick`, paused-log buffering, no forced navigation on notify.
- `src/App.tsx` — handle `monitorTick` events.
- `src/components/MonitorPage.tsx` — real loop count + live results.
- `src/components/DashboardPage.tsx` — real metrics, drop fabricated ones.
- `src/components/EventPanel.tsx` — working pause/resume control.
- `src/components/TripSetupPage.tsx` — "常用车次" adds all presets; 优先级 derived from config.
- `src/lib/formatEventLog.ts` — broaden query-row noise filter.
- Tests: `tests/test_railwatch_bridge.py`, `tests/test_gui_logic.py`, `src/store/railwatchStore.test.ts`, `src/components/MonitorPage.test.tsx`, `src/components/DashboardPage.test.tsx`, `src/components/EventPanel.test.tsx`, `src/components/TripSetupPage.test.tsx`, `src/lib/formatEventLog.test.ts`.

---

### Task 1: Await the 12306 session check in `check_login`

**Files:**
- Modify: `railwatch_bridge.py:390-408`
- Modify: `tests/test_railwatch_bridge.py:150-163`
- Modify: `tests/test_railwatch_bridge.py:347-369`

- [ ] **Step 1: Update the two existing check_login tests to use an async-capable fake driver**

In `tests/test_railwatch_bridge.py`, replace the `FakeDriver` in `test_check_login_marks_ready_when_12306_session_is_valid` (currently lines 150-163):

```python
    def test_check_login_marks_ready_when_12306_session_is_valid(self):
        from railwatch_bridge import RailWatchBridge

        class FakeDriver:
            def execute_async_script(self, script):
                return {"data": {"flag": True}}

        bridge = RailWatchBridge(data_dir=tempfile.mkdtemp(), event_callback=lambda event: None)
        bridge.driver = FakeDriver()

        state = bridge.check_login()

        self.assertTrue(state["login_ready"])
        self.assertEqual(state["status_message"], "登录已验证")
```

And replace the `FakeDriver` in `test_check_login_records_device_id_after_verified_login` (currently lines 350-352):

```python
        class FakeDriver:
            def execute_async_script(self, script):
                return {"data": {"flag": True}}
```

- [ ] **Step 2: Add a regression test proving a real Promise-style driver resolves**

Add this test to `RailWatchBridgeContractTests` in `tests/test_railwatch_bridge.py`:

```python
    def test_check_login_uses_async_script_not_sync_script(self):
        from railwatch_bridge import RailWatchBridge

        class PromiseStyleDriver:
            """Mimics WebDriver: execute_script returns the unresolved value, only execute_async_script resolves."""

            def execute_script(self, script):
                return {}

            def execute_async_script(self, script):
                return {"data": {"flag": True}}

        bridge = RailWatchBridge(data_dir=tempfile.mkdtemp(), event_callback=lambda event: None)
        bridge.driver = PromiseStyleDriver()

        state = bridge.check_login()

        self.assertTrue(state["login_ready"])
```

- [ ] **Step 3: Run the failing test**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_railwatch_bridge.py::RailWatchBridgeContractTests::test_check_login_uses_async_script_not_sync_script -q
```

Expected: FAIL because `check_login` calls `execute_script`, which `PromiseStyleDriver` returns `{}` for.

- [ ] **Step 4: Switch `check_login` to `execute_async_script`**

In `railwatch_bridge.py`, inside `check_login`, replace:

```python
            result = self.driver.execute_script(
                """
                return fetch('/otn/login/checkUser', {credentials: 'include'})
                  .then(response => response.json())
                  .catch(() => ({data: {flag: false}}));
                """
            )
            ready = bool(((result or {}).get("data") or {}).get("flag"))
```

with:

```python
            result = self.driver.execute_async_script(
                """
                const done = arguments[arguments.length - 1];
                fetch('/otn/login/checkUser', {credentials: 'include'})
                  .then(response => response.json())
                  .then(data => done(data))
                  .catch(() => done({data: {flag: false}}));
                """
            )
            ready = bool(((result or {}).get("data") or {}).get("flag"))
```

- [ ] **Step 5: Run the focused tests**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_railwatch_bridge.py -q -k check_login
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add railwatch_bridge.py tests/test_railwatch_bridge.py
git commit -m "fix: await 12306 session check with execute_async_script"
```

---

### Task 2: Make the JSON-lines runtime non-blocking with a thread-safe writer

**Files:**
- Modify: `railwatch_runtime.py`
- Modify: `tests/test_railwatch_bridge.py:312-345`

- [ ] **Step 1: Update the two existing runtime tests to await the dispatched future**

In `tests/test_railwatch_bridge.py`, change `test_json_runtime_dispatches_command_response_and_events` so the `handle_line` call waits:

```python
        runtime.handle_line('{"id":"1","command":"getRuntimeInfo","payload":{}}').result(timeout=5)
```

And change `test_json_runtime_dispatches_check_login` similarly:

```python
        runtime.handle_line('{"id":"1","command":"checkLogin","payload":{}}').result(timeout=5)
```

- [ ] **Step 2: Add a test proving a slow command does not block a fast command**

Add this test method to `RailWatchBridgeContractTests` in `tests/test_railwatch_bridge.py`:

```python
    def test_runtime_does_not_block_fast_command_behind_slow_command(self):
        import threading

        from railwatch_runtime import RailWatchRuntime

        slow_started = threading.Event()
        release_slow = threading.Event()
        order = []
        order_lock = threading.Lock()

        class SlowBridge:
            def check_environment(self):
                slow_started.set()
                release_slow.wait(timeout=5)
                return {"slow": True}

            def get_runtime_info(self):
                return {"fast": True}

        def writer(payload):
            with order_lock:
                order.append(payload["id"])

        runtime = RailWatchRuntime(bridge=SlowBridge(), writer=writer)

        slow_future = runtime.handle_line('{"id":"slow","command":"checkEnvironment","payload":{}}')
        self.assertTrue(slow_started.wait(timeout=5))

        fast_future = runtime.handle_line('{"id":"fast","command":"getRuntimeInfo","payload":{}}')
        fast_future.result(timeout=5)

        self.assertEqual(order, ["fast"])
        release_slow.set()
        slow_future.result(timeout=5)
        runtime.shutdown()
        self.assertEqual(order, ["fast", "slow"])
```

- [ ] **Step 3: Run the failing test**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_railwatch_bridge.py::RailWatchBridgeContractTests::test_runtime_does_not_block_fast_command_behind_slow_command -q
```

Expected: FAIL because `handle_line` currently runs synchronously and returns `None` (no `.result`).

- [ ] **Step 4: Rewrite the runtime to dispatch on a thread pool with a locked writer**

Replace the entire body of `railwatch_runtime.py` with:

```python
"""JSON Lines Python runtime entry for the Electron app."""

from __future__ import annotations

import json
import sys
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Optional

from railwatch_bridge import RailWatchBridge, dumps_json


def configure_stdio() -> None:
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8")


class RailWatchRuntime:
    def __init__(
        self,
        bridge: Optional[RailWatchBridge] = None,
        writer: Optional[Callable[[dict], None]] = None,
        max_workers: int = 4,
    ):
        self._write_lock = threading.Lock()
        self.writer = writer or self._stdout_writer
        self.bridge = bridge or RailWatchBridge(event_callback=self.emit_event)
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="railwatch-cmd")

    def emit_event(self, event: dict) -> None:
        self._write({"type": "event", **event})

    def _write(self, payload: dict) -> None:
        self.writer(payload)

    def handle_line(self, line: str) -> "Future":
        request = json.loads(line)
        request_id = request.get("id")
        command = request.get("command")
        payload = request.get("payload") or {}
        return self._executor.submit(self._run_command, request_id, command, payload)

    def _run_command(self, request_id, command: str, payload: dict) -> None:
        try:
            result = self._dispatch(command, payload)
            self._write({"type": "response", "id": request_id, "ok": True, "result": result})
        except Exception as exc:
            self._write(
                {
                    "type": "response",
                    "id": request_id,
                    "ok": False,
                    "error": {"message": str(exc), "class": exc.__class__.__name__},
                }
            )

    def _dispatch(self, command: str, payload: dict):
        handlers = {
            "getRuntimeInfo": lambda: self.bridge.get_runtime_info(),
            "loadConfig": lambda: self.bridge.load_config(),
            "saveConfig": lambda: self.bridge.save_config(payload.get("config") or payload),
            "checkEnvironment": lambda: self.bridge.check_environment(),
            "downloadChromeDriver": lambda: self.bridge.download_chromedriver(),
            "openLogin": lambda: self.bridge.open_login(),
            "checkLogin": lambda: self.bridge.check_login(),
            "analyzeQuery": lambda: self.bridge.analyze_query(payload.get("config") or payload),
            "startMonitor": lambda: self.bridge.start_monitor(
                payload.get("config") or payload,
                confirmed=bool(payload.get("confirmed", False)),
            ),
            "stopMonitor": lambda: self.bridge.stop_monitor(),
            "closeBrowser": lambda: self.bridge.close_browser(confirmed=bool(payload.get("confirmed", False))),
            "clearLocalData": lambda: self.bridge.clear_local_data(confirmed=bool(payload.get("confirmed", False))),
            "exportLog": lambda: self.bridge.export_log(payload.get("path")),
            "clearLog": lambda: self.bridge.clear_log(),
            "loadPreferences": lambda: self.bridge.load_preferences(),
            "savePreferences": lambda: self.bridge.save_preferences(str(payload.get("theme", "light"))),
        }
        if command not in handlers:
            raise ValueError(f"未知命令: {command}")
        return handlers[command]()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True)

    def _stdout_writer(self, payload: dict) -> None:
        with self._write_lock:
            sys.stdout.write(dumps_json(payload) + "\n")
            sys.stdout.flush()


def main() -> int:
    configure_stdio()
    runtime = RailWatchRuntime()
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            runtime.handle_line(line)
    finally:
        runtime.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run the runtime tests**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_railwatch_bridge.py -q -k "runtime or json_runtime"
```

Expected: PASS (including `test_runtime_process_outputs_utf8_json`, which now flushes via `shutdown(wait=True)` before exit).

- [ ] **Step 6: Commit**

```bash
git add railwatch_runtime.py tests/test_railwatch_bridge.py
git commit -m "fix: dispatch runtime commands off the read loop with a locked writer"
```

---

### Task 3: Serialize driver access and refuse driver commands during monitoring

**Files:**
- Modify: `railwatch_bridge.py` (`__init__`, `check_environment`, `open_login`, `check_login`, `analyze_query`)
- Modify: `tests/test_railwatch_bridge.py`

- [ ] **Step 1: Write a test that analyze is refused while monitoring**

Add to `RailWatchBridgeContractTests` in `tests/test_railwatch_bridge.py`:

```python
    def test_analyze_query_refuses_while_monitoring(self):
        from railwatch_bridge import RailWatchBridge

        bridge = RailWatchBridge(data_dir=tempfile.mkdtemp(), event_callback=lambda event: None)
        bridge.is_monitoring = True

        state = bridge.analyze_query(
            {"from_station_cn": "北京", "to_station_cn": "上海", "date": "2026-06-10"}
        )

        self.assertEqual(state["phase"], "error")
        self.assertIn("监控运行中", state["error_message"])
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_railwatch_bridge.py::RailWatchBridgeContractTests::test_analyze_query_refuses_while_monitoring -q
```

Expected: FAIL because `analyze_query` currently tries to drive Selenium even while monitoring.

- [ ] **Step 3: Add a driver lock and import threading guard**

In `railwatch_bridge.py`, `threading` is already imported. In `RailWatchBridge.__init__`, after `self.is_monitoring = False`, add:

```python
        self._driver_lock = threading.RLock()
```

- [ ] **Step 4: Guard `analyze_query`**

In `railwatch_bridge.py`, change the start of `analyze_query`:

```python
    def analyze_query(self, raw_config: dict) -> dict:
        if self.is_monitoring:
            return self.emit_state(self.state.with_error("监控运行中，请先停止监控后再分析。"))
        config = validate_config(raw_config)
        self.save_config(config)
        self.state = self.state.with_safety(config["auto_submit"], config["auto_alternate"])
        self.emit_state()
        with self._driver_lock:
            try:
                if not CORE_AVAILABLE or PageAnalyzer is None:
                    raise RuntimeError(f"核心模块不可用: {CORE_IMPORT_ERROR}")
                driver = self._ensure_driver()
                analyzer = PageAnalyzer(driver, log_callback=self.log, base_dir=self.data_dir)
                rows = []
                for travel_date in expand_travel_dates(config["date"], config["date_range"]):
                    date_config = {**config, "date": travel_date}
                    date_rows = analyzer.open_fill_query_and_analyze(date_config)
                    if date_rows:
                        rows.extend([{**row, "date": travel_date} for row in date_rows])
                if not rows:
                    raise RuntimeError("未解析到查询结果行。")
                self.query_results = rows
                self.emit("results", {"rows": rows})
                return self.emit_state(self.state.with_query_ready(True, config, f"已解析 {len(rows)} 行查询结果"))
            except Exception as exc:
                return self.emit_state(self.state.with_error(f"查询分析失败: {exc}"))
```

(Only the leading guard and the `with self._driver_lock:` wrapper are new; the loop body is unchanged from the current implementation.)

- [ ] **Step 5: Guard `check_environment`, `open_login`, `check_login` with the lock and a monitoring check**

In `railwatch_bridge.py`, at the very top of `check_environment` (before the `try:`), add:

```python
        if self.is_monitoring:
            return self.emit_state(self.state.with_error("监控运行中，请先停止监控后再检查环境。"))
```

At the very top of `open_login` (before the `try:`), add:

```python
        if self.is_monitoring:
            return self.emit_state(self.state.with_error("监控运行中，请先停止监控后再打开登录页。"))
```

Then wrap the existing `try:` body of each of `check_environment`, `open_login`, and `check_login` in `with self._driver_lock:` (indent the existing `try/except` one level under the `with`). The monitor worker already owns the driver while running, so refusing here prevents two threads from touching the same Chrome session.

- [ ] **Step 6: Hold the driver lock for the monitor worker**

In `railwatch_bridge.py`, change `_monitor_worker` so the driver work runs under the lock:

```python
    def _monitor_worker(self, config: dict) -> None:
        try:
            if config.get("timer_enabled") and not self._wait_for_target_time(config):
                return
            if not CORE_AVAILABLE or TicketMonitor is None:
                raise RuntimeError(f"核心模块不可用: {CORE_IMPORT_ERROR}")
            with self._driver_lock:
                driver = self._ensure_driver()
                monitor = TicketMonitor(
                    driver,
                    config,
                    log_callback=self.log,
                    stop_check=lambda: not self.is_monitoring,
                    notify_callback=self._handle_notify,
                    progress_callback=self._handle_progress,
                    on_hit=self._handle_hit,
                )
                monitor.run()
        except Exception as exc:
            self.emit_state(self.state.with_error(f"监控失败: {exc}"))
        finally:
            self.is_monitoring = False
            if self.state.phase.value != "error":
                self.emit_state(self.state.with_monitoring(False, "监控已停止"))
```

(`progress_callback` and `on_hit` are added in Task 4; adding them here now is safe because Task 4 lands before monitoring is exercised. If executing strictly in order, leave the two new kwargs out until Task 4 Step 6 and re-add them then.)

- [ ] **Step 7: Run the focused tests**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_railwatch_bridge.py -q -k "analyze or check_login or environment"
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add railwatch_bridge.py tests/test_railwatch_bridge.py
git commit -m "fix: serialize Selenium driver access and refuse driver commands during monitoring"
```

---

### Task 4: Stream real monitor telemetry and structured hits from the backend

**Files:**
- Modify: `gui_12306_0.py` (`BaseHandler`, `PageAnalyzer`, `TicketMonitor`)
- Modify: `railwatch_bridge.py` (`_monitor_worker`, `_handle_notify`, add `_handle_progress`/`_handle_hit`)
- Modify: `tests/test_gui_logic.py`
- Modify: `tests/test_railwatch_bridge.py`

- [ ] **Step 1: Write a core test for the monitor progress + hit callbacks**

Add to `tests/test_gui_logic.py` (inside `TicketMonitorLogicTests`):

```python
    def test_monitor_emits_progress_rows_and_structured_hit(self):
        progress_events = []
        hit_events = []

        class Row:
            def __init__(self, text):
                self._text = text
                self.text = text

            def find_elements(self, by=None, value=None):
                return []

        class Table:
            def find_elements(self, by=None, value=None):
                return [Row("G101 北京 上海 二等座 有")]

        class Driver:
            def refresh(self):
                return None

            def find_element(self, by=None, value=None):
                return Table()

        monitor = TicketMonitor(
            Driver(),
            {"interval": 1, "query_timeout": 1, "train_code": ""},
            log_callback=lambda msg: None,
            progress_callback=lambda payload: progress_events.append(payload),
            on_hit=lambda payload: hit_events.append(payload),
        )
        monitor.click_query_button = lambda: True
        monitor.wait_for_rows = lambda timeout=40, stop_check=None: True
        monitor._find_hit_row = lambda indices: ("G101", "二等座", "有", object(), None, "book")
        monitor._focus_and_highlight = lambda row, btn: None

        with patch("gui_12306_0.time.sleep", lambda seconds: None):
            hit = monitor._run_single_loop(1, 1)

        self.assertTrue(hit)
        self.assertEqual(progress_events[0]["loop"], 1)
        self.assertEqual(progress_events[0]["rows"], [{"train": "G101", "raw": "G101 北京 上海 二等座 有"}])
        self.assertEqual(hit_events[0]["train_code"], "G101")
        self.assertEqual(hit_events[0]["seat_type"], "二等座")
        self.assertEqual(hit_events[0]["status"], "有")
        self.assertEqual(hit_events[0]["source"], "regular")
```

- [ ] **Step 2: Run the failing core test**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_gui_logic.py::TicketMonitorLogicTests::test_monitor_emits_progress_rows_and_structured_hit -q
```

Expected: FAIL because `TicketMonitor` has no `progress_callback`/`on_hit` and no row parsing in the loop.

- [ ] **Step 3: Move `_parse_rows` to `BaseHandler` for reuse**

In `gui_12306_0.py`, add this method to `BaseHandler` (place it after `is_alternate_available`):

```python
    def _parse_rows(self) -> List[dict]:
        """解析当前查询结果表格行 -> [{"train","raw"}]"""
        try:
            table = self.driver.find_element(By.ID, "queryLeftTable")
            rows = table.find_elements(By.CSS_SELECTOR, "tr[id^='ticket_']")
            results = []
            for row in rows:
                text = row.text.strip()
                if not text:
                    continue
                train_code = self.extract_train_code(text)
                if not train_code:
                    continue
                results.append({"train": train_code, "raw": text})
            return results
        except (NoSuchElementException, StaleElementReferenceException):
            return []
```

Then delete the now-duplicated `_parse_rows` method from `PageAnalyzer` (currently `gui_12306_0.py:516-533`). `PageAnalyzer` keeps using `self._parse_rows()` via inheritance.

- [ ] **Step 4: Add callbacks to `TicketMonitor.__init__`**

In `gui_12306_0.py`, change the `TicketMonitor.__init__` signature and assignments. Replace:

```python
    def __init__(
        self, 
        driver, 
        cfg: dict, 
        log_callback: Optional[Callable[[str], None]] = None, 
        stop_check: Optional[Callable[[], bool]] = None, 
        notify_callback: Optional[Callable[[str, str], None]] = None
    ):
        super().__init__(driver, log_callback)
        self.cfg = cfg
        self.should_stop = stop_check or (lambda: False)
        self.notify = notify_callback or (lambda title, msg: print(title, msg))
```

with:

```python
    def __init__(
        self, 
        driver, 
        cfg: dict, 
        log_callback: Optional[Callable[[str], None]] = None, 
        stop_check: Optional[Callable[[], bool]] = None, 
        notify_callback: Optional[Callable[[str, str], None]] = None,
        progress_callback: Optional[Callable[[dict], None]] = None,
        on_hit: Optional[Callable[[dict], None]] = None,
    ):
        super().__init__(driver, log_callback)
        self.cfg = cfg
        self.should_stop = stop_check or (lambda: False)
        self.notify = notify_callback or (lambda title, msg: print(title, msg))
        self.progress = progress_callback
        self.on_hit = on_hit
```

- [ ] **Step 5: Emit progress rows and a structured hit inside `_run_single_loop`**

In `gui_12306_0.py`, in `_run_single_loop`, immediately after the `if self.rate_limiter: self.rate_limiter.on_success()` block (right before `# 6) 找到席别列索引（兆底用）`), add:

```python
        if self.progress:
            try:
                self.progress({"loop": loop_count, "date": self.current_loop_date or str(self.cfg.get("date", "")), "rows": self._parse_rows()})
            except Exception:
                pass
```

Then, in the same method, change the hit branch. Replace the block that currently reads:

```python
            # 提醒（GUI 会语音+弹窗）
            self.notify(
                "🎉 发现目标车次/席别可用",
                f"命中：{train_code}\n{seat_name}：{seat_value}\n\n"
                f"已为你定位并高亮该车次行与【{'候补' if action_type == 'alternate' else '预订'}】按钮。\n"
                f"请立即切回浏览器{'确认候补订单' if action_type == 'alternate' else ('确认订单' if self.auto_submit else '手动点击【预订】')}→ 选择乘车人 → 提交订单 → 支付。"
            )
```

with:

```python
            # 提醒（GUI 会语音+弹窗）
            title = "🎉 发现目标车次/席别可用"
            message = (
                f"命中：{train_code}\n{seat_name}：{seat_value}\n\n"
                f"已为你定位并高亮该车次行与【{'候补' if action_type == 'alternate' else '预订'}】按钮。\n"
                f"请立即切回浏览器{'确认候补订单' if action_type == 'alternate' else ('确认订单' if self.auto_submit else '手动点击【预订】')}→ 选择乘车人 → 提交订单 → 支付。"
            )
            if self.on_hit:
                self.on_hit(
                    {
                        "train_code": train_code,
                        "seat_type": seat_name,
                        "status": str(seat_value),
                        "source": "alternate" if action_type == "alternate" else "regular",
                        "title": title,
                        "message": message,
                    }
                )
            self.notify(title, message)
```

- [ ] **Step 6: Run the core test**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_gui_logic.py::TicketMonitorLogicTests::test_monitor_emits_progress_rows_and_structured_hit -q
```

Expected: PASS.

- [ ] **Step 7: Write a bridge test for the new telemetry handlers**

Add to `RailWatchBridgeContractTests` in `tests/test_railwatch_bridge.py`:

```python
    def test_handle_progress_emits_monitor_tick_and_results(self):
        from railwatch_bridge import RailWatchBridge

        events = []
        bridge = RailWatchBridge(data_dir=tempfile.mkdtemp(), event_callback=events.append)

        bridge._handle_progress({"loop": 3, "date": "2026-06-10", "rows": [{"train": "G7", "raw": "G7 有"}]})

        tick = [event for event in events if event["event"] == "monitorTick"][0]
        self.assertEqual(tick["payload"]["loop"], 3)
        self.assertEqual(tick["payload"]["rows"], [{"train": "G7", "raw": "G7 有"}])
        self.assertEqual(bridge.query_results, [{"train": "G7", "raw": "G7 有"}])

    def test_handle_hit_emits_structured_hit_and_state(self):
        from railwatch_bridge import RailWatchBridge

        events = []
        bridge = RailWatchBridge(data_dir=tempfile.mkdtemp(), event_callback=events.append)

        bridge._handle_hit(
            {
                "train_code": "G101",
                "seat_type": "二等座",
                "status": "有",
                "source": "regular",
                "title": "命中",
                "message": "命中：G101",
            }
        )

        notify = [event for event in events if event["event"] == "notify"][0]
        self.assertEqual(notify["payload"]["hit"]["seat_type"], "二等座")
        self.assertEqual(notify["payload"]["hit"]["status"], "有")
        state = [event for event in events if event["event"] == "state"][-1]
        self.assertEqual(state["payload"]["hits"][-1]["seat_type"], "二等座")
```

- [ ] **Step 8: Implement the bridge handlers and trim `_handle_notify`**

In `railwatch_bridge.py`, replace `_handle_notify` and its helper `_extract_after` (currently lines 678-691):

```python
    def _handle_notify(self, title: str, message: str) -> None:
        self.log(f"{title}: {message}", "SUCCESS")

    def _handle_progress(self, payload: dict) -> None:
        rows = payload.get("rows") or []
        self.query_results = rows
        self.emit(
            "monitorTick",
            {"loop": int(payload.get("loop", 0)), "date": str(payload.get("date", "")), "rows": rows},
        )

    def _handle_hit(self, payload: dict) -> None:
        source = "alternate" if payload.get("source") == "alternate" else "regular"
        hit = TicketHit(
            train_code=str(payload.get("train_code", "目标")),
            seat_type=str(payload.get("seat_type", "目标席别")),
            status=str(payload.get("status", "available")),
            source=source,
            detail=str(payload.get("message", "")),
        )
        title = str(payload.get("title", "发现目标车次/席别可用"))
        message = str(payload.get("message", ""))
        self.emit("notify", {"title": title, "message": message, "hit": ticket_hit_to_payload(hit)})
        self.emit_state(self.state.with_hit(hit, title))
```

Confirm `_monitor_worker` passes `progress_callback=self._handle_progress` and `on_hit=self._handle_hit` (added in Task 3 Step 6).

- [ ] **Step 9: Run the Python suite for affected files**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_gui_logic.py tests/test_railwatch_bridge.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add gui_12306_0.py railwatch_bridge.py tests/test_gui_logic.py tests/test_railwatch_bridge.py
git commit -m "feat: stream live monitor rows and structured hits to the bridge"
```

---

### Task 5: Consume monitor telemetry in the renderer

**Files:**
- Modify: `src/types.ts`
- Modify: `src/store/railwatchStore.ts`
- Modify: `src/store/railwatchStore.test.ts`
- Modify: `src/App.tsx`
- Modify: `src/components/MonitorPage.tsx`
- Modify: `src/components/MonitorPage.test.tsx`

- [ ] **Step 1: Add the `monitorTick` types**

In `src/types.ts`, after the `ResultsPayload` type, add:

```typescript
export type MonitorTickPayload = {
  loop: number;
  date: string;
  rows: QueryResultRow[];
};
```

And add a branch to the `BridgeEvent` union (before the catch-all `| { event: string; payload: unknown }`):

```typescript
  | { event: "monitorTick"; payload: MonitorTickPayload }
```

- [ ] **Step 2: Write a store test for `applyMonitorTick`**

Add to `src/store/railwatchStore.test.ts` (inside the `describe` block):

```typescript
  test("applies live monitor ticks to results and loop count", () => {
    const store = createRailWatchStore();

    store.getState().applyMonitorTick({
      loop: 7,
      date: "2026-06-10",
      rows: [{ train: "G55", raw: "G55 北京 上海 二等座 有" }],
    });

    expect(store.getState().monitorLoops).toBe(7);
    expect(store.getState().results.map((row) => row.train)).toEqual(["G55"]);
    expect(store.getState().activePage).toBe("仪表盘");
  });
```

- [ ] **Step 3: Run the failing store test**

Run:

```powershell
npm run test:renderer -- src/store/railwatchStore.test.ts
```

Expected: FAIL because `applyMonitorTick` and `monitorLoops` do not exist.

- [ ] **Step 4: Add `monitorLoops` and `applyMonitorTick` to the store**

In `src/store/railwatchStore.ts`, add to the imports type list `MonitorTickPayload`:

```typescript
  MonitorTickPayload,
```

Add to the `RailWatchStore` type (after `results: QueryResultRow[];`):

```typescript
  monitorLoops: number;
```

Add the action signature (after `applyResults: (payload: ResultsPayload) => void;`):

```typescript
  applyMonitorTick: (payload: MonitorTickPayload) => void;
```

In `createRailWatchStore`, add the initial value (after `results: [],`):

```typescript
    monitorLoops: 0,
```

And add the implementation (after `applyResults`):

```typescript
    applyMonitorTick: (payload) => {
      set({ results: payload.rows, monitorLoops: payload.loop });
    },
```

- [ ] **Step 5: Handle the `monitorTick` event in `App.tsx`**

In `src/App.tsx`, inside `applyEvent`'s `switch`, add a case (after the `results` case):

```typescript
        case "monitorTick":
          state.applyMonitorTick(event.payload as import("./types").MonitorTickPayload);
          break;
```

- [ ] **Step 6: Show the real loop count on the monitor page**

In `src/components/MonitorPage.tsx`, add a store selector inside `MonitorPage` (after `const hits = useRailWatchStore(...)`):

```typescript
  const monitorLoops = useRailWatchStore((state) => state.monitorLoops);
```

Replace the "查询次数" metric value:

```tsx
        <div className="st-metric">
          <RefreshCw size={14} className={status.monitoring ? "spin-slow" : ""} />
          <em>查询次数</em>
          <strong className="st-mono">{monitorLoops}</strong>
        </div>
```

- [ ] **Step 7: Add a monitor-page test for the live loop count**

In `src/components/MonitorPage.test.tsx`, add `monitorLoops: 0` to the `resetStore` `setState` object (after `results: [],`), then add this test inside the `describe`:

```typescript
  test("shows the backend loop count as the query count", () => {
    act(() => {
      railwatchStore.setState({
        status: { ...defaultStatus, query_ready: true, monitoring: true },
        monitorLoops: 12,
        results: [{ train: "G55", raw: "G55 北京 上海 二等座 有" }],
      });
    });

    render(<MonitorPage busy={null} runCommand={(async () => undefined) as CommandRunner} />);

    expect(screen.getByText("12")).toBeTruthy();
    expect(screen.getByText("G55")).toBeTruthy();
  });
```

- [ ] **Step 8: Run the focused renderer tests**

Run:

```powershell
npm run test:renderer -- src/store/railwatchStore.test.ts src/components/MonitorPage.test.tsx
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/types.ts src/store/railwatchStore.ts src/store/railwatchStore.test.ts src/App.tsx src/components/MonitorPage.tsx src/components/MonitorPage.test.tsx
git commit -m "feat: render live monitor loop count and query rows from monitorTick events"
```

---

### Task 6: Replace fabricated dashboard metrics with real values

**Files:**
- Modify: `src/components/DashboardPage.tsx`
- Modify: `src/components/DashboardPage.test.tsx`

- [ ] **Step 1: Write a test asserting no fabricated metrics**

In `src/components/DashboardPage.test.tsx`, add `monitorLoops: 0` to the `resetStore` `setState` object (after `results: [],`), then add this test:

```typescript
  test("does not fabricate elapsed time or submission counts", () => {
    railwatchStore.setState({
      status: { ...defaultStatus, query_ready: true, monitoring: true },
      monitorLoops: 9,
    });

    render(<DashboardPage />);

    expect(screen.queryByText("00:12")).toBeNull();
    expect(screen.queryByText("成功提交")).toBeNull();
    expect(screen.getByText("请求次数").parentElement?.textContent).toContain("9");
  });
```

- [ ] **Step 2: Run the failing dashboard test**

Run:

```powershell
npm run test:renderer -- src/components/DashboardPage.test.tsx
```

Expected: FAIL because the dashboard renders `00:12`, `成功提交`, and a hardcoded `0` request count.

- [ ] **Step 3: Read the real loop count and rewrite the metrics block**

In `src/components/DashboardPage.tsx`, add a selector inside `DashboardPage` (after `const hits = useRailWatchStore(...)`):

```typescript
  const monitorLoops = useRailWatchStore((state) => state.monitorLoops);
```

Replace the entire `<div className="monitor-metrics">...</div>` block (currently lines 367-393) with:

```tsx
        <div className="monitor-metrics">
          <span>
            <Clock3 size={13} />
            <em>下次查询</em>
            <strong>{status.monitoring ? `${config.interval} 秒` : "-"}</strong>
          </span>
          <span>
            <Search size={13} />
            <em>请求次数</em>
            <strong>{status.monitoring ? monitorLoops : "-"}</strong>
          </span>
          <span>
            <Bell size={13} />
            <em>命中记录</em>
            <strong>{hits.length}</strong>
          </span>
        </div>
```

- [ ] **Step 4: Remove now-unused icon imports**

In `src/components/DashboardPage.tsx`, remove `Pause` and `Check` from the `lucide-react` import if they are no longer referenced anywhere else in the file. (Search the file first; `Check` is still used by the workflow stepper, so keep `Check`; `Pause` is only used in the removed block, so remove `Pause`.)

- [ ] **Step 5: Run the focused dashboard test**

Run:

```powershell
npm run test:renderer -- src/components/DashboardPage.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/components/DashboardPage.tsx src/components/DashboardPage.test.tsx
git commit -m "fix: show real request count and drop fabricated dashboard metrics"
```

---

### Task 7: Download ChromeDriver into the writable data directory

**Files:**
- Modify: `railwatch_bridge.py` (`download_chromedriver`)
- Modify: `tests/test_railwatch_bridge.py`

- [ ] **Step 1: Write a test that the download target is the data dir**

Add to `RailWatchBridgeContractTests` in `tests/test_railwatch_bridge.py`:

```python
    def test_download_chromedriver_targets_writable_data_dir(self):
        from railwatch_bridge import RailWatchBridge

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = RailWatchBridge(data_dir=temp_dir, event_callback=lambda event: None)
            bridge.chromedriver_path = os.path.join("C:\\", "Program Files", "packaged", "chromedriver.exe")
            captured = {}

            def fake_install(target_dir, major_version, log_callback):
                captured["target_dir"] = target_dir
                return os.path.join(target_dir, "chromedriver.exe")

            with patch("railwatch_bridge.CD_MANAGER_AVAILABLE", True), \
                patch("railwatch_bridge.detect_chrome_version", lambda: "148"), \
                patch("railwatch_bridge.download_and_install_chromedriver", fake_install):
                result = bridge.download_chromedriver()

            self.assertEqual(captured["target_dir"], temp_dir)
            self.assertEqual(os.path.dirname(result["chromedriver_path"]), temp_dir)
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_railwatch_bridge.py::RailWatchBridgeContractTests::test_download_chromedriver_targets_writable_data_dir -q
```

Expected: FAIL because `dest_dir` is derived from the (possibly packaged) `chromedriver_path`.

- [ ] **Step 3: Point the download at the data directory**

In `railwatch_bridge.py`, in `download_chromedriver`, replace:

```python
        dest_dir = os.path.dirname(self.chromedriver_path) or self.data_dir
```

with:

```python
        dest_dir = self.data_dir
```

- [ ] **Step 4: Run the test**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_railwatch_bridge.py::RailWatchBridgeContractTests::test_download_chromedriver_targets_writable_data_dir -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add railwatch_bridge.py tests/test_railwatch_bridge.py
git commit -m "fix: download ChromeDriver into the writable data directory"
```

---

### Task 8: Stop force-navigating the user on background hit events

**Files:**
- Modify: `src/store/railwatchStore.ts` (`applyNotify`)
- Modify: `src/store/railwatchStore.test.ts`

- [ ] **Step 1: Write a test that a hit does not change the active page**

Add to `src/store/railwatchStore.test.ts` (inside the `describe`):

```typescript
  test("does not yank the active page when a hit notification arrives", () => {
    const store = createRailWatchStore();
    store.getState().setActivePage("行程设置");

    store.getState().applyNotify({
      title: "发现目标车票",
      message: "命中：G101",
      hit: {
        train_code: "G101",
        seat_type: "二等座",
        status: "有",
        source: "regular",
        detail: "命中：G101",
        label: "G101 二等座 有票: 有",
      },
    });

    expect(store.getState().activePage).toBe("行程设置");
    expect(store.getState().notifications).toHaveLength(1);
  });
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
npm run test:renderer -- src/store/railwatchStore.test.ts
```

Expected: FAIL because `applyNotify` sets `activePage: "仪表盘"`.

- [ ] **Step 3: Remove the forced navigation from `applyNotify`**

In `src/store/railwatchStore.ts`, change `applyNotify` to:

```typescript
    applyNotify: (payload) => {
      const nextHits = payload.hit ? [...get().hits, payload.hit] : get().hits;
      set({
        notifications: [...get().notifications, payload],
        hits: nextHits,
      });
    },
```

(The toast popup is still shown by `App.tsx`; only the page jump is removed. `applyResults` keeps switching to 购票监控 because it is triggered by the explicit "分析" action.)

- [ ] **Step 4: Run the test**

Run:

```powershell
npm run test:renderer -- src/store/railwatchStore.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/store/railwatchStore.ts src/store/railwatchStore.test.ts
git commit -m "fix: keep the active page stable when a hit notification arrives"
```

---

### Task 9: Wire a working pause/resume control for the event log

**Files:**
- Modify: `src/store/railwatchStore.ts` (`applyLog`, `setLogPaused`, add buffer)
- Modify: `src/store/railwatchStore.test.ts`
- Modify: `src/components/EventPanel.tsx`
- Modify: `src/components/EventPanel.test.tsx`

- [ ] **Step 1: Write a store test for paused buffering and flush-on-resume**

Add to `src/store/railwatchStore.test.ts` (inside the `describe`):

```typescript
  test("buffers logs while paused and flushes them on resume", () => {
    const store = createRailWatchStore();

    store.getState().applyLog({ time: "09:00:00", level: "INFO", message: "before pause" });
    store.getState().setLogPaused(true);
    store.getState().applyLog({ time: "09:00:01", level: "INFO", message: "while paused" });

    expect(store.getState().logs.map((entry) => entry.message)).toEqual(["before pause"]);

    store.getState().setLogPaused(false);

    expect(store.getState().logs.map((entry) => entry.message)).toEqual(["before pause", "while paused"]);
  });
```

- [ ] **Step 2: Run the failing store test**

Run:

```powershell
npm run test:renderer -- src/store/railwatchStore.test.ts
```

Expected: FAIL because `applyLog` ignores `logPaused` and there is no buffer.

- [ ] **Step 3: Implement paused buffering**

In `src/store/railwatchStore.ts`, add to the `RailWatchStore` type (after `logs: LogEntry[];`):

```typescript
  pausedLogs: LogEntry[];
```

In `createRailWatchStore`, add the initial value (after `logs: [],`):

```typescript
    pausedLogs: [],
```

Replace `applyLog` with:

```typescript
    applyLog: (entry) => {
      if (get().logPaused) {
        set({ pausedLogs: [...get().pausedLogs, entry] });
        return;
      }
      set({ logs: [...get().logs, entry] });
    },
```

Replace `setLogPaused` with:

```typescript
    setLogPaused: (paused) => {
      if (!paused && get().pausedLogs.length > 0) {
        set({ logs: [...get().logs, ...get().pausedLogs], pausedLogs: [], logPaused: false });
        return;
      }
      set({ logPaused: paused });
    },
```

Update `clearLogs` to also drop the buffer:

```typescript
    clearLogs: () => {
      set({ logs: [], pausedLogs: [] });
    },
```

- [ ] **Step 4: Add the pause/resume button to the event panel**

In `src/components/EventPanel.tsx`, change the imports:

```typescript
import { Eraser, Pause, Play } from "lucide-react";
```

Add a `setLogPaused` selector after the `clearLogs` selector:

```typescript
  const setLogPaused = useRailWatchStore((state) => state.setLogPaused);
  const pausedCount = useRailWatchStore((state) => state.pausedLogs.length);
```

Add a button inside `event-head-actions`, before the existing clear `Tooltip`:

```tsx
          <Tooltip title={logPaused ? "恢复事件流" : "暂停事件流"}>
            <button
              aria-label={logPaused ? "恢复事件流" : "暂停事件流"}
              aria-pressed={logPaused}
              className={logPaused ? "event-clear-btn active" : "event-clear-btn"}
              onClick={() => setLogPaused(!logPaused)}
              type="button"
            >
              {logPaused ? <Play size={14} /> : <Pause size={14} />}
              <span>{logPaused ? `恢复${pausedCount ? `(${pausedCount})` : ""}` : "暂停"}</span>
            </button>
          </Tooltip>
```

- [ ] **Step 5: Add an event-panel test for the toggle**

In `src/components/EventPanel.test.tsx`, add `pausedLogs: []` to the store reset `setState` object, then add this test (match the file's existing import style for `render`, `screen`, `userEvent`, and `railwatchStore`):

```typescript
  test("toggles the paused state from the panel", async () => {
    const user = userEvent.setup();
    render(<EventPanel onClose={() => undefined} runCommand={(async () => undefined) as CommandRunner} />);

    await user.click(screen.getByRole("button", { name: "暂停事件流" }));
    expect(railwatchStore.getState().logPaused).toBe(true);

    await user.click(screen.getByRole("button", { name: "恢复事件流" }));
    expect(railwatchStore.getState().logPaused).toBe(false);
  });
```

- [ ] **Step 6: Run the focused tests**

Run:

```powershell
npm run test:renderer -- src/store/railwatchStore.test.ts src/components/EventPanel.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/store/railwatchStore.ts src/store/railwatchStore.test.ts src/components/EventPanel.tsx src/components/EventPanel.test.tsx
git commit -m "feat: make the event-log pause control real with buffered resume"
```

---

### Task 10: Low-severity UI correctness cleanups

**Files:**
- Modify: `src/components/TripSetupPage.tsx` (`applyCommonTrain`, priority state)
- Modify: `src/components/TripSetupPage.test.tsx`
- Modify: `src/lib/formatEventLog.ts`
- Modify: `src/lib/formatEventLog.test.ts`

- [ ] **Step 1: Write a test that "常用车次" adds every preset and priority follows config**

In `src/components/TripSetupPage.test.tsx`, add:

```typescript
  test("常用车次 merges every preset code", async () => {
    const user = userEvent.setup();
    railwatchStore.setState({ config: { ...defaultConfig, train_code: "" } });

    render(
      <TripSetupPage busy={null} confirm={(async () => false) as ConfirmDialog} runCommand={(async () => undefined) as CommandRunner} />,
    );

    await user.click(screen.getByRole("button", { name: "常用车次" }));

    const codes = railwatchStore.getState().config.train_code.split(/[,，、\s]+/).filter(Boolean);
    expect(codes).toEqual(expect.arrayContaining(["G1", "G3", "G17", "D313", "D321"]));
  });
```

(Match the file's existing imports for `defaultConfig`, `railwatchStore`, `ConfirmDialog`, and `CommandRunner`.)

- [ ] **Step 2: Run the failing test**

Run:

```powershell
npm run test:renderer -- src/components/TripSetupPage.test.tsx
```

Expected: FAIL because `applyCommonTrain` only merges `COMMON_TRAINS[0]`.

- [ ] **Step 3: Merge all common trains and derive priority from config**

In `src/components/TripSetupPage.tsx`, change `applyCommonTrain`:

```typescript
  const applyCommonTrain = () => {
    const current = config.train_code
      .split(/[,，、\s]+/)
      .map((code) => code.trim())
      .filter(Boolean);
    const merged = [...new Set([...current, ...COMMON_TRAINS])];
    update({ train_code: merged.join(", ") });
  };
```

Change the `priority` initializer to derive from `smart_rate`:

```typescript
  const [priority, setPriority] = useState<PriorityMode>(() => (config.smart_rate ? "速度优先" : "成功率优先"));
```

In `loadConfig`, after `setRequestMode(...)`, add:

```typescript
      setPriority(loaded.smart_rate ? "速度优先" : "成功率优先");
```

- [ ] **Step 4: Broaden the event-log query-row noise filter**

In `src/lib/formatEventLog.ts`, change:

```typescript
const queryRowPattern = /^G[A-Z0-9]+\s+\|/;
```

to:

```typescript
const queryRowPattern = /^[GDCKTZS]\d+[A-Z0-9]*\s+\|/;
```

- [ ] **Step 5: Add a formatter test for non-G trains**

In `src/lib/formatEventLog.test.ts`, add a test that a `D`-train result row is filtered out (match the file's existing helper/imports):

```typescript
test("filters non-G query result rows out of the event feed", () => {
  const events = presentEventLogs(
    [
      { time: "09:00:00", level: "INFO", message: "🚄 D321 | 北京 上海 二等座 有" },
      { time: "09:00:01", level: "INFO", message: "系统就绪" },
    ],
    "全部",
  );

  expect(events.map((event) => event.title)).toEqual(["系统就绪"]);
});
```

- [ ] **Step 6: Run the focused tests**

Run:

```powershell
npm run test:renderer -- src/components/TripSetupPage.test.tsx src/lib/formatEventLog.test.ts
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/components/TripSetupPage.tsx src/components/TripSetupPage.test.tsx src/lib/formatEventLog.ts src/lib/formatEventLog.test.ts
git commit -m "fix: merge all common trains, sync priority from config, widen log noise filter"
```

---

### Task 11: Full verification and cleanup

**Files:**
- Verify all touched files.

- [ ] **Step 1: Run all renderer and Electron tests**

Run:

```powershell
npm test
```

Expected: all Vitest suites pass.

- [ ] **Step 2: Run all Python tests**

Run:

```powershell
$env:PYTHONPATH='.'; pytest
```

Expected: all Python tests pass.

- [ ] **Step 3: Typecheck**

Run:

```powershell
npm run typecheck
```

Expected: TypeScript checks pass for renderer and Electron code.

- [ ] **Step 4: Inspect the diff**

Run:

```powershell
git diff --stat HEAD~10
```

Expected: changes only in the files listed in this plan plus their tests.

- [ ] **Step 5: Manual desktop smoke test**

Run:

```powershell
npm run dev
```

Manual checks:
- 系统设置 → 打开登录, complete a real 12306 login, then 检查登录 reports "登录已验证" (was always failing before).
- 行程设置 → 分析 keeps the rest of the UI responsive; the 30s runtime poll and 停止 still work while a long analysis runs.
- 购票监控 during live monitoring: 查询次数 increments with backend loops, 查询结果 updates each loop, 命中记录 shows the real seat type/value.
- 仪表盘 no longer shows `00:12` / `成功提交`; 请求次数 reflects backend loops.
- A hit during monitoring shows the toast but does NOT jump you away from the current page.
- 系统设置 → 下载 ChromeDriver writes into the data directory shown in the sidebar.
- 事件日志 暂停/恢复 actually stops and then flushes buffered events.

---

## Self-Review

**Spec coverage:** Every finding in the Findings→Task map has a task: B1→T1, B2→T2, driver race→T3, A1/B3→T4+T5, A2→T6, B4→T7, B5→T8, A3→T9, A4/A5/B8→T10, verification→T11.

**Placeholder scan:** No TBD/TODO; every code step shows complete code. Where a test file's exact import header varies, the step says to match the file's existing imports rather than inventing new ones, and the asserted behavior is fully specified.

**Type consistency:** `MonitorTickPayload` is defined in `src/types.ts` (Task 5 Step 1) and consumed identically in the store action `applyMonitorTick` (Task 5 Step 4), `App.tsx` (Task 5 Step 5), and tests. Backend `_handle_progress`/`_handle_hit` keys (`loop`, `date`, `rows`, `train_code`, `seat_type`, `status`, `source`, `title`, `message`) match the `TicketMonitor` callback payloads emitted in Task 4 Step 5. `progress_callback`/`on_hit` parameter names match between `gui_12306_0.py` and `railwatch_bridge.py._monitor_worker`.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-09-railwatch-frontend-backend-gaps-and-bugs.md`. Two execution options:

**1. Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.
