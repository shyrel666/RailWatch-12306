"""Offline real-browser verification of the install preparation cleanup gate."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import subprocess
import tempfile
import unittest
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from railwatch_bridge import CHROMEDRIVER_PATH, RailWatchBridge


class UpdateCleanupBrowserTests(unittest.TestCase):
    def test_idle_browser_and_driver_exit_before_install_is_ready(self):
        with tempfile.TemporaryDirectory(prefix="railwatch-update-cleanup-") as directory:
            options = webdriver.ChromeOptions()
            options.add_argument("--headless=new")
            options.add_argument("--disable-background-networking")
            options.add_argument(f"--user-data-dir={Path(directory) / 'profile'}")
            driver = webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=options)
            bridge = RailWatchBridge(data_dir=directory)
            bridge.driver = driver
            try:
                driver.execute_cdp_cmd("Network.enable", {})
                driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": ["*12306.cn*"]})
                driver.get("about:blank")
                service_process = driver.service.process
                browser_pid = driver.capabilities.get("goog:processID")
                ready = bridge.prepare_shutdown("install")
                self.assertTrue(ready["ready"])
                self.assertIsNone(bridge.driver)
                self.assertIsNotNone(service_process.poll())
                if sys.platform == "win32":
                    self.assertIsInstance(browser_pid, int)
                    result = subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"Get-Process -Id {int(browser_pid)},{service_process.pid} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"],
                        capture_output=True, text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
                    self.assertEqual(result.stdout.strip(), "", "Test-owned Chrome and ChromeDriver must both be gone")
            finally:
                driver.quit()


if __name__ == "__main__":
    unittest.main(verbosity=2)
