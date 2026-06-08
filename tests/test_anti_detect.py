import builtins
import json
import os
from pathlib import Path

from anti_detect import AntiDetect, DeviceProfile, RailDeviceIdProtector, USER_AGENTS


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


def test_user_agent_pool_matches_windows_profile_values():
    assert all("Windows NT" in user_agent for user_agent in USER_AGENTS)


def test_legacy_profile_migration_returns_profile_when_save_fails(tmp_path, monkeypatch):
    legacy = DeviceProfile.generate_random().to_dict()
    original_user_agent = legacy["user_agent"]
    legacy.pop("canvas_noise_seed")
    legacy.pop("audio_noise_seed")
    profile_path = tmp_path / "device_profile.json"
    profile_path.write_text(json.dumps(legacy), encoding="utf-8")
    real_open = builtins.open

    def open_with_write_failure(path, mode="r", *args, **kwargs):
        if os.path.abspath(os.fspath(path)) == os.path.abspath(os.fspath(profile_path)) and "w" in mode:
            raise OSError("profile is locked")
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", open_with_write_failure)
    logs = []

    profile = AntiDetect(str(tmp_path), log_callback=logs.append).get_or_create_profile()

    assert profile.user_agent == original_user_agent
    assert isinstance(profile.canvas_noise_seed, int)
    assert isinstance(profile.audio_noise_seed, int)
    assert any("迁移设备指纹配置写回失败" in message for message in logs)
    assert not any("重新生成" in message for message in logs)


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


def test_anti_detect_header_uses_compliance_risk_control_language():
    source = Path("anti_detect.py").read_text(encoding="utf-8")
    header = source.split('"""', 2)[1]

    assert "基础检测绕过" not in header
    assert "绕过 navigator.webdriver" not in header
    assert "成功率 >95%" not in header
    assert "TLS 指纹优化" not in header
    assert "风险控制" in header
    assert "不绕过登录、验证码、订单确认、支付或网站规则" in header
