"""System facts exposed to the RailWatch desktop shell."""

from __future__ import annotations

import json
import os
import shutil
import socket
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Tuple

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_PROXY_ENV_KEYS = ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy")
_PROBE_TIMEOUT = 2.5


def get_app_version() -> str:
    env_version = os.environ.get("RAILWATCH_APP_VERSION", "").strip()
    if env_version:
        return env_version

    package_path = os.path.join(_PROJECT_ROOT, "package.json")
    try:
        with open(package_path, encoding="utf-8") as handle:
            payload = json.load(handle)
        version = str(payload.get("version", "")).strip()
        return version or "未知"
    except OSError:
        return "未知"


def inspect_data_dir(data_dir: str) -> Dict[str, object]:
    target = os.path.abspath(data_dir)
    writable = False
    free_bytes = 0

    try:
        os.makedirs(target, exist_ok=True)
        probe_path = os.path.join(target, ".railwatch-write-probe")
        with open(probe_path, "w", encoding="utf-8") as handle:
            handle.write("ok")
        os.remove(probe_path)
        writable = True
        free_bytes = shutil.disk_usage(target).free
    except OSError:
        writable = False
        try:
            free_bytes = shutil.disk_usage(os.path.dirname(target) or target).free
        except OSError:
            free_bytes = 0

    return {
        "data_dir_writable": writable,
        "data_dir_free_bytes": int(free_bytes),
    }


def _probe_host(host: str, port: int = 443, timeout: float = _PROBE_TIMEOUT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _probe_http(url: str, timeout: float = _PROBE_TIMEOUT) -> bool:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "RailWatch/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 500
    except urllib.error.HTTPError as exc:
        return 200 <= exc.code < 500
    except Exception:
        return False


def detect_proxy() -> Tuple[bool, str]:
    for key in _PROXY_ENV_KEYS:
        value = os.environ.get(key, "").strip()
        if value:
            return True, value
    return False, ""


def probe_connectivity() -> Dict[str, object]:
    with ThreadPoolExecutor(max_workers=2) as pool:
        network_future = pool.submit(
            lambda: _probe_http("https://www.baidu.com") or _probe_host("223.5.5.5", 443) or _probe_host("1.1.1.1", 443)
        )
        railway_future = pool.submit(
            lambda: _probe_http("https://kyfw.12306.cn/otn/resources/login.html") or _probe_host("kyfw.12306.cn", 443)
        )
        network_ok = bool(network_future.result())
        railway_ok = bool(railway_future.result())

    proxy_configured, proxy_value = detect_proxy()
    return {
        "network_ok": network_ok,
        "network_label": "正常" if network_ok else "异常",
        "railway_ok": railway_ok,
        "railway_label": "正常" if railway_ok else "异常",
        "proxy_configured": proxy_configured,
        "proxy_label": "已配置" if proxy_configured else "未配置",
        "proxy_value": proxy_value,
    }
