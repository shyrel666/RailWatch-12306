# RailWatch Anti-Detect Risk Control Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the current "anti-detect" implementation into a truthful, stable, testable, compliance-oriented risk-control layer for low-frequency official-page monitoring.

**Architecture:** Keep Selenium usage inside `railwatch_bridge.py`, `gui_12306_0.py`, and `anti_detect.py`. Do not add captcha bypass, login bypass, payment automation, proxy rotation, or hidden service-rule evasion. Fix only reliability, upgrade stability, optional-browser-API safety, honest documentation, and observable session consistency warnings.

**Tech Stack:** Python 3, Selenium, `undetected-chromedriver`, `pytest`/`unittest`, Electron runtime bridge.

---

## Non-Goals

- Do not implement 12306 captcha bypass, login bypass, payment automation, proxy/IP rotation, or private API scraping.
- Do not claim "bypass", ">95% success", "TLS fingerprint optimization", or "high-peak anti-risk guarantee" without evidence.
- Do not silently mutate 12306 cookies to restore identity. For this app, device-id handling is observation and warning only.

## File Structure

- Modify `anti_detect.py`
  - Add backward-compatible `DeviceProfile.from_dict()`.
  - Extract script generation into `_build_anti_detect_script(profile)`.
  - Guard optional browser APIs in injected JS.
  - Reframe `RailDeviceIdProtector` as a consistency tracker that logs mismatches instead of silently restoring cookies.
  - Rewrite module header to accurately describe risk-control scope.
- Modify `railwatch_bridge.py`
  - Record the device id after verified login.
  - Check device-id consistency during keep-alive or monitoring preparation and log a warning if it changes.
  - Keep fallback Selenium injection, but make it testable.
- Create `tests/test_anti_detect.py`
  - Cover legacy profile migration, deterministic seeds, optional API guards, docstring claims, and device-id consistency behavior.
- Modify `tests/test_railwatch_bridge.py`
  - Cover login-time device-id recording.
  - Cover keep-alive consistency checks.
  - Cover fallback basic script injection.

---

### Task 1: Preserve Existing Device Profiles During Upgrade

**Files:**
- Modify: `anti_detect.py:99-210`
- Create: `tests/test_anti_detect.py`

- [ ] **Step 1: Write failing migration tests**

Create `tests/test_anti_detect.py` with:

```python
import json

from anti_detect import AntiDetect, DeviceProfile


def test_legacy_device_profile_is_migrated_without_regeneration(tmp_path):
    legacy = DeviceProfile.generate_random().to_dict()
    original_user_agent = legacy["user_agent"]
    original_screen_width = legacy["screen_width"]
    legacy.pop("canvas_noise_seed")
    legacy.pop("audio_noise_seed")
    profile_path = tmp_path / "device_profile.json"
    profile_path.write_text(json.dumps(legacy), encoding="utf-8")

    logs = []
    profile = AntiDetect(str(tmp_path), log_callback=logs.append).get_or_create_profile()

    assert profile.user_agent == original_user_agent
    assert profile.screen_width == original_screen_width
    assert isinstance(profile.canvas_noise_seed, int)
    assert isinstance(profile.audio_noise_seed, int)
    saved = json.loads(profile_path.read_text(encoding="utf-8"))
    assert saved["user_agent"] == original_user_agent
    assert "canvas_noise_seed" in saved
    assert "audio_noise_seed" in saved
    assert not any("重新生成" in message for message in logs)


def test_device_profile_from_dict_seeds_are_stable_for_same_legacy_profile():
    legacy = DeviceProfile.generate_random().to_dict()
    legacy.pop("canvas_noise_seed")
    legacy.pop("audio_noise_seed")

    first = DeviceProfile.from_dict(legacy)
    second = DeviceProfile.from_dict(legacy)

    assert first.canvas_noise_seed == second.canvas_noise_seed
    assert first.audio_noise_seed == second.audio_noise_seed
```

