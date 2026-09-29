import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tempfile
import threading
import time
import unittest
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from railwatch_bridge import CHROMEDRIVER_PATH
from railwatch_rehearsal_drill import run_drill, isolated_drill_tab, cancellable_browser
from railwatch_rehearsal_checks import read_passenger_book, check_passengers
from railwatch_task import TaskCancelled


class RehearsalBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="rehearsal-smoke-")
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--disable-background-networking")
        options.add_argument(f"--user-data-dir={cls.directory.name}/profile")
        cls.driver = webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=options)

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()
        cls.directory.cleanup()

    def test_regular_and_alternate_are_local_and_restore_tab(self):
        self.driver.get("about:blank")
        original = self.driver.current_window_handle
        config = {"from_station_cn": "北京", "to_station_cn": "上海", "date": "2026-10-12", "train_code": "G9", "seat_keyword": "二等座",
                  "passengers": "阿·测试，测试乙", "auto_submit": True, "auto_alternate": True, "alternate_deadline": "开车前60分钟", "seat_prefer": "靠窗优先"}
        measurements = {}
        with cancellable_browser(self.driver, threading.Event()):
            result = run_drill(self.driver, config, [{"train": "G9", "from_station": "北京南", "to_station": "上海虹桥"}], self.directory.name, threading.Event(), measurements)
        self.assertEqual(result["status"], "pass", result)
        self.assertIn("regular", measurements["drill_ms"])
        self.assertIn("alternate", measurements["drill_ms"])
        self.assertEqual(self.driver.current_window_handle, original)
        self.assertEqual(self.driver.current_url, "about:blank")
        self.assertFalse(list(Path(self.directory.name).glob("rehearsal-*")))

    def test_navigation_guard_and_cancellation_cleanup(self):
        self.driver.get("about:blank")
        original = self.driver.current_window_handle
        cancel = threading.Event()
        with cancellable_browser(self.driver, cancel):
            with self.assertRaises(TaskCancelled):
                with isolated_drill_tab(self.driver, Path(__file__).parent / "fixtures/passengers-page.html", cancel):
                    with self.assertRaises(RuntimeError):
                        self.driver.get("https://kyfw.12306.cn/otn/view/train_order.html")
                    cancel.set()
                    cancelled_at = time.monotonic()
                    self.driver.execute_script("return 1")
        self.assertLess(time.monotonic() - cancelled_at, 1)
        self.assertEqual(self.driver.current_window_handle, original)
        self.assertEqual(self.driver.current_url, "about:blank")

    def test_passenger_reader_follows_only_pagination_and_finds_cross_page_duplicates(self):
        self.driver.get((Path(__file__).parent / "fixtures/passengers-page.html").resolve().as_uri())
        self.driver.execute_script("fixture.pages=[[{name:'测试乙',type:'1',status:'已通过'}],[{name:'测试乙',type:'1',status:'已通过'}]];render()")
        driver = self.driver
        class LocalPassengerPage:
            current_url = "https://kyfw.12306.cn/otn/view/passengers.html"
            def __getattr__(self, key):
                return getattr(driver, key)
        book = read_passenger_book(LocalPassengerPage(), threading.Event())
        self.assertTrue(book["complete"])
        self.assertEqual(check_passengers({"passengers": "测试乙", "auto_submit": True}, book)["status"], "fail")
        self.assertEqual(self.driver.execute_script("return fixture.clicks"), ["next"])

    def test_duplicate_names_cannot_pass_local_order_drill(self):
        self.driver.get("about:blank")
        config = {"from_station_cn": "北京", "to_station_cn": "上海", "date": "2026-10-12", "train_code": "G9", "seat_keyword": "二等座",
                  "passengers": "测试甲，测试甲", "auto_submit": True}
        result = run_drill(self.driver, config, [{"train": "G9", "from_station": "北京南", "to_station": "上海虹桥"}], self.directory.name, threading.Event(), {})
        self.assertEqual(result["status"], "fail")
        self.assertNotIn("测试甲", str(result))
        self.assertEqual(self.driver.current_url, "about:blank")


if __name__ == "__main__":
    unittest.main()
