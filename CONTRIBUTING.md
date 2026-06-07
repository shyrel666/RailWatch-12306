# Contributing To RailWatch 12306

Thanks for helping improve RailWatch 12306. The project is an Electron desktop app with an embedded Python Selenium runtime, so contributions should protect user privacy, keep automation user-controlled, and avoid unnecessary coupling between the frontend and the 12306 page automation core.

## Development Setup

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
npm install
```

Run the app:

```bash
npm run dev
```

## Project Boundaries

- React renderer code lives under `src/`.
- Electron main, preload and Python runtime client code lives under `electron/`.
- Python runtime command handling lives in `railwatch_runtime.py` and `railwatch_bridge.py`.
- Selenium query and monitor logic stays in `gui_12306_0.py` and supporting Python modules.
- Local preferences belong in `railwatch_preferences.py`; do not add desktop UI framework dependencies to Python runtime modules.

## Rules For Contributions

- Do not commit logs, Chrome profiles, cookies, user configs, station caches, build output, release artifacts or downloaded driver binaries.
- New automation behavior must be disabled by default and require explicit user confirmation.
- Do not bypass 12306 login, captcha, order confirmation, payment, website rules or service rate limits.
- Keep UI changes accessible and predictable for long-running monitoring workflows.
- Add focused tests when changing state transitions, config validation, runtime protocol behavior, monitor matching, parsing or safety behavior.

## Verification

Run the relevant checks before opening a pull request:

```bash
python -m unittest discover -s tests -p "test_*.py"
python -m py_compile railwatch_state.py gui_12306_0.py anti_detect.py chromedriver_manager.py railwatch_preferences.py railwatch_bridge.py railwatch_runtime.py
npm run test
npm run build
```

If packaging changed, also run:

```bash
npm run package
```

## Pull Request Checklist

- Tests and build commands pass locally.
- README and docs are updated when setup, behavior, packaging or safety boundaries change.
- No personal data, cookies, Chrome profiles, local configs or generated artifacts are included.
- Dangerous actions remain opt-in and confirmation-gated.
- The change is scoped to the relevant layer and does not mix unrelated refactors.