- [ ] **Step 2: Run tests and verify they fail for the expected reason**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_anti_detect.py -q
```

Expected: fail because `DeviceProfile.from_dict` is missing and legacy profiles are regenerated.

- [ ] **Step 3: Add backward-compatible profile loading**

In `anti_detect.py`, add `Dict` to the typing import:

```python
from typing import Optional, Callable, Tuple, List, Dict
```

Inside `DeviceProfile`, after `to_dict()`, add:

```python
    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "DeviceProfile":
        normalized = dict(data)
        normalized.setdefault("canvas_noise_seed", cls._stable_seed(normalized, "canvas"))
        normalized.setdefault("audio_noise_seed", cls._stable_seed(normalized, "audio"))
        return cls(**normalized)

    @staticmethod
    def _stable_seed(data: Dict[str, object], salt: str) -> int:
        stable = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
        digest = hashlib.sha256(f"{salt}:{stable}".encode("utf-8")).hexdigest()
        return 100000 + (int(digest[:12], 16) % 900000)
```

In `AntiDetect.get_or_create_profile()`, replace:

```python
self.device_profile = DeviceProfile(**data)
self.log("📱 已加载设备指纹配置")
return self.device_profile
```

with:

```python
self.device_profile = DeviceProfile.from_dict(data)
if self.device_profile.to_dict() != data:
    with open(self.profile_path, "w", encoding="utf-8") as f:
        json.dump(self.device_profile.to_dict(), f, ensure_ascii=False, indent=2)
    self.log("📱 已迁移设备指纹配置")
else:
    self.log("📱 已加载设备指纹配置")
return self.device_profile
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_anti_detect.py -q
```

Expected: pass.

---

### Task 2: Make Anti-Detect Script Generation Testable And Optional-API Safe

**Files:**
- Modify: `anti_detect.py:366-715`
- Test: `tests/test_anti_detect.py`

- [ ] **Step 1: Write failing script-safety tests**

Append to `tests/test_anti_detect.py`:

```python
def test_anti_detect_script_guards_optional_browser_apis(tmp_path):
    anti_detect = AntiDetect(str(tmp_path), log_callback=lambda message: None)
    profile = DeviceProfile.generate_random()

    script = anti_detect._build_anti_detect_script(profile)

    assert "const _mediaEnumerateDevices = navigator.mediaDevices && navigator.mediaDevices.enumerateDevices;" in script
    assert "if (_mediaEnumerateDevices) {" in script
    assert "typeof WebGLRenderingContext !== 'undefined'" in script
    assert "typeof AudioBuffer !== 'undefined'" in script
    assert ".filter(fn => typeof fn === 'function')" in script


def test_inject_anti_detect_scripts_uses_cdp_source(tmp_path):
    class FakeDriver:
        def __init__(self):
            self.commands = []

        def execute_cdp_cmd(self, command, payload):
            self.commands.append((command, payload))

    driver = FakeDriver()
    anti_detect = AntiDetect(str(tmp_path), log_callback=lambda message: None)
    anti_detect.inject_anti_detect_scripts(driver)

    command, payload = driver.commands[0]
    assert command == "Page.addScriptToEvaluateOnNewDocument"
    assert "navigator" in payload["source"]
    assert "webdriver" in payload["source"]
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_anti_detect.py -q
```

Expected: fail because `_build_anti_detect_script` does not exist and current JS does not guard all optional APIs.

- [ ] **Step 3: Extract script builder**

In `anti_detect.py`, change `inject_anti_detect_scripts()` to:

```python
    def inject_anti_detect_scripts(self, driver):
        """注入浏览器环境稳定性脚本。"""
        profile = self.device_profile or self.get_or_create_profile()
        anti_detect_js = self._build_anti_detect_script(profile)

        try:
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": anti_detect_js
            })
            self.log("✅ 浏览器环境脚本注入成功（CDP 模式）")
        except Exception:
            try:
                driver.execute_script(anti_detect_js)
                self.log("✅ 浏览器环境脚本注入成功（直接执行）")
            except Exception as exc:
                self.log(f"⚠️ 浏览器环境脚本注入失败: {exc}")
