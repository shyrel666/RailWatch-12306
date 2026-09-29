"""M0 passenger DOM tests, isolated Chrome profile and no railway requests."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import tempfile
import unittest
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from railwatch_bridge import CHROMEDRIVER_PATH
from railwatch_order_page import READ_PASSENGER_BOOK_JS


class PassengerBookBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = tempfile.TemporaryDirectory(prefix="railwatch-passenger-book-")
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--disable-background-networking")
        options.add_argument(f"--user-data-dir={cls.profile.name}")
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        cls.driver = webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=options)
        cls.driver.execute_cdp_cmd("Network.enable", {})
        cls.driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": ["http://*", "https://*", "ws://*", "wss://*"]})

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()
        cls.profile.cleanup()

    def setUp(self):
        self.driver.get((Path(__file__).parent / "fixtures/passengers-page.html").resolve().as_uri())

    def read(self):
        return self.driver.execute_script(READ_PASSENGER_BOOK_JS)

    def test_live_shape_and_self_unknown(self):
        result = self.read()
        self.assertTrue(result["recognized"] and result["complete"])
        self.assertEqual([p["ticket_type"] for p in result["items"]], ["unknown", "adult"])
        self.assertEqual([p["verification"] for p in result["items"]], ["passed", "passed"])
        self.assertNotIn("SENSITIVE", json.dumps(result))
        self.assertEqual(self.driver.execute_script("return fixture.clicks"), [])

    def test_profile_type_codes(self):
        for code, expected in [("1", "adult"), ("2", "child"), ("3", "student"), ("4", "unknown"), ("99", "unknown")]:
            with self.subTest(code=code):
                self.driver.execute_script("fixture.pages[0][1].type=arguments[0];render()", code)
                person = self.read()["items"][1]
                self.assertEqual(person["ticket_type"], expected)
                self.assertEqual(person["unsupported_ticket_type"], code == "4")

    def test_status_icon_title_and_phone_separation(self):
        for title, expected in [("预通过", "prepassed"), ("身份信息未经核验", "pending"),
                                ("身份信息核验未通过", "failed"), ("本网站不再支持一代居民身份证", "failed"),
                                ("注册的信息与其他用户重复", "failed"), ("新状态", "unknown")]:
            with self.subTest(title=title):
                self.driver.execute_script("fixture.pages[0][1].status=arguments[0];render()", title)
                self.assertEqual(self.read()["items"][1]["verification"], expected)

    def test_pagination_and_duplicate_not_deduplicated(self):
        self.driver.execute_script("fixture.pages.push([{...fixture.pages[0][1]}]);render()")
        first = self.read()
        self.assertTrue(first["has_next"])
        self.assertFalse(first["complete"])
        self.driver.find_element("css selector", ".pagination a.next").click()
        second = self.read()
        self.assertTrue(second["complete"])
        self.assertEqual(second["page"], 2)
        self.assertEqual(first["items"][1]["name"], second["items"][0]["name"])
        self.assertEqual(self.driver.execute_script("return fixture.clicks"), ["next"])

    def test_unknown_structure_and_filtered_results(self):
        self.driver.execute_script("document.querySelector('th').textContent='changed'")
        self.assertFalse(self.read()["recognized"])
        self.setUp()
        self.driver.execute_script("document.querySelector('#_search_name').value='filter'")
        self.assertFalse(self.read()["recognized"])

    def test_hidden_rows_and_missing_pager_cannot_prove_complete(self):
        self.driver.execute_script("document.querySelector('.order-item-table tr').style.display='none'")
        self.assertFalse(self.read()["recognized"])
        self.setUp()
        self.driver.execute_script("document.querySelector('.pagination').remove()")
        result = self.read()
        self.assertEqual(len(result["items"]), 2)
        self.assertFalse(result["complete"] or result["pagination_valid"])

    def test_document_is_masked_even_if_source_is_not(self):
        self.driver.execute_script("fixture.pages[0][1].identity='110000200001019999';render()")
        result = self.read()
        self.assertEqual(result["items"][1]["identity_hint"], "11***99")
        self.assertNotIn("110000200001019999", json.dumps(result))

    def test_blocking_is_tab_scoped_and_restores_original_on_error(self):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"<title>local isolation probe</title>")
            def log_message(self, *_args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        original = self.driver.current_window_handle
        # Undo this test class's blanket block on the original tab only.
        self.driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": []})
        url = f"http://127.0.0.1:{server.server_port}/original"
        try:
            self.driver.get(url)
            self.driver.switch_to.new_window("tab")
            drill = self.driver.current_window_handle
            try:
                self.driver.execute_cdp_cmd("Network.enable", {})
                self.driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": ["http://*", "https://*", "ws://*", "wss://*"]})
                self.driver.execute_cdp_cmd("Network.emulateNetworkConditions", {
                    "offline": True, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1})
                self.driver.get((Path(__file__).parent / "fixtures/passengers-page.html").resolve().as_uri())
                self.assertEqual(self.driver.current_window_handle, drill)
                self.assertTrue(self.driver.current_url.startswith("file:"))
                for target in [url.replace("/original", "/blocked")]:
                    self.driver.get_log("performance")
                    try:
                        self.driver.get(target)
                    except Exception as exc:
                        self.assertTrue(any(code in str(exc) for code in ("ERR_BLOCKED_BY_CLIENT", "ERR_INTERNET_DISCONNECTED")))
                    events = [json.loads(item["message"])["message"] for item in self.driver.get_log("performance")]
                    self.assertTrue(any(event["method"] == "Network.loadingFailed"
                                        and (event["params"].get("blockedReason") == "inspector"
                                             or event["params"].get("errorText") == "net::ERR_INTERNET_DISCONNECTED")
                                        for event in events), [event for event in events if event["method"] == "Network.loadingFailed"])
                raise RuntimeError("simulated cancellation or failure")
            except RuntimeError:
                pass
            finally:
                self.driver.close()
                self.driver.switch_to.window(original)
            self.assertEqual(self.driver.current_url, url)
            self.driver.refresh()
            self.assertEqual(requests.count("/original"), 2)
            self.assertNotIn("/blocked", requests)
        finally:
            self.driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": ["http://*", "https://*", "ws://*", "wss://*"]})
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
