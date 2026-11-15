# Contributing To RailWatch 12306

Thanks for helping improve RailWatch 12306. The project is an Electron desktop app with an embedded Python Selenium runtime, so contributions should protect user privacy, keep automation user-controlled, and avoid unnecessary coupling between the frontend and the 12306 page automation core.

## Development Setup

Use the Python version in `.python-version` and the Node.js major in `.nvmrc`; CI and release builds read the same two files. Create the virtual environment with that Python (for example `py -3.14 -m venv .venv` on Windows):

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --require-hashes -r requirements.lock
npm install
```

Run the app:

```bash
npm run dev
```

## Toolchain Versions And Dependencies

- `.python-version` is the only place the Python version is written. CI, release builds and `RailWatch_runtime.spec` read it, and the spec refuses to build with any other version. Move it once a year, in November, to the version released the previous October, so installers always ship a Python that still gets binary releases.
- `.nvmrc` holds the Node.js major bundled with the pinned Electron release. Change it and `@types/node` together with an Electron upgrade.
- `requirements.txt` (runtime) and `requirements-build.txt` (packaging tools) list direct dependencies only. Every environment installs `requirements.lock`, which pins all packages with hashes. After editing either file or `.python-version`, regenerate it and commit the result:

  ```bash
  uv pip compile requirements-build.txt --universal --generate-hashes --python-version 3.14 --output-file requirements.lock
  ```

- `npm run build:runtime` freezes the runtime from `build/python-venv`, which it creates from `requirements.lock`. Do not run PyInstaller from a shared Python environment: it bundles whatever that environment can import.

## Project Boundaries

- React renderer code lives under `src/`.
- Electron main, preload and Python runtime client code lives under `electron/`.
- Python runtime command handling lives in `railwatch_runtime.py` and `railwatch_bridge.py`.
- Selenium query and monitor logic stays in `gui_12306_0.py` and supporting Python modules.
- Local preferences belong in `railwatch_preferences.py`; do not add desktop UI framework dependencies to Python runtime modules.

## Rules For Contributions

- Do not commit logs, Chrome profiles, cookies, user configs, station caches, build output, release artifacts or downloaded driver binaries.
- Keep test/acceptance reports, implementation plans and historical version documents and screenshots local. Test code and fixtures remain part of the repository.
- Under `docs/`, commit only the current version's release notes and four README screenshots allowed by `.gitignore`. When preparing a release, update that allowlist, untrack the previous version's files with `git rm --cached`, and refresh the README images. Do not add a documentation section to the README.
- Release notes and new changelog entries describe only added features and bug fixes. Omit frontend layout/style changes, download or installation instructions, validation reports and other commentary.
- New automation behavior must be disabled by default and require explicit user confirmation.
- Do not bypass 12306 login, captcha, order confirmation, payment, website rules or service rate limits.
- Keep UI changes accessible and predictable for long-running monitoring workflows.
- Add focused tests when changing state transitions, config validation, runtime protocol behavior, monitor matching, parsing or safety behavior.
- A test module whose `RailWatchBridge` saves notification settings or clears local data sets `setUpModule = isolate_system_keychain` (from `scripts/keychain_isolation.py`). On macOS a bridge without a secret store would otherwise use your own login keychain; the test suite refuses that and fails instead.

## Verification

Run the relevant checks before opening a pull request:

```bash
python -m unittest discover -s tests -p "test_*.py"
python -m compileall -q -l . railwatch_policies
npm run test
npm run build
```

If packaging changed, also run the build and both smoke tests. `--non-ascii-profile` repeats a smoke with the data, and on Windows a copy of the app, under a Chinese-named folder with a space, the way a per-user install sits under `C:\Users\<account>`:

```bash
npm run package
python -X utf8 tests/runtime_order_smoke.py --non-ascii-profile
python -X utf8 tests/packaged_smoke.py --non-ascii-profile
```

## Pull Request Checklist

- Tests and build commands pass locally.
- README and current release notes reflect relevant user-facing changes and follow the documentation rules above.
- No personal data, cookies, Chrome profiles, local configs or generated artifacts are included.
- Dangerous actions remain opt-in and confirmation-gated.
- The change is scoped to the relevant layer and does not mix unrelated refactors.