```

Add this method immediately above it:

```python
    def _build_anti_detect_script(self, profile: DeviceProfile) -> str:
        """Build the browser environment stabilization script for a profile."""
        return f"""
        Object.defineProperty(navigator, 'webdriver', {{
            get: () => undefined,
            configurable: true
        }});
        delete navigator.__proto__.webdriver;

        Object.defineProperty(navigator, 'languages', {{
            get: () => {json.dumps(profile.languages)},
        }});
        Object.defineProperty(navigator, 'platform', {{
            get: () => '{profile.platform}',
        }});
        Object.defineProperty(navigator, 'hardwareConcurrency', {{
            get: () => {profile.hardware_concurrency},
        }});
        Object.defineProperty(navigator, 'deviceMemory', {{
            get: () => {profile.device_memory},
        }});
        Object.defineProperty(screen, 'width', {{ get: () => {profile.screen_width} }});
        Object.defineProperty(screen, 'height', {{ get: () => {profile.screen_height} }});
        Object.defineProperty(screen, 'availWidth', {{ get: () => {profile.screen_width} }});
        Object.defineProperty(screen, 'availHeight', {{ get: () => {profile.screen_height - 40} }});
        Object.defineProperty(screen, 'colorDepth', {{ get: () => {profile.color_depth} }});
        Object.defineProperty(screen, 'pixelDepth', {{ get: () => {profile.color_depth} }});
        Object.defineProperty(window, 'devicePixelRatio', {{ get: () => {profile.pixel_ratio} }});

        const originalDateTimeFormat = Intl.DateTimeFormat;
        Intl.DateTimeFormat = function(locale, options) {{
            options = options || {{}};
            options.timeZone = options.timeZone || '{profile.timezone}';
            return new originalDateTimeFormat(locale, options);
        }};
        Intl.DateTimeFormat.prototype = originalDateTimeFormat.prototype;

        const _canvasSeed = {profile.canvas_noise_seed};
        const _canvasNoiseMag = {profile.canvas_noise};
        function _stablePRNG(seed) {{
            let s = seed;
            return function() {{
                s = (s * 1103515245 + 12345) & 0x7fffffff;
                return (s / 0x7fffffff) * 2 - 1;
            }};
        }}
        const _canvasNoiseCache = new WeakMap();
        const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function(type) {{
            if ((type === 'image/png' || type === undefined) && !_canvasNoiseCache.has(this)) {{
                const context = this.getContext('2d');
                if (context) {{
                    const imageData = context.getImageData(0, 0, this.width, this.height);
                    const data = imageData.data;
                    const rng = _stablePRNG(_canvasSeed);
                    for (let i = 0; i < data.length; i += 4) {{
                        data[i] = Math.max(0, Math.min(255, data[i] + Math.floor(rng() * _canvasNoiseMag * 255)));
                        data[i + 1] = Math.max(0, Math.min(255, data[i + 1] + Math.floor(rng() * _canvasNoiseMag * 255)));
                        data[i + 2] = Math.max(0, Math.min(255, data[i + 2] + Math.floor(rng() * _canvasNoiseMag * 255)));
                    }}
                    context.putImageData(imageData, 0, 0);
                    _canvasNoiseCache.set(this, true);
                }}
            }}
            return originalToDataURL.apply(this, arguments);
        }};

        if (typeof WebGLRenderingContext !== 'undefined' && WebGLRenderingContext.prototype.getParameter) {{
            const getParameterOriginal = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {{
                if (parameter === 37445) return '{profile.webgl_vendor}';
                if (parameter === 37446) return '{profile.webgl_renderer}';
                return getParameterOriginal.apply(this, arguments);
            }};
        }}
        if (typeof WebGL2RenderingContext !== 'undefined' && WebGL2RenderingContext.prototype.getParameter) {{
            const getParameter2Original = WebGL2RenderingContext.prototype.getParameter;
            WebGL2RenderingContext.prototype.getParameter = function(parameter) {{
                if (parameter === 37445) return '{profile.webgl_vendor}';
                if (parameter === 37446) return '{profile.webgl_renderer}';
                return getParameter2Original.apply(this, arguments);
            }};
        }}

        if (typeof AudioBuffer !== 'undefined' && AudioBuffer.prototype.getChannelData) {{
            const _audioSeed = {profile.audio_noise_seed};
            const _audioNoiseCache = new WeakMap();
            const originalGetChannelData = AudioBuffer.prototype.getChannelData;
            AudioBuffer.prototype.getChannelData = function(channel) {{
                const data = originalGetChannelData.apply(this, arguments);
                if (!_audioNoiseCache.has(this)) {{
                    const rng = _stablePRNG(_audioSeed + channel);
                    for (let i = 0; i < data.length; i++) {{
                        data[i] = data[i] + (rng() * 0.00005);
                    }}
                    _audioNoiseCache.set(this, true);
                }}
                return data;
            }};
        }}

        window.chrome = window.chrome || {{}};
        window.chrome.runtime = window.chrome.runtime || {{}};
        window.chrome.loadTimes = window.chrome.loadTimes || function() {{}};
        window.chrome.csi = window.chrome.csi || function() {{}};
        window.chrome.app = window.chrome.app || {{}};

        delete window.__puppeteer_evaluation_script__;
        delete window.__playwright_evaluation_script__;
        delete window.__selenium_unwrapped;
        delete window.__webdriver_evaluate;
        delete window.__driver_evaluate;
        delete window.__webdriver_unwrapped;
        delete window.__driver_unwrapped;
        delete window.__fxdriver_evaluate;
        delete window.__fxdriver_unwrapped;

        const originalContentWindow = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'contentWindow');
        if (originalContentWindow && originalContentWindow.get) {{
            Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {{
                get: function() {{
                    const win = originalContentWindow.get.call(this);
                    if (win) {{
                        try {{
                            Object.defineProperty(win.navigator, 'webdriver', {{ get: () => undefined }});
                        }} catch (e) {{}}
                    }}
                    return win;
                }},
            }});
        }}

        const originalQuery = navigator.permissions && navigator.permissions.query;
        if (originalQuery) {{
            navigator.permissions.query = function(parameters) {{
                if (parameters.name === 'notifications') {{
                    return Promise.resolve({{ state: Notification.permission }});
                }}
                return originalQuery.apply(this, arguments);
            }};
        }}

        const originalGetTimezoneOffset = Date.prototype.getTimezoneOffset;
        Date.prototype.getTimezoneOffset = function() {{
            return -{profile.timezone_offset};
        }};

        const _mediaEnumerateDevices = navigator.mediaDevices && navigator.mediaDevices.enumerateDevices;
        if (_mediaEnumerateDevices) {{
            navigator.mediaDevices.enumerateDevices = function() {{
                return _mediaEnumerateDevices.apply(this, arguments).then(devices => {{
                    if (devices.length === 0) {{
                        return [
                            {{ deviceId: 'default', kind: 'audioinput', label: '', groupId: 'default' }},
                            {{ deviceId: 'default', kind: 'videoinput', label: '', groupId: 'default' }},
                            {{ deviceId: 'default', kind: 'audiooutput', label: '', groupId: 'default' }},
                        ];
                    }}
                    return devices;
                }});
            }};
        }}

        const _nativeFunctions = new Set([
            originalQuery && navigator.permissions.query,
            HTMLCanvasElement.prototype.toDataURL,
            typeof WebGLRenderingContext !== 'undefined' && WebGLRenderingContext.prototype.getParameter,
            typeof WebGL2RenderingContext !== 'undefined' && WebGL2RenderingContext.prototype.getParameter,
            typeof AudioBuffer !== 'undefined' && AudioBuffer.prototype.getChannelData,
            Date.prototype.getTimezoneOffset,
            navigator.getBattery,
            _mediaEnumerateDevices && navigator.mediaDevices.enumerateDevices,
        ].filter(fn => typeof fn === 'function'));
        const originalToString = Function.prototype.toString;
        Function.prototype.toString = function() {{
            if (_nativeFunctions.has(this)) {{
                return 'function ' + (this.name || '') + '() {{ [native code] }}';
            }}
            return originalToString.apply(this, arguments);
        }};
        console.log('[RailWatch] 浏览器环境脚本已注入');
        """
