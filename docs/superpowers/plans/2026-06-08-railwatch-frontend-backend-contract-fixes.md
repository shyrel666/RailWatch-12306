# RailWatch Frontend Backend Contract Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every visible RailWatch configuration control either work end-to-end through the Electron/Python backend or disappear from the UI when it is only decorative.

**Architecture:** Treat the Python bridge as the source of truth for runtime configuration. Renderer controls write typed config to the Zustand store, IPC sends that config unchanged, and Python validation/persistence/core logic consumes the same fields. Unsafe or unsupported dashboard affordances are removed instead of being left as fake controls.

**Tech Stack:** React 19, Ant Design 6, Zustand, Electron IPC, Python 3.10, Selenium, Vitest, pytest.

---

## File Structure

- `src/types.ts`: renderer-side config and event types.
- `src/store/railwatchStore.ts`: default config and runtime event state merging.
- `src/App.tsx`: bridge event handling for state/results/logs/runtime labels.
- `src/components/TripSetupPage.tsx`: trip form controls for date range, timeout, interval, strategy toggles.
- `src/components/DashboardPage.tsx`: dashboard summary; remove fake concurrency/payment controls.
- `src/components/SettingsPage.tsx`: login action and new login status check action.
- `electron/ipcSecurity.ts`: allowed command whitelist for any new command.
- `railwatch_runtime.py`: JSON-lines command dispatcher.
- `railwatch_bridge.py`: validation, persistence, runtime state, login check, query orchestration.
- `railwatch_dates.py`: shared Python helper for date-range expansion.
- `gui_12306_0.py`: core query/monitor config model and Selenium behavior.
- `tests/test_railwatch_bridge.py`: bridge contract tests.
- `tests/test_railwatch_dates.py`: date range unit tests.
- `tests/test_gui_logic.py`: core monitor logic tests.
- `src/components/*.test.tsx` and `src/store/railwatchStore.test.ts`: renderer contract tests.

---

### Task 1: Persist the Full Renderer Config Contract

**Files:**
- Modify: `railwatch_bridge.py`
- Modify: `gui_12306_0.py`
- Modify: `tests/test_railwatch_bridge.py`
- Modify: `tests/test_gui_logic.py`

- [ ] **Step 1: Write the failing bridge persistence test**

Add this test to `tests/test_railwatch_bridge.py` inside `RailWatchBridgeContractTests`:

```python
    def test_save_config_persists_renderer_strategy_fields(self):
        from railwatch_bridge import RailWatchBridge

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = RailWatchBridge(data_dir=temp_dir, event_callback=lambda event: None)

            saved = bridge.save_config(
                {
                    "from_station_cn": "北京",
                    "to_station_cn": "上海",
                    "date": "2026-06-10",
                    "date_range": "±2天",
                    "interval": 1.5,
                    "query_timeout": 25,
                    "smart_rate": False,
                    "timer_enabled": True,
                    "target_time": "08:30:00",
                    "keep_alive": False,
                }
            )

            self.assertEqual(saved["date_range"], "±2天")
            self.assertEqual(saved["interval"], 1.5)
            self.assertEqual(saved["query_timeout"], 25)
            self.assertFalse(saved["smart_rate"])
            self.assertTrue(saved["timer_enabled"])
            self.assertEqual(saved["target_time"], "08:30:00")

            with open(os.path.join(temp_dir, "user_config.json"), "r", encoding="utf-8") as handle:
                persisted = json.load(handle)

            self.assertEqual(persisted["date_range"], "±2天")
            self.assertEqual(persisted["interval"], 1.5)
            self.assertEqual(persisted["query_timeout"], 25)
            self.assertFalse(persisted["smart_rate"])
            self.assertTrue(persisted["timer_enabled"])
            self.assertEqual(persisted["target_time"], "08:30:00")
            self.assertFalse(persisted["keep_alive"])
```

