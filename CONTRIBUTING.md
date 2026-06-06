# Contributing to RailWatch 12306

Thanks for helping improve RailWatch 12306. This project is a desktop companion for personal 12306 trip monitoring, so contributions should stay practical, respectful of the official service, and protective of user privacy.

## Development Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m unittest discover -s tests -p "test_*.py"
```

Run the app:

```bash
python t12306_gui_0.py
```

ChromeDriver is optional in the repository. If you need a local driver, download the version matching your Chrome browser and place `chromedriver.exe` in the project root or the RailWatch user data directory.

## Contribution Rules

- Keep UI code in `railwatch_ui.py` and UI state in `railwatch_state.py`.
- Keep Selenium query and monitoring behavior in `gui_12306_0.py`.
- Do not commit logs, Chrome profiles, cookies, user configs, station caches, build output, or downloaded driver binaries.
- New automation behavior must be disabled by default and require clear user confirmation.
- Add focused tests when changing state transitions, parsing, monitor matching, config persistence, or safety behavior.

## Pull Request Checklist

- Tests pass with `python -m unittest discover -s tests -p "test_*.py"`.
- Python files compile with `python -m py_compile railwatch_state.py railwatch_ui.py t12306_gui_0.py gui_12306_0.py anti_detect.py`.
- README and docs are updated when behavior or setup changes.
- No personal data, cookies, profiles, local configs, or generated artifacts are included.

## Project Boundaries

RailWatch does not bypass login verification, does not crack captchas, and does not call private 12306 APIs. Keep the project aligned with user-controlled browser automation and local-only data storage.
