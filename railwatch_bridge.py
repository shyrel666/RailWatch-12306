"""UI-independent RailWatch bridge for Electron and other frontends."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timedelta
from dataclasses import replace
from copy import deepcopy
from functools import wraps
from railwatch_task import MonitorTask, TaskCancelled, guard_browser
from railwatch_query import FillResult, fill_result, LOGIN_CHECK_JS, QueryExecutor
from typing import Callable, Dict, List, Optional

from railwatch_config_contract import (
    AUTOMATION_ROUTE,
    config_for_persistence,
    default_config as contract_default_config,
    merge_notification_settings,
    validate_config as contract_validate_config,
)
from railwatch_notify import NotificationService
from railwatch_preferences import load_theme_preference, save_theme_preference, normalize_theme
from railwatch_dates import expand_travel_dates, eligible_travel_dates, beijing_now, PRESALE_WINDOW_DAYS
from railwatch_state import APP_DISPLAY_NAME, APP_PAGES, APP_SLUG, AppPhase, RailWatchState, TicketHit
from railwatch_system import get_app_version, inspect_data_dir, probe_connectivity
from railwatch_time import ServerTimeSync, get_server_time_sync, resolve_sale_timestamp
from railwatch_orders import OrderJournal, OrderIntent, OrderResult, STAGES
from railwatch_order_page import OrderPage

try:
    from chromedriver_manager import (
        detect_chrome_version,
        detect_chromedriver_version,
        download_and_install_chromedriver,
        get_chrome_version_info,
    )

    CD_MANAGER_AVAILABLE = True
except ImportError:
    detect_chrome_version = None
    detect_chromedriver_version = None
    download_and_install_chromedriver = None
    get_chrome_version_info = None
    CD_MANAGER_AVAILABLE = False

SELENIUM_IMPORT_ERROR = None
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    # selenium >= 4.44 lazy-loads browser submodules via module __getattr__, so a
    # frozen/partial install only fails when ChromeOptions is first touched.
    # Resolve it here to surface the real error at startup instead of mid-task.
    webdriver.ChromeOptions
    SELENIUM_AVAILABLE = True
except ImportError as exc:
    webdriver = None
    Service = None
    SELENIUM_AVAILABLE = False
    SELENIUM_IMPORT_ERROR = exc

try:
    from anti_detect import AntiDetect, BehaviorSimulator, RailDeviceIdProtector

    ANTI_DETECT_AVAILABLE = True
except ImportError:
    AntiDetect = None
    BehaviorSimulator = None
    RailDeviceIdProtector = None
    ANTI_DETECT_AVAILABLE = False

try:
    from gui_12306_0 import ConfigManager, PageAnalyzer, QueryConfig, TicketMonitor

    CORE_AVAILABLE = True
    CORE_IMPORT_ERROR = None
except ImportError as exc:
    ConfigManager = None
    PageAnalyzer = None
    QueryConfig = None
    TicketMonitor = None
    CORE_AVAILABLE = False
    CORE_IMPORT_ERROR = exc


LOGIN_URL = "https://kyfw.12306.cn/otn/resources/login.html"
QUERY_URL = "https://kyfw.12306.cn/otn/leftTicket/init?linktypeid=dc"
MAX_LOG_ENTRIES = 1000
MONITOR_HEARTBEAT_TIMEOUT_SECONDS = 180.0
MONITOR_PREWARM_INTERVAL_SECONDS = 30.0
NOTIFICATION_SETTINGS_FILE = "notification_settings.json"

# 用户可以在应用之外关掉受控的 Chrome 窗口。此时缓存的 WebDriver 句柄看上去仍然可用，
# 只有真正发一条命令才会发现 ChromeDriver 已经不认识这个会话（invalid session id）。
SESSION_LOST_EXCEPTION_NAMES = frozenset({
    "InvalidSessionIdException",
    "NoSuchSessionException",
    "SessionNotCreatedException",
})
SESSION_LOST_MESSAGE_HINTS = (
    "invalid session id",
    "no such session",
    "disconnected",
    "chrome not reachable",
    "cannot connect to the service",
    "connection refused",
    "connection aborted",
    "max retries exceeded",
    "newconnectionerror",
    "unable to connect to",
)


def is_session_lost(exc: BaseException) -> bool:
    """判断异常是否表示句柄背后的浏览器会话已经不存在。"""
    if any(klass.__name__ in SESSION_LOST_EXCEPTION_NAMES for klass in type(exc).__mro__):
        return True
    message = str(exc).lower()
    return any(hint in message for hint in SESSION_LOST_MESSAGE_HINTS)


def driver_session_alive(driver) -> bool:
    """在复用缓存句柄前探测一次，避免拿着已关闭的会话继续发命令。

    探测走的是真实请求，所以能区分「窗口已被关掉」和「句柄从未打开过页面」。
    只有明确的会话失效才算死亡：抛出其他异常的测试替身或残缺对象保持原样，
    探测本身不会误杀一个健康浏览器。
    """
    if driver is None:
        return False
    try:
        driver.window_handles
    except Exception as exc:
        return not is_session_lost(exc)
    return True


def get_resource_path(relative_path: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


def get_data_path(filename: str = "") -> str:
    if sys.platform == "win32":
        base_path = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        base_path = os.path.join(base_path, APP_SLUG)
    elif sys.platform == "darwin":
        base_path = os.path.join(os.path.expanduser("~/Library/Application Support"), APP_SLUG)
    else:
        base_path = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")), APP_SLUG)
    return os.path.join(base_path, filename) if filename else base_path


DATA_DIR = get_data_path()
PACKAGED_CHROMEDRIVER_PATH = get_resource_path("chromedriver.exe")
DEFAULT_CHROMEDRIVER_PATH = get_data_path("chromedriver.exe")
CHROMEDRIVER_PATH = DEFAULT_CHROMEDRIVER_PATH if os.path.exists(DEFAULT_CHROMEDRIVER_PATH) else PACKAGED_CHROMEDRIVER_PATH


def default_config(today: Optional[date] = None, now: Optional[datetime] = None) -> dict:
    return contract_default_config(today=today, now=now)


def validate_config(raw_config: dict) -> dict:
    return contract_validate_config(raw_config)


def state_to_payload(state: RailWatchState) -> dict:
    return {
        "brand_name": state.brand_name,
        "data_dir_name": state.data_dir_name,
        "pages": list(state.pages),
        "phase": state.phase.value,
        "environment_ready": state.environment_ready,
        "login_ready": state.login_ready,
        "query_ready": state.query_ready,
        "monitoring": state.monitoring,
        "auto_submit_enabled": state.auto_submit_enabled,
        "auto_alternate_enabled": state.auto_alternate_enabled,
        "risk_level": state.risk_level,
        "status_message": state.status_message,
        "error_message": state.error_message,
        "current_config": dict(state.current_config),
        "hits": [ticket_hit_to_payload(hit) for hit in state.hits],
        "summary": state.summary(),
        "task": dict(state.task),
        "order": dict(state.order),
    }


def ticket_hit_to_payload(hit: TicketHit) -> dict:
    return {
        "train_code": hit.train_code,
        "seat_type": hit.seat_type,
        "status": hit.status,
        "source": hit.source,
        "detail": hit.detail,
        "label": hit.label(),
    }


def idle_browser_command(method):
    """Reserve the browser before scheduling a task or another browser command."""
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._task_lock:
            if self.is_monitoring or self._browser_busy:
                raise RuntimeError("监控运行中或浏览器正在操作，请等待当前操作结束。")
            self._browser_busy = True
        try:
            with self._driver_lock:
                return method(self, *args, **kwargs)
        finally:
            with self._task_lock:
                self._browser_busy = False
    return call


class RailWatchBridge:
    """Wraps existing RailWatch core behavior behind a frontend-neutral API."""

    def __init__(self, data_dir: str = DATA_DIR, event_callback: Optional[Callable[[dict], None]] = None):
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self.event_callback = event_callback or (lambda event: None)
        self.state = RailWatchState.initial()
        self.driver = None
        self.behavior_simulator = None
        self.device_id_protector = None
        self._task = None
        self._task_lock = threading.RLock()
        self._browser_busy = False
        self._event_context = threading.local()
        self._pending_human_action: Optional[str] = None
        self._driver_lock = threading.RLock()
        self.worker_threads: List[threading.Thread] = []
        self.log_entries: List[Dict[str, str]] = []
        self._log_lock = threading.RLock()
        self.query_results: List[dict] = []
        self.config_manager = ConfigManager(self.data_dir) if CORE_AVAILABLE and ConfigManager else None
        self.chromedriver_path = CHROMEDRIVER_PATH
        self._chromedriver_repair_failed = False
        self.server_time_sync: ServerTimeSync = get_server_time_sync(log_callback=self.log)
        self.notification_service = NotificationService(self._load_notification_settings(), log_callback=self.log)
        self.order_journal = OrderJournal(os.path.join(data_dir, "orders.sqlite3"))
        pending = self.order_journal.pending()
        if pending:
            stage = "alternate_pending_payment" if pending["result"]["status"] == "pending_payment" and pending["intent"]["kind"] == "alternate" else pending["result"]["status"]
            self.state = replace(self.state, order={**pending["result"], "stage": stage, "label": STAGES[stage], "intent": pending["intent"], "recovery_required": True},
                                 status_message="发现未完成订单，请继续处理并核对官方订单", risk_level="warning")
        self._monitor_last_tick = 0.0
        self._monitor_heartbeat_thread: Optional[threading.Thread] = None
        self._param_filler: Optional[Callable[[str, str, str], bool]] = None
        self._keep_alive_last_state: Optional[str] = None
        self._keep_alive_unknown_count = 0

    @property
    def is_monitoring(self):
        return bool(self._task and self._task.active)

    @is_monitoring.setter
    def is_monitoring(self, active):
        # Compatibility for embedded callers; production starts through start_monitor.
        if active and not self.is_monitoring:
            self._task = MonitorTask({})
        elif not active and self._task:
            self._task.cancel.set()
            if self._task.thread is None:
                self._task.done.set()

    def _transition(self, task, status=None, next_query_at=None, message=None):
        with self._task_lock:
            if task is not self._task:
                return
            task.last_tick = time.monotonic()
            self._monitor_last_tick = time.time()
            if task.cancel.is_set() and status not in ("stopping", "stopped", "human_action", "error", "hit"):
                return
            if status is None:
                return
            task.status, task.next_query_at = status, next_query_at
            task.sequence += 1
            risk = {"error":"critical", "human_action":"warning", "hit":"success", "stopped":"notice"}.get(status, "active")
            phase = {"error": AppPhase.ERROR, "stopped": AppPhase.QUERY_READY, "human_action": AppPhase.QUERY_READY,
                     "hit": AppPhase.ALTERNATE if self.state.phase == AppPhase.ALTERNATE else AppPhase.HIT}.get(status, AppPhase.MONITORING)
            self.state = replace(self.state, task=task.payload(), current_config=deepcopy(task.config),
                                 phase=phase, monitoring=task.active, risk_level=risk,
                                 status_message=message or {"preparing":"准备监控", "waiting":"等待定时启动", "querying":"查询中", "backoff":"等待下一次查询", "stopping":"正在停止监控...", "stopped":"监控已停止"}.get(status, self.state.status_message))
            self.emit_state()

    def _task_wait(self, task, seconds):
        deadline = time.monotonic() + max(0, seconds)
        while not task.cancel.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            self._transition(task)
            task.cancel.wait(min(remaining, 0.2))

    def _valid_dates(self, config, timestamp=None, announce=False):
        dates, skipped = eligible_travel_dates(config["date"], config.get("date_range", "单日"), beijing_now(timestamp).date())
        if announce:
            for item in skipped:
                self.log(f"跳过 {item['date']}：{item['reason']}", "WARN")
        if not dates:
            raise ValueError("所有出行日期均无效，请修改日期或日期范围。")
        return dates

    def emit(self, name: str, payload: dict) -> None:
        owner = getattr(self._event_context, "run_id", None)
        if owner and (not self._task or owner != self._task.run_id):
            return
        if owner:
            payload = {**payload, "run_id": owner}
        self.event_callback({"event": name, "payload": payload})

    def emit_state(self, state: Optional[RailWatchState] = None) -> dict:
        if state is not None:
            self.state = state
        payload = state_to_payload(self.state)
        self.emit("state", payload)
        return payload

    def log(self, message: str, level: str = "INFO") -> dict:
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "message": str(message),
        }
        with self._log_lock:
            self.log_entries.append(entry)
            if len(self.log_entries) > MAX_LOG_ENTRIES:
                del self.log_entries[: len(self.log_entries) - MAX_LOG_ENTRIES]
            self.emit("log", entry)
        return entry

    def get_runtime_info(self) -> dict:
        chrome_version = get_chrome_version_info() if CD_MANAGER_AVAILABLE and get_chrome_version_info else "未知"
        data_dir_status = inspect_data_dir(self.data_dir)
        connectivity = probe_connectivity()
        return {
            "app_display_name": APP_DISPLAY_NAME,
            "app_version": get_app_version(),
            "app_slug": APP_SLUG,
            "pages": list(APP_PAGES),
            "data_dir": self.data_dir,
            "data_dir_writable": data_dir_status["data_dir_writable"],
            "data_dir_free_bytes": data_dir_status["data_dir_free_bytes"],
            "chromedriver_path": self.chromedriver_path,
            "chrome_version": chrome_version,
            "core_available": CORE_AVAILABLE,
            "core_import_error": str(CORE_IMPORT_ERROR) if CORE_IMPORT_ERROR else "",
            "selenium_available": SELENIUM_AVAILABLE,
            "chromedriver_manager_available": CD_MANAGER_AVAILABLE,
            "network_ok": connectivity["network_ok"],
            "network_label": connectivity["network_label"],
            "railway_ok": connectivity["railway_ok"],
            "railway_label": connectivity["railway_label"],
            "proxy_configured": connectivity["proxy_configured"],
            "proxy_label": connectivity["proxy_label"],
            "proxy_value": str(connectivity.get("proxy_value", "")),
            "automation_route": AUTOMATION_ROUTE,
            "server_time_offset_seconds": round(self.server_time_sync.offset_seconds, 3),
            "server_time_last_error": self.server_time_sync.last_error,
            "notification_settings": self.notification_service.settings,
            "date_policy": {"presale_window_days": PRESALE_WINDOW_DAYS, "timezone": "Asia/Shanghai"},
            "state": state_to_payload(self.state),
        }

    def load_config(self) -> dict:
        config = default_config()
        if self.config_manager:
            saved = self.config_manager.load()
            if saved:
                config.update(saved.to_dict())
                self.log("已加载保存的设置。", "SUCCESS")
        if not self.is_monitoring:
            self.state = self.state.with_safety(bool(config["auto_submit"]), bool(config["auto_alternate"]))
        self.emit_state()
        return validate_config(config)

    def save_config(self, raw_config: dict) -> dict:
        config = validate_config(raw_config)
        manager = self._require_config_manager()
        query_config = self._make_query_config(config_for_persistence(config))
        if manager.save(query_config):
            self.log("设置已保存。", "SUCCESS")
            return config
        self.log("保存设置失败。", "ERROR")
        raise RuntimeError("保存设置失败。")

    def _ensure_matching_chromedriver(self, force: bool = False) -> None:
        """Chrome 会自动升级，本地 ChromeDriver 可能落后于已安装 Chrome；发现大版本不匹配时自动补齐。

        force=True 供「检查环境」显式触发，即使上一次自动修复失败也重试；
        普通启动路径不强制重试，避免离线时反复等待下载超时。
        """
        if not CD_MANAGER_AVAILABLE or not detect_chrome_version or not download_and_install_chromedriver:
            return
        if self._chromedriver_repair_failed and not force:
            return
        chrome_major = detect_chrome_version()
        if not chrome_major:
            return

        driver_version = None
        if detect_chromedriver_version and os.path.exists(self.chromedriver_path):
            driver_version = detect_chromedriver_version(self.chromedriver_path)
        driver_major = driver_version.split(".")[0] if driver_version else None
        if driver_major == chrome_major:
            self._chromedriver_repair_failed = False
            return

        if driver_major:
            self.log(
                f"ChromeDriver ({driver_version}) 与已安装 Chrome ({chrome_major}) 大版本不匹配，正在自动下载匹配版本...",
                "WARN",
            )
        else:
            self.log(f"未找到可用的 ChromeDriver，正在自动下载 Chrome {chrome_major} 对应版本...", "WARN")
        try:
            dest_path = download_and_install_chromedriver(
                target_dir=self.data_dir,
                major_version=chrome_major,
                log_callback=self.log,
            )
        except Exception as exc:
            self._chromedriver_repair_failed = True
            self.log(f"自动下载 ChromeDriver 失败，将继续使用现有配置: {exc}", "WARN")
            return
        self.chromedriver_path = dest_path
        self._chromedriver_repair_failed = False
        self.emit("labels", {"chromedriver_path": dest_path, "chrome_version": f"Chrome {chrome_major}"})
        self.log("ChromeDriver 已自动更新到匹配版本。", "SUCCESS")

    @idle_browser_command
    def check_environment(self) -> dict:
        if self.is_monitoring:
            raise RuntimeError("监控运行中，请先停止监控后再检查环境。")
        try:
            self.log("正在检查 Python、Selenium 和 ChromeDriver...")
            if not SELENIUM_AVAILABLE:
                detail = f"（{SELENIUM_IMPORT_ERROR}）" if SELENIUM_IMPORT_ERROR else ""
                raise RuntimeError(f"Selenium 未安装或加载失败{detail}，请运行 pip install -r requirements.txt。")
            self.log(f"Python {sys.version.split()[0]}")
            self.log(f"平台 {sys.platform}")

            self._ensure_matching_chromedriver(force=True)

            chrome_ver = detect_chrome_version() if CD_MANAGER_AVAILABLE and detect_chrome_version else None
            if chrome_ver:
                self.log(f"Chrome 版本: {chrome_ver}")
            else:
                self.log("未检测到 Chrome 浏览器。", "WARN")

            if os.path.exists(self.chromedriver_path):
                self.log(f"ChromeDriver 已找到: {self.chromedriver_path}", "SUCCESS")
            else:
                self.log("未找到 ChromeDriver。", "WARN")
                if chrome_ver and CD_MANAGER_AVAILABLE:
                    self.log(f"提示: 点击「下载 ChromeDriver」自动获取 Chrome {chrome_ver} 对应版本。", "INFO")
                else:
                    self.log("提示: 请手动下载 ChromeDriver: https://googlechromelabs.github.io/chrome-for-testing/", "INFO")

            with self._driver_lock:
                if self.driver and not driver_session_alive(self.driver):
                    self.log("受控浏览器已关闭，将重新启动 Chrome 进行环境检查。", "WARN")
                    self._release_driver()
                if self.driver:
                    self.driver.execute_script("return document.readyState")
                    return self.emit_state(self.state.with_environment(True, "环境就绪"))
                driver = self._ensure_driver(test_only=True)
                driver.quit()
                if self.driver is driver:
                    self.driver = None
            return self.emit_state(self.state.with_environment(True, "环境就绪"))
        except Exception as exc:
            error_msg = str(exc)
            lowered = error_msg.lower()
            if "version" in lowered or "session not created" in lowered:
                if CD_MANAGER_AVAILABLE:
                    error_msg += "\n\n可能是 ChromeDriver 版本与 Chrome 不匹配，点击「下载 ChromeDriver」自动获取正确版本。"
                else:
                    error_msg += "\n\n请下载与 Chrome 版本匹配的 ChromeDriver: https://googlechromelabs.github.io/chrome-for-testing/"
            message = f"环境检查失败: {error_msg}"
            self.log(message, "ERROR")
            return self.emit_state(self.state.with_error(message))

    @idle_browser_command
    def download_chromedriver(self) -> dict:
        if not CD_MANAGER_AVAILABLE or not detect_chrome_version or not download_and_install_chromedriver:
            raise RuntimeError(
                "chromedriver_manager 模块不可用。请手动下载 ChromeDriver：https://googlechromelabs.github.io/chrome-for-testing/"
            )
        chrome_ver = detect_chrome_version()
        if not chrome_ver:
            self.log("未检测到 Chrome 浏览器，无法自动匹配版本。", "WARN")
            self.log("请先安装 Chrome: https://www.google.com/chrome/", "WARN")
            return {"chromedriver_path": self.chromedriver_path, "chrome_version": ""}
        dest_dir = self.data_dir
        dest_path = download_and_install_chromedriver(
            target_dir=dest_dir,
            major_version=chrome_ver,
            log_callback=self.log,
        )
        self.chromedriver_path = dest_path
        self.emit("labels", {"chromedriver_path": dest_path, "chrome_version": f"Chrome {chrome_ver}"})
        self.log("ChromeDriver 下载完成，可以运行环境检查。", "SUCCESS")
        return {"chromedriver_path": dest_path, "chrome_version": f"Chrome {chrome_ver}"}

    @idle_browser_command
    def open_login(self) -> dict:
        if self.is_monitoring:
            raise RuntimeError("监控运行中，请先停止监控后再打开登录页。")
        try:
            with self._driver_lock:
                try:
                    driver = self._ensure_driver()
                    driver.get(LOGIN_URL)
                except Exception as exc:
                    if not is_session_lost(exc):
                        raise
                    # 窗口是在应用之外被关掉的（或浏览器刚刚崩溃）：放掉旧句柄后新开一个，
                    # 而不是把无效会话错误一直抛给用户。
                    self.log("浏览器窗口已被关闭，正在重新打开登录页。", "WARN")
                    self._release_driver()
                    driver = self._ensure_driver()
                    driver.get(LOGIN_URL)
                self.log("登录页面已打开，请在浏览器中完成 12306 登录。")
                return self.emit_state(self.state.with_login_opened("登录页面已打开，请在浏览器中完成 12306 登录。"))
        except Exception as exc:
            return self.emit_state(self.state.with_error(f"打开登录页失败: {exc}"))

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

    @idle_browser_command
    def check_login(self) -> dict:
        if self.is_monitoring:
            raise RuntimeError("监控运行中，请先停止监控后再检查登录。")
        if not self.driver:
            return self.emit_state(self.state.with_login_verified(False, "请先打开登录页。"))
        try:
            with self._driver_lock:
                result = self.driver.execute_async_script(
                    """
                    const done = arguments[arguments.length - 1];
                    fetch('/otn/login/checkUser', {credentials: 'include'})
                      .then(response => response.json())
                      .then(data => done(data))
                      .catch(() => done({data: {flag: false}}));
                    """
                )
            ready = bool(((result or {}).get("data") or {}).get("flag"))
            if ready:
                self._record_device_id_after_login()
                self.log("12306 登录状态已验证。", "SUCCESS")
                return self.emit_state(self.state.with_login_verified(True, "登录已验证"))
            return self.emit_state(self.state.with_login_verified(False, "12306 登录未完成。"))
        except Exception as exc:
            return self.emit_state(self.state.with_login_verified(False, f"登录状态检查失败: {exc}"))

    @idle_browser_command
    def analyze_query(self, raw_config: dict) -> dict:
        if self.is_monitoring:
            raise RuntimeError("监控运行中，请先停止监控后再分析。")
        config = validate_config(raw_config)
        self.save_config(config)
        self.state = self.state.with_safety(config["auto_submit"], config["auto_alternate"])
        self.emit_state()
        with self._driver_lock:
            try:
                if not CORE_AVAILABLE or PageAnalyzer is None:
                    raise RuntimeError(f"核心模块不可用: {CORE_IMPORT_ERROR}")
                driver = self._ensure_driver()
                analyzer = PageAnalyzer(driver, log_callback=self.log, base_dir=self.data_dir)
                rows = []
                queries = []
                for travel_date in self._valid_dates(config, announce=True):
                    date_config = {**config, "date": travel_date}
                    date_rows = analyzer.open_fill_query_and_analyze(date_config)
                    if date_rows is None:
                        raise RuntimeError("查询未完成")
                    queries.append({**getattr(analyzer, "last_query", {}), "date": travel_date})
                    if date_rows:
                        rows.extend([{**row, "date": travel_date} for row in date_rows])
                self.query_results = rows
                self.emit("results", {"rows": rows, "queries": queries, "fetched_at": time.time()})
                return self.emit_state(self.state.with_query_ready(True, config, f"已解析 {len(rows)} 行查询结果"))
            except Exception as exc:
                return self.emit_state(self.state.with_error(f"查询分析失败: {exc}"))

    def start_monitor(self, raw_config: dict, confirmed: bool = False) -> dict:
        requested_at = time.time()
        config = validate_config(raw_config)
        if self.order_journal.pending():
            raise RuntimeError("存在待支付或待核对订单，请点击继续处理，不能重复启动提交。")
        if config.get("auto_submit") or config.get("auto_alternate"):
            from railwatch_config_contract import parse_passenger_names
            names = parse_passenger_names(config.get("passengers", ""))
            if not names or len(names) != len(set(names)) or not config.get("seat_keyword", "").strip() or not config.get("train_code", "").strip():
                raise ValueError("自动提交需要明确的目标车次、可接受席别及不重复的乘车人姓名。")
            if config.get("auto_alternate") and len(names) > 19:
                raise ValueError("候补单最多支持19名乘车人。")
        confirmation = self._automation_confirmation(config)
        if confirmation and not confirmed:
            return confirmation
        with self._task_lock:
            if self.is_monitoring or self._browser_busy:
                raise RuntimeError("监控运行中或正在停止，请等待当前任务退出。")
            target = resolve_sale_timestamp(config) if config.get("timer_enabled") else None
            self._valid_dates(config, max(requested_at, target or requested_at), announce=True)
            task = MonitorTask(config, target, started_at=requested_at)
            self._task = task
            self.order_journal.mark(task.run_id, "target_sale", detail={"target_at": target})
            self.state = self.state.with_safety(config["auto_submit"], config["auto_alternate"]).with_monitoring(True)
            self._transition(task, "preparing")
            task.thread = threading.Thread(target=lambda: self._monitor_worker(deepcopy(config), task), name=f"railwatch-monitor-{task.run_id[:8]}", daemon=True)
            self.worker_threads.append(task.thread)
            task.thread.start()
            threading.Thread(target=lambda: self._finish_task(task), name="railwatch-task-finalizer", daemon=True).start()
            return state_to_payload(self.state)

    def dismiss_order(self, intent_id: str, confirmed: bool = False) -> dict:
        with self._task_lock:
            if self.is_monitoring or self._browser_busy:
                raise RuntimeError("请等待当前监控或浏览器任务退出后再结束核对。")
            pending = self.order_journal.pending()
            if not pending or not intent_id or pending["intent"]["intent_id"] != intent_id:
                raise ValueError("待核对记录已变化，请刷新后重试。")
            if not confirmed:
                return {"requires_confirmation": True, "title": "结束本次核对",
                        "message": "结束后可重新启动监控，并保留本地历史记录。此操作不会取消12306订单；如曾提交或手动下单，请先在官方页面核对并处理。是否继续？"}
            self.order_journal.dismiss(intent_id)
            self._task = None
            self._pending_human_action = None
            self.state = replace(self.state, order={}, task={}, monitoring=False,
                                 phase=AppPhase.QUERY_READY, risk_level="notice", error_message="",
                                 status_message="已结束本次核对，可重新启动监控")
            self.log("已结束本次本地订单核对，保留历史记录，可重新启动监控。", "INFO")
            result = self.emit_state()
            self.emit("orderDismissed", {"intent_id": intent_id})
            return result

    def continue_order(self) -> dict:
        """Resume only the saved intent; never replay an uncertain submission."""
        with self._task_lock:
            if self.is_monitoring or self._browser_busy:
                raise RuntimeError("请等待当前浏览器任务退出后再继续处理")
            pending = self.order_journal.pending()
            if not pending:
                raise ValueError("没有待处理订单")
            task = MonitorTask(pending["config"])
            self._task = task
            self._transition(task, "reconciling", message="正在核对原订单")
            task.thread = threading.Thread(target=lambda: self._resume_order_worker(task, pending), daemon=True)
            task.thread.start()
            threading.Thread(target=lambda: self._finish_task(task), daemon=True).start()
            return state_to_payload(self.state)

    def _resume_order_worker(self, task, pending):
        self._event_context.run_id = task.run_id
        self._start_monitor_heartbeat()
        intent = OrderIntent.from_dict(pending["intent"])
        try:
            with self._driver_lock:
                driver = self._ensure_driver()
                driver.set_page_load_timeout(15)
                driver.set_script_timeout(3)
                with guard_browser(driver, task, lambda: self._transition(task)):
                    page = OrderPage(driver, task.cancel.is_set, lambda seconds: self._task_wait(task, seconds),
                                     lambda stage, detail=None: self.order_journal.mark(task.run_id, stage, intent.intent_id, detail), log=self.log)
                    known_id = pending["result"].get("order_id", "")
                    result = page.result(intent, submitted=True, known_id=known_id)
                    if result.status == "unknown" and page.snapshot().get("formReady") and self.order_journal.claim_resume(task.run_id, intent.intent_id):
                        try:
                            result = page.alternate(None, intent) if intent.kind == "alternate" else page.regular(None, intent, seat_preference=task.config.get("seat_prefer", "无偏好"))
                        finally:
                            self.order_journal.release_resume(task.run_id, intent.intent_id)
                    elif result.status in ("unknown", "verification"):
                        result = page.reconcile(intent, known_id=known_id, navigate=True,
                                                allow_empty=not self.order_journal.submission_started(intent.intent_id))
                    result = self.order_journal.record(intent, result)
                    self._handle_order(intent, result)
                    if result.status in ("pending_payment", "active"):
                        self._observe_order(task, driver, intent, result)
                    elif result.status in ("unknown", "verification"):
                        self._handle_human_action({"message": result.reason})
        except TaskCancelled:
            pass
        except Exception:
            self._handle_human_action({"message": "无法恢复浏览器订单，请在官方订单页面核对后继续处理。"})
        finally:
            self._event_context.run_id = None

    def _handle_order(self, intent, result):
        stage = "alternate_pending_payment" if result.status == "pending_payment" and intent.kind == "alternate" else result.status
        payload = {**result.payload(), "stage": stage, "label": STAGES[stage],
                   "intent": {"intent_id": intent.intent_id, "kind": intent.kind, "train_code": intent.train_code,
                              "date": intent.date, "seat": intent.seat}, "updated_at": time.time(), "recovery_required": result.status in ("unknown", "verification")}
        self.state = replace(self.state, order=payload, status_message=STAGES[stage])
        self.emit("orderStage", payload)
        if self._task:
            self._transition(self._task, stage, message=STAGES[stage])
        else:
            self.emit_state()
        if result.status in ("pending_payment", "active", "fulfilled"):
            message = "请在官方页面立即完成预付款；支付后候补才生效。" if stage == "alternate_pending_payment" else "请在官方页面完成支付。" if stage == "pending_payment" else "已根据匹配的官方订单确认状态。"
            self.emit("notify", {"title": STAGES[stage], "message": message, "priority": "urgent"})
            self._notify_async(STAGES[stage], message)

    def _notify_async(self, title, message):
        threading.Thread(target=lambda: self.notification_service.notify(title, message, urgent=True),
                         name="railwatch-notify", daemon=True).start()

    def _observe_order(self, task, driver, intent, previous):
        # Read the page only; never refresh or leave an interactive payment page.
        page = OrderPage(driver, task.cancel.is_set, lambda seconds: self._task_wait(task, seconds))
        unknown_since = None
        while not task.cancel.is_set():
            self._task_wait(task, 1)
            if task.cancel.is_set(): break
            result = page.result(intent, submitted=True, known_id=previous.order_id)
            if result.status == "unknown":
                unknown_since = unknown_since or time.monotonic()
                if time.monotonic() - unknown_since > 30:
                    self._handle_human_action({"message": "请完成支付后打开官方订单详情，再点击继续处理核对生效状态。"})
                    break
                continue
            unknown_since = None
            if result.status != previous.status:
                result = self.order_journal.record(intent, result)
                self.order_journal.mark(task.run_id, result.status, intent.intent_id)
                self._handle_order(intent, result)
            previous = result
            if result.status not in ("pending_payment",):
                break  # Official queue continues after the local observer stops.

    def _finish_task(self, task):
        if task.thread:
            task.thread.join()
        with self._task_lock:
            task.done.set()
            if task is self._task:
                terminal = task.status if task.status in ("human_action", "error", "hit", *STAGES.keys()) else "stopped"
                self._transition(task, terminal)

    def stop_monitor(self) -> dict:
        with self._task_lock:
            if self.is_monitoring:
                self._task.cancel.set()
                self._transition(self._task, "stopping")
            return self.emit_state()

    def system_resumed(self) -> dict:
        if self.is_monitoring:
            self._handle_human_action({"message": "电脑已从休眠恢复，请核对时间、登录及订单状态后继续。"})
        return self.emit_state()

    @idle_browser_command
    def close_browser(self, confirmed: bool = False) -> dict:
        if not self.driver:
            return {"closed": False}
        if self.is_monitoring:
            raise RuntimeError("监控运行中，请先停止监控后再关闭浏览器。")
        if not confirmed:
            return {
                "requires_confirmation": True,
                "title": "关闭浏览器",
                "message": "是否关闭受控的 Chrome 会话？",
            }
        try:
            with self._driver_lock:
                driver, self.driver = self.driver, None
                error = self._dispose_driver(driver)
                if error is not None and not is_session_lost(error):
                    raise error
                if error is not None:
                    self.log("浏览器窗口已被关闭，残留会话已释放。", "WARN")
            self.log("浏览器已关闭。", "SUCCESS")
            return {"closed": True}
        except Exception as exc:
            self.log(f"关闭浏览器失败: {exc}", "ERROR")
            raise

    @idle_browser_command
    def clear_local_data(self, confirmed: bool = False) -> dict:
        if not confirmed:
            return {
                "requires_confirmation": True,
                "title": "清除本地数据",
                "message": "此操作将删除本地数据目录中的 RailWatch 配置、日志和 Chrome 配置。源代码目录不受影响。",
            }
        if self.is_monitoring:
            raise RuntimeError("监控运行中，请先停止监控后再清除本地数据。")
        if self.order_journal.pending():
            raise RuntimeError("仍有未完成订单，请先核对官方订单状态，避免清除记录后重复提交。")
        target = os.path.abspath(self.data_dir)
        if os.path.basename(target) != APP_SLUG:
            self.log(f"拒绝清除意外的数据目录: {target}", "ERROR")
            raise RuntimeError(f"拒绝清除意外的数据目录: {target}")
        if self.driver:
            self._release_driver()
        if os.path.exists(target):
            shutil.rmtree(target)
        os.makedirs(target, exist_ok=True)
        self.order_journal = OrderJournal(os.path.join(target, "orders.sqlite3"))
        self.state = replace(self.state, order={})
        self.log("本地 RailWatch 数据已清除。", "SUCCESS")
        return {"cleared": True, "data_dir": target}

    def export_log(self, path: Optional[str] = None, entries: Optional[list] = None) -> dict:
        if entries is None:
            with self._log_lock:
                entries = list(self.log_entries)
        else:
            # The desktop snapshot includes stderr and paused events that are
            # not necessarily present in this runtime's in-memory buffer.
            if not isinstance(entries, list) or len(entries) > MAX_LOG_ENTRIES * 2:
                raise ValueError("导出日志数据无效。")
            if any(not isinstance(entry, dict) or any(not isinstance(entry.get(key), str)
                   for key in ("time", "level", "message")) for entry in entries):
                raise ValueError("导出日志条目无效。")
            entries = [{key: entry[key] for key in ("time", "level", "message")} for entry in entries]
        export_path = path or os.path.join(self.data_dir, f"railwatch-events-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt")
        os.makedirs(os.path.dirname(export_path) or self.data_dir, exist_ok=True)
        with open(export_path, "w", encoding="utf-8") as file:
            for entry in entries:
                file.write(f"[{entry['time']}] [{entry['level']}] {entry['message']}\n")
        self.log(f"事件已导出到 {export_path}", "SUCCESS")
        return {"path": export_path}

    def clear_log(self) -> dict:
        with self._log_lock:
            self.log_entries.clear()
            self.emit("logsCleared", {})
        return {"cleared": True}

    def load_preferences(self) -> dict:
        return {
            "theme": load_theme_preference(self.data_dir),
            "notification_settings": self._load_notification_settings(),
        }

    def save_preferences(self, theme: str, notification_settings: Optional[dict] = None) -> dict:
        selected = normalize_theme(theme)
        save_theme_preference(self.data_dir, selected)
        if notification_settings is not None:
            self._save_notification_settings(notification_settings)
            self.notification_service.update_settings(notification_settings)
        return {
            "theme": selected,
            "notification_settings": self.notification_service.settings,
        }

    def sync_server_time(self) -> dict:
        offset = self.server_time_sync.sync(force=True)
        return {
            "offset_seconds": round(offset, 3),
            "server_time": self.server_time_sync.server_now().isoformat(timespec="seconds"),
            "last_error": self.server_time_sync.last_error,
            "clock_source": "system",
            "http_uncertainty_seconds": self.server_time_sync.uncertainty_seconds,
        }

    def _notification_settings_path(self) -> str:
        return os.path.join(self.data_dir, NOTIFICATION_SETTINGS_FILE)

    def _load_notification_settings(self) -> dict:
        path = self._notification_settings_path()
        if not os.path.exists(path):
            return merge_notification_settings()
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return merge_notification_settings(payload if isinstance(payload, dict) else {})
        except (OSError, json.JSONDecodeError):
            return merge_notification_settings()

    def _save_notification_settings(self, settings: dict) -> None:
        path = self._notification_settings_path()
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(merge_notification_settings(settings), handle, ensure_ascii=False, indent=2)

    def _monitor_worker(self, config: dict, task=None) -> None:
        task = task or self._task or MonitorTask(config)
        if self._task is not None and task is not self._task:
            return
        if not task.config:
            task.config = deepcopy(config)
        self._task = task
        self._event_context.run_id = task.run_id
        self._pending_human_action = None
        self._keep_alive_last_state = None
        self._keep_alive_unknown_count = 0
        self._transition(task)
        self._start_monitor_heartbeat()
        try:
            # Freeze the date before every potentially blocking initialization step.
            if config.get("timer_enabled") and task.target_timestamp is None:
                task.target_timestamp = resolve_sale_timestamp(config)
            if task.cancel.is_set():
                return
            if not CORE_AVAILABLE or TicketMonitor is None:
                raise RuntimeError(f"核心模块不可用: {CORE_IMPORT_ERROR}")
            with self._driver_lock:
                driver = self._ensure_driver()
                with guard_browser(driver, task, lambda: self._transition(task)):
                    driver.set_page_load_timeout(30)
                    driver.set_script_timeout(3)
                    self._transition(task)
                    if task.cancel.is_set():
                        return
                    self._param_filler = self._make_param_filler(driver)
                    if task.cancel.is_set():
                        return
                    if not self._prepare_query_page(driver, config, task):
                        return
                    if config.get("auto_submit") or config.get("auto_alternate"):
                        self._send_keep_alive()
                        task.last_login_check = time.monotonic()
                        if not self.state.login_ready:
                            self._handle_human_action({"message": "自动提交前未能确认登录有效，请在官方页面完成登录并重新检查。"})
                            return
                    if not self._check_session_for_task(task):
                        return
                    prepared_at = time.time()
                    self.order_journal.mark(task.run_id, "prepared", detail={"prepared_at": prepared_at, "target_at": task.target_timestamp})
                    if task.target_timestamp and prepared_at > task.target_timestamp - 10:
                        self.log("准备完成时已进入最后10秒或超过起售点；本次继续执行，但不能计作准点准备完成。", "WARN")
                    if config.get("timer_enabled"):
                        config["_target_timestamp"] = task.target_timestamp
                        if not self._wait_for_target_time(config):
                            return
                    if task.cancel.is_set():
                        return
                    self._valid_dates(task.config, announce=True)
                    monitor = TicketMonitor(
                        driver, config, log_callback=self.log, stop_check=task.cancel.is_set,
                        notify_callback=self._handle_notify, progress_callback=self._handle_progress,
                        on_hit=self._handle_hit, human_action_callback=self._handle_human_action,
                        server_time_sync=self.server_time_sync, param_filler=self._param_filler,
                        wait_callback=lambda seconds: self._task_wait(task, seconds),
                        tick_callback=lambda **kwargs: self._transition(task, **kwargs),
                        session_check=lambda: self._check_session_for_task(task),
                        date_provider=lambda: self._valid_dates(task.config),
                        order_journal=self.order_journal, on_order=self._handle_order, run_id=task.run_id,
                    )
                    monitor.run()
                    pending = self.order_journal.pending()
                    if pending and not task.cancel.is_set() and pending["result"]["status"] == "pending_payment":
                        self._observe_order(task, driver, OrderIntent.from_dict(pending["intent"]), OrderResult(**pending["result"]))
        except TaskCancelled:
            pass
        except Exception as exc:
            if task is self._task and not task.cancel.is_set():
                self.state = self.state.with_error(f"监控失败: {exc}")
                self._transition(task, "error")
        finally:
            task.done.set()
            if task.thread is None:
                self._finish_task(task)
            self._event_context.run_id = None

    def _prepare_query_page(self, driver, config, task):
        for attempt in range(3):
            if task.cancel.is_set():
                return False
            result = self._fill_query_page_from_config(config) if attempt == 0 and "/otn/leftTicket/" in str(driver.current_url) else self._prewarm_query_page(driver, config)
            self._transition(task)
            if result:
                return True
            result = fill_result(result)
            if result.status == "config_error":
                raise ValueError(result.reason)
            self._task_wait(task, 1)
        raise RuntimeError("连续三次无法准备查询页")

    def _check_session_for_task(self, task):
        if task.cancel.is_set():
            return False
        if task.config.get("keep_alive") and time.monotonic() - task.last_login_check >= 60:
            if task.target_timestamp is not None and task.target_timestamp - 10 <= time.time() <= task.target_timestamp + 5:
                return True
            self._send_keep_alive()
            task.last_login_check = time.monotonic()
        return not task.cancel.is_set()

    def _wait_for_target_time(self, config: dict) -> bool:
        target = config.get("_target_timestamp")
        if target is None:
            target = resolve_sale_timestamp(config)
        wait_until = target
        self.log(f"定时启动：{beijing_now(target).isoformat(timespec='seconds')}")
        if self._task:
            self._transition(self._task, "waiting", next_query_at=wait_until)
        if not self._wait_for_target_timestamp(wait_until, config):
            return False
        now = self.server_time_sync.server_timestamp()
        if now > target + float(config.get("burst_window_seconds", 45)):
            self.log("初始化已超过冲刺窗口，立即继续普通监控。", "WARN")
        # A date which opens at midnight must not be queried during the previous day's prepare window.
        if self._task:
            try:
                self._valid_dates(self._task.config)
            except ValueError:
                if now < target:
                    return self._wait_for_target_timestamp(target, config)
                raise
        return True

    def _send_keep_alive(self) -> None:
        if not self.driver:
            return
        try:
            self.driver.set_script_timeout(3)
            result = self.driver.execute_async_script(LOGIN_CHECK_JS)
        except Exception:
            result = "unknown"
        if result not in ("ok", "expired"):
            result = "unknown"
        self._keep_alive_unknown_count = self._keep_alive_unknown_count + 1 if result == "unknown" else 0
        previous, self._keep_alive_last_state = self._keep_alive_last_state, result
        if result == "expired" or self._keep_alive_unknown_count >= 3:
            self.state = replace(self.state, login_ready=False)
            if result != previous or self._keep_alive_unknown_count == 3:
                self._handle_human_action({"title":"需要检查登录", "message":"12306 登录态已失效，请重新登录后手动启动。" if result == "expired" else "连续三次无法确认登录状态，请检查浏览器和网络后手动启动。"})
        elif result == "ok":
            self.state = replace(self.state, login_ready=True)
            self._check_device_id_consistency()
        else:
            self.log("暂时无法确认登录状态，将在下次保活时重试。", "WARN")

    def _wait_for_target_timestamp(self, wait_until: float, config: dict) -> bool:
        wall, mono = time.time(), time.monotonic()
        deadline = mono + max(0, wait_until - wall)
        last_check, last_tick = mono, mono
        while self.is_monitoring:
            task = self._task
            if task.cancel.is_set():
                return False
            current_mono, current_wall = time.monotonic(), time.time()
            drift = (current_wall - wall) - (current_mono - mono)
            if abs(drift) > 1 or current_mono - last_tick > 5:
                self._handle_human_action({"message": "系统时间发生跳变或电脑刚从休眠恢复，请重新检查起售时间、登录和订单后启动。"})
                return False
            last_tick = current_mono
            remaining = deadline - current_mono
            if remaining <= 0:
                self.order_journal.mark(task.run_id, "scheduler_wake", detail={"target_at": wait_until, "late_ms": max(0, -remaining * 1000)})
                return True
            self._transition(task)
            # No navigation, HTTP calibration or login probes in the final ten seconds.
            if remaining > 10 and config.get("keep_alive") and current_mono - last_check >= 60:
                self._send_keep_alive()
                last_check = time.monotonic()
                task.last_login_check = last_check
            task.cancel.wait(min(0.02 if remaining <= 10 else 0.2, remaining))
        return False

    def _make_param_filler(self, driver) -> Optional[Callable[[str, str, str], bool]]:
        """构造"在查询页上同步填参"的回调；站点编码在此预热缓存，避免开抢瞬间再联网下载。"""
        if not CORE_AVAILABLE or PageAnalyzer is None:
            return None
        analyzer = PageAnalyzer(driver, log_callback=self.log, base_dir=self.data_dir)
        try:
            analyzer.resolver.load()
        except Exception as exc:
            self.log(f"站点编码预加载失败：{exc}", "WARN")
        return analyzer.fill_query_form

    def _fill_query_page_from_config(self, config: dict) -> FillResult:
        if not all(config.get(key) for key in ("from_station_cn", "to_station_cn", "date")):
            return FillResult("config_error", "出发站、到达站和日期不能为空")
        if not self._param_filler:
            return FillResult("retry", "查询参数适配器不可用")
        try:
            return fill_result(self._param_filler(str(config.get("from_station_cn", "")), str(config.get("to_station_cn", "")), str(config.get("date", ""))))
        except Exception as exc:
            return FillResult("retry", str(exc))

    def _prewarm_query_page(self, driver, config: dict) -> FillResult:
        try:
            driver.get(QUERY_URL)
            result = self._fill_query_page_from_config(config)
            if result:
                self.log("已打开查询页并同步查询参数。")
            else:
                self.log(f"查询页准备失败：{result.reason}", "WARN")
            return result
        except Exception as exc:
            return FillResult("retry", str(exc))

    def _start_monitor_heartbeat(self) -> None:
        task = self._task
        if not task:
            return
        def heartbeat():
            while not task.done.wait(5):
                if task is not self._task:
                    return
                if time.monotonic() - task.last_tick > MONITOR_HEARTBEAT_TIMEOUT_SECONDS:
                    task.cancel.set()
                    self.state = self.state.with_error("监控心跳超时，等待浏览器任务退出。")
                    self._transition(task, "error")
                    return
        self._monitor_heartbeat_thread = threading.Thread(target=heartbeat, name="railwatch-heartbeat", daemon=True)
        self._monitor_heartbeat_thread.start()

    def _stop_monitor_heartbeat(self):
        # The task's done event owns heartbeat lifetime.
        pass

    def _dispose_driver(self, driver) -> Optional[Exception]:
        """尽力关闭浏览器并结束它背后的 ChromeDriver 进程，返回 quit 时的异常。"""
        error = None
        try:
            driver.quit()
        except Exception as exc:
            error = exc
        service = getattr(driver, "service", None)
        if service is not None:
            try:
                service.stop()
            except Exception:
                pass
        return error

    def _release_driver(self) -> None:
        """丢弃缓存句柄，并清理它残留的浏览器与 ChromeDriver 进程。"""
        driver, self.driver = self.driver, None
        self.device_id_protector = None
        if driver is None:
            return
        self._dispose_driver(driver)

    def _terminate_profile_chrome(self) -> int:
        """停止仍占用本应用浏览器配置目录的残留 Chrome。

        应用被强制退出时 Selenium Chrome 会存活下来；配置目录被它占用后，
        新启动的 Chrome 会在 DevToolsActivePort 生成前直接退出。
        只按命令行里的配置目录匹配，不会波及用户自己的 Chrome 窗口。
        """
        profile_dir = os.path.join(self.data_dir, "chrome_profile_12306")
        try:
            if sys.platform == "win32":
                # Keep the path out of PowerShell source. Match the complete
                # argument, including either quoting form used by Windows.
                script = r'''
$cleanupEscapedPath = [regex]::Escape($env:RAILWATCH_CLEANUP_PROFILE.Replace('\', '/'))
$pattern = '(?:^|\s)(?:"--user-data-dir=' + $cleanupEscapedPath + '"|--user-data-dir="' + $cleanupEscapedPath + '"|--user-data-dir=' + $cleanupEscapedPath + ')(?=\s|$)'
$targets = @(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine.Replace('\', '/') -match $pattern } |
    Select-Object -ExpandProperty ProcessId)
$targets | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
$targets.Count
'''
                result = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                                        capture_output=True, text=True, timeout=30,
                                        env={**os.environ, "RAILWATCH_CLEANUP_PROFILE": profile_dir},
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                numbers = [int(part) for part in result.stdout.split() if part.strip().isdigit()]
                return numbers[-1] if numbers else 0
            result = subprocess.run(["pkill", "-f", "(^|[[:space:]])--user-data-dir="
                                    + re.escape(profile_dir) + "([[:space:]]|$)"],
                                    capture_output=True, text=True, timeout=15)
            return 1 if result.returncode == 0 else 0
        except (OSError, subprocess.SubprocessError) as exc:
            self.log(f"清理残留 Chrome 失败（{type(exc).__name__}），如反复出现请手动关闭旧的受控浏览器窗口。", "WARN")
            return 0

    @staticmethod
    def _is_profile_locked_start(exc: Exception) -> bool:
        text = str(exc)
        lowered = text.lower()
        return ("devtoolsactiveport" in lowered
                or ("session not created" in lowered and "crashed" in lowered))

    def _launch_chrome(self, options):
        service = Service(executable_path=self.chromedriver_path) if Service and os.path.exists(self.chromedriver_path) else None
        try:
            return webdriver.Chrome(options=options, service=service) if service else webdriver.Chrome(options=options)
        except Exception:
            # A failed session still leaves its ChromeDriver listening; stop it.
            if service is not None:
                try:
                    service.stop()
                except Exception:
                    pass
            raise

    def _ensure_driver(self, test_only: bool = False):
        if self.driver and not test_only:
            if driver_session_alive(self.driver):
                return self.driver
            self.log("受控浏览器已关闭，正在重新启动 Chrome。", "WARN")
            self._release_driver()
        if not SELENIUM_AVAILABLE or webdriver is None:
            raise RuntimeError("Selenium 未安装。")

        self._ensure_matching_chromedriver()

        profile_dir = os.path.join(self.data_dir, "chrome_profile_12306")
        os.makedirs(profile_dir, exist_ok=True)
        options = webdriver.ChromeOptions()
        options.add_argument(f"--user-data-dir={profile_dir}")
        options.add_argument("--profile-directory=Default")
        options.add_argument("--start-maximized")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-dev-shm-usage")
        # Same ordinary profile; no UA/screen/WebGL/canvas spoofing.
        options.add_experimental_option("prefs", {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
        })
        try:
            from anti_detect import apply_chrome_launch_hardening
            apply_chrome_launch_hardening(options)
        except Exception as harden_exc:
            self.log(f"启动硬化未应用（继续使用默认 Chrome 选项）: {harden_exc}", "WARN")
        try:
            driver = self._launch_chrome(options)
        except Exception as exc:
            if not self._is_profile_locked_start(exc):
                raise
            # One recoverable cause: a previous hard exit left Chrome holding the profile.
            self.log("检测到残留的受控 Chrome 仍占用浏览器配置，已自动清理并重试。", "WARN")
            self._terminate_profile_chrome()
            time.sleep(0.5)
            driver = self._launch_chrome(options)
        try:
            from anti_detect import inject_automation_hygiene
            if inject_automation_hygiene(driver):
                self.log("已安装浏览器环境稳定脚本（仅清除自动化特征，不伪造指纹）。")
            else:
                self.log("浏览器环境稳定脚本未注入，不影响主流程。", "WARN")
        except Exception as hygiene_exc:
            self.log(f"浏览器环境稳定脚本跳过: {hygiene_exc}", "WARN")
        # Bound a disconnected driver's transport as well as page/script waits.
        driver.command_executor.client_config.timeout = 35
        if not test_only:
            self.driver = driver
            self.device_id_protector = RailDeviceIdProtector(driver, self.log) if RailDeviceIdProtector else None
        return driver

    def _run_worker(self, name: str, target: Callable[[], None]) -> None:
        self.worker_threads = [thread for thread in self.worker_threads if thread.is_alive()]

        def run() -> None:
            try:
                target()
            except Exception as exc:
                self.emit_state(self.state.with_error(f"{name} 失败: {exc}"))

        thread = threading.Thread(target=run, name=f"railwatch-{name}", daemon=True)
        self.worker_threads.append(thread)
        thread.start()

    def _owns_context(self):
        owner = getattr(self._event_context, "run_id", None)
        return not owner or bool(self._task and owner == self._task.run_id)

    def _handle_notify(self, title: str, message: str) -> None:
        if not self._owns_context():
            return
        self.log(f"{title}: {message}", "SUCCESS")
        self._notify_async(title, message)

    def _handle_progress(self, payload: dict) -> None:
        if not self._owns_context():
            return
        self._monitor_last_tick = time.time()
        rows = payload.get("rows") or []
        self.query_results = rows
        self.emit(
            "monitorTick",
            {**payload, "loop": int(payload.get("loop", 0)), "date": str(payload.get("date", "")), "rows": rows},
        )

    def _handle_hit(self, payload: dict) -> None:
        if not self._owns_context():
            return
        source = "alternate" if payload.get("source") == "alternate" else "regular"
        hit = TicketHit(
            train_code=str(payload.get("train_code", "目标")),
            seat_type=str(payload.get("seat_type", "目标席别")),
            status=str(payload.get("status", "available")),
            source=source,
            detail=str(payload.get("message", "")),
        )
        title = str(payload.get("title", "发现目标车次/席别可用"))
        message = str(payload.get("message", ""))
        self.emit(
            "notify",
            {
                "title": title,
                "message": message,
                "hit": ticket_hit_to_payload(hit),
                "priority": "urgent",
            },
        )
        self._notify_async(title, message)
        self.emit_state(self.state.with_hit(hit, title))
        if self._task:
            self._transition(self._task, "hit", message=title)

    def _handle_human_action(self, payload: dict) -> None:
        if not self._owns_context():
            return
        title = str(payload.get("title", "需要人工操作"))
        message = str(payload.get("message", ""))
        status = f"{title}：{message}" if message else title
        self._pending_human_action = status
        if self._task:
            self._task.cancel.set()
            self._transition(self._task, "human_action", message=status)
        self.log(f"{title}: {message}", "WARN")
        self.emit(
            "humanAction",
            {
                "title": title,
                "message": message,
                "train_code": str(payload.get("train_code", "")),
                "priority": "urgent",
            },
        )
        self._notify_async(title, message)
        # 非错误的警示状态，让界面在停止后仍显示「需要人工核验」，而不是普通的「监控已停止」
        self.emit_state(replace(self.state.with_human_action(status), monitoring=self.is_monitoring))

    def _automation_confirmation(self, config: dict) -> Optional[dict]:
        enabled = []
        if config.get("auto_submit"):
            enabled.append("自动提交")
        if config.get("auto_alternate"):
            enabled.append("自动候补")
        if not enabled:
            return None
        return {
            "requires_confirmation": True,
            "title": "确认自动化",
            "message": f"你已启用 {', '.join(enabled)}。RailWatch 仍依赖 12306 官方页面和你的登录会话。",
        }

    def _require_config_manager(self):
        if self.config_manager is None:
            raise RuntimeError(f"配置管理器不可用: {CORE_IMPORT_ERROR}")
        return self.config_manager

    def _make_query_config(self, config: dict):
        if QueryConfig is None:
            raise RuntimeError(f"核心配置不可用: {CORE_IMPORT_ERROR}")
        return QueryConfig(
            from_station_cn=config["from_station_cn"],
            to_station_cn=config["to_station_cn"],
            date=config["date"],
            train_code=config["train_code"],
            seat_keyword=config["seat_keyword"],
            interval=config["interval"],
            query_timeout=config["query_timeout"],
            query_priority=config["query_priority"],
            request_mode=config["request_mode"],
            auto_submit=config["auto_submit"],
            seat_prefer=config["seat_prefer"],
            passenger_count=config["passenger_count"],
            prepare_time=config["prepare_time"],
            keep_alive=config["keep_alive"],
            passengers=config["passengers"],
            auto_alternate=config["auto_alternate"],
            alternate_deadline=config["alternate_deadline"],
            date_range=config["date_range"],
            smart_rate=config["smart_rate"],
            timer_enabled=config["timer_enabled"],
            target_time=config["target_time"],
            sale_at=config.get("sale_at", ""),
            sale_time_source=config.get("sale_time_source", "manual"),
            sale_time_checked_at=config.get("sale_time_checked_at", ""),
            burst_window_seconds=config.get("burst_window_seconds", 45),
            prewarm_lead_seconds=config.get("prewarm_lead_seconds", 120),
        )


def dumps_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
