import unittest
from pathlib import Path

import anti_detect
from anti_detect import (
    AdaptiveRateLimiter,
    RailDeviceIdProtector,
    apply_chrome_launch_hardening,
    build_automation_hygiene_script,
)

ANTI_DETECT_PATH = Path(__file__).resolve().parents[1] / "anti_detect.py"


class AntiDetectTests(unittest.TestCase):
    def test_module_carries_no_fingerprint_spoofing_or_behaviour_simulation(self):
        for name in ("AntiDetect", "DeviceProfile", "BehaviorSimulator", "USER_AGENTS", "create_anti_detect_driver"):
            self.assertFalse(hasattr(anti_detect, name))
        source = ANTI_DETECT_PATH.read_text(encoding="utf-8")
        for marker in ("--user-agent=", "undetected", "toDataURL", "WebGLRenderingContext", "getChannelData"):
            self.assertNotIn(marker, source)

    def test_device_id_tracker_reports_consistent_cookie(self):
        class FakeDriver:
            def get_cookies(self):
                return [{"name": "RAIL_DEVICEID", "value": "abc"}]

        logs = []
        tracker = RailDeviceIdProtector(FakeDriver(), log_callback=logs.append)
        tracker.save_device_id()

        self.assertIs(tracker.check_consistency(), True)
        self.assertTrue(logs[0].startswith("💾 已记录 RAIL_DEVICEID"))

    def test_device_id_tracker_warns_on_cookie_change_without_restoring(self):
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

        self.assertIs(tracker.check_consistency(), False)
        self.assertEqual(driver.add_cookie_calls, [])
        self.assertTrue(any("变化" in message for message in logs))

    def test_anti_detect_header_uses_compliance_risk_control_language(self):
        source = ANTI_DETECT_PATH.read_text(encoding="utf-8")
        header = source.split('"""', 2)[1]

        self.assertNotIn("基础检测绕过", header)
        self.assertNotIn("绕过 navigator.webdriver", header)
        self.assertNotIn("成功率 >95%", header)
        self.assertNotIn("TLS 指纹优化", header)
        self.assertIn("风险控制", header)
        self.assertIn("不绕过登录、验证码、订单确认、支付或网站规则", header)

    def test_apply_chrome_launch_hardening_sets_automation_hygiene_only(self):
        class FakeOptions:
            def __init__(self):
                self.arguments = []
                self.experimental = {}

            def add_argument(self, value):
                self.arguments.append(value)

            def add_experimental_option(self, key, value):
                self.experimental[key] = value

        options = FakeOptions()
        apply_chrome_launch_hardening(options)

        self.assertIn("--disable-blink-features=AutomationControlled", options.arguments)
        self.assertIn("enable-automation", options.experimental["excludeSwitches"])
        self.assertIs(options.experimental["useAutomationExtension"], False)
        self.assertEqual(options.arguments, ["--disable-blink-features=AutomationControlled"])

    def test_automation_hygiene_script_avoids_fingerprint_spoofing(self):
        script = build_automation_hygiene_script()

        self.assertIn("webdriver", script)
        self.assertIn("cdc_", script)
        self.assertNotIn("toDataURL", script)
        self.assertNotIn("WebGLRenderingContext", script)
        self.assertNotIn("devicePixelRatio", script)
        self.assertNotIn("hardwareConcurrency", script)

    def test_rate_limiter_consumes_risk_alert_once(self):
        limiter = AdaptiveRateLimiter(5, 3, 30, log_callback=lambda _: None)
        limiter.on_error("操作过快，请稍后再试")

        self.assertIs(limiter.risk_detected, True)
        self.assertEqual(limiter.consume_risk_alert(), "操作过快，请稍后再试")
        self.assertIsNone(limiter.consume_risk_alert())


if __name__ == "__main__":
    unittest.main()
