# RailWatch 12306 Release Checklist

Use this checklist before publishing a source release or packaged desktop build.

## Source Hygiene

- No `build/`, `dist/`, `__pycache__/` or `.pytest_cache/` directories.
- No `chrome_profile_12306/`, cookies, sessions, local configs, logs or exported event logs.
- No downloaded `chromedriver.exe` in the repository.
- README, CHANGELOG, LICENSE, CONTRIBUTING, SECURITY and PRIVACY are current.

## Verification

```bash
python -m unittest discover -s tests -p "test_*.py"
python -m py_compile railwatch_state.py railwatch_ui.py t12306_gui_0.py gui_12306_0.py anti_detect.py
```

Before publishing from GitHub, confirm the `CI` workflow is green on the target commit.

Run a UI smoke test:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -c "from PySide6.QtWidgets import QApplication; from railwatch_ui import RailWatchMainWindow; app=QApplication([]); w=RailWatchMainWindow(); assert w.windowTitle() == 'RailWatch 12306'; assert w.pages.count() == 4; w.close()"
```

## Packaging

```bat
package.bat
```

GitHub releases can also use the manual `Package Windows` workflow.

Expected output:

```text
dist\RailWatch 12306\RailWatch 12306.exe
```

If `chromedriver.exe` is present locally, the build script bundles it. Otherwise, users must install ChromeDriver separately or keep it on `PATH`.

## Manual QA

- Start the app and verify all four pages switch correctly.
- Run environment check.
- Open 12306 login page.
- Confirm dangerous actions show confirmation dialogs.
- Confirm event log filtering and export work.
- Confirm packaged executable starts on a clean machine with dependencies bundled by PyInstaller.