- [ ] **Step 2: Run the failing bridge test**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_railwatch_bridge.py::RailWatchBridgeContractTests::test_save_config_persists_renderer_strategy_fields -q
```

Expected: FAIL because `user_config.json` does not contain `date_range`, `query_timeout`, `smart_rate`, `timer_enabled`, or `target_time`.

- [ ] **Step 3: Update Python validation to preserve float interval and timeout**

In `railwatch_bridge.py`, add `_to_float` after `_to_int`:

```python
def _to_float(value: object, fallback: float, minimum: Optional[float] = None, maximum: Optional[float] = None) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = fallback
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed
```

Then change `validate_config` so the interval is not truncated and the timeout is validated:

```python
    config["interval"] = _to_float(config.get("interval"), 5.0, minimum=1.0, maximum=60.0)
    config["query_timeout"] = _to_int(config.get("query_timeout"), 40, minimum=5, maximum=120)
```

Keep the existing `passenger_count` and `prepare_time` integer validation.

- [ ] **Step 4: Extend `QueryConfig` with renderer strategy fields**

In `gui_12306_0.py`, change the `QueryConfig` dataclass to include these fields:

```python
    interval: float = 3.0
    query_timeout: int = 40
    date_range: str = "单日"
    smart_rate: bool = True
    timer_enabled: bool = False
    target_time: str = "00:00:00"
```

Update `to_dict` to include:

```python
            "query_timeout": self.query_timeout,
            "date_range": self.date_range,
            "smart_rate": self.smart_rate,
            "timer_enabled": self.timer_enabled,
            "target_time": self.target_time,
```

Update `from_dict` to include:

```python
            interval=data.get("interval", 3.0),
            query_timeout=data.get("query_timeout", 40),
            date_range=data.get("date_range", "单日"),
            smart_rate=data.get("smart_rate", True),
            timer_enabled=data.get("timer_enabled", False),
            target_time=data.get("target_time", "00:00:00"),
```

- [ ] **Step 5: Pass the new fields through `_make_query_config`**

In `railwatch_bridge.py`, update `_make_query_config`:

```python
            interval=config["interval"],
            query_timeout=config["query_timeout"],
            date_range=config["date_range"],
            smart_rate=config["smart_rate"],
            timer_enabled=config["timer_enabled"],
            target_time=config["target_time"],
```

- [ ] **Step 6: Add a core config persistence test**

Extend `tests/test_gui_logic.py` with:

```python
    def test_query_config_persists_renderer_strategy_fields(self):
        cfg = QueryConfig(
            interval=1.5,
            query_timeout=25,
            date_range="±2天",
            smart_rate=False,
            timer_enabled=True,
            target_time="08:30:00",
        )

        data = cfg.to_dict()

        self.assertEqual(data["interval"], 1.5)
        self.assertEqual(data["query_timeout"], 25)
        self.assertEqual(data["date_range"], "±2天")
        self.assertFalse(data["smart_rate"])
        self.assertTrue(data["timer_enabled"])
        self.assertEqual(data["target_time"], "08:30:00")
```

- [ ] **Step 7: Run focused Python tests**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_railwatch_bridge.py tests/test_gui_logic.py -q
```

Expected: PASS.

---

### Task 2: Implement Date Range Expansion and Query Timeout in Backend Logic

**Files:**
- Create: `railwatch_dates.py`
- Create: `tests/test_railwatch_dates.py`
- Modify: `railwatch_bridge.py`
- Modify: `gui_12306_0.py`
- Modify: `tests/test_railwatch_bridge.py`
- Modify: `tests/test_gui_logic.py`

- [ ] **Step 1: Write date range helper tests**

Create `tests/test_railwatch_dates.py`:

```python
import unittest


class RailWatchDateRangeTests(unittest.TestCase):
    def test_expands_supported_presets(self):
        from railwatch_dates import expand_travel_dates

        self.assertEqual(expand_travel_dates("2026-06-10", "单日"), ["2026-06-10"])
        self.assertEqual(
            expand_travel_dates("2026-06-10", "±1天"),
            ["2026-06-09", "2026-06-10", "2026-06-11"],
        )
        self.assertEqual(
            expand_travel_dates("2026-06-10", "±2天"),
            ["2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12"],
        )

    def test_unknown_or_invalid_range_falls_back_to_selected_date(self):
        from railwatch_dates import expand_travel_dates

        self.assertEqual(expand_travel_dates("2026-06-10", "自定义"), ["2026-06-10"])
        self.assertEqual(expand_travel_dates("bad-date", "±2天"), ["bad-date"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the failing helper test**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_railwatch_dates.py -q
```

