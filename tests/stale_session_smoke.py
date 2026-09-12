"""Run explicitly: python -X utf8 tests/stale_session_smoke.py

Live check for the "user closed the controlled Chrome window" failure mode.
It launches two short-lived visible Chrome windows in an isolated temp profile
and never touches the running app's session or the 12306 network.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from railwatch_bridge import RailWatchBridge, driver_session_alive, is_session_lost


def chromedriver_pids():
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-Process chromedriver -ErrorAction SilentlyContinue).Id -join ','"],
        capture_output=True, text=True, errors="replace",
    )
    return {int(pid) for pid in completed.stdout.strip().split(",") if pid.strip().isdigit()}


def kill_browser_tree(pid):
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                   capture_output=True, text=True, errors="replace")


class StaleSessionSmokeTests(unittest.TestCase):
    def test_killed_browser_is_detected_and_replaced(self):
        with tempfile.TemporaryDirectory(prefix="railwatch-stale-smoke-") as data_dir:
            bridge = RailWatchBridge(data_dir=data_dir, event_callback=lambda event: None)
            self.addCleanup(lambda: bridge.driver and bridge.close_browser(confirmed=True))
            leftover_before = chromedriver_pids()
            first = bridge._ensure_driver()
            self.addCleanup(lambda: driver_session_alive(first) and first.quit())
            first.get("about:blank")
            self.assertTrue(driver_session_alive(first))

            kill_browser_tree(first.capabilities["goog:processID"])
            time.sleep(2)

            self.assertFalse(driver_session_alive(first))
            with self.assertRaises(Exception) as caught:
                first.window_handles
            self.assertTrue(is_session_lost(caught.exception), str(caught.exception))

            second = bridge._ensure_driver()
            second.get("about:blank")
            self.assertIsNot(second, first)
            self.assertIs(bridge.driver, second)
            self.assertTrue(driver_session_alive(second))
            self.assertTrue(any("受控浏览器已关闭" in entry["message"] for entry in bridge.log_entries))

            self.assertEqual(bridge.close_browser(confirmed=True), {"closed": True})
            time.sleep(1)
            self.assertEqual(chromedriver_pids() - leftover_before, set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
