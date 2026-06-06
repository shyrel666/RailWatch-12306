## Summary

- 

## Verification

- [ ] `python -m unittest discover -s tests -p "test_*.py"`
- [ ] `python -m py_compile railwatch_state.py railwatch_ui.py t12306_gui_0.py gui_12306_0.py anti_detect.py`
- [ ] UI smoke test, if UI behavior changed

## Safety and Privacy

- [ ] No cookies, sessions, Chrome profiles, logs, local configs, build output or downloaded drivers are included.
- [ ] New automation behavior is disabled by default and requires confirmation.