Expected: FAIL because `railwatch_dates.py` does not exist.

- [ ] **Step 3: Create the shared date helper**

Create `railwatch_dates.py`:

```python
from __future__ import annotations

from datetime import date, timedelta


def expand_travel_dates(travel_date: str, date_range: str) -> list[str]:
    try:
        base = date.fromisoformat(str(travel_date))
    except ValueError:
        return [str(travel_date)]

    radius_by_range = {
        "单日": 0,
        "±1天": 1,
        "±2天": 2,
    }
    radius = radius_by_range.get(str(date_range).strip(), 0)
    return [(base + timedelta(days=offset)).isoformat() for offset in range(-radius, radius + 1)]
```

- [ ] **Step 4: Write a bridge test proving `analyzeQuery` loops over the range**

Add this test to `tests/test_railwatch_bridge.py`:

```python
    def test_analyze_query_expands_date_range_and_tags_rows(self):
        from railwatch_bridge import RailWatchBridge

        analyzed_dates = []
        emitted_events = []

        class FakeAnalyzer:
            def __init__(self, driver, log_callback=None, base_dir=None):
                self.driver = driver

            def open_fill_query_and_analyze(self, config):
                analyzed_dates.append(config["date"])
                return [{"train": "G101", "raw": f"G101 {config['date']} 二等座 有"}]

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = RailWatchBridge(data_dir=temp_dir, event_callback=emitted_events.append)
            bridge._ensure_driver = lambda: object()

            with patch("railwatch_bridge.PageAnalyzer", FakeAnalyzer), patch("railwatch_bridge.CORE_AVAILABLE", True):
                result = bridge.analyze_query(
                    {
                        "from_station_cn": "北京",
                        "to_station_cn": "上海",
                        "date": "2026-06-10",
                        "date_range": "±1天",
                    }
                )

        self.assertEqual(analyzed_dates, ["2026-06-09", "2026-06-10", "2026-06-11"])
        self.assertTrue(result["query_ready"])
        self.assertEqual(bridge.query_results[0]["date"], "2026-06-09")
        self.assertEqual(bridge.query_results[2]["date"], "2026-06-11")
```

Ensure `tests/test_railwatch_bridge.py` imports `patch`:

```python
from unittest.mock import Mock, patch
```

- [ ] **Step 5: Implement bridge-side range analysis**

In `railwatch_bridge.py`, import the helper:

```python
from railwatch_dates import expand_travel_dates
```

Change `analyze_query` after analyzer creation:

```python
            rows = []
            for travel_date in expand_travel_dates(config["date"], config["date_range"]):
                date_config = {**config, "date": travel_date}
                date_rows = analyzer.open_fill_query_and_analyze(date_config)
                if date_rows:
                    rows.extend([{**row, "date": travel_date} for row in date_rows])
            if not rows:
                raise RuntimeError("未解析到查询结果行。")
```

- [ ] **Step 6: Wire query timeout into query analysis and monitor loops**

In `gui_12306_0.py`, change `PageAnalyzer.open_fill_query_and_analyze`:

```python
        query_timeout = int(cfg.get("query_timeout", 60))
        if not self.wait_for_rows(timeout=query_timeout):
```

In `TicketMonitor._run_single_loop`, replace the hardcoded monitor timeout:

```python
        query_timeout = int(self.cfg.get("query_timeout", 40))
        if not self.wait_for_rows(timeout=query_timeout, stop_check=self.should_stop):
```

- [ ] **Step 7: Add a monitor date cycling test**

Add to `tests/test_gui_logic.py`:

```python
class FakeDateCyclingDriver:
    def __init__(self):
        self.scripts = []

    def execute_script(self, script, *args):
        self.scripts.append((script, args))
        return None


class TicketMonitorDateRangeTests(unittest.TestCase):
    def test_monitor_applies_date_range_dates_by_loop(self):
        driver = FakeDateCyclingDriver()
        monitor = TicketMonitor(
            driver,
            {"date": "2026-06-10", "date_range": "±1天"},
            log_callback=lambda msg: None,
        )

        monitor._apply_loop_date(1)
        monitor._apply_loop_date(2)
        monitor._apply_loop_date(3)
        monitor._apply_loop_date(4)

        applied_dates = [args[0] for script, args in driver.scripts if "train_date" in script]
        self.assertEqual(applied_dates, ["2026-06-09", "2026-06-10", "2026-06-11", "2026-06-09"])
```

