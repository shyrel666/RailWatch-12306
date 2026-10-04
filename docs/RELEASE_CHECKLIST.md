# RailWatch 12306 Release Checklist

Use this checklist before publishing a source release or packaged Electron build.

## Source Hygiene

- No `build/`, `dist/`, `dist-electron/`, `dist-runtime/`, `release/`, `__pycache__/` or `.pytest_cache/` directories.
- No `chrome_profile_12306/`, cookies, sessions, local configs, logs, exported event logs or station caches.
- No downloaded `chromedriver.exe` in the repository.
- README, CHANGELOG, LICENSE, CONTRIBUTING, SECURITY, PRIVACY and `docs/release-qa.md` are current.

## Automated Verification

```bash
python -X utf8 -m unittest discover -s tests -p "test_*.py"
python -m py_compile railwatch_state.py gui_12306_0.py anti_detect.py chromedriver_manager.py railwatch_preferences.py railwatch_bridge.py railwatch_runtime.py
npm run test
npm run build
python -X utf8 tests/browser_smoke.py
python -X utf8 tests/order_browser_smoke.py
python -X utf8 tests/passenger_book_browser_smoke.py
python -X utf8 tests/rehearsal_browser_smoke.py
python -X utf8 tests/rehearsal_ui_smoke.py
python -X utf8 tests/query_ui_smoke.py
python -X utf8 tests/notification_ui_smoke.py
python -X utf8 tests/trip_order_ui_smoke.py
.\package-windows.cmd 0.5.5
```

Use `.\package-windows.cmd 0.5.5 --install-deps` only when Node or Python packaging dependencies need to be reinstalled. Before publishing from GitHub, confirm the `CI` workflow is green on the target commit. For Windows packages, also run the manual `Package Windows` workflow.

Upload only matching assets from the same build to the GitHub Release:

- `release/*.exe`
- `release/*.blockmap`
- `release/latest.yml`

## Packaged App Smoke

- Run `python -X utf8 tests/packaged_smoke.py` with matching ChromeDriver installed for the browser fixture suite.
- Start `release/win-unpacked/RailWatch 12306.exe`.
- Confirm the Electron window loads `RailWatch 12306`.
- Confirm the renderer shows five functional pages: `Dashboard`, `Trip Setup`, `Monitor`, `Order Center`, `Settings`, plus `About`.
- Confirm the Python runtime process starts and exits with the app.
- Confirm no `RailWatch 12306.exe` or `railwatch_runtime.exe` processes remain after exit.

## Manual QA

Run the checks in [release-qa.md](release-qa.md) before publishing an installer.

For v0.5.0, complete [rehearsal validation](v0.5.0-validation.md): a valid logged-in read-only run, cancellation while querying, unchanged transaction counts, and an isolated packaged-runtime rehearsal. Do not treat fixture success as confirmation of a current official session or official transaction DOM. Run `scripts/validate_rehearsal_live.py` only while the desktop task is idle; it attaches a dedicated tab and uses a temporary journal, then restores the original tab.
