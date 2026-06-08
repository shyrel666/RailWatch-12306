# RailWatch 候补 (Waitlist) Reliability — Design Spec

**Date:** 2026-06-09
**Status:** Approved for planning (no git commit yet, per user preference)
**Topic:** Make "到点能提交候补" actually work and reliable, with compliant human-in-the-loop for any verification.

---

## 1. Context

RailWatch drives the real 12306 web pages with Selenium. The monitor loop (`gui_12306_0.py` `TicketMonitor`) refreshes the leftTicket query page, parses rows, and on a "hit" either books (`_try_auto_submit`) or submits a waitlist order (`_try_alternate_order`).

**The core problem:** waitlist (候补) detection is effectively dead. `TicketMonitor._find_hit_row` decides 候补 is possible only when the *seat-cell text* contains the word "候补":

```python
if self.auto_alternate and self.is_alternate_available(seat_value):  # is_alternate_available => "候补" in seat_value
```

On 12306, a sold-out train shows seat cells like `无 / -- / <number>` and the word "候补" is on the **row's action button**, not in the seat cell. So `is_alternate_available(seat_value)` is almost always false, and the `不限席别` branch never attempts 候补 at all. Result: `auto_alternate` rarely or never fires.

Additionally, the submission paths use fragile selectors, contain redundant fixed `sleep`s, and have no explicit handling for 12306's mandatory human verification (人脸核验 / 验证码 / 滑块) — they either silently fail or loop until timeout.

## 2. Goals

- Waitlist (候补) **detection** triggers correctly: based on the presence of a 候补 button on the target train row, for both specified-seat and 不限席别 cases.
- Waitlist **submission** runs end-to-end automatically up to (and including) the no-captcha "确认候补" dialog: select passengers (safety-gated), set the candidate deadline, submit, and auto-confirm.
- **Hit priority:** if a real ticket for the target is available, take the book path; only submit 候补 when there is no real ticket but 候补 is available.
- **Compliant human handoff:** when 12306 requires 人脸核验 / 验证码 / 滑块 at any step, stop automation, keep the browser open, focus the window, and raise a loud "需要人工操作" alert. Never bypass verification.
- **Passenger safety:** if named passengers cannot all be matched, abort the 候补 submission (never submit for the wrong people).
- After a successful 候补 submission, stop the monitor (waitlist is a one-time lock) and notify.

## 3. Non-Goals (explicit boundaries)

- Do **not** bypass or auto-solve 人脸核验, 验证码, or 滑块.
- Do **not** call 12306 private order/候补 JSON APIs to evade page protections; stay on the page-driven flow.
- **Multi-train 候补** in a single order is out of scope (v1 = single-train, first matching target).
- No payment automation.
- No aggressive pre-warm / sub-second latency optimization for hot-train "秒抢" in this iteration (separate follow-up). The book (有票) submit path's own verification handoff is a small consistent follow-up, not part of v1's core; v1 focuses on 候补.

## 4. Design

### 4.1 Fix waitlist detection — `TicketMonitor._find_hit_row`

Decide actions from the row's **buttons**, not seat-cell text:

The return tuple keeps the existing 6-element shape that `_run_single_loop` already unpacks: `(train_code, seat_name, seat_value, row_el, button, action_type)`.

- Compute `book_btn = self._find_book_button(row)` and, only when `self.auto_alternate`, `alternate_btn = self._find_alternate_button(row)`.
- **Specified seats** (`self.target_seats` non-empty):
  - For each target seat: if `is_seat_available(seat_value)` → return `(train_code, seat, seat_value, row, book_btn, "book")`.
  - If no target seat is available and `alternate_btn` exists → return `(train_code, ",".join(target_seats), "候补", row, alternate_btn, "alternate")`.
- **不限席别** (`self.target_seats` empty):
  - If `book_btn` exists → return `(train_code, "未指定席别", "有票", row, book_btn, "book")`.
  - Else if `alternate_btn` exists → return `(train_code, "未指定席别", "候补", row, alternate_btn, "alternate")`.
- `is_alternate_available` (seat-cell based) is no longer used for the decision. (Keep the static method for backward compatibility / tests, but it must not gate 候补.)

This preserves "有票优先" and makes 候补 fire whenever the official 候补 button is present.

### 4.2 Waitlist submission + human handoff — `TicketMonitor._try_alternate_order`

Return a tri-state result so the loop can decide whether to stop:

- `"success"` — 候补 submitted (and the no-captcha 确认候补 dialog auto-confirmed). → loop stops, bridge emits an alternate hit.
- `"human"` — a verification step appeared (人脸核验 / 验证码 / 滑块) → loop stops, bridge raises a "需要人工操作" handoff. Browser is left as-is for the user.
- `"failed"` — element not found / could not complete after opening the 候补 page → loop stops and hands off to the user (avoids spinning on a stranded 候补 page that is no longer the query page).

Steps (each with resilient multi-selectors and clear logging):
1. Click the 候补 button (reuse existing selector fallbacks).
2. Wait for the candidate page/list. If a verification element is detected here or at any later step → return `"human"` (after firing the handoff signal).
3. Select passengers with the existing JS + Selenium fallback. Gate with `_passenger_selection_sufficient`; if named passengers are not all matched → log and return `"failed"` (abort, do not submit).
4. Set the candidate deadline if configured (best-effort).
5. Click 提交候补.
6. Handle the **确认候补** confirmation dialog automatically (no captcha there): click the confirm button via resilient selectors.
7. Detect success (success dialog / URL change / candidate-success marker). On success → return `"success"`; if a verification appears at confirm → return `"human"`.

