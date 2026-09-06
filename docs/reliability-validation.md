# Reliability implementation validation — 2026-09-06

## Implemented behavior

- Fixed target timestamp, bounded login checks, verified form filling and allowlisted query dialogs.
- Per-run ownership, cancellation at the Selenium command boundary, heartbeat protection and terminal state publication after thread exit.
- Sequenced state events reject delayed start responses and retired task events.
- Page-visible query transactions reject unchanged old rows, invalidated conditions and results from a previous page; confirmed empty results are valid.
- Beijing calendar validation filters execution ranges; active tasks retain their original configuration snapshot.
- Accurate station labels, backend countdowns, bounded log buffers and variable-height virtual event lists.

## Results

| Check | Result |
| --- | --- |
| Python unittest discovery | 119 passed |
| Electron Vitest | 30 passed |
| Renderer Vitest | 73 passed |
| Isolated real Chrome fixture suite | 10 passed |
| Date/store tests with `TZ=America/Los_Angeles` | 9 passed (subset of renderer tests) |
| TypeScript checks and production build | Passed |
| PyInstaller + electron-builder Windows NSIS package | Passed |
| Packaged Electron/preload/runtime smoke | Passed |
| Git whitespace check | Passed |

The packaged smoke uses temporary APPDATA/LOCALAPPDATA, checks the four navigation pages, preload commands, legacy configuration save/load, backend date policy, task metadata, stop command, and enabling start for a valid trip without prior query results. It closes the app and leaves no RailWatch/runtime processes. The screenshot was visually inspected; logs and screenshots remain ignored under `build/qa/`.

Artifacts are generated under `release/`, including `RailWatch-12306-0.2.3-x64.exe`. This is a local validation build; no release was published and no update/version migration was performed.

## Remaining release validation

Authenticated 12306 login, live ticket queries and candidate-order behavior require the maintainer's manual release QA. The automated Chrome tests use only local HTML and an isolated profile, and block 12306 network requests. They do not submit real orders or exercise the user's saved browser session.

The DOM observer intentionally treats unrecognized page changes as incomplete queries. Future 12306 page changes may require selector/fixture updates before live release validation passes.