```

- [ ] **Step 4: Remove the old inline `anti_detect_js = f"""..."""` block**

Delete the old large inline script from `inject_anti_detect_scripts()` after confirming `_build_anti_detect_script()` contains the guarded replacement.

- [ ] **Step 5: Run tests and verify they pass**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_anti_detect.py -q
```

Expected: pass.

---

### Task 3: Make Device-ID Handling Observable, Not Silent Cookie Mutation

**Files:**
- Modify: `anti_detect.py:805-858`
- Modify: `railwatch_bridge.py:373-389, 543-550`
- Test: `tests/test_anti_detect.py`
- Test: `tests/test_railwatch_bridge.py`

- [ ] **Step 1: Write failing device-id tracker tests**

Append to `tests/test_anti_detect.py`:

```python
def test_device_id_tracker_reports_consistent_cookie():
    class FakeDriver:
        def get_cookies(self):
            return [{"name": "RAIL_DEVICEID", "value": "abc"}]

    logs = []
    tracker = RailDeviceIdProtector(FakeDriver(), log_callback=logs.append)
    tracker.save_device_id()

    assert tracker.check_consistency() is True
    assert logs[0].startswith("💾 已记录 RAIL_DEVICEID")


def test_device_id_tracker_warns_on_cookie_change_without_restoring():
    class FakeDriver:
        def __init__(self):
            self.cookies = [{"name": "RAIL_DEVICEID", "value": "abc"}]
            self.add_cookie_calls = []

        def get_cookies(self):
            return self.cookies

        def add_cookie(self, cookie):
            self.add_cookie_calls.append(cookie)

    driver = FakeDriver()
    logs = []
    tracker = RailDeviceIdProtector(driver, log_callback=logs.append)
    tracker.save_device_id()
    driver.cookies = [{"name": "RAIL_DEVICEID", "value": "changed"}]

    assert tracker.check_consistency() is False
    assert driver.add_cookie_calls == []
    assert any("变化" in message for message in logs)
```