- [ ] **Step 8: Implement monitor date cycling**

In `gui_12306_0.py`, import:

```python
from railwatch_dates import expand_travel_dates
```

In `TicketMonitor.__init__`, add:

```python
        self.travel_dates = expand_travel_dates(str(cfg.get("date", "")), str(cfg.get("date_range", "单日")))
        self.current_loop_date = ""
```

Add this method to `TicketMonitor`:

```python
    def _apply_loop_date(self, loop_count: int) -> None:
        if not self.travel_dates:
            return
        travel_date = self.travel_dates[(loop_count - 1) % len(self.travel_dates)]
        if travel_date == self.current_loop_date:
            return
        self.driver.execute_script(
            """
            const date = arguments[0];
            const input = document.querySelector('#train_date');
            if (input) {
                input.removeAttribute('readonly');
                input.value = date;
                input.dispatchEvent(new Event('input', {bubbles: true}));
                input.dispatchEvent(new Event('change', {bubbles: true}));
            }
            """,
            travel_date,
        )
        self.current_loop_date = travel_date
        self.cfg["date"] = travel_date
        if len(self.travel_dates) > 1:
            self.log(f"📅 本轮监控日期：{travel_date}")
```

Call it at the start of `_run_single_loop`, before refresh/click:

```python
        self._apply_loop_date(loop_count)
```

- [ ] **Step 9: Run focused Python tests**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_railwatch_dates.py tests/test_railwatch_bridge.py tests/test_gui_logic.py -q
```

Expected: PASS.

---

### Task 3: Wire Renderer Config for Timeout and Accurate Date Range Display

**Files:**
- Modify: `src/types.ts`
- Modify: `src/store/railwatchStore.ts`
- Modify: `src/components/TripSetupPage.tsx`
- Modify: `src/components/DashboardPage.tsx`
- Modify: `src/components/TripSetupPage.test.tsx`
- Modify: `src/components/DashboardPage.test.tsx`

- [ ] **Step 1: Write renderer tests for timeout and supported date ranges**

In `src/components/TripSetupPage.test.tsx`, add:

```typescript
  test("writes query timeout and supported date range into backend config shape", async () => {
    const user = userEvent.setup();
    const confirm = vi.fn(async () => false) as ConfirmDialog;
    const runCommand = vi.fn(async () => undefined) as CommandRunner;

    render(<TripSetupPage busy={null} confirm={confirm} runCommand={runCommand} />);

    await user.click(screen.getByRole("button", { name: "±2天" }));
    await user.click(screen.getByLabelText("增加超时时间"));

    expect(railwatchStore.getState().config.date_range).toBe("±2天");
    expect(railwatchStore.getState().config.query_timeout).toBe(41);
    expect(screen.queryByRole("button", { name: "自定义" })).toBeNull();
  });
```

In `src/components/DashboardPage.test.tsx`, add:

```typescript
  test("shows the configured date range instead of a hardcoded range", () => {
    railwatchStore.setState({
      config: { ...defaultConfig, date: "2026-06-10", date_range: "±2天" },
    });

    render(<DashboardPage />);

    expect(screen.getByText("6月10日（±2天）")).toBeTruthy();
    expect(screen.queryByText("6月10日（±3天）")).toBeNull();
  });
```

- [ ] **Step 2: Run failing renderer tests**

Run:

```powershell
npm run test:renderer -- src/components/TripSetupPage.test.tsx src/components/DashboardPage.test.tsx
```

Expected: FAIL because `query_timeout` is not part of `RailWatchConfig` and dashboard range text is hardcoded.

- [ ] **Step 3: Add `query_timeout` to renderer config types/defaults**

In `src/types.ts`, add:

```typescript
  query_timeout: number;
```

after `interval: number;`.

In `src/store/railwatchStore.ts`, add:

```typescript
  query_timeout: 40,
