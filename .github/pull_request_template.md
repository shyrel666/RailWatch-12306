## Summary

-

## Verification

- [ ] `python -m unittest discover -s tests -p "test_*.py"`
- [ ] `python -m py_compile railwatch_state.py gui_12306_0.py anti_detect.py chromedriver_manager.py railwatch_preferences.py railwatch_bridge.py railwatch_runtime.py`
- [ ] `npm run test`
- [ ] `npm run build`
- [ ] `npm run package`, if packaging changed

## Safety And Privacy

- [ ] No cookies, sessions, Chrome profiles, logs, local configs, build output or downloaded drivers are included.
- [ ] New automation behavior is disabled by default and requires explicit confirmation.
- [ ] The change does not bypass 12306 login, captcha, order confirmation or payment flows.