Add this import at the top of `tests/test_anti_detect.py`:

```python
from anti_detect import AntiDetect, DeviceProfile, RailDeviceIdProtector
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_anti_detect.py -q
```

Expected: fail because `check_consistency()` does not exist and current behavior can restore cookies.

- [ ] **Step 3: Implement consistency-only device-id tracking**

In `anti_detect.py`, update the `RailDeviceIdProtector` class docstring to:

```python
    """
    RAIL_DEVICEID consistency tracker.

    This app does not silently restore or rewrite 12306 cookies. It records the
    device id observed after user login and warns if the official page changes
    or clears it during a session.
    """
```

Replace `save_device_id()` with:

```python
    def save_device_id(self) -> bool:
        """Record the current RAIL_DEVICEID after a verified user login."""
        device_id = self.get_current_device_id()
        if not device_id:
            self.log("⚠️ 未检测到 RAIL_DEVICEID。")
            return False
        self.saved_device_id = device_id
        self.log(f"💾 已记录 RAIL_DEVICEID: {device_id[:20]}...")
        return True
```

Add this method:

```python
    def check_consistency(self) -> bool:
        """Return False if the observed device id changed after being recorded."""
        if not self.saved_device_id:
            return True
        current_id = self.get_current_device_id()
        if not current_id:
            self.log("⚠️ RAIL_DEVICEID 已缺失，请留意官方页面是否要求重新验证。")
            return False
        if current_id != self.saved_device_id:
            self.log("⚠️ RAIL_DEVICEID 已变化，请留意官方页面是否要求重新验证。")
            return False
        return True
```

Replace `check_and_restore()` with a compatibility wrapper that no longer mutates cookies:

```python
    def check_and_restore(self) -> bool:
        """Deprecated compatibility wrapper. Does not restore cookies."""
        return self.check_consistency()
```

- [ ] **Step 4: Run device-id tracker tests**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_anti_detect.py::test_device_id_tracker_reports_consistent_cookie tests/test_anti_detect.py::test_device_id_tracker_warns_on_cookie_change_without_restoring -q
```

Expected: pass.

- [ ] **Step 5: Write failing bridge integration tests**

Append to `tests/test_railwatch_bridge.py`:

```python
    def test_check_login_records_device_id_after_verified_login(self):
        from railwatch_bridge import RailWatchBridge

        class FakeDriver:
            def execute_script(self, script):
                return {"data": {"flag": True}}

        class FakeDeviceIdTracker:
            def __init__(self):
                self.saved = False

            def save_device_id(self):
                self.saved = True
                return True

        tracker = FakeDeviceIdTracker()
        bridge = RailWatchBridge(data_dir=tempfile.mkdtemp(), event_callback=lambda event: None)
        bridge.driver = FakeDriver()
        bridge.device_id_protector = tracker

        bridge.check_login()

        self.assertTrue(tracker.saved)

    def test_keep_alive_checks_device_id_consistency(self):
        from railwatch_bridge import RailWatchBridge

        class FakeDriver:
            def execute_script(self, script):
                return None

        class FakeDeviceIdTracker:
            def __init__(self):
                self.checked = False

            def check_consistency(self):
                self.checked = True
                return True

        tracker = FakeDeviceIdTracker()
        bridge = RailWatchBridge(data_dir=tempfile.mkdtemp(), event_callback=lambda event: None)
        bridge.driver = FakeDriver()
        bridge.device_id_protector = tracker

        bridge._send_keep_alive()

        self.assertTrue(tracker.checked)