```

after `interval: 5,`.

- [ ] **Step 4: Replace local query timeout state with config state**

In `src/components/TripSetupPage.tsx`, remove:

```typescript
  const [queryTimeout, setQueryTimeout] = useState(10);
```

Change the timeout stepper to:

```tsx
              <NumberStepper
                ariaLabel="超时时间"
                max={120}
                min={5}
                step={1}
                suffix="秒"
                value={config.query_timeout}
                onChange={(value) => update({ query_timeout: value })}
              />
```

Change `DateRangePreset` to remove unsupported custom mode:

```typescript
type DateRangePreset = "单日" | "±1天" | "±2天";
```

Change the segmented options:

```tsx
                options={["单日", "±1天", "±2天"] as const}
```

- [ ] **Step 5: Show the actual date range on the dashboard**

In `src/components/DashboardPage.tsx`, replace:

```tsx
              <dd>{compactTripDate}（±3天）</dd>
```

with:

```tsx
              <dd>{compactTripDate}（{config.date_range || "单日"}）</dd>
```

- [ ] **Step 6: Run focused renderer tests**

Run:

```powershell
npm run test:renderer -- src/components/TripSetupPage.test.tsx src/components/DashboardPage.test.tsx
```

Expected: PASS.

---

### Task 4: Remove Fake Dashboard Controls and Unsupported Payment Signal

**Files:**
- Modify: `src/components/DashboardPage.tsx`
- Modify: `src/components/DashboardPage.test.tsx`

- [ ] **Step 1: Update dashboard tests to reject fake controls**

In `src/components/DashboardPage.test.tsx`, change the dashboard chrome test assertions around monitor settings:

```typescript
    expect(screen.getByText("请求模式")).toBeTruthy();
    expect(screen.queryByText("并发请求")).toBeNull();
    expect(screen.queryByText("自动跳转支付")).toBeNull();
    expect(screen.queryByRole("button", { name: "了解更多风险说明" })).toBeNull();
```

- [ ] **Step 2: Run the failing dashboard test**

Run:

```powershell
npm run test:renderer -- src/components/DashboardPage.test.tsx
```

Expected: FAIL because the dashboard still renders `并发请求`, `自动跳转支付`, and a non-wired risk button.

- [ ] **Step 3: Remove the fake concurrency control**

In `src/components/DashboardPage.tsx`, delete this block:

```tsx
          <label>
            <span>并发请求</span>
            <span className="stepper-control">
              <button type="button" aria-label="减少并发">
                -
              </button>
              <strong>3</strong>
              <button type="button" aria-label="增加并发">
                +
              </button>
            </span>
          </label>
```

- [ ] **Step 4: Remove the unsupported payment automation row and inert risk button**

In `src/components/DashboardPage.tsx`, delete:

```tsx
            <label className="automation-toggle">
              <Switch checked={false} disabled size="small" />
              <span>
                自动跳转支付 <strong>未启用</strong>
              </span>
            </label>
```

Delete:

```tsx
          <button type="button">了解更多风险说明</button>
```

- [ ] **Step 5: Run focused renderer tests**

Run:

```powershell
npm run test:renderer -- src/components/DashboardPage.test.tsx
```

Expected: PASS.

---

### Task 5: Apply Runtime Label Events and Clear Stale Hits

**Files:**
- Modify: `src/store/railwatchStore.ts`
- Modify: `src/store/railwatchStore.test.ts`
- Modify: `src/App.tsx`

- [ ] **Step 1: Write store tests for runtime labels and hit clearing**

Add to `src/store/railwatchStore.test.ts`:

```typescript
  test("applies runtime label patches from backend events", () => {
    const store = createRailWatchStore();

    store.getState().applyRuntimeLabels({
      chromedriver_path: "D:/RailWatch/chromedriver.exe",
      chrome_version: "Chrome 148",
    });

    expect(store.getState().runtime.chromedriver_path).toBe("D:/RailWatch/chromedriver.exe");
    expect(store.getState().runtime.chrome_version).toBe("Chrome 148");
  });

  test("clears stale hits when backend state reports no hits", () => {
    const store = createRailWatchStore();

    store.getState().applyNotify({
      title: "发现目标车票",
      message: "命中：G101",
      hit: {
        train_code: "G101",
        seat_type: "二等座",
        status: "available",
        source: "regular",
        detail: "命中：G101",
        label: "G101 二等座 有票: available",
      },
    });

    expect(store.getState().hits).toHaveLength(1);

    store.getState().applyState({
      ...store.getState().status,
      hits: [],
    });

    expect(store.getState().hits).toEqual([]);
  });
