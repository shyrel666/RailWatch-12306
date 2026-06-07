# RailWatch 12306 Release Checklist

Use this checklist before publishing a source release or packaged Electron build.

## Source Hygiene

- No `build/`, `dist/`, `dist-electron/`, `dist-runtime/`, `release/`, `__pycache__/` or `.pytest_cache/` directories.
- No `chrome_profile_12306/`, cookies, sessions, local configs, logs, exported event logs or station caches.
- No downloaded `chromedriver.exe` in the repository.
- README, CHANGELOG, LICENSE, CONTRIBUTING, SECURITY, PRIVACY and `docs/release-qa.md` are current.

## Automated Verification

```bash
python -m unittest discover -s tests -p "test_*.py"
python -m py_compile railwatch_state.py gui_12306_0.py anti_detect.py chromedriver_manager.py railwatch_preferences.py railwatch_bridge.py railwatch_runtime.py
npm run test
npm run build
npm run package
```

Before publishing from GitHub, confirm the `CI` workflow is green on the target commit. For Windows packages, also run the manual `Package Windows` workflow.

## Packaged App Smoke

- Start `release/win-unpacked/RailWatch 12306.exe`.
- Confirm the Electron window loads `RailWatch 12306`.
- Confirm the renderer shows the four pages: `Dashboard`, `Trip Setup`, `Monitor`, `Settings`.
- Confirm the Python runtime process starts and exits with the app.
- Confirm no `RailWatch 12306.exe` or `railwatch_runtime.exe` processes remain after exit.

## Manual QA

Run the checks in [release-qa.md](release-qa.md) before publishing an installer.