**Verification detection helper:** a small predicate that scans the page for verification signals — slider container, 验证码 image, 人脸核验 text/markers, or a redirect to a verify/login page. Used between steps to short-circuit into the `"human"` handoff.

### 4.3 Loop integration — `_run_single_loop`

In the hit branch, when `action_type == "alternate"`:
- Call `_try_alternate_order(...)`.
- `"success"` → fire `on_hit` (source=alternate) + `notify`, return `True` (stop loop).
- `"human"` → fire `on_human_action(...)`, return `True` (stop loop; user must act).
- `"failed"` → signal a human handoff ("候补未能自动完成，请手动检查并提交") and return `True` (stop). Re-looping is unsafe because the browser already navigated into the 候补 flow; clicking 候补 opens the afterNate page, so continuing would query the wrong page. Stopping + alerting is the safe choice.

Trim redundant fixed `sleep`s in the 候补 path (keep only the minimal waits required for page transitions).

### 4.4 Callbacks, bridge events, and state

- Add a `human_action_callback` (parallel to the existing `on_hit`) to `TicketMonitor`.
- `RailWatchBridge`:
  - Pass `human_action_callback=self._handle_human_action` into `TicketMonitor` (alongside `progress_callback` / `on_hit` already added).
  - `_handle_human_action(payload)`: log WARN, emit a `humanAction` event `{title, message}`, and `emit_state` with a non-error status message (e.g. risk_level `warning`, status_message "需要人工核验") so the app surfaces it without flipping to an error phase.
  - Existing `_handle_hit` already maps the alternate hit to a structured `TicketHit(source="alternate")` + `notify` + `emit_state(with_hit(...))`.
- Renderer:
  - `src/types.ts`: add `HumanActionPayload` and a `BridgeEvent` branch `{ event: "humanAction"; payload: HumanActionPayload }`.
  - `src/App.tsx`: handle `humanAction` with `notification.warning(...)` (persistent / high-visibility) so the user is prompted to finish in the browser.
  - No new page is required; the existing 监控页 hit card + event log already surface alternate hits and warnings.

### 4.5 Stop semantics

- After `"success"` or `"human"`, the monitor stops (loop returns `True`). The bridge's `_monitor_worker` `finally` already emits a stopped state; for `success` the phase is ALTERNATE (via `with_hit`), for `human` it stays a warning with the browser left open.

## 5. Error Handling

- Every Selenium interaction in the 候补 path is wrapped; selector-not-found → `"failed"` (retry next loop) rather than a crash.
- Verification detected → `"human"` handoff, never a silent failure.
- Passenger mismatch → abort with an explicit log, no submission.
- All exceptions inside the worker are already caught by `_run_worker` / `_monitor_worker`.

## 6. Testing Strategy

Use the existing fake-Selenium harness in `tests/test_gui_logic.py`:

- `_find_hit_row`:
  - Sold-out row with a 候补 button + `auto_alternate=True` → returns an `"alternate"` tuple (specified-seat case).
  - 不限席别 + only a 候补 button → returns `"alternate"`.
  - 有票 present → returns `"book"` even if a 候补 button also somehow exists (priority).
  - `auto_alternate=False` → never returns `"alternate"`.
- `_try_alternate_order`:
  - Named passengers not fully matched → returns `"failed"`, no submit click.
  - Verification element present → returns `"human"` and calls the handoff callback.
  - Happy path (passengers matched, submit + confirm succeed) → returns `"success"` and calls `on_hit`.
- Bridge (`tests/test_railwatch_bridge.py`): `_handle_human_action` emits a `humanAction` event and a non-error state.
- Renderer (`src/store` / `src/App` as applicable): `humanAction` type wired; store/types compile; a light App/store test if practical.

## 7. Files to Change

- `gui_12306_0.py`: `_find_hit_row` rewrite; `_try_alternate_order` tri-state + verification detection + auto-confirm; `_run_single_loop` integration; `TicketMonitor.__init__` add `human_action_callback`; trim sleeps; add a verification-detection helper.
- `railwatch_bridge.py`: add `_handle_human_action`; pass `human_action_callback` into `TicketMonitor`.
- `src/types.ts`: `HumanActionPayload` + `BridgeEvent` branch.
- `src/App.tsx`: handle `humanAction` (warning notification).
- Tests: `tests/test_gui_logic.py`, `tests/test_railwatch_bridge.py`, and renderer tests as needed.

## 8. Success Criteria

- With `auto_alternate` on and a target train that is sold out but 候补-able, the monitor submits a 候补 order automatically through the 确认候补 dialog, then stops and notifies — verified by tests for the decision/submit logic and by a manual run.
- If 12306 demands 人脸核验/验证码/滑块, the app stops, keeps the browser open, and shows a "需要人工操作" warning — verified by a test that injects a verification element.
- Named-passenger safety: a mismatch aborts submission — verified by test.
- `有票优先` preserved — verified by test.
- All existing Python + renderer + Electron tests stay green; typecheck clean.

## 9. Risks / Open Notes

- **Selector drift:** 12306 changes DOM frequently; mitigated by multi-selector fallbacks and `"failed"`-retry semantics, but real-world selectors must be validated during implementation/manual testing. The plan should keep selectors centralized for easy updates.
- **First-time 候补 face verification:** the very first 候补 for an account requires 人脸核验; this always lands in the `"human"` handoff path by design (cannot be automated, by policy).
- **No live 12306 in CI:** correctness is covered by fake-Selenium unit tests + a manual smoke checklist; the page-interaction details (exact button/text) are validated manually.
