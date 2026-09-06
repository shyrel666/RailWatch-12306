"""UI-independent RailWatch bridge for Electron and other frontends."""

from __future__ import annotations

import json
import os
import shutil
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
from railwatch_preferences import load_theme_preference, save_theme_preference
from railwatch_dates import expand_travel_dates, eligible_travel_dates, beijing_now, PRESALE_WINDOW_DAYS
from railwatch_state import APP_DISPLAY_NAME, APP_PAGES, APP_SLUG, AppPhase, RailWatchState, TicketHit
from railwatch_system import get_app_version, inspect_data_dir, probe_connectivity
from railwatch_time import ServerTimeSync, get_server_time_sync

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

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service

    SELENIUM_AVAILABLE = True
except ImportError:
    webdriver = None
    Service = None
    SELENIUM_AVAILABLE = False

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
        self.query_results: List[dict] = []
        self.config_manager = ConfigManager(self.data_dir) if CORE_AVAILABLE and ConfigManager else None
        self.chromedriver_path = CHROMEDRIVER_PATH
        self._chromedriver_repair_failed = False
        self.server_time_sync: ServerTimeSync = get_server_time_sync(log_callback=self.log)
        self.notification_service = NotificationService(self._load_notification_settings(), log_callback=self.log)
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
                raise RuntimeError("Selenium 未安装，请运行 pip install -r requirements.txt。")
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
            if "version" in error_msg.lower() or "session" in error_msg.lower():
                if CD_MANAGER_AVAILABLE:
                    error_msg += "\n\n可能是 ChromeDriver 版本与 Chrome 不匹配，点击「下载 ChromeDriver」自动获取正确版本。"
                else:
                    error_msg += "\n\n请下载与 Chrome 版本匹配的 ChromeDriver: https://googlechromelabs.github.io/chrome-for-testing/"
            return self.emit_state(self.state.with_error(f"环境检查失败: {error_msg}"))

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
        confirmation = self._automation_confirmation(config)
        if confirmation and not confirmed:
            return confirmation
        with self._task_lock:
            if self.is_monitoring or self._browser_busy:
                raise RuntimeError("监控运行中或正在停止，请等待当前任务退出。")
            reference = beijing_now(requested_at + self.server_time_sync.offset_seconds)
            target = self.server_time_sync.parse_target_datetime(config["target_time"], reference).timestamp() if config.get("timer_enabled") else None
            self._valid_dates(config, max(requested_at, target or requested_at), announce=True)
            task = MonitorTask(config, target, started_at=requested_at)
            self._task = task
            self.state = self.state.with_safety(config["auto_submit"], config["auto_alternate"]).with_monitoring(True)
            self._transition(task, "preparing")
            task.thread = threading.Thread(target=lambda: self._monitor_worker(deepcopy(config), task), name=f"railwatch-monitor-{task.run_id[:8]}", daemon=True)
            self.worker_threads.append(task.thread)
            task.thread.start()
            threading.Thread(target=lambda: self._finish_task(task), name="railwatch-task-finalizer", daemon=True).start()
            return state_to_payload(self.state)

    def _finish_task(self, task):
        if task.thread:
            task.thread.join()
        with self._task_lock:
            task.done.set()
            if task is self._task:
                terminal = task.status if task.status in ("human_action", "error", "hit") else "stopped"
                self._transition(task, terminal)

    def stop_monitor(self) -> dict:
        with self._task_lock:
            if self.is_monitoring:
                self._task.cancel.set()
                self._transition(self._task, "stopping")
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
                self.driver.quit()
                self.driver = None
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
        target = os.path.abspath(self.data_dir)
        if os.path.basename(target) != APP_SLUG:
            self.log(f"拒绝清除意外的数据目录: {target}", "ERROR")
            raise RuntimeError(f"拒绝清除意外的数据目录: {target}")
        if self.driver:
            try:
                self.driver.quit()
            finally:
                self.driver = None
        if os.path.exists(target):
            shutil.rmtree(target)
        os.makedirs(target, exist_ok=True)
        self.log("本地 RailWatch 数据已清除。", "SUCCESS")
        return {"cleared": True, "data_dir": target}

    def export_log(self, path: Optional[str] = None) -> dict:
        export_path = path or os.path.join(self.data_dir, f"railwatch-events-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt")
        os.makedirs(os.path.dirname(export_path) or self.data_dir, exist_ok=True)
        with open(export_path, "w", encoding="utf-8") as file:
            for entry in self.log_entries:
                file.write(f"[{entry['time']}] [{entry['level']}] {entry['message']}\n")
        self.log(f"事件已导出到 {export_path}", "SUCCESS")
        return {"path": export_path}

    def clear_log(self) -> dict:
        self.log_entries.clear()
        self.emit("logsCleared", {})
        return {"cleared": True}

    def load_preferences(self) -> dict:
        return {
            "theme": load_theme_preference(self.data_dir),
            "notification_settings": self._load_notification_settings(),
        }

    def save_preferences(self, theme: str, notification_settings: Optional[dict] = None) -> dict:
        selected = "dark" if str(theme).lower() == "dark" else "light"
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
                task.target_timestamp = self.server_time_sync.parse_target_datetime(config["target_time"], beijing_now(task.started_at + self.server_time_sync.offset_seconds)).timestamp()
            self.server_time_sync.sync(force=True)
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
                    if config.get("timer_enabled"):
                        config["_target_timestamp"] = task.target_timestamp
                        if not self._wait_for_target_time(config):
                            return
                    if task.cancel.is_set():
                        return
                    self._valid_dates(task.config, announce=True)
                    if not self._prepare_query_page(driver, config, task):
                        return
                    monitor = TicketMonitor(
                        driver, config, log_callback=self.log, stop_check=task.cancel.is_set,
                        notify_callback=self._handle_notify, progress_callback=self._handle_progress,
                        on_hit=self._handle_hit, human_action_callback=self._handle_human_action,
                        server_time_sync=self.server_time_sync, param_filler=self._param_filler,
                        wait_callback=lambda seconds: self._task_wait(task, seconds),
                        tick_callback=lambda **kwargs: self._transition(task, **kwargs),
                        session_check=lambda: self._check_session_for_task(task),
                        date_provider=lambda: self._valid_dates(task.config),
                    )
                    monitor.run()
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
            if task.target_timestamp is not None and task.target_timestamp - 3 <= self.server_time_sync.server_timestamp() <= task.target_timestamp:
                return True
            self._send_keep_alive()
            task.last_login_check = time.monotonic()
        return not task.cancel.is_set()

    def _wait_for_target_time(self, config: dict) -> bool:
        target = config.get("_target_timestamp")
        if target is None:
            target = self.server_time_sync.parse_target_datetime(config["target_time"]).timestamp()
        wait_until = target - int(config.get("prepare_time", 0))
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
        last_keep_alive, last_prewarm = 0.0, 0.0
        while True:
            if self._task and self._task.cancel.is_set():
                return False
            now_server = self.server_time_sync.server_timestamp()
            if now_server >= wait_until:
                return True
            if not self.is_monitoring:
                return False
            self._monitor_last_tick = time.time()
            now_mono = time.monotonic()
            if self._task:
                self._transition(self._task)
            if config.get("keep_alive") and now_mono-last_keep_alive >= 60 and wait_until-now_server >= 3:
                self._send_keep_alive()
                last_keep_alive = now_mono
                if self._task:
                    self._task.last_login_check = now_mono
                    if self._task.cancel.is_set():
                        return False
            if self.driver and (wait_until-now_server >= 3 or not last_prewarm) and wait_until-now_server <= float(config.get("prewarm_lead_seconds",120)) and now_mono-last_prewarm >= MONITOR_PREWARM_INTERVAL_SECONDS:
                result = self._prewarm_query_page(self.driver, config)
                if isinstance(result, FillResult) and result.status == "config_error":
                    raise ValueError(result.reason)
                last_prewarm = now_mono
            if self._task and self._task.thread:
                self._task_wait(self._task, 0.2)
            else:
                time.sleep(0.2)

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

    def _ensure_driver(self, test_only: bool = False):
        if self.driver and not test_only:
            return self.driver
        if not SELENIUM_AVAILABLE or webdriver is None:
            raise RuntimeError("Selenium 未安装。")

        self._ensure_matching_chromedriver()

        profile_dir = os.path.join(self.data_dir, "chrome_profile_12306")
        os.makedirs(profile_dir, exist_ok=True)
        if ANTI_DETECT_AVAILABLE and AntiDetect is not None:
            try:
                self.log("已启用反检测浏览器配置。")
                anti_detect = AntiDetect(self.data_dir, log_callback=self.log, driver_path=self.chromedriver_path)
                driver = anti_detect.create_driver(profile_dir)
                if not test_only:
                    self.driver = driver
                    if BehaviorSimulator is not None:
                        self.behavior_simulator = BehaviorSimulator(driver, self.log)
                    if RailDeviceIdProtector is not None:
                        self.device_id_protector = RailDeviceIdProtector(driver, self.log)
                return driver
            except Exception as exc:
                self.log(f"反检测启动失败，回退到标准 Selenium: {exc}", "WARN")

        options = webdriver.ChromeOptions()
        options.add_argument(f"--user-data-dir={profile_dir}")
        options.add_argument("--profile-directory=Default")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--start-maximized")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        options.add_experimental_option("useAutomationExtension", False)
        # 反检测首选项
        options.add_experimental_option("prefs", {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
            "webrtc.ip_handling_policy": "disable_non_proxied_udp",
            "webrtc.multiple_routes_enabled": False,
            "webrtc.nonproxied_udp_enabled": False,
        })
        service = Service(executable_path=self.chromedriver_path) if Service and os.path.exists(self.chromedriver_path) else None
        driver = webdriver.Chrome(options=options, service=service) if service else webdriver.Chrome(options=options)
        # 注入基础反检测脚本（即使 AntiDetect 模块不可用）
        self._inject_basic_anti_detect(driver)
        if not test_only:
            self.driver = driver
        return driver

    def _inject_basic_anti_detect(self, driver) -> None:
        """Inject minimal anti-detect JS when AntiDetect module is unavailable."""
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
        const originalQuery = navigator.permissions && navigator.permissions.query;
        const origToString = Function.prototype.toString;
        Function.prototype.toString = function() {
            if (originalQuery && this === originalQuery) return 'function query() { [native code] }';
            return origToString.apply(this, arguments);
        };
        console.log('[RailWatch] 基础浏览器环境脚本已注入');
        '''
        try:
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": basic_js})
            self.log("基础反检测脚本注入成功（回退模式）。", "SUCCESS")
        except Exception:
            try:
                driver.execute_script(basic_js)
                self.log("基础反检测脚本注入成功（直接执行）。")
            except Exception as exc:
                self.log(f"基础反检测脚本注入失败: {exc}", "WARN")

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
        self.notification_service.notify(title, message, urgent=True)

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
        self.notification_service.notify(title, message, urgent=True)
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
        self.notification_service.notify(title, message, urgent=True)
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
            burst_window_seconds=config.get("burst_window_seconds", 45),
            prewarm_lead_seconds=config.get("prewarm_lead_seconds", 120),
        )


def dumps_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