```

- [ ] **Step 6: Run bridge tests and verify they fail**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_railwatch_bridge.py::RailWatchBridgeTests::test_check_login_records_device_id_after_verified_login tests/test_railwatch_bridge.py::RailWatchBridgeTests::test_keep_alive_checks_device_id_consistency -q
```

Expected: fail because bridge does not call the tracker.

- [ ] **Step 7: Wire tracker into verified login and keep-alive**

In `railwatch_bridge.py`, add:

```python
    def _record_device_id_after_login(self) -> None:
        if self.device_id_protector is None:
            return
        try:
            self.device_id_protector.save_device_id()
        except Exception as exc:
            self.log(f"RAIL_DEVICEID 记录失败: {exc}", "WARN")

    def _check_device_id_consistency(self) -> None:
        if self.device_id_protector is None:
            return
        try:
            if not self.device_id_protector.check_consistency():
                self.log("会话设备标识发生变化，请关注官方页面提示。", "WARN")
        except Exception as exc:
            self.log(f"RAIL_DEVICEID 检查失败: {exc}", "WARN")
```

In `check_login()`, inside the `if ready:` block before the success log:

```python
self._record_device_id_after_login()
```

In `_send_keep_alive()`, after `self.log("会话保活已发送。")`:

```python
self._check_device_id_consistency()
```

- [ ] **Step 8: Run bridge integration tests**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_railwatch_bridge.py::RailWatchBridgeTests::test_check_login_records_device_id_after_verified_login tests/test_railwatch_bridge.py::RailWatchBridgeTests::test_keep_alive_checks_device_id_consistency -q
```

Expected: pass.

---

### Task 4: Test And Keep Fallback Basic Injection Minimal

**Files:**
- Modify: `railwatch_bridge.py:614-658`
- Test: `tests/test_railwatch_bridge.py`

- [ ] **Step 1: Write failing fallback injection test**

Append to `tests/test_railwatch_bridge.py`:

```python
    def test_basic_anti_detect_injection_prefers_cdp(self):
        from railwatch_bridge import RailWatchBridge

        class FakeDriver:
            def __init__(self):
                self.commands = []
                self.executed_scripts = []

            def execute_cdp_cmd(self, command, payload):
                self.commands.append((command, payload))

            def execute_script(self, script):
                self.executed_scripts.append(script)

        driver = FakeDriver()
        bridge = RailWatchBridge(data_dir=tempfile.mkdtemp(), event_callback=lambda event: None)

        bridge._inject_basic_anti_detect(driver)

        self.assertEqual(driver.commands[0][0], "Page.addScriptToEvaluateOnNewDocument")
        self.assertIn("navigator", driver.commands[0][1]["source"])
        self.assertIn("webdriver", driver.commands[0][1]["source"])
        self.assertEqual(driver.executed_scripts, [])
```

- [ ] **Step 2: Run the fallback injection test**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_railwatch_bridge.py::RailWatchBridgeTests::test_basic_anti_detect_injection_prefers_cdp -q
```

Expected: pass if GLM's fallback injection is still intact. If it fails, fix only the injection call shape, not additional evasion logic.

- [ ] **Step 3: Make fallback script API-safe if needed**

If the test passes, skip this step. If the source string uses unguarded optional APIs, update only this part in `railwatch_bridge.py`:

```python
        basic_js = '''
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined, configurable: true});
        delete navigator.__proto__.webdriver;
        window.chrome = window.chrome || {};
        window.chrome.runtime = window.chrome.runtime || {};
        delete window.__puppeteer_evaluation_script__;
        delete window.__playwright_evaluation_script__;
        delete window.__selenium_unwrapped;
        delete window.__webdriver_evaluate;
        delete window.__driver_evaluate;
        delete window.__webdriver_unwrapped;
        delete window.__driver_unwrapped;
        Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN','zh','en-US','en']});
        Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
        const originalToString = Function.prototype.toString;
        Function.prototype.toString = function() {
            return originalToString.apply(this, arguments);
        };
        console.log('[RailWatch] 基础浏览器环境脚本已注入');
        '''
```