```

- [ ] **Step 2: Run the failing store tests**

Run:

```powershell
npm run test:renderer -- src/store/railwatchStore.test.ts
```

Expected: FAIL because `applyRuntimeLabels` does not exist and `applyState` preserves stale hits.

- [ ] **Step 3: Add the runtime label store action**

In `src/store/railwatchStore.ts`, add the action type:

```typescript
  applyRuntimeLabels: (patch: Partial<Pick<RuntimeInfo, "chromedriver_path" | "chrome_version">>) => void;
```

Add the implementation after `applyRuntimeInfo`:

```typescript
    applyRuntimeLabels: (patch) => {
      set({ runtime: { ...get().runtime, ...patch } });
    },
```

- [ ] **Step 4: Make backend state authoritative for hits**

In `src/store/railwatchStore.ts`, change `applyState` to:

```typescript
    applyState: (status) => {
      set({
        status,
        hits: status.hits,
      });
    },
```

- [ ] **Step 5: Handle `labels` bridge events**

In `src/App.tsx`, add a `labels` branch inside `applyEvent`:

```typescript
        case "labels":
          state.applyRuntimeLabels(event.payload as { chromedriver_path?: string; chrome_version?: string });
          break;
```

- [ ] **Step 6: Run focused renderer tests**

Run:

```powershell
npm run test:renderer -- src/store/railwatchStore.test.ts
```

Expected: PASS.

---

### Task 6: Correct Login State Semantics and Add an Explicit Login Check

**Files:**
- Modify: `railwatch_state.py`
- Modify: `railwatch_bridge.py`
- Modify: `railwatch_runtime.py`
- Modify: `electron/ipcSecurity.ts`
- Modify: `src/components/SettingsPage.tsx`
- Modify: `tests/test_railwatch_state.py`
- Modify: `tests/test_railwatch_bridge.py`
- Modify: `electron/__tests__/ipcSecurity.test.ts`
- Modify: `src/components/SettingsPage.test.tsx`

- [ ] **Step 1: Write state tests for login opened vs login verified**

Add to `tests/test_railwatch_state.py`:

```python
def test_login_opened_is_not_login_ready():
    state = RailWatchState.initial().with_login_opened("登录页面已打开")

    assert state.phase == AppPhase.LOGIN
    assert not state.login_ready
    assert state.status_message == "登录页面已打开"
    assert state.error_message == ""


def test_login_verified_marks_login_ready():
    state = RailWatchState.initial().with_login_verified(True, "登录已验证")

    assert state.phase == AppPhase.LOGIN
    assert state.login_ready
    assert state.status_message == "登录已验证"
    assert state.error_message == ""
```

- [ ] **Step 2: Implement login state helpers**

In `railwatch_state.py`, add these methods to `RailWatchState`:

```python
    def with_login_opened(self, message: str = "") -> "RailWatchState":
        return replace(
            self,
            phase=AppPhase.LOGIN,
            login_ready=False,
            risk_level="notice",
            status_message=message or "登录页面已打开，请完成登录",
            error_message="",
        )

    def with_login_verified(self, ready: bool, message: str = "") -> "RailWatchState":
        return replace(
            self,
            phase=AppPhase.LOGIN if ready else AppPhase.ERROR,
            login_ready=ready,
            risk_level="notice" if ready else "warning",
            status_message=message or ("登录已验证" if ready else "登录未完成"),
            error_message="" if ready else (message or "登录未完成"),
        )
```

- [ ] **Step 3: Change `open_login` to opened, not ready**

In `railwatch_bridge.py`, replace:

```python
            return self.emit_state(self.state.with_login(True, "登录页面已打开"))
```

with:

```python
            return self.emit_state(self.state.with_login_opened("登录页面已打开，请在浏览器中完成 12306 登录。"))
