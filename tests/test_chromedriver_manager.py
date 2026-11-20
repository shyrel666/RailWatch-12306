import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import json
import os
import plistlib
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, Mock, patch
from urllib.error import HTTPError, URLError
import zipfile

import chromedriver_manager as cm


def _make_zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(zipfile.ZipInfo(name), content)
    return buf.getvalue()


def _pin(version, platform, archive):
    return patch.dict(cm._ARCHIVE_SHA256, {(version, platform): hashlib.sha256(archive).hexdigest()})


def _object_hash(data):
    return "md5=" + base64.b64encode(hashlib.md5(data, usedforsecurity=False).digest()).decode("ascii")


def _stream_fixture(fetch):
    def get(url, timeout=30, progress_callback=None, *, write=None, publisher=False):
        data = fetch(url, timeout)
        if write is None:
            return data
        write(data)
    return get


class ChromeDriverManagerTests(unittest.TestCase):
    def _http_404(self, url: str) -> HTTPError:
        return self.enterContext(HTTPError(url, 404, "Not Found", hdrs=None, fp=None))

    def test_requests_download_reports_real_bytes_speed_and_remaining_time(self):
        response = Mock()
        response.headers = {"Content-Length": "6"}
        response.iter_content.return_value = iter([b"abc", b"def"])
        progress = []
        with patch.object(cm, "REQUESTS_AVAILABLE", True), \
            patch.object(cm.requests, "get", return_value=response) as request, \
            patch.object(cm.time, "monotonic", side_effect=[0, 0, 1, 2, 2]):
            content = cm._http_get("https://example.test/driver.zip", progress_callback=progress.append)

        self.assertEqual(content, b"abcdef")
        self.assertTrue(request.call_args.kwargs["stream"])
        self.assertEqual(request.call_args.kwargs["headers"]["Accept-Encoding"], "identity")
        self.assertEqual(progress[0]["downloaded_bytes"], 0)
        self.assertIsNone(progress[0]["eta_seconds"])
        self.assertEqual(progress[1]["downloaded_bytes"], 3)
        self.assertEqual(progress[1]["total_bytes"], 6)
        self.assertEqual(progress[1]["bytes_per_second"], 3)
        self.assertEqual(progress[1]["eta_seconds"], 1)
        self.assertEqual(progress[-1]["downloaded_bytes"], 6)
        self.assertEqual(progress[-1]["eta_seconds"], 0)
        response.close.assert_called_once()

    def test_urllib_download_without_size_does_not_invent_total_or_eta(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.headers = {}
        response.read.side_effect = [b"abc", b"def", b""]
        progress = []
        with patch.object(cm, "REQUESTS_AVAILABLE", False), \
            patch.object(cm, "URLLIB_AVAILABLE", True), \
            patch.object(cm, "urlopen", return_value=response), \
            patch.object(cm.time, "monotonic", side_effect=[0, 0, 1, 2, 2]):
            content = cm._http_get("https://example.test/driver.zip", progress_callback=progress.append)

        self.assertEqual(content, b"abcdef")
        self.assertEqual(progress[-1]["downloaded_bytes"], 6)
        self.assertEqual(progress[-1]["bytes_per_second"], 3)
        self.assertTrue(all(event["total_bytes"] is None for event in progress))
        self.assertTrue(all(event["eta_seconds"] is None for event in progress))
        response.__exit__.assert_called_once()

    def test_urllib_download_closes_http_error_before_propagating_it(self):
        url = "https://example.test/driver.zip"
        error = self._http_404(url)
        with patch.object(cm, "REQUESTS_AVAILABLE", False), \
            patch.object(cm, "urlopen", side_effect=error), \
            self.assertRaises(HTTPError) as caught:
            cm._http_get(url)

        self.assertIs(caught.exception, error)
        self.assertTrue(error.closed)

    def test_streamed_download_rejects_truncated_response_and_closes_it(self):
        response = Mock()
        response.headers = {"Content-Length": "20"}
        response.iter_content.return_value = iter([b"abc"])
        with patch.object(cm, "REQUESTS_AVAILABLE", True), \
            patch.object(cm.requests, "get", return_value=response):
            with self.assertRaisesRegex(IOError, "下载不完整"):
                cm._http_get("https://example.test/driver.zip", progress_callback=lambda event: None)
        response.close.assert_called_once()

    def test_progress_clears_old_transfer_metrics_when_falling_back_and_installing(self):
        mirror = cm._DownloadCandidate("https://mirror.test/driver.zip", "137.0.1.2", "npmmirror 镜像")
        official = cm._DownloadCandidate(cm._cft_official_zip_url("137.0.1.2", "win32"), "137.0.1.2", "官方源")
        mirror_response = Mock()
        mirror_response.headers = {"Content-Length": "100"}

        def failing_chunks():
            yield b"partial"
            raise URLError("connection lost")

        mirror_response.iter_content.return_value = failing_chunks()
        archive = _make_zip_bytes({"chromedriver.exe": b"working-binary"})
        official_response = Mock()
        self.enterContext(_pin("137.0.1.2", "win32", archive))
        official_response.headers = {"Content-Length": str(len(archive)), "x-goog-hash": _object_hash(archive)}
        official_response.iter_content.return_value = iter([archive])
        progress = []
        with tempfile.TemporaryDirectory() as target_dir, \
            patch.object(cm.platform, "system", return_value="Windows"), \
            patch.object(cm, "_candidate_resolvers", return_value=[lambda: [mirror, official]]), \
            patch.object(cm, "REQUESTS_AVAILABLE", True), \
            patch.object(cm.requests, "get", side_effect=[mirror_response, official_response]), \
            patch.object(cm, "detect_chromedriver_version", return_value="137.0.1.2"):
            dest = cm.download_and_install_chromedriver(
                target_dir, major_version="137", progress_callback=progress.append,
            )
            with open(dest, "rb") as handle:
                self.assertEqual(handle.read(), b"working-binary")

        stages = [event["stage"] for event in progress]
        self.assertEqual(stages[0], "resolving")
        self.assertIn("retrying", stages)
        self.assertEqual(stages[-3:], ["extracting", "installing", "complete"])
        downloads = [event for event in progress if event["stage"] == "downloading"]
        self.assertEqual(downloads[0]["source"], "npmmirror 镜像")
        self.assertEqual(downloads[-1]["source"], "官方源")
        self.assertEqual(downloads[-1]["downloaded_bytes"], len(archive))
        self.assertEqual(downloads[-1]["total_bytes"], len(archive))
        for event in progress:
            if event["stage"] != "downloading":
                self.assertIsNone(event["downloaded_bytes"])
                self.assertIsNone(event["total_bytes"])
                self.assertIsNone(event["eta_seconds"])
        mirror_response.close.assert_called_once()
        official_response.close.assert_called_once()

    def test_metadata_connection_timeout_reports_official_fallback_and_streams_metadata(self):
        official_url = f"{cm.CFT_BINARY_PREFIX}/137.0.1.2/win32/chromedriver-win32.zip"
        metadata = json.dumps({"milestones": {"137": {
            "version": "137.0.1.2",
            "downloads": {"chromedriver": [{"platform": "win32", "url": official_url}]},
        }}}).encode()
        archive = _make_zip_bytes({"chromedriver.exe": b"working-binary"})
        requested = []
        responses = []

        def fake_request(url, **kwargs):
            requested.append(url)
            self.assertTrue(kwargs["stream"])
            if url == cm.NPMMIRROR_PATCH_VERSIONS_URL:
                raise cm.requests.exceptions.ConnectTimeout("mirror unreachable")
            if url == cm.CFT_MILESTONE_URL:
                self.assertEqual(kwargs["timeout"], cm._METADATA_TIMEOUT)
                body = metadata
            elif url == official_url:
                body = archive
            else:
                raise AssertionError(url)
            response = Mock()
            response.headers = {"Content-Length": str(len(body)), "x-goog-hash": _object_hash(body)}
            response.iter_content.return_value = iter([body[:20], body[20:]])
            responses.append(response)
            return response

        progress = []
        with tempfile.TemporaryDirectory() as target_dir, \
            patch.object(cm.platform, "system", return_value="Windows"), \
            patch.object(cm, "REQUESTS_AVAILABLE", True), \
            patch.object(cm.requests, "get", side_effect=fake_request), \
            patch.object(cm, "detect_chromedriver_version", return_value="137.0.1.2"):
            cm.download_and_install_chromedriver(target_dir, "137", progress_callback=progress.append)

        self.assertEqual(requested, [cm.NPMMIRROR_PATCH_VERSIONS_URL, cm.CFT_MILESTONE_URL, official_url])
        resolving = [event for event in progress if event["stage"] == "resolving"]
        self.assertEqual(resolving[0]["source"], "npmmirror 镜像")
        self.assertEqual(resolving[-1]["source"], "官方源")
        self.assertEqual(resolving[-1]["downloaded_bytes"], len(metadata))
        self.assertEqual(resolving[-1]["total_bytes"], len(metadata))
        connecting = next(event for event in progress if event["stage"] == "connecting")
        self.assertIsNone(connecting["downloaded_bytes"])
        self.assertEqual(progress[-1]["stage"], "complete")
        for response in responses:
            response.close.assert_called_once()

    def test_full_metadata_without_content_length_reports_bytes_in_resolving_stage(self):
        zip_url = f"{cm.NPMMIRROR_CFT_CDN_PREFIX}/137.0.1.2/win32/chromedriver-win32.zip"
        metadata = json.dumps({"versions": [{
            "version": "137.0.1.2", "downloads": {"chromedriver": [{
                "platform": "win32", "url": f"{cm.CFT_BINARY_PREFIX}/137.0.1.2/win32/chromedriver-win32.zip",
            }]},
        }]}).encode()
        archive = _make_zip_bytes({"chromedriver.exe": b"working-binary"})
        self.enterContext(_pin("137.0.1.2", "win32", archive))

        def fake_request(url, **kwargs):
            self.assertTrue(kwargs["stream"])
            response = Mock()
            response.headers = {}
            if url == cm.NPMMIRROR_PATCH_VERSIONS_URL:
                response.status_code = 404
                response.raise_for_status.side_effect = cm.requests.HTTPError("404 Not Found", response=response)
                return response
            if url == cm.NPMMIRROR_CFT_URL:
                body = metadata
            elif url == zip_url:
                body = archive
            else:
                raise AssertionError(url)
            response.iter_content.return_value = iter([body])
            return response

        progress = []
        with tempfile.TemporaryDirectory() as target_dir, \
            patch.object(cm.platform, "system", return_value="Windows"), \
            patch.object(cm, "REQUESTS_AVAILABLE", True), \
            patch.object(cm.requests, "get", side_effect=fake_request), \
            patch.object(cm, "detect_chromedriver_version", return_value="137.0.1.2"):
            cm.download_and_install_chromedriver(target_dir, "137", progress_callback=progress.append)

        metadata_done = [event for event in progress if event["stage"] == "resolving"][-1]
        self.assertEqual(metadata_done["downloaded_bytes"], len(metadata))
        self.assertEqual(metadata_done["source"], "npmmirror 镜像")
        self.assertIsNone(metadata_done["total_bytes"])
        self.assertIsNone(metadata_done["eta_seconds"])
        self.assertEqual(progress[-1]["stage"], "complete")

    def test_cft_prefers_npmmirror_patch_index_and_verifies_archive_with_publisher(self):
        self.enterContext(_pin("137.0.7151.119", "win32", _make_zip_bytes({"chromedriver-win32/chromedriver.exe": b"mirror-driver-binary"})))
        patch_payload = {
            "builds": {
                "137.0.7151.9": {"version": "137.0.7151.9"},
                "137.0.7151.119": {"version": "137.0.7151.119"},
                "137.0.7151.20": {"version": "137.0.7151.20"},
                "138.0.7200.1": {"version": "138.0.7200.1"},
            }
        }
        dir_url = f"{cm.NPMMIRROR_CFT_API_PREFIX}/137.0.7151.119/win32/"
        cdn_url = f"{cm.NPMMIRROR_CFT_CDN_PREFIX}/137.0.7151.119/win32/chromedriver-win32.zip"
        requested: list[str] = []

        def fake_http_get(url: str, timeout: int = 30) -> bytes:
            requested.append(url)
            if url == cm.NPMMIRROR_PATCH_VERSIONS_URL:
                return json.dumps(patch_payload).encode("utf-8")
            if url == dir_url:
                return json.dumps([{"name": "chromedriver-win32.zip", "type": "file"}]).encode("utf-8")
            if url == cdn_url:
                return _make_zip_bytes({"chromedriver-win32/chromedriver.exe": b"mirror-driver-binary"})
            raise AssertionError(f"Unexpected network call: {url}")

        logs: list[str] = []
        with tempfile.TemporaryDirectory() as temp_dir, \
            patch("chromedriver_manager.platform.system", return_value="Windows"), \
            patch("chromedriver_manager._http_get", side_effect=_stream_fixture(fake_http_get)), \
            patch("chromedriver_manager.detect_chromedriver_version", return_value="137.0.7151.119"):
            dest = cm.download_and_install_chromedriver(temp_dir, major_version="137", log_callback=logs.append)
            with open(dest, "rb") as handle:
                self.assertEqual(handle.read(), b"mirror-driver-binary")

        self.assertEqual(requested, [cm.NPMMIRROR_PATCH_VERSIONS_URL, dir_url, cdn_url])
        self.assertTrue(any("已安装到" in msg for msg in logs))

    def test_cft_rewrites_google_urls_inside_npmmirror_known_good_json(self):
        self.enterContext(_pin("137.0.7151.119", "mac-arm64", _make_zip_bytes({"chromedriver-mac-arm64/chromedriver": b"mac-mirror-bin"})))
        # Even though npmmirror's known-good JSON embeds storage.googleapis.com URLs,
        # the downloader must try cdn.npmmirror.com first before touching Google storage.
        known_good_payload = {
            "versions": [
                {
                    "version": "137.0.7151.119",
                    "downloads": {
                        "chromedriver": [
                            {
                                "platform": "mac-arm64",
                                "url": "https://storage.googleapis.com/chrome-for-testing-public/137.0.7151.119/mac-arm64/chromedriver-mac-arm64.zip",
                            }
                        ]
                    },
                }
            ]
        }
        expected_cdn_url = (
            f"{cm.NPMMIRROR_CFT_CDN_PREFIX}/137.0.7151.119/mac-arm64/chromedriver-mac-arm64.zip"
        )
        requested: list[str] = []

        def fake_http_get(url: str, timeout: int = 30) -> bytes:
            requested.append(url)
            if url == cm.NPMMIRROR_PATCH_VERSIONS_URL:
                raise self._http_404(url)
            if url == cm.NPMMIRROR_CFT_URL:
                return json.dumps(known_good_payload).encode("utf-8")
            if url == expected_cdn_url:
                return _make_zip_bytes({"chromedriver-mac-arm64/chromedriver": b"mac-mirror-bin"})
            raise AssertionError(f"Should not fall back to Google storage when CDN works: {url}")

        with tempfile.TemporaryDirectory() as temp_dir, \
            patch("chromedriver_manager.platform.system", return_value="Darwin"), \
            patch("chromedriver_manager.platform.machine", return_value="arm64"), \
            patch("chromedriver_manager._http_get", side_effect=_stream_fixture(fake_http_get)), \
            patch("chromedriver_manager.detect_chromedriver_version", return_value="137.0.7151.119"):
            dest = cm.download_and_install_chromedriver(temp_dir, major_version="137")
            with open(dest, "rb") as handle:
                self.assertEqual(handle.read(), b"mac-mirror-bin")

        self.assertEqual(requested, [cm.NPMMIRROR_PATCH_VERSIONS_URL, cm.NPMMIRROR_CFT_URL, expected_cdn_url])

    def test_cft_skips_same_host_full_json_on_timeout_and_falls_back_to_official(self):
        official_zip_url = "https://storage.googleapis.com/chrome-for-testing-public/139.0.7258.5/win32/chromedriver-win32.zip"
        milestone_payload = {
            "milestones": {
                "139": {
                    "version": "139.0.7258.5",
                    "downloads": {
                        "chromedriver": [{"platform": "win32", "url": official_zip_url}]
                    },
                }
            }
        }
        requested: list[str] = []

        def fake_http_get(url: str, timeout: int = 30) -> bytes:
            requested.append(url)
            if url == cm.NPMMIRROR_PATCH_VERSIONS_URL:
                raise URLError("timed out")
            if url == cm.CFT_MILESTONE_URL:
                return json.dumps(milestone_payload).encode("utf-8")
            if url == official_zip_url:
                return _make_zip_bytes({"chromedriver.exe": b"official-driver"})
            raise AssertionError(f"Unexpected URL requested: {url}")

        with tempfile.TemporaryDirectory() as temp_dir, \
            patch("chromedriver_manager.platform.system", return_value="Windows"), \
            patch("chromedriver_manager._http_get", side_effect=_stream_fixture(fake_http_get)), \
            patch("chromedriver_manager.detect_chromedriver_version", return_value="139.0.7258.5"):
            dest = cm.download_and_install_chromedriver(temp_dir, major_version="139")
            with open(dest, "rb") as handle:
                self.assertEqual(handle.read(), b"official-driver")

        self.assertNotIn(cm.NPMMIRROR_CFT_URL, requested)
        self.assertNotIn(cm.CFT_URL, requested)
        self.assertEqual(requested, [cm.NPMMIRROR_PATCH_VERSIONS_URL, cm.CFT_MILESTONE_URL, official_zip_url])

    def test_cft_falls_back_to_official_when_new_milestone_not_synced_to_mirror(self):
        official_zip_url = "https://storage.googleapis.com/chrome-for-testing-public/161.0.8200.1/win32/chromedriver-win32.zip"
        requested: list[str] = []

        def fake_http_get(url: str, timeout: int = 30) -> bytes:
            requested.append(url)
            if url == cm.NPMMIRROR_PATCH_VERSIONS_URL:
                return json.dumps({"builds": {"160.0.1": {"version": "160.0.1.0"}}}).encode("utf-8")
            if url == cm.NPMMIRROR_CFT_URL:
                return json.dumps({"versions": []}).encode("utf-8")
            if url == cm.CFT_MILESTONE_URL:
                return json.dumps({
                    "milestones": {
                        "161": {
                            "version": "161.0.8200.1",
                            "downloads": {"chromedriver": [{"platform": "win32", "url": official_zip_url}]},
                        }
                    }
                }).encode("utf-8")
            if url == official_zip_url:
                return _make_zip_bytes({"chromedriver.exe": b"fresh-official-driver"})
            raise AssertionError(f"Unexpected URL: {url}")

        with tempfile.TemporaryDirectory() as temp_dir, \
            patch("chromedriver_manager.platform.system", return_value="Windows"), \
            patch("chromedriver_manager._http_get", side_effect=_stream_fixture(fake_http_get)), \
            patch("chromedriver_manager.detect_chromedriver_version", return_value="161.0.8200.1"):
            dest = cm.download_and_install_chromedriver(temp_dir, major_version="161")
            with open(dest, "rb") as handle:
                self.assertEqual(handle.read(), b"fresh-official-driver")

        self.assertEqual(requested[-1], official_zip_url)

    def test_cdn_zip_failure_falls_back_to_official_binary_url(self):
        self.enterContext(_pin("137.0.7151.119", "win32", _make_zip_bytes({"chromedriver.exe": b"official-fallback-bin"})))
        patch_payload = {"builds": {"137.0.7151": {"version": "137.0.7151.119"}}}
        dir_url = f"{cm.NPMMIRROR_CFT_API_PREFIX}/137.0.7151.119/win32/"
        cdn_url = f"{cm.NPMMIRROR_CFT_CDN_PREFIX}/137.0.7151.119/win32/chromedriver-win32.zip"
        official_url = f"{cm.CFT_BINARY_PREFIX}/137.0.7151.119/win32/chromedriver-win32.zip"

        def fake_http_get(url: str, timeout: int = 30) -> bytes:
            if url == cm.NPMMIRROR_PATCH_VERSIONS_URL:
                return json.dumps(patch_payload).encode("utf-8")
            if url == dir_url:
                return json.dumps([{"name": "chromedriver-win32.zip", "type": "file"}]).encode("utf-8")
            if url == cdn_url:
                raise self._http_404(url)
            if url == official_url:
                return _make_zip_bytes({"chromedriver.exe": b"official-fallback-bin"})
            raise AssertionError(f"Unexpected URL: {url}")

        with tempfile.TemporaryDirectory() as temp_dir, \
            patch("chromedriver_manager.platform.system", return_value="Windows"), \
            patch("chromedriver_manager._http_get", side_effect=_stream_fixture(fake_http_get)), \
            patch("chromedriver_manager.detect_chromedriver_version", return_value="137.0.7151.119"):
            dest = cm.download_and_install_chromedriver(temp_dir, major_version="137")
            with open(dest, "rb") as handle:
                self.assertEqual(handle.read(), b"official-fallback-bin")

    def test_corrupt_or_mismatched_binary_rejected_before_replace(self):
        self.enterContext(_pin("137.0.7151.119", "win32", _make_zip_bytes({"chromedriver.exe": b"good-official-binary"})))
        patch_payload = {"builds": {"137.0.7151": {"version": "137.0.7151.119"}}}
        dir_url = f"{cm.NPMMIRROR_CFT_API_PREFIX}/137.0.7151.119/win32/"
        cdn_url = f"{cm.NPMMIRROR_CFT_CDN_PREFIX}/137.0.7151.119/win32/chromedriver-win32.zip"
        official_url = f"{cm.CFT_BINARY_PREFIX}/137.0.7151.119/win32/chromedriver-win32.zip"

        def fake_http_get(url: str, timeout: int = 30) -> bytes:
            if url == cm.NPMMIRROR_PATCH_VERSIONS_URL:
                return json.dumps(patch_payload).encode("utf-8")
            if url == dir_url:
                return json.dumps([{"name": "chromedriver-win32.zip", "type": "file"}]).encode("utf-8")
            if url == cdn_url:
                return _make_zip_bytes({"chromedriver.exe": b"bad-version-binary"})
            if url == official_url:
                return _make_zip_bytes({"chromedriver.exe": b"good-official-binary"})
            raise AssertionError(f"Unexpected URL: {url}")

        probed = []
        def fake_detect(path: str):
            with open(path, "rb") as handle:
                data = handle.read()
            probed.append(data)
            return "137.0.7151.119"

        with tempfile.TemporaryDirectory() as temp_dir:
            existing = os.path.join(temp_dir, "chromedriver.exe")
            with open(existing, "wb") as handle:
                handle.write(b"working-old-driver")

            with patch("chromedriver_manager.platform.system", return_value="Windows"), \
                patch("chromedriver_manager._http_get", side_effect=_stream_fixture(fake_http_get)), \
                patch("chromedriver_manager.detect_chromedriver_version", side_effect=fake_detect):
                dest = cm.download_and_install_chromedriver(temp_dir, major_version="137")
                with open(dest, "rb") as handle:
                    self.assertEqual(handle.read(), b"good-official-binary")
            self.assertEqual(probed, [b"good-official-binary"])

    def test_unpinned_version_uses_only_the_canonical_publisher_and_rejects_redirects(self):
        version = "137.0.1.2"
        mirror, official = cm._build_cft_candidates(version, "win32")
        response = Mock()
        response.is_redirect = True
        with tempfile.TemporaryDirectory() as directory, patch.object(cm.platform, "system", return_value="Windows"), \
                patch.object(cm, "_candidate_resolvers", return_value=[lambda: [mirror, official]]), \
                patch.object(cm, "REQUESTS_AVAILABLE", True), patch.object(cm.requests, "get", return_value=response) as get, \
                patch.object(cm, "detect_chromedriver_version") as detect:
            with self.assertRaisesRegex(RuntimeError, "重定向"):
                cm.download_and_install_chromedriver(directory, "137")
            self.assertEqual([call.args[0] for call in get.call_args_list], [official.url])
            self.assertFalse(get.call_args.kwargs["allow_redirects"])
            detect.assert_not_called()
            self.assertEqual(os.listdir(directory), [])

    def test_urllib_publisher_refuses_redirects_before_following_them(self):
        hits = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/elsewhere")
                self.end_headers()

            def log_message(self, *_):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.shutdown)
        with patch.object(cm, "REQUESTS_AVAILABLE", False), \
                self.assertRaisesRegex(ValueError, "重定向") as caught:
            cm._http_get(f"http://127.0.0.1:{server.server_port}/driver.zip", publisher=True)
        self.assertEqual(hits, ["/driver.zip"])
        self.assertIsInstance(caught.exception.__cause__, HTTPError)
        self.assertTrue(caught.exception.__cause__.closed)

        response = Mock()
        response.is_redirect = False
        response.status_code = 300
        with patch.object(cm, "REQUESTS_AVAILABLE", True), \
                patch.object(cm.requests, "get", return_value=response):
            with self.assertRaisesRegex(ValueError, "重定向"):
                cm._http_get("https://example.test/driver.zip", publisher=True)
        response.close.assert_called_once()

    def test_install_rejects_mismatched_full_version_and_preserves_existing_binary(self):
        for detected in ("137.0.7151.118", "136.0.0.1"):
            with self.subTest(detected=detected), tempfile.TemporaryDirectory() as directory:
                existing = os.path.join(directory, "chromedriver.exe")
                with open(existing, "wb") as handle:
                    handle.write(b"working-old-driver")
                archive = io.BytesIO(_make_zip_bytes({"chromedriver.exe": b"mismatched-binary"}))
                with patch.object(cm.platform, "system", return_value="Windows"), \
                        patch.object(cm, "detect_chromedriver_version", return_value=detected):
                    with self.assertRaisesRegex(cm._CandidateDownloadError, "版本校验不匹配"):
                        cm._install_verified_binary(archive, directory, "chromedriver.exe", "137.0.7151.119")
                with open(existing, "rb") as handle:
                    self.assertEqual(handle.read(), b"working-old-driver")
                self.assertEqual(os.listdir(directory), ["chromedriver.exe"])

    def test_publisher_transfer_requires_its_object_checksum(self):
        for headers in ({}, {"x-goog-hash": _object_hash(b"other")}):
            with self.subTest(headers=headers), self.assertRaises(cm._CandidateDownloadError):
                cm._read_download_chunks([b"archive"], headers, None, 0, publisher=True)

    def test_rejects_oversized_download_and_driver_before_version_probe(self):
        with self.assertRaisesRegex(ValueError, "大小限制"):
            cm._read_download_chunks([b"123", b"456"], {}, None, 0, limit=5)
        archive = io.BytesIO(_make_zip_bytes({"chromedriver.exe": b"123456"}))
        with tempfile.TemporaryDirectory() as directory, patch.object(cm, "_MAX_DRIVER_BYTES", 5), \
                patch.object(cm, "detect_chromedriver_version") as detect:
            with self.assertRaisesRegex(cm._CandidateDownloadError, "大小异常"):
                cm._install_verified_binary(archive, directory, "chromedriver.exe", "137")
            detect.assert_not_called()
            self.assertEqual(os.listdir(directory), [])

    def test_all_failed_preserves_existing_binary_and_leaves_no_temp_files(self):
        patch_payload = {"builds": {"137.0.7151": {"version": "137.0.7151.119"}}}
        dir_url = f"{cm.NPMMIRROR_CFT_API_PREFIX}/137.0.7151.119/win32/"
        cdn_url = f"{cm.NPMMIRROR_CFT_CDN_PREFIX}/137.0.7151.119/win32/chromedriver-win32.zip"
        official_url = f"{cm.CFT_BINARY_PREFIX}/137.0.7151.119/win32/chromedriver-win32.zip"

        def fake_http_get(url: str, timeout: int = 30) -> bytes:
            if url == cm.NPMMIRROR_PATCH_VERSIONS_URL:
                return json.dumps(patch_payload).encode("utf-8")
            if url == dir_url:
                return json.dumps([{"name": "chromedriver-win32.zip", "type": "file"}]).encode("utf-8")
            if url in (cdn_url, official_url):
                return _make_zip_bytes({"chromedriver.exe": b"corrupt-non-executable"})
            raise URLError("offline")

        with tempfile.TemporaryDirectory() as temp_dir:
            existing = os.path.join(temp_dir, "chromedriver.exe")
            with open(existing, "wb") as handle:
                handle.write(b"working-old-driver")

            with patch("chromedriver_manager.platform.system", return_value="Windows"), \
                patch("chromedriver_manager._http_get", side_effect=_stream_fixture(fake_http_get)), \
                patch("chromedriver_manager.detect_chromedriver_version", return_value=None):
                with self.assertRaises(RuntimeError) as ctx:
                    cm.download_and_install_chromedriver(temp_dir, major_version="137")

            self.assertIn("无法执行或版本校验失败", str(ctx.exception))
            with open(existing, "rb") as handle:
                self.assertEqual(handle.read(), b"working-old-driver")
            self.assertEqual(os.listdir(temp_dir), ["chromedriver.exe"])

    def test_pre115_prefers_npmmirror_and_falls_back_to_official(self):
        self.enterContext(_pin("114.0.5735.16", "win32", _make_zip_bytes({"chromedriver.exe": b"legacy"})))
        mirror_release_url = f"{cm.NPMMIRROR_LEGACY_API_PREFIX}/LATEST_RELEASE_114"
        mirror_zip_url = f"{cm.NPMMIRROR_LEGACY_CDN_PREFIX}/114.0.5735.16/chromedriver_win32.zip"
        official_release_url = f"{cm.LEGACY_URL_PREFIX}/LATEST_RELEASE_114"
        official_zip_url = f"{cm.LEGACY_URL_PREFIX}/114.0.5735.16/chromedriver_win32.zip"

        def fake_mirror_first(url: str, timeout: int = 30) -> bytes:
            if url == mirror_release_url:
                return b"114.0.5735.16"
            raise AssertionError(url)

        with patch("chromedriver_manager.platform.system", return_value="Windows"), \
            patch("chromedriver_manager._http_get", side_effect=fake_mirror_first):
            self.assertEqual(
                cm.get_chromedriver_download_url("114"),
                (mirror_zip_url, "114.0.5735.16"),
            )

        def fake_official_fallback(url: str, timeout: int = 30) -> bytes:
            if url == mirror_release_url:
                raise URLError("mirror down")
            if url == official_release_url:
                return b"114.0.5735.16"
            raise AssertionError(url)

        with patch("chromedriver_manager.platform.system", return_value="Windows"), \
            patch("chromedriver_manager._http_get", side_effect=fake_official_fallback):
            self.assertEqual(
                cm.get_chromedriver_download_url("114"),
                (official_zip_url, "114.0.5735.16"),
            )

    def test_posix_chmods_temp_binary_before_version_verification(self):
        self.enterContext(_pin("137.0.7151.119", "mac-arm64", _make_zip_bytes({"chromedriver": b"posix-binary"})))
        patch_payload = {"builds": {"137.0.7151": {"version": "137.0.7151.119"}}}
        dir_url = f"{cm.NPMMIRROR_CFT_API_PREFIX}/137.0.7151.119/mac-arm64/"
        cdn_url = f"{cm.NPMMIRROR_CFT_CDN_PREFIX}/137.0.7151.119/mac-arm64/chromedriver-mac-arm64.zip"
        events: list[str] = []

        def fake_http_get(url: str, timeout: int = 30) -> bytes:
            if url == cm.NPMMIRROR_PATCH_VERSIONS_URL:
                return json.dumps(patch_payload).encode("utf-8")
            if url == dir_url:
                return json.dumps([{"name": "chromedriver-mac-arm64.zip", "type": "file"}]).encode("utf-8")
            if url == cdn_url:
                return _make_zip_bytes({"chromedriver": b"posix-binary"})
            raise AssertionError(url)

        def fake_chmod(path: str, mode: int) -> None:
            events.append(f"chmod:{os.path.basename(path)}:{oct(mode)}")

        def fake_detect(path: str) -> str:
            events.append(f"detect:{os.path.basename(path)}")
            return "137.0.7151.119"

        with tempfile.TemporaryDirectory() as temp_dir, \
            patch("chromedriver_manager.platform.system", return_value="Darwin"), \
            patch("chromedriver_manager.platform.machine", return_value="arm64"), \
            patch("chromedriver_manager._http_get", side_effect=_stream_fixture(fake_http_get)), \
            patch("chromedriver_manager.os.chmod", side_effect=fake_chmod), \
            patch("chromedriver_manager.detect_chromedriver_version", side_effect=fake_detect):
            cm.download_and_install_chromedriver(temp_dir, major_version="137")

        self.assertGreaterEqual(len(events), 2)
        self.assertTrue(events[0].startswith("chmod:.chromedriver."))
        self.assertTrue(events[1].startswith("detect:.chromedriver."))

    def test_detect_chrome_macos_reads_info_plist_without_spawning_chrome(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            contents_dir = os.path.join(tmp_dir, "Google Chrome.app", "Contents")
            macos_dir = os.path.join(contents_dir, "MacOS")
            os.makedirs(macos_dir)
            binary = os.path.join(macos_dir, "Google Chrome")
            with open(binary, "wb") as handle:
                handle.write(b"fake-chrome")
            with open(os.path.join(contents_dir, "Info.plist"), "wb") as handle:
                plistlib.dump({"CFBundleShortVersionString": "137.0.7151.119"}, handle)

            orig_isfile = os.path.isfile
            # Only the temporary bundle exists for this test; a Chrome installed on the machine must not answer.
            with patch("chromedriver_manager.os.path.isfile", side_effect=lambda p: p.startswith(tmp_dir) and orig_isfile(p)), \
                patch.object(subprocess, "run", side_effect=AssertionError("subprocess.run must not be called")), \
                patch.object(cm, "_detect_chrome_macos", wraps=cm._detect_chrome_macos):
                orig_expanduser = os.path.expanduser
                # Replace expected macOS path via _read_macos_plist_version + _detect_chrome_macos flow
                self.assertEqual(cm._read_macos_plist_version(binary), "137")
                with patch("chromedriver_manager.os.path.expanduser", return_value=binary):
                    self.assertEqual(cm._detect_chrome_macos(), "137")

    def test_detect_chrome_macos_falls_back_to_cli_when_plist_missing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            macos_dir = os.path.join(tmp_dir, "Google Chrome.app", "Contents", "MacOS")
            os.makedirs(macos_dir)
            binary = os.path.join(macos_dir, "Google Chrome")
            with open(binary, "wb") as handle:
                handle.write(b"fake-chrome")

            fake_res = subprocess.CompletedProcess([binary, "--version"], 0, stdout="Google Chrome 138.0.7204.49\n")
            with patch("chromedriver_manager.os.path.isfile", side_effect=lambda p: p == binary), \
                patch("chromedriver_manager.os.path.expanduser", return_value=binary), \
                patch.object(subprocess, "run", return_value=fake_res) as mock_run:
                self.assertEqual(cm._detect_chrome_macos(), "138")
            mock_run.assert_called_once()

    def test_local_directory_creation_failure_raises_without_fallback_download(self):
        patch_payload = {"builds": {"137.0.7151": {"version": "137.0.7151.119"}}}
        dir_url = f"{cm.NPMMIRROR_CFT_API_PREFIX}/137.0.7151.119/win32/"
        cdn_url = f"{cm.NPMMIRROR_CFT_CDN_PREFIX}/137.0.7151.119/win32/chromedriver-win32.zip"
        requested: list[str] = []

        def fake_http_get(url: str, timeout: int = 30) -> bytes:
            requested.append(url)
            if url == cm.NPMMIRROR_PATCH_VERSIONS_URL:
                return json.dumps(patch_payload).encode("utf-8")
            if url == dir_url:
                return json.dumps([{"name": "chromedriver-win32.zip", "type": "file"}]).encode("utf-8")
            if url == cdn_url:
                raise AssertionError("Binary archive should not be downloaded when target_dir cannot be prepared")
            raise AssertionError(f"Unexpected fallback network call: {url}")

        with patch("chromedriver_manager.platform.system", return_value="Windows"), \
            patch("chromedriver_manager._http_get", side_effect=_stream_fixture(fake_http_get)), \
            patch("chromedriver_manager.os.makedirs", side_effect=PermissionError("read-only directory")):
            with self.assertRaises(RuntimeError) as ctx:
                cm.download_and_install_chromedriver("Z:/locked-dir", major_version="137")

        self.assertIn("准备 ChromeDriver 安装目录失败", str(ctx.exception))
        self.assertEqual(requested, [cm.NPMMIRROR_PATCH_VERSIONS_URL, dir_url])

    def test_local_mkstemp_failure_raises_without_retrying_official_source(self):
        self.enterContext(_pin("137.0.7151.119", "win32", _make_zip_bytes({"chromedriver.exe": b"mirror-driver-binary"})))
        patch_payload = {"builds": {"137.0.7151": {"version": "137.0.7151.119"}}}
        dir_url = f"{cm.NPMMIRROR_CFT_API_PREFIX}/137.0.7151.119/win32/"
        cdn_url = f"{cm.NPMMIRROR_CFT_CDN_PREFIX}/137.0.7151.119/win32/chromedriver-win32.zip"
        requested: list[str] = []

        def fake_http_get(url: str, timeout: int = 30) -> bytes:
            requested.append(url)
            if url == cm.NPMMIRROR_PATCH_VERSIONS_URL:
                return json.dumps(patch_payload).encode("utf-8")
            if url == dir_url:
                return json.dumps([{"name": "chromedriver-win32.zip", "type": "file"}]).encode("utf-8")
            if url == cdn_url:
                return _make_zip_bytes({"chromedriver.exe": b"mirror-driver-binary"})
            raise AssertionError(f"Should not fall back to another source on local IO failure: {url}")

        with tempfile.TemporaryDirectory() as temp_dir, \
            patch("chromedriver_manager.platform.system", return_value="Windows"), \
            patch("chromedriver_manager._http_get", side_effect=_stream_fixture(fake_http_get)), \
            patch("chromedriver_manager.tempfile.mkstemp", side_effect=OSError("No space left on device")):
            with self.assertRaises(RuntimeError) as ctx:
                cm.download_and_install_chromedriver(temp_dir, major_version="137")

        self.assertIn("无法在目标目录创建 ChromeDriver 临时文件", str(ctx.exception))
        self.assertEqual(requested, [cm.NPMMIRROR_PATCH_VERSIONS_URL, dir_url, cdn_url])

    def test_local_temp_write_failure_cleans_up_and_skips_fallback(self):
        self.enterContext(_pin("137.0.7151.119", "win32", _make_zip_bytes({"chromedriver.exe": b"mirror-driver-binary"})))
        patch_payload = {"builds": {"137.0.7151": {"version": "137.0.7151.119"}}}
        dir_url = f"{cm.NPMMIRROR_CFT_API_PREFIX}/137.0.7151.119/win32/"
        cdn_url = f"{cm.NPMMIRROR_CFT_CDN_PREFIX}/137.0.7151.119/win32/chromedriver-win32.zip"
        requested: list[str] = []

        def fake_http_get(url: str, timeout: int = 30) -> bytes:
            requested.append(url)
            if url == cm.NPMMIRROR_PATCH_VERSIONS_URL:
                return json.dumps(patch_payload).encode("utf-8")
            if url == dir_url:
                return json.dumps([{"name": "chromedriver-win32.zip", "type": "file"}]).encode("utf-8")
            if url == cdn_url:
                return _make_zip_bytes({"chromedriver.exe": b"mirror-driver-binary"})
            raise AssertionError(f"Should not fall back to another source on disk write failure: {url}")

        class FailingWriter:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def write(self, _data):
                raise OSError("No space left on device")

        def fake_fdopen(fd, mode="r", *args, **kwargs):
            os.close(fd)
            return FailingWriter()

        with tempfile.TemporaryDirectory() as temp_dir, \
            patch("chromedriver_manager.platform.system", return_value="Windows"), \
            patch("chromedriver_manager._http_get", side_effect=_stream_fixture(fake_http_get)), \
            patch("chromedriver_manager.os.fdopen", side_effect=fake_fdopen):
            with self.assertRaises(RuntimeError) as ctx:
                cm.download_and_install_chromedriver(temp_dir, major_version="137")
            self.assertEqual(os.listdir(temp_dir), [])

        self.assertIn("写入 ChromeDriver 临时文件失败", str(ctx.exception))
        self.assertEqual(requested, [cm.NPMMIRROR_PATCH_VERSIONS_URL, dir_url, cdn_url])


if __name__ == "__main__":
    unittest.main()
