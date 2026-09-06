# Changelog

## 0.1.0 - Unreleased

### Added

- Added the Electron + React/Vite desktop shell.
- Added the JSON Lines Python runtime used by Electron.
- Added `RailWatchBridge` as the frontend-neutral command facade for runtime info, config, environment checks, login, query analysis, monitoring, logging and preferences.
- Added renderer state management and component tests for navigation, trip setup and monitor controls.
- Added Windows Electron packaging with `electron-builder` and PyInstaller runtime bundling.
- Added open-source GitHub docs, issue templates, PR template, CI workflow and release QA checklist.

### Changed

- Repositioned Python code as runtime/core support for the Electron app.
- Updated source hygiene rules to keep runtime data, logs, Chrome profiles, downloaded drivers and build output out of Git.
- Updated Vite build splitting for stable React, icon and vendor chunks.
- Timed (定时抢票) monitoring now creates the browser before the wait, keeps the query page prewarmed with from/to/date synced from the config during the prewarm window, and no longer depends on the browser restoring the previous query.
- Only allowlisted not-on-sale dialogs use short retries; unknown failures retain configured query timeouts and adaptive backoff. Login, verification, order and unknown blocking dialogs require human action.
- Non-timed monitoring opens the query page and syncs query params from the saved config on start, instead of relying on whatever page the browser was left on.
- Session keep-alive reads the result within the current bounded asynchronous call. Expiry or three inconclusive probes stop the task and require manual restart.
- Environment checks and browser startup now detect when the local ChromeDriver major version no longer matches the installed Chrome (Chrome auto-updates itself) and automatically download a matching ChromeDriver into the data directory before failing, so "检查环境" self-heals instead of reporting a session-not-created error.
- The `dev` and `electron` npm scripts now clear `NODE_OPTIONS` before launching Electron, so machines with a global `NODE_OPTIONS=--openssl-legacy-provider` (a common legacy-webpack workaround that Electron's bundled Node rejects with exit code 9) can still run the dev shell.

### Reliability improvements

- Freeze timed task targets before browser initialization, including midnight boundaries and late starts.
- Add per-run cancellation, browser ownership and sequenced status events; block restart until the previous worker exits.
- Share query transactions between analysis and monitoring, validate form fields, reject stale results and accept confirmed empty results.
- Validate calendar dates and filter execution ranges in Beijing time using a backend-provided presale policy.
- Display actual stations and the running configuration snapshot; drive countdowns from backend deadlines.
- Bound frontend log buffers and render variable-height event rows with virtualization.
- Add fault-combination unit tests, isolated Chrome page fixtures and packaged Electron smoke checks.