- [ ] **Step 4: Run fallback injection test again**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_railwatch_bridge.py::RailWatchBridgeTests::test_basic_anti_detect_injection_prefers_cdp -q
```

Expected: pass.

---

### Task 5: Remove Overstated Anti-Detection Claims

**Files:**
- Modify: `anti_detect.py:1-37`
- Modify: `README.md:139-142`
- Test: `tests/test_anti_detect.py`

- [ ] **Step 1: Write failing claim-safety test**

Append to `tests/test_anti_detect.py`:

```python
from pathlib import Path


def test_anti_detect_header_uses_compliance_risk_control_language():
    source = Path("anti_detect.py").read_text(encoding="utf-8")
    header = source.split('"""', 2)[1]

    assert "绕过" not in header
    assert "成功率 >95%" not in header
    assert "TLS 指纹优化" not in header
    assert "风险控制" in header
    assert "不绕过登录、验证码、订单确认、支付或网站规则" in header
```

- [ ] **Step 2: Run the claim-safety test and verify it fails**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_anti_detect.py::test_anti_detect_header_uses_compliance_risk_control_language -q
```

Expected: fail because the current header still claims bypass, TLS optimization, and >95% success.

- [ ] **Step 3: Replace the module header**

Replace `anti_detect.py:1-37` with:

```python
"""
RailWatch browser environment and risk-control helpers.

Scope:
1. Use a persistent Chrome profile for official 12306 pages.
2. Keep browser-visible environment values stable across app restarts.
3. Add conservative random pacing for low-frequency monitoring.
4. Track session/device-id consistency and warn when the official page changes it.
5. Keep automation user-controlled and visible.

This module does not bypass login, captcha, order confirmation, payment, website
rules, or service rate limits. It does not guarantee ticket availability or
successful purchase. It is intended to reduce accidental instability in normal
personal-use monitoring, not to defeat platform protections.
"""
```

- [ ] **Step 4: Update README safety wording**

In `README.md`, ensure the safety notes contain this wording:

```markdown
- Browser environment helpers keep local Chrome profile and page-visible values stable for low-frequency monitoring.
- RailWatch does not bypass login, captcha, order confirmation, payment, website rules or service rate limits.
- Stop monitoring if 12306 shows verification, risk prompts or unusual page states.
```

- [ ] **Step 5: Run the claim-safety test**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_anti_detect.py::test_anti_detect_header_uses_compliance_risk_control_language -q
```

Expected: pass.

---

### Task 6: Full Verification And Review

**Files:**
- No new production files.
- Verify all modified files.

- [ ] **Step 1: Run focused Python tests**

Run:

```powershell
$env:PYTHONPATH='.'; pytest tests/test_anti_detect.py tests/test_railwatch_bridge.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run full Python tests**

Run:

```powershell
$env:PYTHONPATH='.'; pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Run Python compile check**

Run:

```powershell
python -m py_compile anti_detect.py railwatch_bridge.py gui_12306_0.py
```

Expected: no output and exit code `0`.

- [ ] **Step 4: Run frontend/electron regression tests**

Run:

```powershell
npm test
npm run typecheck
```

Expected: all Vitest suites pass and TypeScript typecheck exits `0`.

- [ ] **Step 5: Manual diff review**

Run:

```powershell
git diff -- anti_detect.py railwatch_bridge.py README.md tests/test_anti_detect.py tests/test_railwatch_bridge.py
```

Check:
- No claims of bypassing 12306 protections remain.
- No automatic cookie restoration remains.
- Legacy `device_profile.json` migration preserves existing profile values.
- Optional browser APIs are guarded before access.
- Device-id warnings are observable through logs.

- [ ] **Step 6: Final assessment**

Report:

```text
修复后可评为：合规低频个人辅助风险控制 B / B+。
仍不能评为：强风控、高峰期对抗、防检测绕过达标。
```

Do not state that anti-detection is guaranteed or "达标" for bypassing platform protections.

---

## Self-Review

- Spec coverage: covers legacy profile migration, optional JS guards, device-id integration, fallback injection testing, and overclaim removal.
- Placeholder scan: no unresolved placeholder markers remain.
- Type consistency: `DeviceProfile.from_dict`, `RailDeviceIdProtector.check_consistency`, `_build_anti_detect_script`, `_record_device_id_after_login`, and `_check_device_id_consistency` are defined before use.
