# RailWatch 12306 Release Checklist

Use this checklist before publishing a source release or packaged Electron build.

## Source Hygiene

- No `build/`, `dist/`, `dist-electron/`, `dist-runtime/`, `release/`, `__pycache__/` or `.pytest_cache/` directories.
- No `chrome_profile_12306/`, cookies, sessions, local configs, logs, exported event logs or station caches.
- No downloaded `chromedriver.exe` or `chromedriver` in the repository.
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
.\package-windows.cmd 0.6.0
```

Use `.\package-windows.cmd 0.6.0 --install-deps` only when Node or Python packaging dependencies need to be reinstalled. On a Mac, `./package-macos.sh 0.6.0` builds the ad-hoc signed DMG and ZIP for that Mac's architecture.

## Publishing

Bump `package.json`, `package-lock.json` and `pyproject.toml` to the same version, add `docs/releases/v<version>.md`, and confirm the `CI` workflow is green on the target commit. Pushing the `v<version>` tag runs [`Package Release`](../.github/workflows/package-release.yml): Windows, macOS arm64 and macOS x64 build in parallel, each verifies and smokes its final package, and a single publish job creates or updates the Release. The workflow refuses branches and tags whose version does not match `package.json` and `pyproject.toml`.

A complete release contains assets from one run only:

- Windows: `RailWatch-12306-<version>-x64.exe`, its `.blockmap`, `latest.yml`
- macOS: `RailWatch-12306-<version>-arm64.dmg`, `-arm64.zip`, `-x64.dmg`, `-x64.zip`, their `.blockmap` files, and `latest-mac.yml` merged from both architectures

If a macOS build fails, re-run the failed job first. If it keeps failing, run `Package Release` manually on the same tag with `platforms=windows` (or `macos` to add the other platform later). Single-platform runs keep the other platform's assets, never change the "latest" marker of an existing Release, and a new single-platform latest Release makes the other platform's clients show "最新版本暂未提供本平台安装包" until its assets are added. On first adoption of the workflow, run `all`, `windows` and `macos` once each and keep the job results and asset lists.

## Packaged App Smoke

- Run `python -X utf8 tests/packaged_smoke.py` with matching ChromeDriver installed for the browser fixture suite.
- macOS CI runs `tests/runtime_order_smoke.py --exe <runtime inside the .app>` and `tests/packaged_smoke.py --exe "<app>/Contents/MacOS/RailWatch 12306"` after `scripts/keychain_probe.py` confirms the temporary default keychain. Run them locally only with a temporary default keychain; the runtime smoke writes and deletes the `notification-secrets` keychain item.
- Start `release/win-unpacked/RailWatch 12306.exe`.
- Confirm the Electron window loads `RailWatch 12306`.
- Confirm the renderer shows five functional pages: `Dashboard`, `Trip Setup`, `Monitor`, `Order Center`, `Settings`, plus `About`.
- Confirm the Python runtime process starts and exits with the app.
- Confirm no `RailWatch 12306.exe` or `railwatch_runtime.exe` processes remain after exit.

## Manual QA

Run the checks in [release-qa.md](release-qa.md) before publishing an installer.

For v0.5.0, complete [rehearsal validation](v0.5.0-validation.md): a valid logged-in read-only run, cancellation while querying, unchanged transaction counts, and an isolated packaged-runtime rehearsal. Do not treat fixture success as confirmation of a current official session or official transaction DOM. Run `scripts/validate_rehearsal_live.py` only while the desktop task is idle; it attaches a dedicated tab and uses a temporary journal, then restores the original tab.