```

- [ ] **Step 4: Add bridge login check tests**

Add to `tests/test_railwatch_bridge.py`:

```python
    def test_check_login_marks_ready_when_12306_session_is_valid(self):
        from railwatch_bridge import RailWatchBridge

        class FakeDriver:
            def execute_script(self, script):
                return {"data": {"flag": True}}

        bridge = RailWatchBridge(data_dir=tempfile.mkdtemp(), event_callback=lambda event: None)
        bridge.driver = FakeDriver()

        state = bridge.check_login()

        self.assertTrue(state["login_ready"])
        self.assertEqual(state["status_message"], "登录已验证")

    def test_check_login_rejects_missing_browser_session(self):
        from railwatch_bridge import RailWatchBridge

        bridge = RailWatchBridge(data_dir=tempfile.mkdtemp(), event_callback=lambda event: None)

        state = bridge.check_login()

        self.assertFalse(state["login_ready"])
        self.assertIn("请先打开登录页", state["error_message"])
```

- [ ] **Step 5: Implement bridge login check**

In `railwatch_bridge.py`, add:

```python
    def check_login(self) -> dict:
        if not self.driver:
            return self.emit_state(self.state.with_login_verified(False, "请先打开登录页。"))
        try:
            result = self.driver.execute_script(
                """
                return fetch('/otn/login/checkUser', {credentials: 'include'})
                  .then(response => response.json())
                  .catch(() => ({data: {flag: false}}));
                """
            )
            ready = bool(((result or {}).get("data") or {}).get("flag"))
            if ready:
                self.log("12306 登录状态已验证。", "SUCCESS")
                return self.emit_state(self.state.with_login_verified(True, "登录已验证"))
            return self.emit_state(self.state.with_login_verified(False, "12306 登录未完成。"))
        except Exception as exc:
            return self.emit_state(self.state.with_login_verified(False, f"登录状态检查失败: {exc}"))
```

- [ ] **Step 6: Add command routing**

In `electron/ipcSecurity.ts`, add to `RAILWATCH_COMMANDS`:

```typescript
  "checkLogin",
```

In `railwatch_runtime.py`, add to `handlers`:

```python
            "checkLogin": lambda: self.bridge.check_login(),
```

In `electron/__tests__/ipcSecurity.test.ts`, add:

```typescript
    expect(isRailWatchCommand("checkLogin")).toBe(true);
```

- [ ] **Step 7: Add a settings page action**

In `src/components/SettingsPage.tsx`, add a maintenance card next to "打开登录":

```tsx
          <button
            className="sw-action-card"
            disabled={busy === "checkLogin"}
            onClick={() => void runCommand("checkLogin")}
            type="button"
          >
            <LogIn size={18} />
            <span className="sw-action-label">检查登录</span>
            <span className="sw-action-desc">验证当前 12306 会话状态</span>
          </button>
```

- [ ] **Step 8: Run focused tests**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_railwatch_state.py tests/test_railwatch_bridge.py -q
npm run test:electron -- electron/__tests__/ipcSecurity.test.ts
npm run test:renderer -- src/components/SettingsPage.test.tsx
```

Expected: PASS.

---

### Task 7: Make Keep-Alive a Real Backend Behavior During Timed Waiting

**Files:**
- Modify: `railwatch_bridge.py`
- Modify: `tests/test_railwatch_bridge.py`

- [ ] **Step 1: Write keep-alive tests for timed waiting**

Add to `tests/test_railwatch_bridge.py`:

```python
    def test_wait_for_target_time_sends_keep_alive_when_enabled(self):
        from railwatch_bridge import RailWatchBridge

        class FakeDriver:
            def __init__(self):
                self.keep_alive_calls = 0

            def execute_script(self, script):
                if "checkUser" in script:
                    self.keep_alive_calls += 1
                return None

        bridge = RailWatchBridge(data_dir=tempfile.mkdtemp(), event_callback=lambda event: None)
        bridge.driver = FakeDriver()
        bridge.is_monitoring = True

        with patch("railwatch_bridge.time.time", side_effect=[0, 61, 62]), patch("railwatch_bridge.time.sleep", lambda seconds: None):
            bridge._wait_for_target_timestamp(62, {"keep_alive": True})

        self.assertEqual(bridge.driver.keep_alive_calls, 1)

    def test_wait_for_target_time_skips_keep_alive_when_disabled(self):
        from railwatch_bridge import RailWatchBridge

        class FakeDriver:
            def __init__(self):
                self.keep_alive_calls = 0

            def execute_script(self, script):
                self.keep_alive_calls += 1

        bridge = RailWatchBridge(data_dir=tempfile.mkdtemp(), event_callback=lambda event: None)
        bridge.driver = FakeDriver()
        bridge.is_monitoring = True

        with patch("railwatch_bridge.time.time", side_effect=[0, 61, 62]), patch("railwatch_bridge.time.sleep", lambda seconds: None):
            bridge._wait_for_target_timestamp(62, {"keep_alive": False})

        self.assertEqual(bridge.driver.keep_alive_calls, 0)
```

- [ ] **Step 2: Extract wait loop and implement keep-alive**

In `railwatch_bridge.py`, add:

```python
    def _send_keep_alive(self) -> None:
        if not self.driver:
            return
        try:
            self.driver.execute_script(
                """
                fetch('/otn/login/checkUser', {credentials: 'include'}).catch(() => null);
                """
            )
            self.log("会话保活已发送。")
        except Exception as exc:
            self.log(f"会话保活失败: {exc}", "WARN")

    def _wait_for_target_timestamp(self, wait_until: float, config: dict) -> bool:
        last_keep_alive = 0.0
        while time.time() < wait_until:
            if not self.is_monitoring:
                return False
            now = time.time()
            if config.get("keep_alive") and now - last_keep_alive >= 60:
                self._send_keep_alive()
                last_keep_alive = now
            time.sleep(1)
        return True
```

Change `_wait_for_target_time` loop to:

```python
        return self._wait_for_target_timestamp(wait_until, config)
```

- [ ] **Step 3: Run focused Python tests**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_railwatch_bridge.py -q
```

Expected: PASS.

---

### Task 8: Full Verification and Cleanup

**Files:**
- Verify all touched files.

- [ ] **Step 1: Run all renderer and Electron tests**

Run:

```powershell
npm test
```

Expected: all Electron and renderer Vitest suites pass.

- [ ] **Step 2: Run all Python tests with explicit import path**

Run:

```powershell
$env:PYTHONPATH='.'; pytest
```

Expected: all Python tests pass.

- [ ] **Step 3: Run typecheck**

Run:

```powershell
npm run typecheck
```

Expected: TypeScript checks pass for renderer and Electron code.

- [ ] **Step 4: Inspect the diff**

Run:

```powershell
git diff -- src tests electron railwatch_bridge.py railwatch_runtime.py railwatch_state.py gui_12306_0.py railwatch_dates.py
```

Expected: diff only contains contract fixes, tests, and UI removal for unsupported fake controls.

- [ ] **Step 5: Manual desktop smoke test**

Run:

```powershell
npm run dev
```

Manual checks:
- 行程设置 shows date range options `单日`, `±1天`, `±2天`; no `自定义`.
- 超时时间 changes `config.query_timeout` and is sent with `saveConfig`, `analyzeQuery`, and `startMonitor`.
- 仪表盘 no longer shows `并发请求` or `自动跳转支付`.
- 下载 ChromeDriver updates displayed driver labels immediately after the backend `labels` event.
- 打开登录 does not mark login ready until `检查登录` succeeds.
- 定时启动 with `保持会话` enabled logs periodic keep-alive events while waiting.

---

## Coverage Check

- Date range presets are implemented through shared Python range expansion and renderer display.
- Unsupported custom date range is removed from the renderer because no custom range picker exists.
- Query timeout is typed, persisted, and consumed by analysis/monitor wait loops.
- Float interval is preserved instead of being truncated.
- Fake concurrency and payment UI are removed.
- ChromeDriver label events update runtime state.
- Backend state can clear stale hit records.
- Login state separates "page opened" from "session verified".
- Keep-alive has concrete backend behavior during timed waiting.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-08-railwatch-frontend-backend-contract-fixes.md`. Two execution options:

**1. Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

