"""PySide6 product interface for RailWatch 12306."""

from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from railwatch_state import APP_DISPLAY_NAME, APP_PAGES, APP_SLUG, RailWatchState, TicketHit


try:
    from PySide6.QtCore import QDate, QObject, Qt, QTime, Signal
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import (
        QApplication,
        QAbstractItemView,
        QCheckBox,
        QComboBox,
        QDateEdit,
        QFileDialog,
        QFrame,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QSpinBox,
        QStackedWidget,
        QTableWidget,
        QTableWidgetItem,
        QTimeEdit,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )

    PYSIDE6_AVAILABLE = True
except ImportError as exc:
    PYSIDE6_AVAILABLE = False
    PYSIDE6_IMPORT_ERROR = exc


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
LOG_FILE = os.path.join(DATA_DIR, "railwatch.log")
CHROMEDRIVER_PATH = get_data_path("chromedriver.exe")
if not os.path.exists(CHROMEDRIVER_PATH):
    CHROMEDRIVER_PATH = get_resource_path("chromedriver.exe")


if PYSIDE6_AVAILABLE:

    class RailWatchSignals(QObject):
        log = Signal(str, str)
        state = Signal(object)
        results = Signal(object)
        buttons = Signal()
        notify = Signal(str, str)


    class RailWatchMainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            os.makedirs(DATA_DIR, exist_ok=True)

            self.state = RailWatchState.initial()
            self.signals = RailWatchSignals()
            self.driver = None
            self.behavior_simulator = None
            self.device_id_protector = None
            self.is_monitoring = False
            self.worker_threads: List[threading.Thread] = []
            self.log_entries: List[Dict[str, str]] = []
            self.query_results: List[dict] = []
            self.config_manager = ConfigManager(DATA_DIR) if CORE_AVAILABLE else None

            self.setObjectName("RailWatchRoot")
            self.setWindowTitle(APP_DISPLAY_NAME)
            self.resize(1380, 860)
            self.setMinimumSize(1180, 720)

            self._build_ui()
            self._wire_signals()
            self._load_saved_config()
            self._apply_state(self.state)

            self.log(f"{APP_DISPLAY_NAME} ready. Data directory: {DATA_DIR}", "INFO")
            if not CORE_AVAILABLE:
                self.log(f"Core module unavailable: {CORE_IMPORT_ERROR}", "ERROR")

        # ------------------------------------------------------------------
        # UI construction
        # ------------------------------------------------------------------
        def _build_ui(self):
            root = QWidget()
            root_layout = QHBoxLayout(root)
            root_layout.setContentsMargins(0, 0, 0, 0)
            root_layout.setSpacing(0)

            self.sidebar = self._build_sidebar()
            self.main_region = self._build_main_region()
            self.event_panel = self._build_event_panel()

            root_layout.addWidget(self.sidebar)
            root_layout.addWidget(self.main_region, 1)
            root_layout.addWidget(self.event_panel)
            self.setCentralWidget(root)
            self.setStyleSheet(self._stylesheet())

        def _build_sidebar(self) -> QWidget:
            side = QFrame()
            side.setObjectName("Sidebar")
            side.setFixedWidth(220)
            layout = QVBoxLayout(side)
            layout.setContentsMargins(18, 22, 18, 18)
            layout.setSpacing(16)

            brand = QLabel(APP_DISPLAY_NAME)
            brand.setObjectName("Brand")
            brand.setWordWrap(True)
            subtitle = QLabel("Operations Console")
            subtitle.setObjectName("BrandSubtitle")
            layout.addWidget(brand)
            layout.addWidget(subtitle)

            self.nav_buttons: List[QToolButton] = []
            nav_box = QVBoxLayout()
            nav_box.setSpacing(6)
            for index, page_name in enumerate(APP_PAGES):
                button = QToolButton()
                button.setText(page_name)
                button.setCheckable(True)
                button.setToolButtonStyle(Qt.ToolButtonTextOnly)
                button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                button.clicked.connect(lambda _checked=False, i=index: self._set_page(i))
                self.nav_buttons.append(button)
                nav_box.addWidget(button)
            layout.addLayout(nav_box)
            layout.addStretch(1)

            self.sidebar_status = QLabel("Idle")
            self.sidebar_status.setObjectName("SidebarStatus")
            self.sidebar_status.setWordWrap(True)
            layout.addWidget(self.sidebar_status)
            return side

        def _build_main_region(self) -> QWidget:
            region = QFrame()
            region.setObjectName("MainRegion")
            layout = QVBoxLayout(region)
            layout.setContentsMargins(18, 16, 18, 16)
            layout.setSpacing(12)

            layout.addWidget(self._build_top_status())
            self.pages = QStackedWidget()
            self.pages.addWidget(self._build_dashboard_page())
            self.pages.addWidget(self._build_trip_setup_page())
            self.pages.addWidget(self._build_monitor_page())
            self.pages.addWidget(self._build_settings_page())
            layout.addWidget(self.pages, 1)
            return region

        def _build_top_status(self) -> QWidget:
            top = QFrame()
            top.setObjectName("TopStatus")
            layout = QHBoxLayout(top)
            layout.setContentsMargins(14, 12, 14, 12)
            layout.setSpacing(10)

            self.status_title = QLabel("RailWatch Operations Console")
            self.status_title.setObjectName("TopTitle")
            layout.addWidget(self.status_title)
            layout.addStretch(1)

            self.status_chips: Dict[str, QLabel] = {}
            for key, text in (
                ("environment", "Environment"),
                ("login", "Login"),
                ("query", "Query"),
                ("monitor", "Monitor"),
                ("risk", "Risk"),
            ):
                chip = QLabel(text)
                chip.setObjectName("StatusChip")
                chip.setProperty("tone", "idle")
                chip.setAlignment(Qt.AlignCenter)
                chip.setMinimumWidth(104)
                self.status_chips[key] = chip
                layout.addWidget(chip)

            self.toggle_events_btn = QPushButton("Events")
            self.toggle_events_btn.setObjectName("SecondaryButton")
            self.toggle_events_btn.clicked.connect(self._toggle_event_panel)
            layout.addWidget(self.toggle_events_btn)
            return top

        def _build_dashboard_page(self) -> QWidget:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(12)

            headline = QLabel("Operational readiness")
            headline.setObjectName("PageTitle")
            layout.addWidget(headline)

            grid = QGridLayout()
            grid.setHorizontalSpacing(12)
            grid.setVerticalSpacing(12)
            self.dashboard_cards: Dict[str, QLabel] = {}
            cards = (
                ("environment", "Environment", "ChromeDriver and browser profile are not checked."),
                ("login", "Login", "Open 12306 and complete manual sign-in."),
                ("query", "Query setup", "Prepare stations, date, train and seat rules."),
                ("monitor", "Monitor", "Run controlled polling after query analysis."),
                ("hit", "Ticket hits", "No target ticket has been found."),
                ("risk", "Risk and compliance", "Automation is opt-in and requires confirmation."),
            )
            for index, (key, title, body) in enumerate(cards):
                card = QFrame()
                card.setObjectName("Surface")
                card_layout = QVBoxLayout(card)
                card_layout.setContentsMargins(14, 12, 14, 12)
                title_label = QLabel(title)
                title_label.setObjectName("CardTitle")
                body_label = QLabel(body)
                body_label.setObjectName("CardBody")
                body_label.setWordWrap(True)
                self.dashboard_cards[key] = body_label
                card_layout.addWidget(title_label)
                card_layout.addWidget(body_label)
                grid.addWidget(card, index // 3, index % 3)
            layout.addLayout(grid)

            self.recent_hits_table = QTableWidget(0, 4)
            self.recent_hits_table.setObjectName("DataTable")
            self.recent_hits_table.setHorizontalHeaderLabels(["Time", "Train", "Seat", "Source"])
            self.recent_hits_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            self.recent_hits_table.verticalHeader().setVisible(False)
            self.recent_hits_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.recent_hits_table.setSelectionBehavior(QAbstractItemView.SelectRows)
            layout.addWidget(self.recent_hits_table, 1)
            return page

        def _build_trip_setup_page(self) -> QWidget:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            page = QWidget()
            scroll.setWidget(page)
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 8, 0)
            layout.setSpacing(12)

            title = QLabel("Trip setup")
            title.setObjectName("PageTitle")
            layout.addWidget(title)

            route = QGroupBox("Route and target")
            route_layout = QGridLayout(route)
            route_layout.setHorizontalSpacing(12)
            route_layout.setVerticalSpacing(10)
            self.from_input = QLineEdit()
            self.from_input.setPlaceholderText("Beijing")
            self.to_input = QLineEdit()
            self.to_input.setPlaceholderText("Shanghai")
            self.date_input = QDateEdit()
            self.date_input.setCalendarPopup(True)
            self.date_input.setDisplayFormat("yyyy-MM-dd")
            self.date_input.setDate(QDate.currentDate().addDays(1))
            self.train_input = QLineEdit()
            self.train_input.setPlaceholderText("G101, G103")
            self.seat_input = QLineEdit()
            self.seat_input.setPlaceholderText("Second class, First class")
            self.passengers_input = QLineEdit()
            self.passengers_input.setPlaceholderText("Passenger names, separated by comma")

            self._add_form_row(route_layout, 0, "From", self.from_input)
            self._add_form_row(route_layout, 0, "To", self.to_input, col=2)
            self._add_form_row(route_layout, 1, "Date", self.date_input)
            self._add_form_row(route_layout, 1, "Train codes", self.train_input, col=2)
            self._add_form_row(route_layout, 2, "Seat types", self.seat_input)
            self._add_form_row(route_layout, 2, "Passengers", self.passengers_input, col=2)
            layout.addWidget(route)

            behavior = QGroupBox("Monitoring behavior")
            behavior_layout = QGridLayout(behavior)
            behavior_layout.setHorizontalSpacing(12)
            behavior_layout.setVerticalSpacing(10)

            self.interval_input = QSpinBox()
            self.interval_input.setRange(1, 60)
            self.interval_input.setValue(5)
            self.passenger_count_input = QSpinBox()
            self.passenger_count_input.setRange(1, 20)
            self.passenger_count_input.setValue(1)
            self.seat_prefer_input = QComboBox()
            self.seat_prefer_input.addItems(["No preference", "Window first", "Aisle first"])
            self.prepare_time_input = QSpinBox()
            self.prepare_time_input.setRange(0, 30)
            self.prepare_time_input.setValue(2)
            self.timer_check = QCheckBox("Timed start")
            self.target_time_input = QTimeEdit()
            self.target_time_input.setDisplayFormat("HH:mm:ss")
            self.target_time_input.setTime(QTime.currentTime().addSecs(120))
            self.keep_alive_check = QCheckBox("Keep session alive")
            self.keep_alive_check.setChecked(True)
            self.smart_rate_check = QCheckBox("Adaptive polling")
            self.smart_rate_check.setChecked(True)

            self._add_form_row(behavior_layout, 0, "Interval seconds", self.interval_input)
            self._add_form_row(behavior_layout, 0, "Passenger count", self.passenger_count_input, col=2)
            self._add_form_row(behavior_layout, 1, "Seat preference", self.seat_prefer_input)
            self._add_form_row(behavior_layout, 1, "Prepare seconds", self.prepare_time_input, col=2)
            behavior_layout.addWidget(self.timer_check, 2, 0)
            behavior_layout.addWidget(self.target_time_input, 2, 1)
            behavior_layout.addWidget(self.keep_alive_check, 2, 2)
            behavior_layout.addWidget(self.smart_rate_check, 2, 3)
            layout.addWidget(behavior)

            automation = QGroupBox("Automation guardrails")
            automation_layout = QGridLayout(automation)
            automation_layout.setHorizontalSpacing(12)
            automation_layout.setVerticalSpacing(10)
            self.auto_submit_check = QCheckBox("Auto submit when ticket is available")
            self.auto_submit_check.toggled.connect(self._on_auto_submit_toggled)
            self.auto_alternate_check = QCheckBox("Auto alternate when only waitlist is available")
            self.auto_alternate_check.toggled.connect(self._on_auto_alternate_toggled)
            self.alternate_deadline_input = QTimeEdit()
            self.alternate_deadline_input.setDisplayFormat("HH:mm")
            self.alternate_deadline_input.setTime(QTime(18, 0))
            automation_layout.addWidget(self.auto_submit_check, 0, 0, 1, 2)
            automation_layout.addWidget(self.auto_alternate_check, 1, 0, 1, 2)
            self._add_form_row(automation_layout, 1, "Deadline", self.alternate_deadline_input, col=2)
            layout.addWidget(automation)

            actions = QHBoxLayout()
            self.save_config_btn = QPushButton("Save setup")
            self.save_config_btn.setObjectName("SecondaryButton")
            self.save_config_btn.clicked.connect(self._save_config)
            self.analyze_btn = QPushButton("Analyze query")
            self.analyze_btn.setObjectName("PrimaryButton")
            self.analyze_btn.clicked.connect(self.analyze_query)
            actions.addStretch(1)
            actions.addWidget(self.save_config_btn)
            actions.addWidget(self.analyze_btn)
            layout.addLayout(actions)
            layout.addStretch(1)
            return scroll

        def _build_monitor_page(self) -> QWidget:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(12)

            header = QHBoxLayout()
            title = QLabel("Monitor workspace")
            title.setObjectName("PageTitle")
            header.addWidget(title)
            header.addStretch(1)
            self.start_monitor_btn = QPushButton("Start monitor")
            self.start_monitor_btn.setObjectName("PrimaryButton")
            self.start_monitor_btn.clicked.connect(self.start_monitor)
            self.stop_monitor_btn = QPushButton("Stop")
            self.stop_monitor_btn.setObjectName("DangerButton")
            self.stop_monitor_btn.clicked.connect(self.stop_monitor)
            header.addWidget(self.start_monitor_btn)
            header.addWidget(self.stop_monitor_btn)
            layout.addLayout(header)

            self.monitor_status = QLabel("Run query analysis before starting monitor.")
            self.monitor_status.setObjectName("InlineStatus")
            layout.addWidget(self.monitor_status)

            self.results_table = QTableWidget(0, 3)
            self.results_table.setObjectName("DataTable")
            self.results_table.setHorizontalHeaderLabels(["Train", "Snapshot", "Raw result"])
            self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
            self.results_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
            self.results_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
            self.results_table.verticalHeader().setVisible(False)
            self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
            layout.addWidget(self.results_table, 1)
            return page

        def _build_settings_page(self) -> QWidget:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(12)

            title = QLabel("Settings")
            title.setObjectName("PageTitle")
            layout.addWidget(title)

            storage = QGroupBox("Local data")
            storage_layout = QGridLayout(storage)
            self.data_dir_label = QLabel(DATA_DIR)
            self.data_dir_label.setWordWrap(True)
            self.driver_path_label = QLabel(CHROMEDRIVER_PATH)
            self.driver_path_label.setWordWrap(True)
            storage_layout.addWidget(QLabel("Data directory"), 0, 0)
            storage_layout.addWidget(self.data_dir_label, 0, 1)
            storage_layout.addWidget(QLabel("ChromeDriver"), 1, 0)
            storage_layout.addWidget(self.driver_path_label, 1, 1)
            layout.addWidget(storage)

            safety = QGroupBox("Safety controls")
            safety_layout = QHBoxLayout(safety)
            self.check_env_btn = QPushButton("Check environment")
            self.check_env_btn.setObjectName("SecondaryButton")
            self.check_env_btn.clicked.connect(self.check_environment)
            self.open_login_btn = QPushButton("Open login")
            self.open_login_btn.setObjectName("SecondaryButton")
            self.open_login_btn.clicked.connect(self.open_login)
            self.close_browser_btn = QPushButton("Close browser")
            self.close_browser_btn.setObjectName("DangerButton")
            self.close_browser_btn.clicked.connect(self.close_browser)
            self.clear_data_btn = QPushButton("Clear local data")
            self.clear_data_btn.setObjectName("DangerButton")
            self.clear_data_btn.clicked.connect(self.clear_local_data)
            safety_layout.addWidget(self.check_env_btn)
            safety_layout.addWidget(self.open_login_btn)
            safety_layout.addWidget(self.close_browser_btn)
            safety_layout.addWidget(self.clear_data_btn)
            safety_layout.addStretch(1)
            layout.addWidget(safety)

            notice = QLabel(
                "RailWatch stores configuration, logs and Chrome profile data locally. "
                "Cookies and sessions should never be committed to source control."
            )
            notice.setObjectName("SettingsNotice")
            notice.setWordWrap(True)
            layout.addWidget(notice)
            layout.addStretch(1)
            return page

        def _build_event_panel(self) -> QWidget:
            panel = QFrame()
            panel.setObjectName("EventPanel")
            panel.setFixedWidth(360)
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(14, 16, 14, 16)
            layout.setSpacing(10)

            header = QHBoxLayout()
            title = QLabel("Events")
            title.setObjectName("PanelTitle")
            self.log_filter = QComboBox()
            self.log_filter.addItems(["All", "INFO", "WARN", "ERROR", "SUCCESS"])
            self.log_filter.currentTextChanged.connect(self._refresh_log_view)
            header.addWidget(title)
            header.addStretch(1)
            header.addWidget(self.log_filter)
            layout.addLayout(header)

            self.event_log = QPlainTextEdit()
            self.event_log.setObjectName("EventLog")
            self.event_log.setReadOnly(True)
            layout.addWidget(self.event_log, 1)

            controls = QHBoxLayout()
            self.export_log_btn = QPushButton("Export")
            self.export_log_btn.setObjectName("SecondaryButton")
            self.export_log_btn.clicked.connect(self.export_log)
            self.clear_log_btn = QPushButton("Clear")
            self.clear_log_btn.setObjectName("SecondaryButton")
            self.clear_log_btn.clicked.connect(self.clear_log)
            controls.addWidget(self.export_log_btn)
            controls.addWidget(self.clear_log_btn)
            layout.addLayout(controls)
            return panel

        @staticmethod
        def _add_form_row(layout: QGridLayout, row: int, label: str, widget: QWidget, col: int = 0):
            label_widget = QLabel(label)
            label_widget.setObjectName("FieldLabel")
            layout.addWidget(label_widget, row, col)
            layout.addWidget(widget, row, col + 1)

        def _wire_signals(self):
            self.signals.log.connect(self._append_log)
            self.signals.state.connect(self._apply_state)
            self.signals.results.connect(self._handle_results)
            self.signals.buttons.connect(self._update_buttons)
            self.signals.notify.connect(self._handle_notify)
            self._set_page(0)

        # ------------------------------------------------------------------
        # State and rendering
        # ------------------------------------------------------------------
        def _set_page(self, index: int):
            self.pages.setCurrentIndex(index)
            for button_index, button in enumerate(self.nav_buttons):
                button.setChecked(button_index == index)

        def _apply_state(self, state: RailWatchState):
            self.state = state
            self.sidebar_status.setText(state.summary())
            self.status_title.setText(state.summary())

            self._set_chip("environment", "Environment ready" if state.environment_ready else "Environment", "ok" if state.environment_ready else "idle")
            self._set_chip("login", "Login ready" if state.login_ready else "Login", "ok" if state.login_ready else "idle")
            self._set_chip("query", "Query ready" if state.query_ready else "Query", "ok" if state.query_ready else "idle")
            self._set_chip("monitor", "Running" if state.monitoring else "Monitor", "active" if state.monitoring else "idle")
            self._set_chip("risk", state.risk_level.title(), state.risk_level)

            self.dashboard_cards["environment"].setText(
                "ChromeDriver and browser profile are ready." if state.environment_ready else "ChromeDriver and browser profile are not checked."
            )
            self.dashboard_cards["login"].setText("12306 login has been opened." if state.login_ready else "Open 12306 and complete manual sign-in.")
            self.dashboard_cards["query"].setText("Query analysis completed." if state.query_ready else "Prepare stations, date, train and seat rules.")
            self.dashboard_cards["monitor"].setText("Monitoring is active." if state.monitoring else "Run controlled polling after query analysis.")
            self.dashboard_cards["hit"].setText(state.hits[-1].label() if state.hits else "No target ticket has been found.")
            self.dashboard_cards["risk"].setText(self._risk_text(state))

            self.monitor_status.setText(state.summary())
            self._update_buttons()

        def _set_chip(self, key: str, text: str, tone: str):
            chip = self.status_chips[key]
            chip.setText(text)
            chip.setProperty("tone", tone)
            chip.style().unpolish(chip)
            chip.style().polish(chip)

        def _risk_text(self, state: RailWatchState) -> str:
            if state.error_message:
                return state.error_message
            if state.auto_submit_enabled or state.auto_alternate_enabled:
                return "Automation is enabled and will require confirmation before running."
            return "Automation is opt-in and requires confirmation."

        def _update_buttons(self):
            can_use_core = CORE_AVAILABLE and SELENIUM_AVAILABLE
            self.check_env_btn.setEnabled(can_use_core and not self.is_monitoring)
            self.open_login_btn.setEnabled(can_use_core and not self.is_monitoring)
            self.analyze_btn.setEnabled(can_use_core and not self.is_monitoring)
            self.start_monitor_btn.setEnabled(can_use_core and self.state.query_ready and not self.is_monitoring)
            self.stop_monitor_btn.setEnabled(self.is_monitoring)
            self.close_browser_btn.setEnabled(self.driver is not None)

        # ------------------------------------------------------------------
        # Logging
        # ------------------------------------------------------------------
        def log(self, message: str, level: str = "INFO"):
            level = self._infer_level(message, level)
            if threading.current_thread() is threading.main_thread():
                self._append_log(level, message)
            else:
                self.signals.log.emit(level, message)

        @staticmethod
        def _infer_level(message: str, level: str) -> str:
            if level != "INFO":
                return level
            if "ERROR" in message or "失败" in message or "错误" in message or "❌" in message:
                return "ERROR"
            if "WARN" in message or "警告" in message or "候补" in message or "⚠" in message:
                return "WARN"
            if "命中" in message or "成功" in message or "✅" in message:
                return "SUCCESS"
            return "INFO"

        def _append_log(self, level: str, message: str):
            timestamp = datetime.now().strftime("%H:%M:%S")
            entry = {"time": timestamp, "level": level, "message": message}
            self.log_entries.append(entry)
            self._refresh_log_view()
            try:
                with open(LOG_FILE, "a", encoding="utf-8") as file:
                    file.write(f"[{datetime.now().isoformat()}] [{level}] {message}\n")
            except OSError:
                pass

        def _refresh_log_view(self):
            selected = self.log_filter.currentText() if hasattr(self, "log_filter") else "All"
            lines = []
            for entry in self.log_entries:
                if selected != "All" and entry["level"] != selected:
                    continue
                lines.append(f"[{entry['time']}] [{entry['level']}] {entry['message']}")
            self.event_log.setPlainText("\n".join(lines))
            self.event_log.verticalScrollBar().setValue(self.event_log.verticalScrollBar().maximum())

        def clear_log(self):
            self.log_entries.clear()
            self._refresh_log_view()

        def export_log(self):
            default_name = os.path.join(DATA_DIR, f"railwatch-events-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt")
            path, _ = QFileDialog.getSaveFileName(self, "Export events", default_name, "Text files (*.txt);;All files (*.*)")
            if not path:
                return
            try:
                with open(path, "w", encoding="utf-8") as file:
                    for entry in self.log_entries:
                        file.write(f"[{entry['time']}] [{entry['level']}] {entry['message']}\n")
                self.log(f"Events exported to {path}", "SUCCESS")
            except OSError as exc:
                self.log(f"Export failed: {exc}", "ERROR")

        # ------------------------------------------------------------------
        # Config
        # ------------------------------------------------------------------
        def _load_saved_config(self):
            if not self.config_manager:
                return
            config = self.config_manager.load()
            if not config:
                self.from_input.setText("北京")
                self.to_input.setText("上海")
                return

            self.from_input.setText(config.from_station_cn or "北京")
            self.to_input.setText(config.to_station_cn or "上海")
            if config.date:
                parsed = QDate.fromString(config.date, "yyyy-MM-dd")
                if parsed.isValid():
                    self.date_input.setDate(parsed)
            self.train_input.setText(config.train_code)
            self.seat_input.setText(config.seat_keyword)
            self.interval_input.setValue(max(1, int(config.interval or 5)))
            self.auto_submit_check.blockSignals(True)
            self.auto_submit_check.setChecked(bool(config.auto_submit))
            self.auto_submit_check.blockSignals(False)
            self.passenger_count_input.setValue(max(1, int(getattr(config, "passenger_count", 1) or 1)))
            self.prepare_time_input.setValue(max(0, int(getattr(config, "prepare_time", 2) or 0)))
            self.keep_alive_check.setChecked(bool(getattr(config, "keep_alive", True)))
            self.passengers_input.setText(getattr(config, "passengers", ""))
            self.auto_alternate_check.blockSignals(True)
            self.auto_alternate_check.setChecked(bool(getattr(config, "auto_alternate", False)))
            self.auto_alternate_check.blockSignals(False)
            if getattr(config, "alternate_deadline", ""):
                deadline = QTime.fromString(config.alternate_deadline, "HH:mm")
                if deadline.isValid():
                    self.alternate_deadline_input.setTime(deadline)
            self.state = self.state.with_safety(self.auto_submit_check.isChecked(), self.auto_alternate_check.isChecked())
            self.log("Loaded saved setup.", "SUCCESS")

        def _save_config(self):
            if not self.config_manager or QueryConfig is None:
                self.log("Config manager unavailable.", "ERROR")
                return
            try:
                cfg = self._collect_cfg()
                config = QueryConfig(
                    from_station_cn=cfg["from_station_cn"],
                    to_station_cn=cfg["to_station_cn"],
                    date=cfg["date"],
                    train_code=cfg["train_code"],
                    seat_keyword=cfg["seat_keyword"],
                    interval=cfg["interval"],
                    auto_submit=cfg["auto_submit"],
                    seat_prefer=cfg["seat_prefer"],
                    passenger_count=cfg["passenger_count"],
                    prepare_time=cfg["prepare_time"],
                    keep_alive=cfg["keep_alive"],
                    passengers=cfg["passengers"],
                    auto_alternate=cfg["auto_alternate"],
                    alternate_deadline=cfg["alternate_deadline"],
                )
                if self.config_manager.save(config):
                    self.log("Setup saved.", "SUCCESS")
                else:
                    self.log("Setup save failed.", "ERROR")
            except ValueError as exc:
                self._show_warning("Setup incomplete", str(exc))

        def _collect_cfg(self) -> dict:
            cfg = {
                "from_station_cn": self.from_input.text().strip(),
                "to_station_cn": self.to_input.text().strip(),
                "date": self.date_input.date().toString("yyyy-MM-dd"),
                "train_code": self.train_input.text().strip().upper(),
                "seat_keyword": self.seat_input.text().strip(),
                "interval": int(self.interval_input.value()),
                "auto_submit": bool(self.auto_submit_check.isChecked()),
                "passenger_count": int(self.passenger_count_input.value()),
                "seat_prefer": self._seat_prefer_value(),
                "prepare_time": int(self.prepare_time_input.value()),
                "keep_alive": bool(self.keep_alive_check.isChecked()),
                "passengers": self.passengers_input.text().strip(),
                "auto_alternate": bool(self.auto_alternate_check.isChecked()),
                "alternate_deadline": self.alternate_deadline_input.time().toString("HH:mm"),
                "smart_rate": bool(self.smart_rate_check.isChecked()),
                "timer_enabled": bool(self.timer_check.isChecked()),
                "target_time": self.target_time_input.time().toString("HH:mm:ss"),
            }
            if not cfg["from_station_cn"]:
                raise ValueError("From station is required.")
            if not cfg["to_station_cn"]:
                raise ValueError("To station is required.")
            if not cfg["date"]:
                raise ValueError("Travel date is required.")
            return cfg

        def _seat_prefer_value(self) -> str:
            value = self.seat_prefer_input.currentText()
            mapping = {
                "No preference": "无偏好",
                "Window first": "靠窗优先",
                "Aisle first": "靠过道优先",
            }
            return mapping.get(value, value)

        # ------------------------------------------------------------------
        # Product actions
        # ------------------------------------------------------------------
        def check_environment(self):
            self._run_worker("environment-check", self._check_environment_worker)

        def _check_environment_worker(self):
            try:
                self.log("Checking Python, Selenium and ChromeDriver...")
                if not SELENIUM_AVAILABLE:
                    raise RuntimeError("Selenium is not installed. Run pip install -r requirements.txt.")
                self.log(f"Python {sys.version.split()[0]}")
                self.log(f"Platform {sys.platform}")
                if os.path.exists(CHROMEDRIVER_PATH):
                    self.log(f"ChromeDriver found at {CHROMEDRIVER_PATH}", "SUCCESS")
                else:
                    self.log("Bundled ChromeDriver not found; Selenium will try PATH.", "WARN")
                driver = self._ensure_driver(test_only=True)
                driver.quit()
                if self.driver is driver:
                    self.driver = None
                self.signals.state.emit(self.state.with_environment(True, "Environment ready"))
            except Exception as exc:
                self.signals.state.emit(self.state.with_error(f"Environment check failed: {exc}"))
            finally:
                self.signals.buttons.emit()

        def open_login(self):
            self._run_worker("open-login", self._open_login_worker)

        def _open_login_worker(self):
            try:
                driver = self._ensure_driver()
                driver.get(LOGIN_URL)
                self.log("Login page opened. Complete 12306 sign-in in the browser.")
                self.signals.state.emit(self.state.with_login(True, "Login page opened"))
            except Exception as exc:
                self.signals.state.emit(self.state.with_error(f"Open login failed: {exc}"))
            finally:
                self.signals.buttons.emit()

        def analyze_query(self):
            try:
                cfg = self._collect_cfg()
                self._save_config()
            except ValueError as exc:
                self._show_warning("Setup incomplete", str(exc))
                return
            self.state = self.state.with_safety(cfg["auto_submit"], cfg["auto_alternate"])
            self.signals.state.emit(self.state)
            self._run_worker("query-analysis", lambda: self._analyze_query_worker(cfg))

        def _analyze_query_worker(self, cfg: dict):
            try:
                driver = self._ensure_driver()
                analyzer = PageAnalyzer(driver, log_callback=self.log, base_dir=DATA_DIR)
                rows = analyzer.open_fill_query_and_analyze(cfg)
                if not rows:
                    raise RuntimeError("No query rows were parsed.")
                self.signals.results.emit(rows)
                self.signals.state.emit(self.state.with_query_ready(True, cfg, f"Parsed {len(rows)} query rows"))
            except Exception as exc:
                self.signals.state.emit(self.state.with_error(f"Query analysis failed: {exc}"))
            finally:
                self.signals.buttons.emit()

        def start_monitor(self):
            try:
                cfg = self._collect_cfg()
            except ValueError as exc:
                self._show_warning("Setup incomplete", str(exc))
                return
            if not self._confirm_automation(cfg):
                return

            self.is_monitoring = True
            self.state = self.state.with_safety(cfg["auto_submit"], cfg["auto_alternate"]).with_monitoring(True)
            self.signals.state.emit(self.state)
            self._run_worker("ticket-monitor", lambda: self._monitor_worker(cfg))

        def _monitor_worker(self, cfg: dict):
            try:
                if cfg.get("timer_enabled") and not self._wait_for_target_time(cfg):
                    return
                driver = self._ensure_driver()
                monitor = TicketMonitor(
                    driver,
                    cfg,
                    log_callback=self.log,
                    stop_check=lambda: not self.is_monitoring,
                    notify_callback=lambda title, msg: self.signals.notify.emit(title, msg),
                )
                monitor.run()
            except Exception as exc:
                self.signals.state.emit(self.state.with_error(f"Monitor failed: {exc}"))
            finally:
                self.is_monitoring = False
                if self.state.phase.value != "error":
                    self.signals.state.emit(self.state.with_monitoring(False, "Monitoring stopped"))
                self.signals.buttons.emit()

        def stop_monitor(self):
            self.is_monitoring = False
            self.signals.state.emit(self.state.with_monitoring(False, "Stopping monitor..."))
            self.log("Stop requested.")
            self._update_buttons()

        def _wait_for_target_time(self, cfg: dict) -> bool:
            target_str = cfg.get("target_time", "")
            try:
                hour, minute, second = [int(part) for part in target_str.split(":")]
            except ValueError:
                self.log("Invalid target time; starting immediately.", "WARN")
                return True
            now = datetime.now()
            target = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
            if target <= now:
                target = target + timedelta(days=1)
            wait_until = target.timestamp() - int(cfg.get("prepare_time", 0))
            self.log(f"Timed start armed for {target.strftime('%H:%M:%S')}.")
            while time.time() < wait_until:
                if not self.is_monitoring:
                    return False
                time.sleep(1)
            self.log("Prepare window reached; starting monitor.", "SUCCESS")
            return True

        def _ensure_driver(self, test_only: bool = False):
            if self.driver and not test_only:
                return self.driver
            if not SELENIUM_AVAILABLE:
                raise RuntimeError("Selenium is not installed.")

            profile_dir = os.path.join(DATA_DIR, "chrome_profile_12306")
            os.makedirs(profile_dir, exist_ok=True)
            if ANTI_DETECT_AVAILABLE and AntiDetect is not None:
                try:
                    self.log("Anti-detection browser profile enabled.")
                    anti_detect = AntiDetect(DATA_DIR, log_callback=self.log, driver_path=CHROMEDRIVER_PATH)
                    driver = anti_detect.create_driver(profile_dir)
                    if not test_only:
                        self.driver = driver
                        if BehaviorSimulator is not None:
                            self.behavior_simulator = BehaviorSimulator(driver, self.log)
                        if RailDeviceIdProtector is not None:
                            self.device_id_protector = RailDeviceIdProtector(driver, self.log)
                    return driver
                except Exception as exc:
                    self.log(f"Anti-detection startup failed; falling back to standard Selenium: {exc}", "WARN")

            options = webdriver.ChromeOptions()
            options.add_argument(f"--user-data-dir={profile_dir}")
            options.add_argument("--profile-directory=Default")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--start-maximized")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)
            service = Service(executable_path=CHROMEDRIVER_PATH) if Service and os.path.exists(CHROMEDRIVER_PATH) else None
            driver = webdriver.Chrome(options=options, service=service) if service else webdriver.Chrome(options=options)
            if not test_only:
                self.driver = driver
            return driver

        def _run_worker(self, name: str, target):
            self._update_buttons()

            def run():
                try:
                    target()
                except Exception as exc:
                    self.signals.state.emit(self.state.with_error(f"{name} failed: {exc}"))
                    self.signals.buttons.emit()

            thread = threading.Thread(target=run, name=f"railwatch-{name}", daemon=True)
            self.worker_threads.append(thread)
            thread.start()

        # ------------------------------------------------------------------
        # Event handling and safety
        # ------------------------------------------------------------------
        def _handle_results(self, rows: List[dict]):
            self.query_results = rows
            self.results_table.setRowCount(0)
            for row in rows:
                index = self.results_table.rowCount()
                self.results_table.insertRow(index)
                self.results_table.setItem(index, 0, QTableWidgetItem(str(row.get("train", ""))))
                self.results_table.setItem(index, 1, QTableWidgetItem("Parsed"))
                raw = str(row.get("raw", "")).replace("\n", " / ")
                self.results_table.setItem(index, 2, QTableWidgetItem(raw))
            self._set_page(2)

        def _handle_notify(self, title: str, message: str):
            self.log(f"{title}: {message}", "SUCCESS")
            train = self._extract_after(message, "命中：", "\n") or "Target"
            hit = TicketHit(train_code=train, seat_type="Target seat", status="available", detail=message)
            self.signals.state.emit(self.state.with_hit(hit, title))
            self._append_recent_hit(hit)
            QMessageBox.information(self, title, message)

        def _append_recent_hit(self, hit: TicketHit):
            index = self.recent_hits_table.rowCount()
            self.recent_hits_table.insertRow(index)
            self.recent_hits_table.setItem(index, 0, QTableWidgetItem(datetime.now().strftime("%H:%M:%S")))
            self.recent_hits_table.setItem(index, 1, QTableWidgetItem(hit.train_code))
            self.recent_hits_table.setItem(index, 2, QTableWidgetItem(hit.seat_type))
            self.recent_hits_table.setItem(index, 3, QTableWidgetItem(hit.source))

        @staticmethod
        def _extract_after(text: str, prefix: str, stop: str) -> str:
            if prefix not in text:
                return ""
            tail = text.split(prefix, 1)[1]
            return tail.split(stop, 1)[0].strip()

        def _on_auto_submit_toggled(self, checked: bool):
            if not checked:
                self.state = self.state.with_safety(False, self.auto_alternate_check.isChecked())
                self.signals.state.emit(self.state)
                return
            if not self._confirm(
                "Enable auto submit",
                "Auto submit can click through to the order flow after a ticket is found. Continue only if this is intentional.",
            ):
                self.auto_submit_check.blockSignals(True)
                self.auto_submit_check.setChecked(False)
                self.auto_submit_check.blockSignals(False)
            self.state = self.state.with_safety(self.auto_submit_check.isChecked(), self.auto_alternate_check.isChecked())
            self.signals.state.emit(self.state)

        def _on_auto_alternate_toggled(self, checked: bool):
            if not checked:
                self.state = self.state.with_safety(self.auto_submit_check.isChecked(), False)
                self.signals.state.emit(self.state)
                return
            if not self._confirm(
                "Enable auto alternate",
                "Auto alternate can prepare a waitlist order when no regular ticket is available. Continue only if this is intentional.",
            ):
                self.auto_alternate_check.blockSignals(True)
                self.auto_alternate_check.setChecked(False)
                self.auto_alternate_check.blockSignals(False)
            self.state = self.state.with_safety(self.auto_submit_check.isChecked(), self.auto_alternate_check.isChecked())
            self.signals.state.emit(self.state)

        def _confirm_automation(self, cfg: dict) -> bool:
            if not cfg.get("auto_submit") and not cfg.get("auto_alternate"):
                return True
            enabled = []
            if cfg.get("auto_submit"):
                enabled.append("auto submit")
            if cfg.get("auto_alternate"):
                enabled.append("auto alternate")
            return self._confirm(
                "Confirm automation",
                f"You enabled {', '.join(enabled)}. RailWatch will still rely on the official 12306 page and your active login session.",
            )

        def close_browser(self):
            if not self.driver:
                return
            if not self._confirm("Close browser", "Close the controlled Chrome session now?"):
                return
            try:
                self.driver.quit()
                self.driver = None
                self.log("Browser closed.", "SUCCESS")
            except Exception as exc:
                self.log(f"Close browser failed: {exc}", "ERROR")
            self._update_buttons()

        def clear_local_data(self):
            if not self._confirm(
                "Clear local data",
                "This removes RailWatch config, logs and Chrome profile from the local data directory. The source folder is not touched.",
            ):
                return
            target = os.path.abspath(DATA_DIR)
            if os.path.basename(target) != APP_SLUG:
                self.log(f"Refusing to clear unexpected data directory: {target}", "ERROR")
                return
            try:
                self.close_browser()
                if os.path.exists(target):
                    shutil.rmtree(target)
                os.makedirs(target, exist_ok=True)
                self.log("Local RailWatch data cleared.", "SUCCESS")
            except OSError as exc:
                self.log(f"Clear local data failed: {exc}", "ERROR")

        def _toggle_event_panel(self):
            self.event_panel.setVisible(not self.event_panel.isVisible())

        def _confirm(self, title: str, message: str) -> bool:
            reply = QMessageBox.warning(
                self,
                title,
                message,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            return reply == QMessageBox.Yes

        def _show_warning(self, title: str, message: str):
            QMessageBox.warning(self, title, message)
            self.log(f"{title}: {message}", "WARN")

        def closeEvent(self, event: QCloseEvent):
            if self.is_monitoring:
                if not self._confirm("Exit RailWatch", "Monitoring is still running. Stop monitoring and exit?"):
                    event.ignore()
                    return
                self.is_monitoring = False
            if self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    pass
            event.accept()

        # ------------------------------------------------------------------
        # Styling
        # ------------------------------------------------------------------
        @staticmethod
        def _stylesheet() -> str:
            return """
            #RailWatchRoot {
                background: #f6f8f7;
                color: #17211b;
                font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
                font-size: 13px;
            }
            #Sidebar {
                background: #10281f;
                color: #eef7f1;
                border-right: 1px solid #d7e0da;
            }
            #Brand {
                font-size: 22px;
                font-weight: 700;
                color: #ffffff;
            }
            #BrandSubtitle {
                color: #9ccdb7;
                font-size: 12px;
                letter-spacing: 0;
            }
            #Sidebar QToolButton {
                border: 0;
                border-radius: 6px;
                color: #cfe3d9;
                padding: 10px 12px;
                text-align: left;
                background: transparent;
            }
            #Sidebar QToolButton:hover {
                background: #18372b;
            }
            #Sidebar QToolButton:checked {
                background: #1b8a5a;
                color: #ffffff;
                font-weight: 600;
            }
            #SidebarStatus {
                border-radius: 6px;
                background: #18372b;
                color: #d9efe5;
                padding: 10px;
            }
            #MainRegion {
                background: #f6f8f7;
            }
            #TopStatus, #Surface, QGroupBox {
                background: #ffffff;
                border: 1px solid #dbe4df;
                border-radius: 8px;
            }
            QGroupBox {
                margin-top: 14px;
                padding: 16px 12px 12px 12px;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 4px;
                color: #315047;
            }
            #TopTitle {
                font-size: 16px;
                font-weight: 700;
                color: #17211b;
            }
            #StatusChip {
                border: 1px solid #dbe4df;
                border-radius: 6px;
                padding: 6px 8px;
                background: #f5f7f6;
                color: #52625a;
            }
            #StatusChip[tone="ok"], #StatusChip[tone="success"] {
                background: #e8f5ee;
                color: #17633f;
                border-color: #b7dcc9;
            }
            #StatusChip[tone="active"] {
                background: #e9f1ff;
                color: #1f5bbf;
                border-color: #bfd2ff;
            }
            #StatusChip[tone="warning"] {
                background: #fff5df;
                color: #8b5a00;
                border-color: #f1d28f;
            }
            #StatusChip[tone="critical"] {
                background: #ffeded;
                color: #a4262c;
                border-color: #f0b5b8;
            }
            #PageTitle {
                font-size: 20px;
                font-weight: 700;
                color: #17211b;
            }
            #CardTitle {
                font-weight: 700;
                color: #24332c;
            }
            #CardBody, #InlineStatus, #SettingsNotice {
                color: #52625a;
                line-height: 1.35;
            }
            QLabel#FieldLabel {
                color: #52625a;
                font-weight: 600;
            }
            QLineEdit, QSpinBox, QDateEdit, QTimeEdit, QComboBox {
                min-height: 30px;
                border: 1px solid #cbd8d1;
                border-radius: 6px;
                padding: 4px 8px;
                background: #ffffff;
                color: #17211b;
            }
            QLineEdit:focus, QSpinBox:focus, QDateEdit:focus, QTimeEdit:focus, QComboBox:focus {
                border: 1px solid #1b8a5a;
            }
            QPushButton {
                min-height: 32px;
                border-radius: 6px;
                padding: 6px 12px;
                border: 1px solid #cbd8d1;
                background: #ffffff;
                color: #24332c;
                font-weight: 600;
            }
            QPushButton:hover {
                border-color: #8fb9a5;
                background: #f3faf6;
            }
            QPushButton:disabled {
                color: #9aa8a1;
                background: #eef2ef;
                border-color: #dbe4df;
            }
            #PrimaryButton {
                background: #1b8a5a;
                border-color: #1b8a5a;
                color: #ffffff;
            }
            #PrimaryButton:hover {
                background: #176f49;
            }
            #SecondaryButton {
                background: #f7faf8;
            }
            #DangerButton {
                color: #a4262c;
                border-color: #e0b2b5;
                background: #fff7f7;
            }
            #EventPanel {
                background: #ffffff;
                border-left: 1px solid #dbe4df;
            }
            #PanelTitle {
                font-size: 16px;
                font-weight: 700;
            }
            #EventLog {
                border: 1px solid #dbe4df;
                border-radius: 8px;
                background: #fbfcfb;
                color: #24332c;
                font-family: Consolas, "Courier New", monospace;
                font-size: 12px;
            }
            #DataTable {
                background: #ffffff;
                border: 1px solid #dbe4df;
                border-radius: 8px;
                gridline-color: #edf2ef;
                selection-background-color: #dff2e9;
                selection-color: #17211b;
            }
            QHeaderView::section {
                background: #eef3f0;
                color: #315047;
                padding: 7px;
                border: 0;
                border-right: 1px solid #dbe4df;
                font-weight: 700;
            }
            """


else:

    class RailWatchMainWindow:
        def __init__(self):
            raise RuntimeError(f"PySide6 is required for {APP_DISPLAY_NAME}: {PYSIDE6_IMPORT_ERROR}")


def main() -> int:
    if not PYSIDE6_AVAILABLE:
        raise RuntimeError(f"PySide6 is required for {APP_DISPLAY_NAME}: {PYSIDE6_IMPORT_ERROR}")

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setOrganizationName("RailWatch")
    window = RailWatchMainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
