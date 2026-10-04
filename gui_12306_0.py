"""
GUI 专用：12306 查询页分析 + 余票监控（合规版）- 风控优化增强版
改进点：
1) 自动下载/缓存 station_name.js，中文站名 -> 三字码
2) 自动填入 fromStationText/fromStation/toStationText/toStation/train_date
3) 自动点击"查询"按钮
4) 等待结果行出现再解析
5) [优化] 移除硬编码选择器，动态定位预订按钮
6) [优化] 支持多车次、多席别监控
7) [优化] 改进异常处理和日志记录
8) [优化] 添加配置持久化
9) [风控优化] 随机刷新间隔（±30% 浮动）
10) 受控查询与错误退避
"""

import time
import re
import sys
import os
import json
import urllib.request
import random
import threading
import uuid
from typing import Optional, List, Dict, Callable, Tuple, Any
from dataclasses import dataclass, field, replace
from enum import Enum

from railwatch_dates import expand_travel_dates
from railwatch_query import FillResult, fill_result, QueryExecutor, FILL_QUERY_FORM_JS, DISMISS_DIALOG_JS, query_snapshot, query_conditions
from railwatch_row_parser import RowParser, TRAIN_CODE_PATTERN, DISPLAY_SEATS
from railwatch_selectors import (
    ALTERNATE_BUTTON_SELECTORS,
    BOOK_BUTTON_SELECTORS,
    QUERY_BUTTON_ID,
    QUERY_ROW_SELECTOR,
    QUERY_TABLE_ID,
)
from railwatch_submit_flow import SubmitFlow
from railwatch_alternate_flow import AlternateFlow
from railwatch_orders import OrderIntent, OrderResult
from railwatch_config_contract import parse_codes, parse_passenger_names
from railwatch_order_page import OrderPage
from railwatch_time import ServerTimeSync, get_server_time_sync
from railwatch_preferences import atomic_write_json
from railwatch_seats import seat_prefix
from railwatch_task import is_session_lost
from railwatch_date_plan import DatePlan
from railwatch_policies import DATE_STRATEGIES
from railwatch_timing import PhaseTiming


def _safe_print(title: str, msg: str) -> None:
    """Print that won't crash on Windows cp1252 when string contains emoji / CJK."""
    try:
        print(title, msg, flush=True)
    except UnicodeEncodeError:
        safe_title = title.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8", errors="replace")
        safe_msg = msg.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8", errors="replace")
        print(safe_title, safe_msg, flush=True)

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import (
    TimeoutException, 
    NoSuchElementException, 
    StaleElementReferenceException,
    ElementClickInterceptedException
)

# 尝试导入反检测模块
try:
    from anti_detect import AdaptiveRateLimiter, get_random_interval, human_delay
    ANTI_DETECT_AVAILABLE = True
except ImportError:
    ANTI_DETECT_AVAILABLE = False
    AdaptiveRateLimiter = None
    # 定义兜底函数
    import random
    def get_random_interval(base_interval: int) -> float:
        variation = base_interval * 0.3
        return base_interval + random.uniform(-variation, variation)
    def human_delay(min_s: float = 0.3, max_s: float = 1.5):
        import time
        time.sleep(random.uniform(min_s, max_s))


# ==================== 常量定义 ====================
STATION_JS_URL = "https://kyfw.12306.cn/otn/resources/js/framework/station_name.js"
CACHE_FILE = "station_codes_cache.json"
STATION_SEARCH_FILE = "station_search_cache.json"
USER_CONFIG_FILE = "user_config.json"

# 仅明确未起售提示在冲刺期间使用短重试，其他故障遵循正常退避。
BURST_RETRY_SLEEP_SECONDS = 1.0

def _read_float(value: object, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


# ==================== 席别映射 ====================
class SeatType(Enum):
    """席别类型枚举"""
    SECOND_CLASS = ("二等座", "ZE")
    FIRST_CLASS = ("一等座", "ZY")
    BUSINESS = ("商务座", "SWZ")
    SPECIAL = ("特等座", "TZ")
    NO_SEAT = ("无座", "WZ")
    HARD_SEAT = ("硬座", "YZ")
    SOFT_SEAT = ("软座", "RZ")
    HARD_SLEEPER = ("硬卧", "YW")
    SOFT_SLEEPER = ("软卧", "RW")
    DELUXE_SOFT_SLEEPER = ("高级软卧", "GR")
    DYNAMIC_SLEEPER = ("动卧", "SRRB")
    
    @classmethod
    def get_prefix(cls, seat_name: str) -> Optional[str]:
        """根据统一席别能力表获取 td id 前缀。"""
        return seat_prefix((seat_name or "").strip())


# ==================== 配置数据类 ====================
@dataclass
class MonitorTarget:
    """监控目标配置"""
    train_codes: List[str] = field(default_factory=list)  # 目标车次列表，空表示不限
    seat_types: List[str] = field(default_factory=list)   # 目标席别列表，空表示不限
    
    def matches_train(self, train_code: str) -> bool:
        """检查车次是否匹配"""
        if not self.train_codes:
            return True  # 不限车次
        return train_code in self.train_codes
    
    def get_seat_list(self) -> List[str]:
        """获取席别列表"""
        return self.seat_types if self.seat_types else [""]


@dataclass 
class QueryConfig:
    """查询配置"""
    from_station_cn: str = ""
    to_station_cn: str = ""
    date: str = ""
    train_code: str = ""      # 兼容旧版单车次
    seat_keyword: str = ""    # 兼容旧版单席别
    interval: float = 3.0
    query_timeout: int = 40
    query_priority: str = "reliability"
    request_mode: str = "legacy"
    auto_submit: bool = False  # 是否自动提交订单
    seat_prefer: str = "无偏好"  # 座位偏好：无偏好/靠窗优先/靠过道优先
    passenger_count: int = 1    # 未指定姓名时默认勾选的乘车人数
    
    # 定时开抢增强
    prepare_time: int = 2      # 兼容字段：仅用于冲刺窗口判断，不提前定时查询
    keep_alive: bool = True     # 是否开启会话保活
    passengers: str = ""       # 目标乘车人姓名，逗号分隔
    passenger_selections: List[dict] = field(default_factory=list)
    
    # 候补订单功能
    auto_alternate: bool = False  # 是否启用无票时自动候补
    alternate_deadline: str = ""  # 候补截止时间，如 "18:00"
    alternate_mode: str = "single"
    alternate_max_combinations: int = 5
    order_watch_enabled: bool = True
    order_watch_interval_seconds: int = 60
    date_range: str = "单日"
    date_strategy: str = "round_robin"
    date_scan_budget_seconds: float = 30.0
    smart_rate: bool = True
    timer_enabled: bool = False
    target_time: str = "00:00:00"
    sale_at: str = ""
    sale_time_source: str = "manual"
    sale_time_checked_at: str = ""
    burst_window_seconds: float = 45.0
    prewarm_lead_seconds: float = 120.0  # 兼容字段；桌面端在启动任务时立即准备页面
    
    # 新增：多目标支持
    targets: List[MonitorTarget] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "from_station_cn": self.from_station_cn,
            "to_station_cn": self.to_station_cn,
            "date": self.date,
            "train_code": self.train_code,
            "seat_keyword": self.seat_keyword,
            "interval": self.interval,
            "query_timeout": self.query_timeout,
            "query_priority": self.query_priority,
            "request_mode": self.request_mode,
            "auto_submit": self.auto_submit,
            "seat_prefer": self.seat_prefer,
            "passenger_count": self.passenger_count,
            "prepare_time": self.prepare_time,
            "keep_alive": self.keep_alive,
            "passengers": self.passengers,
            "passenger_selections": self.passenger_selections,
            "auto_alternate": self.auto_alternate,
            "alternate_deadline": self.alternate_deadline,
            "alternate_mode": self.alternate_mode,
            "alternate_max_combinations": self.alternate_max_combinations,
            "order_watch_enabled": self.order_watch_enabled,
            "order_watch_interval_seconds": self.order_watch_interval_seconds,
            "date_range": self.date_range,
            "date_strategy": self.date_strategy,
            "date_scan_budget_seconds": self.date_scan_budget_seconds,
            "smart_rate": self.smart_rate,
            "timer_enabled": self.timer_enabled,
            "target_time": self.target_time,
            "sale_at": self.sale_at,
            "sale_time_source": self.sale_time_source,
            "sale_time_checked_at": self.sale_time_checked_at,
            "burst_window_seconds": self.burst_window_seconds,
            "prewarm_lead_seconds": self.prewarm_lead_seconds,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "QueryConfig":
        """从字典创建"""
        return cls(
            from_station_cn=data.get("from_station_cn", ""),
            to_station_cn=data.get("to_station_cn", ""),
            date=data.get("date", ""),
            train_code=data.get("train_code", ""),
            seat_keyword=data.get("seat_keyword", ""),
            interval=data.get("interval", 3.0),
            query_timeout=data.get("query_timeout", 40),
            query_priority=data.get("query_priority", "reliability"),
            request_mode=data.get("request_mode", "legacy"),
            auto_submit=data.get("auto_submit", False),
            seat_prefer=data.get("seat_prefer", "无偏好"),
            passenger_count=data.get("passenger_count", 1),
            prepare_time=data.get("prepare_time", 2),
            keep_alive=data.get("keep_alive", True),
            passengers=data.get("passengers", ""),
            passenger_selections=data.get("passenger_selections", []),
            auto_alternate=data.get("auto_alternate", False),
            alternate_deadline=data.get("alternate_deadline", ""),
            alternate_mode=data.get("alternate_mode", "single"),
            alternate_max_combinations=data.get("alternate_max_combinations", 5),
            order_watch_enabled=data.get("order_watch_enabled", True),
            order_watch_interval_seconds=data.get("order_watch_interval_seconds", 60),
            date_range=data.get("date_range", "单日"),
            date_strategy=data.get("date_strategy", "round_robin"),
            date_scan_budget_seconds=data.get("date_scan_budget_seconds", 30.0),
            smart_rate=data.get("smart_rate", True),
            timer_enabled=data.get("timer_enabled", False),
            target_time=data.get("target_time", "00:00:00"),
            sale_at=data.get("sale_at", ""),
            sale_time_source=data.get("sale_time_source", "manual"),
            sale_time_checked_at=data.get("sale_time_checked_at", ""),
            burst_window_seconds=_read_float(data.get("burst_window_seconds", 45), 45.0),
            prewarm_lead_seconds=_read_float(data.get("prewarm_lead_seconds", 120), 120.0),
        )


# ==================== 配置管理器 ====================
class ConfigManager:
    """配置持久化管理器"""
    
    def __init__(self, base_dir: str):
        self.config_path = os.path.join(base_dir, USER_CONFIG_FILE)
        self._lock = threading.RLock()
        self.last_error = ""
    
    def save(self, config: QueryConfig) -> bool:
        """保存配置"""
        try:
            with self._lock:
                atomic_write_json(self.config_path, config.to_dict())
            self.last_error = ""
            return True
        except Exception as exc:
            self.last_error = str(exc)
            return False
    
    def load(self) -> Optional[QueryConfig]:
        """加载配置"""
        if not os.path.exists(self.config_path):
            self.last_error = ""
            return None
        try:
            with self._lock:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            self.last_error = ""
            return QueryConfig.from_dict(data)
        except Exception as exc:
            self.last_error = str(exc)
            return None


# ==================== 基础工具类 ====================
class BaseHandler:
    """基础处理器，提供公共方法"""
    
    def __init__(self, driver, log_callback: Optional[Callable[[str], None]] = None):
        self.driver = driver
        self.log = log_callback or (lambda x: print(x))
    
    def wait_for_rows(self, timeout: int = 40, stop_check: Optional[Callable[[], bool]] = None) -> bool:
        """等待查询结果行出现"""
        end_time = time.time() + timeout
        while time.time() < end_time:
            if stop_check and stop_check():
                return False
            try:
                table = self.driver.find_element(By.ID, "queryLeftTable")
                rows = table.find_elements(By.CSS_SELECTOR, "tr[id^='ticket_']")
                for row in rows:
                    text = row.text.strip()
                    if text and TRAIN_CODE_PATTERN.search(text):
                        return True
            except (NoSuchElementException, StaleElementReferenceException):
                pass
            time.sleep(0.5)
        return False
    
    def click_query_button(self) -> bool:
        """点击查询按钮"""
        try:
            btn = WebDriverWait(self.driver, 15).until(
                EC.element_to_be_clickable((By.ID, "query_ticket"))
            )
            btn.click()
            return True
        except TimeoutException:
            self.log("⚠️ 等待查询按钮超时")
        except ElementClickInterceptedException:
            # 尝试 JS 点击
            try:
                self.driver.execute_script("""
                    const b = document.querySelector('#query_ticket') || document.querySelector('.btn92s');
                    if (b) b.click();
                """)
                return True
            except Exception as e:
                self.log(f"⚠️ JS 点击查询按钮失败：{e}")
        except Exception as e:
            self.log(f"⚠️ 点击查询按钮失败：{e}")
        return False
    
    def extract_train_code(self, text: str) -> Optional[str]:
        """从文本中提取车次号"""
        match = TRAIN_CODE_PATTERN.search(text)
        return match.group(1) if match else None
    
    def get_seat_value_by_prefix(self, row_element, seat_keyword: str) -> Optional[str]:
        """通过 td id 前缀获取席别值"""
        prefix = SeatType.get_prefix(seat_keyword)
        if not prefix:
            return None
        try:
            td = row_element.find_element(By.CSS_SELECTOR, f"td[id^='{prefix}_']")
            return td.text.strip().replace("\n", "")
        except NoSuchElementException:
            return None
        except Exception:
            return None
    
    @staticmethod
    def is_seat_available(value: str) -> bool:
        """判断席别是否可用"""
        if value is None:
            return False
        value = value.strip()
        if value in ("", "--", "无", "0", "*"):
            return False
        if value == "有":
            return True
        if re.fullmatch(r"\d+", value):
            try:
                return int(value) > 0
            except ValueError:
                return False
        return False
    
    @staticmethod
    def is_alternate_available(value: str) -> bool:
        """判断是否可提交候补"""
        if value is None:
            return False
        return "候补" in value.strip()

    def _parse_rows(self) -> List[dict]:
        parser = getattr(self, "row_parser", None) or RowParser(self.driver, SeatType.get_prefix)
        return parser.parse_rows()


# ==================== 站点编码解析器 ====================
class StationCodeResolver:
    """站点编码解析器"""
    
    def __init__(self, base_dir: str, log: Optional[Callable[[str], None]] = None):
        self.base_dir = base_dir
        self.log = log or (lambda x: None)
        self.cache_path = os.path.join(base_dir, CACHE_FILE)
        self._name2code: Optional[Dict[str, str]] = None
        self._search_index: Optional[Tuple[List[dict], bool]] = None

    def load(self) -> Dict[str, str]:
        """加载站点编码映射"""
        if self._name2code is not None:
            return self._name2code

        # 优先读缓存
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if not isinstance(loaded, dict) or not all(isinstance(name, str) and isinstance(code, str)
                                                          for name, code in loaded.items()):
                    raise ValueError("站码缓存格式无效")
                self._name2code = loaded
                self.log(f"✅ 站点编码缓存已加载：{len(self._name2code)} 条")
                return self._name2code
            except (json.JSONDecodeError, IOError, ValueError) as e:
                self.log(f"⚠️ 缓存读取失败，将重新下载：{e}")

        # 下载 station_name.js
        self._name2code = self._download_and_parse()
        return self._name2code
    
    def _download_and_parse(self) -> Dict[str, str]:
        """下载并解析站点数据"""
        self.log("⬇️ 正在下载站点编码（station_name.js）...")
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                with urllib.request.urlopen(STATION_JS_URL, timeout=20) as response:
                    js_text = response.read().decode("utf-8", errors="ignore")
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    self.log(f"⚠️ 下载失败，重试中 ({attempt + 1}/{max_retries})：{e}")
                    time.sleep(1)
                else:
                    raise RuntimeError(f"下载站点数据失败：{e}")

        # 提取 station_names = '...'
        match = re.search(r"station_names\s*=\s*'([^']+)'", js_text)
        if not match:
            raise RuntimeError("无法解析 station_name.js（可能路径更新）")

        raw = match.group(1)
        # 格式：@bjb|北京北|VAP|beijingbei|bjb|0@...
        name2code: Dict[str, str] = {}
        searchable = []
        items = raw.split("@")
        for item in items:
            if not item.strip():
                continue
            parts = item.split("|")
            if len(parts) >= 3:
                cn_name = parts[1].strip()
                code = parts[2].strip()
                if cn_name and code:
                    name2code[cn_name] = code
                    searchable.append({"name": cn_name, "code": code,
                                       "pinyin": parts[3].strip() if len(parts) > 3 else "",
                                       "initials": parts[4].strip() if len(parts) > 4 else ""})
        if not name2code:
            raise RuntimeError("站码数据为空，旧缓存已保留。")

        # 保存缓存
        try:
            atomic_write_json(self.cache_path, name2code)
            self.log(f"✅ 站点编码已缓存：{len(name2code)} 条")
        except IOError as e:
            self.log(f"⚠️ 缓存保存失败：{e}")

        try:
            atomic_write_json(os.path.join(self.base_dir, STATION_SEARCH_FILE), searchable)
        except OSError as e:
            self.log(f"⚠️ 站名联想缓存保存失败：{e}")

        self._search_index = (searchable, False)
        return name2code

    def _load_search_index(self, names: Dict[str, str]) -> Tuple[List[dict], bool]:
        """Return (records, from_legacy_cache), reading the disk cache only once per resolver."""
        if self._search_index is not None:
            return self._search_index
        records = None
        try:
            with open(os.path.join(self.base_dir, STATION_SEARCH_FILE), encoding="utf-8") as handle:
                value = json.load(handle)
            if isinstance(value, list):
                records = [entry for entry in value if isinstance(entry, dict) and
                           names.get(entry.get("name")) == entry.get("code")]
        except (OSError, ValueError, TypeError):
            pass
        old_cache = records is None
        if records is None:
            records = [{"name": name, "code": code, "pinyin": "", "initials": ""}
                       for name, code in names.items()]
        self._search_index = (records, old_cache)
        return self._search_index

    def search(self, query: str, limit: int = 12) -> dict:
        """Search known stations without broadening the submitted station name."""
        if not isinstance(query, str) or len(query) > 80 or type(limit) is not int or not 1 <= limit <= 30:
            raise ValueError("站名搜索参数无效。")
        needle = query.strip().lower()
        if not needle:
            return {"items": [], "warning": None}
        try:
            names = self.load()
        except Exception as exc:
            return {"items": [], "warning": f"站码缓存不可用，请检查网络后重试；仍可手动输入完整站名。原因：{exc}"}
        records, old_cache = self._load_search_index(names)
        matches = [entry for entry in records if any(needle in str(entry.get(key, "")).lower()
                   for key in ("name", "pinyin", "initials"))]
        matches.sort(key=lambda entry: (0 if entry["name"].lower() == needle else
                                        1 if entry["name"].lower().startswith(needle) else 2,
                                        entry["name"]))
        warning = "旧站码缓存仅支持中文联想；联网后可更新站码数据。" if old_cache and needle.isascii() else None
        return {"items": matches[:limit], "warning": warning}

    def refresh(self) -> dict:
        """Explicit user refresh; a failed download leaves the old cache intact."""
        names = self._download_and_parse()
        self._name2code = names
        return {"count": len(names)}

    def get_code(self, cn_name: str) -> str:
        """获取站点编码"""
        data = self.load()
        cn_name = cn_name.strip()
        
        # 精确匹配
        if cn_name in data:
            return data[cn_name]
        if cn_name.endswith("站") and cn_name[:-1] in data:
            return data[cn_name[:-1]]
        
        matches = [(key, value) for key, value in data.items() if cn_name in key or key in cn_name]
        if len(matches) == 1:
            return matches[0][1]
        if matches:
            raise ValueError(f"站名不明确：{cn_name}，请填写完整站名。")
        raise ValueError(f"未知站名：{cn_name}")


class PageAnalyzer(BaseHandler):
    """页面分析器"""
    
    def __init__(self, driver, log_callback: Optional[Callable[[str], None]] = None, base_dir: Optional[str] = None):
        super().__init__(driver, log_callback)
        if base_dir is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        self.resolver = StationCodeResolver(base_dir, log=self.log)

    def fill_query_form(self, from_cn: str, to_cn: str, date: str, timeout: int = 3) -> FillResult:
        from_cn, to_cn, date = (str(value or "").strip() for value in (from_cn, to_cn, date))
        if not (from_cn and to_cn and date):
            return FillResult("config_error", "出发站、到达站和日期不能为空")
        try:
            from_code, to_code = self.resolver.get_code(from_cn), self.resolver.get_code(to_cn)
        except ValueError as exc:
            return FillResult("config_error", str(exc))
        except Exception as exc:
            return FillResult("retry", f"站码加载失败：{exc}")
        try:
            WebDriverWait(self.driver, timeout).until(EC.presence_of_element_located((By.ID, "fromStationText")))
            if self.driver.execute_script(FILL_QUERY_FORM_JS, from_cn, from_code, to_cn, to_code, date) is not True:
                return FillResult("retry", "查询字段缺失或回读不一致")
        except Exception as exc:
            return FillResult("retry", f"查询页未就绪：{exc}")
        return FillResult("success")

    def open_fill_query_and_analyze(self, cfg: dict) -> Optional[List[dict]]:
        """
        打开查询页 -> 自动填参 -> 自动点查询 -> 等待结果行 -> 解析
        """
        self.last_query = {}
        self.log("🌐 正在打开 12306 车票查询页...")
        self.driver.get("https://kyfw.12306.cn/otn/leftTicket/init?linktypeid=dc")

        # 等页面输入框出现
        self.log("⏳ 等待查询输入框加载...")
        try:
            WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located((By.ID, "fromStationText"))
            )
            WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located((By.ID, "toStationText"))
            )
            WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located((By.ID, "train_date"))
            )
        except TimeoutException:
            self.log("❌ 页面加载超时，请检查网络连接")
            return None

        # 站码 + 一次性写入（包含隐藏字段），复用 fill_query_form
        from_cn = cfg["from_station_cn"]
        to_cn = cfg["to_station_cn"]
        date = cfg["date"]

        filled = fill_result(self.fill_query_form(from_cn, to_cn, date))
        if not filled:
            raise ValueError(filled.reason) if filled.status == "config_error" else RuntimeError(filled.reason)

        executor = QueryExecutor(self.driver, stop_check=getattr(self, "stop_check", lambda: False),
                                 wait=getattr(self, "wait_callback", None))
        result = executor.execute(self.click_query_button, int(cfg.get("query_timeout", 40)))
        self.last_query = result
        if result["status"] not in ("ok", "empty"):
            raise RuntimeError(result.get("reason") or "本轮查询未完成")
        rows = [] if result["status"] == "empty" else self._parse_rows()
        if not executor.current():
            raise RuntimeError("查询结果已失效，请重新查询")
        self.last_query = result
        return [{**row, "date": date} for row in rows]

    @staticmethod
    def _format_row(row: dict) -> str:
        """格式化行显示"""
        return f"🚄 {row['train']} | {row['raw'].replace(chr(10), ' / ')[:140]}..."


# ==================== 余票监控器 ====================
class TicketMonitor(BaseHandler):
    """
    余票监控器（优化版）：
    - 每轮：刷新页面 -> 自动点击[查询] -> 等待结果 -> 解析是否命中
    - 命中条件：
        1) 车次匹配（支持多车次）
        2) 指定席别列（支持多席别）对应单元格出现：有 / 候补 / 数字>0
    - 命中后：定位到车次行 + 高亮 + 语音/弹窗提醒
    - [优化] 移除硬编码选择器，动态定位
    - [优化] 可选自动提交订单
    """

    CANDIDATE_RETRY_SECONDS = 30.0

    def __init__(
        self, 
        driver, 
        cfg: dict, 
        log_callback: Optional[Callable[[str], None]] = None, 
        stop_check: Optional[Callable[[], bool]] = None, 
        notify_callback: Optional[Callable[[str, str], None]] = None,
        progress_callback: Optional[Callable[[dict], None]] = None,
        on_hit: Optional[Callable[[dict], None]] = None,
        human_action_callback: Optional[Callable[[dict], None]] = None,
        server_time_sync: Optional[ServerTimeSync] = None,
        param_filler: Optional[Callable[[str, str, str], bool]] = None,
        wait_callback=None,
        tick_callback=None,
        session_check=None,
        date_provider=None,
        order_journal=None,
        on_order=None,
        run_id="",
        query_start_callback=None,
    ):
        super().__init__(driver, log_callback)
        self.cfg = dict(cfg)
        self.should_stop = stop_check or (lambda: False)
        self._wait_callback = wait_callback
        self.tick = tick_callback or (lambda **kwargs: None)
        self.session_check = session_check or (lambda: True)
        self.date_provider = date_provider
        self._fill_failures = 0
        self._needs_navigation = False
        self.last_query = {}
        self.order_journal, self.on_order, self.run_id = order_journal, on_order, run_id
        self._prefer_alternate = False
        self._fallback_date = ""
        self._candidate_cooldowns = {}
        self._prepared = False
        self._last_query_started = None
        self.query_executor = QueryExecutor(driver, self.should_stop, self._poll_wait, lambda: self.tick()) if param_filler else None
        self.notify = notify_callback or (lambda title, msg: print(title, msg, flush=True) if title.isascii() and msg.isascii() else _safe_print(title, msg))
        self.progress = progress_callback
        self.query_start_callback = query_start_callback
        self.on_hit = on_hit
        self.human_action = human_action_callback
        self.server_time_sync = server_time_sync or get_server_time_sync(log_callback=self.log)
        
        # 解析目标车次和席别
        self.target_trains = self._parse_train_targets()
        self.target_seats = self._parse_seat_targets()
        self.auto_submit = cfg.get("auto_submit", False)
        self.auto_alternate = cfg.get("auto_alternate", False)
        self.rate_limiter = None
        if cfg.get("smart_rate", False) and AdaptiveRateLimiter:
            from railwatch_policies import rate_bounds
            min_interval, max_interval = rate_bounds(cfg)
            base_interval = max(min_interval, _read_float(cfg.get("interval", 3), 3.0))
            self.rate_limiter = AdaptiveRateLimiter(
                base_interval=base_interval,
                min_interval=min_interval,
                max_interval=max(max_interval, base_interval),
                log_callback=self.log,
            )
        travel_date = str(cfg.get("date", "")).strip()
        self.preferred_date = travel_date
        self.date_plan = DatePlan(travel_date, cfg.get("date_strategy", "round_robin"),
                                  cfg.get("date_scan_budget_seconds", 30))
        self._date_last_query = {}
        self._query_timing = None
        self._query_invalidated = False
        self._date_revisit_ms = None
        self.travel_dates = expand_travel_dates(travel_date, str(cfg.get("date_range", "单日"))) if travel_date else []
        self.current_loop_date = ""
        # 参数同步：定时/爆发路径不依赖浏览器残留的上次查询条件
        self.param_filler = param_filler
        self.params_filled = False
        self._form_snapshot = None
        self.row_parser = RowParser(self.driver, SeatType.get_prefix)
        self._row_snapshot = None
        self.submit_flow = SubmitFlow(
            self.driver,
            cfg,
            log_callback=self.log,
            popup_handler=self._handle_popups,
        )
        self.alternate_flow = AlternateFlow(
            self.driver,
            cfg,
            log_callback=self.log,
            human_action_callback=self.human_action,
            find_alternate_button=self._find_alternate_button,
        )
        self.order_page = OrderPage(driver, self.should_stop, self._poll_wait, self._mark, log=self.log,
                                    poll_interval=0.05 if cfg.get("timer_enabled") else 0.1)
        self.submit_flow.order_page = self.order_page
        self.alternate_flow.order_page = self.order_page

    def _mark(self, stage, detail=None):
        if self.order_journal:
            marker = self.order_journal.record_telemetry if stage in ("query_click", "query_result") else self.order_journal.mark
            marker(self.run_id, stage, getattr(self, "_intent_id", ""), detail)

    def _execute_order(self, hit):
        self._timing_step("pre_submit")
        train, seat, _, row, button, action = hit
        if not self.order_journal:
            self._signal_human_action(train, "订单持久化不可用，已停止自动提交")
            return True
        intent = OrderIntent.from_config(self.cfg, train, seat, "alternate" if action == "alternate" else "regular")
        route = self.row_parser.selected_route(row)
        if route:
            intent = replace(intent, from_station=route[0], to_station=route[1])
        self._intent_id = intent.intent_id
        saved_config = dict(self.cfg)
        if action == "alternate" and self.cfg.get("alternate_mode") == "multiple":
            # Freeze the eligible date set from the task, not a range expanded
            # again around the most recently queried date.
            self.date_plan.sync(self.travel_dates)
            saved_config["_alternate_dates"] = ([intent.date] if self._sale_focus_active() or self._prefer_alternate
                                                else list(self.date_plan.dates))
            self.alternate_flow.cfg = saved_config
            def bind_intent(updated):
                nonlocal intent
                self.order_journal.bind_alternatives(updated)
                intent = updated
                if self.on_order:
                    self.on_order(intent, OrderResult("submitting"))
            self.order_page.bind_intent = bind_intent
        try:
            self.order_journal.begin(self.run_id, intent, saved_config)
        except Exception:
            self._signal_human_action(train, "无法取得订单提交权限，请先核对未完成订单和本地存储")
            return True
        if self.on_order:
            self.on_order(intent, OrderResult("submitting"))
        self._mark("no_inventory" if action == "alternate" else "inventory_found")
        self._finish_query_timing()
        result = (self.alternate_flow.try_alternate_order(row, train, seat, intent=intent)
                  if action == "alternate" else self.submit_flow.try_auto_submit(button, seat, intent=intent))
        if not isinstance(result, OrderResult):
            result = OrderResult("unknown", "提交适配器未返回可验证的订单结果")
        if action == "book" and result.status == "unknown" and result.reason == "官方提示余票不足":
            # Only OrderPage knows whether confirmation was dispatched. A sold-out
            # message alone must not authorize leaving an ambiguous confirmation.
            result = self.order_page.reconcile(intent, navigate=False)
        try:
            result = self.order_journal.record(intent, result)
            self._mark("confirmed_failure" if result.can_fallback else result.status)
        except Exception:
            self._signal_human_action(train, "订单结果无法保存，请保留当前页面并核对订单，禁止重新提交")
            return True
        if self.on_order:
            self.on_order(intent, result)
        if self.should_stop():
            return True
        # Only journal-verified failures before submission permit another action.
        # A missing *entry* button is retryable; a missing final submit button or
        # a human verification requirement still needs inspection of the page.
        retry_candidate = (action == "book" and result.can_fallback) or (
            action == "alternate" and result.status == "not_submitted" and result.no_order
            and result.evidence.get("candidate_unavailable") is True)
        if retry_candidate:
            self._cool_down_candidate(train, seat, action)
            self._prefer_alternate = action == "book" and self.auto_alternate
            self._fallback_date = intent.date if self._prefer_alternate else ""
            self._needs_navigation = True
            if not self._prefer_alternate:
                interval = (self.rate_limiter.get_interval() if self.rate_limiter else
                            get_random_interval(max(1.0, _read_float(self.cfg.get("interval", 3), 3.0))))
                self._sleep(interval)
            return False  # Sold-out to waitlist stays immediate; other retries use normal cadence.
        if result.status in ("unknown", "verification", "not_submitted", "sold_out"):
            self._signal_human_action(train, result.reason or "请检查官方订单状态")
        return True
    
    def _parse_train_targets(self) -> List[str]:
        """解析目标车次列表"""
        return parse_codes(self.cfg.get("train_code", ""), upper=True)

    def _parse_seat_targets(self) -> List[str]:
        """解析目标席别列表"""
        return parse_codes(self.cfg.get("seat_keyword", ""))

    def _apply_loop_date(self, loop_count: int, force: bool = False) -> None:
        if self.date_provider:
            self.travel_dates = self.date_provider()
            if not self.travel_dates:
                raise ValueError("所有出行日期均已失效，请修改行程")
        if not self.travel_dates:
            return
        if self._prefer_alternate and self._fallback_date not in self.travel_dates:
            raise ValueError("原预订日期已失效，已停止候补回退，请核对行程")
        travel_date = self._loop_date(loop_count)
        if travel_date == self.current_loop_date and not force:
            return
        self.driver.execute_script(
            """
            const date = arguments[0];
            const input = document.querySelector('#train_date');
            if (input) {
                input.removeAttribute('readonly');
                input.value = date;
                input.dispatchEvent(new Event('input', {bubbles: true}));
                input.dispatchEvent(new Event('change', {bubbles: true}));
            }
            """,
            travel_date,
        )
        self.current_loop_date = travel_date
        self.cfg["date"] = travel_date
        if len(self.travel_dates) > 1:
            self.log(f"📅 本轮监控日期：{travel_date}")

    def _human_delay(self, low, high):
        self._sleep(random.uniform(low, high))

    def _poll_wait(self, seconds):
        if self._wait_callback:
            self._wait_callback(seconds)
        else:
            time.sleep(seconds)

    def _sleep(self, seconds):
        self._finish_query_timing()
        self.tick(status="backoff", next_query_at=time.time() + seconds)
        self._poll_wait(seconds)

    def _fill_query_params(self, force: bool = False) -> bool:
        if not self.param_filler:
            return True
        expected = (str(self.cfg.get("from_station_cn", "")), str(self.cfg.get("to_station_cn", "")),
                    self.current_loop_date or str(self.cfg.get("date", "")))
        if force:
            self.params_filled = False
            self._form_snapshot = None
        if self.params_filled and self.query_executor.snapshot_form() == self._form_snapshot:
            values = self._form_snapshot.get("values", []) if isinstance(self._form_snapshot, dict) else []
            if len(values) == 5 and (values[0], values[2], values[4]) == expected:
                return True
        result = fill_result(self.param_filler(*expected))
        self.params_filled = bool(result)
        if result:
            self._fill_failures = 0
            self._form_snapshot = self.query_executor.snapshot_form()
            return True
        self._fill_failures += 1
        self.log(f"查询参数同步失败：{result.reason}")
        if result.status == "config_error" or self._fill_failures >= 3:
            raise ValueError(result.reason or "连续三次无法同步查询参数")
        return False

    def _dismiss_query_blockers(self) -> str:
        executor = self.query_executor or QueryExecutor(self.driver)
        dialog = executor.inspect_dialog()
        if dialog["kind"] == "not_on_sale":
            if self.driver.execute_script(DISMISS_DIALOG_JS, dialog["text"]) is True:
                self.log(f"已关闭未起售提示：{dialog['text']}")
                return dialog["text"]
        elif dialog["kind"] != "none":
            self._signal_human_action("", dialog["text"] or "需要检查浏览器弹窗")
        return ""

    def prepare(self):
        """Finish local setup and first-date filling before the scheduled deadline."""
        if self.should_stop():
            return False
        base_interval = max(1.0, _read_float(self.cfg.get("interval", 3), 3.0))
        if self.rate_limiter:
            self.log(f"⏱ 智能限速：基础 {self.rate_limiter.base_interval}s，±20% 浮动，范围 {self.rate_limiter.min_interval}–{self.rate_limiter.max_interval}s")
        else:
            self.log(f"⏱ 基础刷新间隔：{base_interval}s（实际将随机浮动 ±30%）")
        self.log(f"🚄 目标车次：{', '.join(self.target_trains) if self.target_trains else '不限定'}")
        self.log(f"💺 目标席别：{', '.join(self.target_seats) if self.target_seats else '不限定'}")
        self.log(f"📝 自动提交：{'开启' if self.auto_submit else '关闭'}")
        self.log(f"🔄 自动候补：{'开启' if self.auto_alternate else '关闭'}")
        policy = DATE_STRATEGIES["strategies"][self.date_plan.strategy]
        self.log(f"多日期策略：{policy['label']}。{policy['description']}")
        if self.date_plan.strategy == "inventory_first":
            self.log(f"跨日期扫描预算：{self.date_plan.budget:g}秒；查询、限频等待与候补重查仍按正常节奏执行。")
        self.log("监控流程：查询 → 校验结果 → 预订或首选候补 → 核对订单证据")
        self.log("受控查询；遇到核验或未知订单结果时暂停处理。")

        # 确保在查询页
        try:
            WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located((By.ID, "query_ticket"))
            )
        except TimeoutException:
            self.log("⚠️ 未检测到查询按钮：请确认当前页面是余票查询页。")
            return False

        if self.cfg.get("timer_enabled"):
            self._apply_loop_date(1)
            if not self._fill_query_params():
                raise ValueError("定时首轮查询参数未就绪，请检查官方页面后重新启动。")
            self.log(f"定时首轮已准备：{self.current_loop_date or self.preferred_date}；起售窗口优先查询所选日期。")
        self._prepared = True
        return True

    def _candidate_key(self, train, seat, action):
        return (self.cfg.get("from_station_cn", ""), self.cfg.get("to_station_cn", ""),
                self.cfg.get("date", ""), train, seat, action)

    def _cool_down_candidate(self, train, seat, action):
        self._candidate_cooldowns[self._candidate_key(train, seat, action)] = (
            time.monotonic() + self.CANDIDATE_RETRY_SECONDS)
        self.log(f"{train} {seat} {'候补入口不可用' if action == 'alternate' else '已确认售罄'}，"
                 f"该组合暂避 {self.CANDIDATE_RETRY_SECONDS:g} 秒，继续检查其他目标。")
        self._mark("candidate_cooldown", {"train": train, "seat": seat, "action": action,
                                          "date": self.cfg.get("date", ""),
                                          "seconds": self.CANDIDATE_RETRY_SECONDS})

    def _candidate_ready(self, train, seat, action):
        return self._candidate_key(train, seat, action) not in self._candidate_cooldowns

    def run(self):
        """Run a prepared monitor without repeating startup work at the deadline."""
        if not self._prepared and not self.prepare():
            return
        base_interval = max(1.0, _read_float(self.cfg.get("interval", 3), 3.0))

        loop_count = 0
        while not self.should_stop():
            loop_count += 1
            try:
                # 生成本轮的随机间隔
                actual_interval = self.rate_limiter.get_interval() if self.rate_limiter else get_random_interval(base_interval)
                 
                # 如果命中了，退出循环（只通知一次）
                if self._run_single_loop(loop_count, actual_interval):
                    break
            except ValueError:
                raise
            except Exception as e:
                if is_session_lost(e):
                    self._signal_human_action("", "受控浏览器已关闭或失联，监控已停止，请重新打开登录页后再启动。")
                    break
                self.log(f"⚠️ 监控异常：{e}")
                if self.rate_limiter:
                    self.rate_limiter.on_error(str(e))
                    self._flush_rate_limit_alert()
                self._sleep(self.rate_limiter.get_interval() if self.rate_limiter else get_random_interval(base_interval))

        self.log("⏹ 监控结束/停止")

    def _flush_rate_limit_alert(self) -> None:
        """Surface a one-shot human notice when the limiter first sees risk signals."""
        if not self.rate_limiter:
            return
        message = self.rate_limiter.consume_risk_alert()
        if not message:
            return
        self._signal_human_action(
            "",
            f"查询节奏触发限频信号：{message}。已自动放慢轮询，请稍后再启动或在官方页面完成核验。",
        )

    def _is_burst_mode(self, loop_count: int) -> bool:
        target = self.cfg.get("_target_timestamp")
        if target is not None:
            now = self.server_time_sync.server_timestamp()
            return target - float(self.cfg.get("prepare_time", 2)) <= now <= target + float(self.cfg.get("burst_window_seconds", 45))
        if self.cfg.get("timer_enabled"):
            prepare_seconds = _read_float(self.cfg.get("prepare_time", 2), 2.0)
            burst_seconds = _read_float(self.cfg.get("burst_window_seconds", 45), 45.0)
            if self.server_time_sync.is_in_burst_window(
                str(self.cfg.get("target_time", "00:00:00")),
                prepare_seconds,
                burst_seconds,
            ):
                return True
            return False
        return loop_count <= 5

    def _sale_focus_active(self):
        target = self.cfg.get("_target_timestamp")
        return bool(self.cfg.get("timer_enabled") and target is not None
                    and self.server_time_sync.server_timestamp() <= target + float(self.cfg.get("burst_window_seconds", 45)))

    def _loop_date(self, loop_count):
        if self._prefer_alternate:
            self.date_plan.reset()
            return self._fallback_date
        if self._sale_focus_active():
            self.date_plan.reset()
            if self.preferred_date not in self.travel_dates:
                raise ValueError("定时目标乘车日期当前不可查询，请核对日期；不会改抢其他日期。")
            return self.preferred_date
        self.date_plan.sync(self.travel_dates)
        return self.date_plan.select(loop_count, time.monotonic())

    def _wait_next_query(self, interval):
        # During the scheduled sale window, response/DOM work counts toward the
        # start-to-start interval. Failures and server cooldowns use _sleep instead.
        delay = interval
        if self._sale_focus_active() and self._last_query_started is not None:
            delay = max(0.0, interval - (time.monotonic() - self._last_query_started))
        self._sleep(delay)

    def _run_single_loop(self, loop_count: int, interval: float) -> bool:
        self._query_timing = PhaseTiming()
        self._query_timing.step("prepare")
        self._date_revisit_ms = None
        self._snapshot_query_id = uuid.uuid4().hex
        self._query_invalidated = False
        self._snapshot_sequence = loop_count
        self._snapshot_published = False
        self.last_query = {}
        self._last_query_started = None
        self._snapshot_config = dict(self.cfg)
        if self.travel_dates:
            self._snapshot_config["date"] = self._loop_date(loop_count)
        try:
            return self._query_loop(loop_count, interval)
        except Exception as exc:
            self._publish_query(error=f"查询失败：{exc}")
            raise
        finally:
            self._finish_query_timing()

    def _timing_step(self, name):
        if self._query_timing is not None:
            self._query_timing.step(name)

    def _finish_query_timing(self):
        timing = self._query_timing
        if timing is None or timing.finished:
            return
        steps = timing.finish()
        if self.order_journal:
            try:
                self.order_journal.record_telemetry(self.run_id, "query_timing", detail={
                    "query_id": self._snapshot_query_id, "date": self._snapshot_config.get("date", ""),
                    "status": ("invalid" if self._query_invalidated else self.last_query.get("status", "unconfirmed")),
                    "revisit_ms": self._date_revisit_ms, "steps": steps})
            except Exception:
                pass  # Optional diagnostics cannot change query or order decisions.

    def _publish_query(self, error=None):
        if error is not None and self.last_query.get("status") in ("ok", "empty"):
            self._query_invalidated = True
        if self._snapshot_published or self.should_stop():
            return
        if not self.progress:
            return
        rows = [] if error is not None else self.row_parser.structured_rows(self._row_snapshot or [], self._snapshot_config.get("date", ""))
        snapshot = query_snapshot(self._snapshot_config, rows, run_id=self.run_id,
                                  query_id=self._snapshot_query_id, sequence=self._snapshot_sequence,
                                  error=error, fetched_at=self.last_query.get("fetched_at"))
        self._snapshot_published = True
        try:
            self.progress({**self.last_query, "query_id": snapshot["query_id"], "fetched_at": snapshot["fetched_at"],
                           "loop": self._snapshot_sequence, "date": snapshot["conditions"]["date"],
                           "rows": snapshot["rows"], "snapshot": snapshot})
        except Exception:
            pass  # A display callback must not alter transaction decisions.

    def _query_loop(self, loop_count: int, interval: float) -> bool:
        """单次监控循环，返回是否命中（风控优化版）"""
        self._row_snapshot = None
        if self.should_stop() or not self.session_check():
            return True
        self.tick(status="querying", next_query_at=None)
        is_burst_mode = self._is_burst_mode(loop_count)

        # Recreate a document only when the previous query was invalidated.
        navigated = False
        if self._needs_navigation:
            self.driver.get("https://kyfw.12306.cn/otn/leftTicket/init?linktypeid=dc")
            self._needs_navigation = False
            self.params_filled = False
            navigated = True
        self.log(f"🔎 第 {loop_count} 次查询 (间隔: {interval:.1f}s)")

        self._apply_loop_date(loop_count, force=navigated)
        self._snapshot_config = dict(self.cfg)
        if self.query_start_callback:
            try:
                self.query_start_callback({"run_id": self.run_id or None, "query_id": self._snapshot_query_id,
                                           "sequence": loop_count, "conditions": query_conditions(self._snapshot_config), "started_at": time.time()})
            except Exception:
                pass  # Display observers cannot interrupt a query or transaction.
        if not self._fill_query_params(force=navigated):
            self._publish_query(error="查询参数未就绪，本轮未取得有效结果")
            self._sleep(interval)
            return False
        if self.should_stop():
            return True

        self._timing_step("query")
        if self.query_executor:
            self.tick(status="querying", next_query_at=None)
            result = self.query_executor.execute(self._timed_query_click, int(self.cfg.get("query_timeout", 40)))
            self.last_query = result
            if result.get("status") in ("ok", "empty"): self._mark("query_result")
            status = result["status"]
            if status == "cancelled":
                return True
            if status not in ("ok", "empty"):
                self._publish_query(error=result.get("reason") or {"not_on_sale": "尚未起售", "rate_limited": "查询限频", "server_backoff": "服务端要求等待"}.get(status, "本轮查询未完成"))
            if status in ("rate_limited", "server_backoff"):
                reason = result.get("reason", f"查询收到 HTTP {result.get('http_status')}")
                if self.rate_limiter:
                    if status == "rate_limited":
                        self.rate_limiter.on_error("操作过快：" + reason)
                        self.rate_limiter.consume_risk_alert()  # Handled by this branch.
                    else:
                        self.rate_limiter.on_timeout()
                retry_after = result.get("retry_after_seconds")
                if retry_after is None:
                    self._signal_human_action("", reason + "，未提供有效等待时间，已暂停自动查询，请检查官方页面后再启动。")
                    return True
                delay = max(interval, retry_after,
                            self.rate_limiter.get_interval() if self.rate_limiter else interval)
                self.log(f"{reason}，服务端要求等待 {retry_after:.1f}s；将在至少 {delay:.1f}s 后重试。")
                # Server cooldown is independent of smart-rate settings and its
                # local upper bound. Do not reload, query or submit while waiting.
                self._sleep(delay)
                self._needs_navigation = True
                return False
            if status in ("human_action", "unknown"):
                self._signal_human_action("", result.get("reason", "请检查浏览器页面"))
                return True
            if status == "not_on_sale":
                if not self._dismiss_query_blockers():
                    self._signal_human_action("", "未起售提示无法关闭，请检查浏览器")
                    return True
                if self._sale_focus_active():
                    self._wait_next_query(interval)
                else:
                    self._sleep(min(interval, BURST_RETRY_SLEEP_SECONDS) if is_burst_mode and not self.rate_limiter else interval)
                return False
            if status not in ("ok", "empty"):
                self.log(f"本轮查询未完成：{result.get('reason', status)}")
                self._needs_navigation = True
                if self.rate_limiter:
                    self.rate_limiter.on_timeout()
                self._sleep(max(interval, self.rate_limiter.get_interval() if self.rate_limiter else interval))
                return False
            if not self.query_executor.current():
                self._publish_query(error="查询条件或结果已改变，本轮结果无效")
                self._needs_navigation = True
                self._sleep(interval)
                return False
        else:
            # Compatibility for standalone core callers without a form adapter.
            if not self.click_query_button() or not self.wait_for_rows(timeout=int(self.cfg.get("query_timeout", 40)), stop_check=self.should_stop):
                self._publish_query(error="本轮查询未完成")
                if self.rate_limiter:
                    self.rate_limiter.on_timeout()
                self._sleep(max(interval, self.rate_limiter.get_interval() if self.rate_limiter else interval))
                return False
        if self.rate_limiter:
            self.rate_limiter.on_success()

        self._timing_step("snapshot")
        self._row_snapshot = [] if self.last_query.get("status") == "empty" else self.row_parser.snapshot_rows(list(dict.fromkeys([*DISPLAY_SEATS, *self.target_seats])))

        if self.last_query.get("status") == "empty" and self.query_executor and not self.query_executor.current():
            self._publish_query(error="读取结果期间查询已失效，本轮结果已丢弃")
            self._needs_navigation = True
            self._sleep(interval)
            return False
        self._timing_step("decision")
        try:
            hit = None if self.last_query.get("status") == "empty" else self._scan_current_rows()
        except StaleElementReferenceException:
            self._needs_navigation = True
            self._publish_query(error="结果页面持续变化，本轮快照无效，将在下一轮重新核对")
            self.log("结果页面持续变化，本轮快照无效，未作无票或候补判断。")
            self._sleep(interval)
            return False
        if (not hit or hit[-1] == "alternate") and not self._sale_focus_active() and not self._prefer_alternate:
            self.date_plan.sync(self.travel_dates)
            allowed = self.date_plan.allow_alternate(self.cfg.get("date", ""), bool(hit), time.monotonic())
            if hit and not allowed:
                self.log("本日可候补，按多日期策略继续查现票；候补提交前会重新确认对应日期。")
                hit = None
        self._timing_step("publish")
        self._publish_query()
        if hit:
            train_code, seat_name, seat_value, row_el, action_btn, action_type = hit
            self.log(f"🎯 命中：{train_code} | {seat_name}={seat_value}")

            if self.should_stop():
                return True
            if self.query_executor and not self.query_executor.current():
                self._query_invalidated = True
                self._needs_navigation = True
                self._sleep(interval)
                return False
            if action_type == "alternate" or (self.auto_submit and action_btn):
                return self._execute_order(hit)
            self._finish_query_timing()
            self._focus_and_highlight(row_el, action_btn)
            title = "🎉 发现目标车次/席别可用"
            message = (
                f"命中：{train_code}\n{seat_name}：{seat_value}\n\n"
                f"已为你定位并高亮该车次行与【预订】按钮。\n"
                f"请立即切回浏览器{'确认订单' if self.auto_submit else '手动点击【预订】'}→ 选择乘车人 → 提交订单 → 支付。"
            )
            if self.on_hit:
                self.on_hit(
                    {
                        "train_code": train_code,
                        "seat_type": seat_name,
                        "status": str(seat_value),
                        "source": "regular",
                        "title": title,
                        "message": message,
                    }
                )
            else:
                self.notify(title, message)
            self.log("⏸ 已命中，暂停自动刷新。如需继续监控，请点击【停止】再重新【开始监控余票】。")
            return True

        if self._prefer_alternate:
            self._prefer_alternate = False
            self._fallback_date = ""
            self.log("原订单日期暂无可用现票或候补入口，恢复正常日期轮询。")
        self.log("❌ 未命中目标票，继续监控...")
        self._wait_next_query(interval)
        return False

    def _timed_query_click(self):
        self._mark("query_click")
        clicked = self.click_query_button()
        # Anchor after acknowledgement: time waiting for a disabled button must
        # not consume the interval between two actual query requests.
        if clicked:
            self._last_query_started = time.monotonic()
            travel_date = self.cfg.get("date", "")
            previous = self._date_last_query.get(travel_date)
            self._date_revisit_ms = (round((self._last_query_started - previous) * 1000, 3)
                                     if previous is not None else None)
            self._date_last_query[travel_date] = self._last_query_started
        return clicked

    def _scan_current_rows(self):
        """Retry a stale DOM snapshot once without sending another ticket query."""
        for attempt in range(2):
            if self.should_stop():
                return None
            if self.query_executor and not self.query_executor.current():
                if not attempt and self.query_executor.current(accept_revision=True):
                    self._row_snapshot = self.row_parser.snapshot_rows(
                        list(dict.fromkeys([*DISPLAY_SEATS, *self.target_seats])))
                    continue
                raise StaleElementReferenceException("Query ownership changed")
            try:
                return self._find_hit_row()
            except StaleElementReferenceException:
                if attempt:
                    raise
                if self.query_executor and not self.query_executor.current(accept_revision=True):
                    raise
                self._row_snapshot = self.row_parser.snapshot_rows(
                    list(dict.fromkeys([*DISPLAY_SEATS, *self.target_seats])))

    def _find_hit_row(self, seat_col_indices=None):
        """Inspect every target for cash inventory before considering one waitlist seat."""
        seat_col_indices = seat_col_indices or {}
        now = time.monotonic()
        self._candidate_cooldowns = {key: deadline for key, deadline in self._candidate_cooldowns.items()
                                     if deadline > now}
        try:
            rows = self._row_snapshot if self._row_snapshot is not None else self.row_parser.snapshot_rows(self.target_seats)
            ranked = []
            priorities = {train: index for index, train in reversed(list(enumerate(self.target_trains)))}
            count = len(parse_passenger_names(self.cfg.get("passengers", ""))) or int(self.cfg.get("passenger_count", 1))
            for snapshot in rows:
                train = snapshot["train"]
                if self.target_trains and train not in priorities:
                    continue
                ranked.append((priorities.get(train, len(ranked)), train, snapshot))
            ranked.sort(key=lambda item: item[0])
            for _, train, snapshot in ranked:
                row = snapshot["element"]
                candidates = [seat for seat in self.target_seats
                              if self._candidate_ready(train, seat, "book")
                              and self.is_seat_available(snapshot["seats"].get(seat))
                              and (not str(snapshot["seats"][seat]).isdigit() or int(snapshot["seats"][seat]) >= count)]
                if self.target_seats and not candidates:
                    continue
                book = self._find_book_button(row)
                if book is None:
                    continue
                for seat in candidates:
                    # Re-read only the selected candidate before taking action.
                    value = self._get_seat_value(row, seat, snapshot.get("seat_indices", {}).get(seat, seat_col_indices.get(seat)))
                    if self.is_seat_available(value) and (not str(value).isdigit() or int(value) >= count):
                        return train, seat, value, row, book, "book"
                if not self.target_seats and not self.auto_submit:
                    return train, "未指定席别", "有票", row, book, "book"
            if self.auto_alternate:
                for _, train, snapshot in ranked:
                    row = snapshot["element"]
                    for seat in self.target_seats:
                        if not self._candidate_ready(train, seat, "alternate"):
                            continue
                        # Batch evidence eliminates remote lookups for every
                        # unavailable seat. Re-read only plausible candidates.
                        if snapshot.get("alternate_available", {}).get(seat) is False:
                            continue
                        button = self._find_alternate_button(row, seat)
                        if button is not None:
                            return train, seat, "候补", row, button, "alternate"
            return None
        except NoSuchElementException:
            return None

    def _get_seat_value(self, row, seat_keyword: str, col_index: Optional[int]) -> Optional[str]:
        """获取席别值"""
        return self.row_parser.get_seat_value(row, seat_keyword, col_index)

    def _find_book_button(self, row) -> Optional[Any]:
        """查找预订按钮（动态定位，不硬编码）"""
        return self.row_parser.find_button(row, BOOK_BUTTON_SELECTORS)

    def _find_alternate_button(self, row, seat_name=None):
        # Waitlist is a per-seat action. A different seat's button is not a match.
        seat_name = seat_name or (self.target_seats[0] if self.target_seats else "")
        prefix = SeatType.get_prefix(seat_name)
        if not prefix:
            return None
        try:
            cell = row.find_element(By.CSS_SELECTOR, f"td[id^='{prefix}_']")
            for button in cell.find_elements(By.CSS_SELECTOR, "a,button,div"):
                if (button.text.strip() == "候补" and button.is_displayed() and button.is_enabled()
                        and button.get_attribute("aria-disabled") != "true"):
                    return button
        except NoSuchElementException:
            pass
        return None

    def _focus_and_highlight(self, row_el, action_btn):
        """定位并高亮命中行与操作按钮（预订/候补）"""
        try:
            # 滚动到视图
            self.driver.execute_script(
                "arguments[0].scrollIntoView({behavior:'instant', block:'center'});",
                row_el
            )
            self._sleep(0.2)

            # 行高亮
            self.driver.execute_script(
                "arguments[0].style.outline='4px solid #ff4d4f'; arguments[0].style.background='#fff1f0';",
                row_el
            )

            # 操作按钮高亮（预订 / 候补）
            if action_btn is not None:
                self.driver.execute_script(
                    "arguments[0].style.outline='4px solid #52c41a';"
                    "arguments[0].style.boxShadow='0 0 12px rgba(82,196,26,.8)';",
                    action_btn
                )
                # 移动鼠标到按钮
                try:
                    ActionChains(self.driver).move_to_element(action_btn).perform()
                except Exception:
                    pass

            # 确保窗口聚焦
            try:
                self.driver.switch_to.window(self.driver.current_window_handle)
            except Exception:
                pass

        except Exception as e:
            self.log(f"⚠️ 定位/高亮失败（可忽略）：{e}")

    def _handle_popups(self):
        """
        处理12306页面上可能出现的各种弹窗
        包括：学生票确认（点击取消选成人票）、温馨提示、座位选择提示等
        """
        popup_handled = False
        
        # 首先处理学生票确认弹窗 - 点击"取消"选择成人票
        try:
            # 查找学生票弹窗中的"取消"按钮
            js_student_ticket = """
            // 查找学生票确认弹窗
            var dialogs = document.querySelectorAll('.dhtmlx_window_active, .modal, .layui-layer');
            for (var i = 0; i < dialogs.length; i++) {
                var dialog = dialogs[i];
                var text = dialog.innerText || '';
                // 检查是否是学生票相关弹窗
                if (text.indexOf('学生') !== -1 || text.indexOf('学生票') !== -1) {
                    // 查找"取消"按钮
                    var buttons = dialog.querySelectorAll('a.btn, button');
                    for (var j = 0; j < buttons.length; j++) {
                        var btn = buttons[j];
                        var btnText = btn.innerText.trim();
                        if (btnText === '取消' || btnText === '否') {
                            btn.click();
                            return 'student_cancel';
                        }
                    }
                }
            }
            return null;
            """
            result = self.driver.execute_script(js_student_ticket)
            if result == 'student_cancel':
                self.log("✅ 已点击【取消】，选择购买成人票")
                popup_handled = True
                self._sleep(0.5)
                return popup_handled
        except Exception:
            pass
        
        # 处理其他一般性弹窗 - 点击"确定"
        popup_selectors = [
            # 通用确认按钮
            (".dhtmlx_window_active .btn-primary", "温馨提示"),
            (".dhtmlx_window_active a.btn:last-child", "对话框确认"),
            # 模态框确认按钮
            (".modal-ft .btn-primary", "模态确认"),
            (".layui-layer-btn0", "layui确认"),
            # 12306常用确认按钮类
            ("#qd_closeDefaultWarningWindowDialog_id", "关闭警告"),
        ]
        
        for selector, name in popup_selectors:
            try:
                buttons = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for btn in buttons:
                    if btn.is_displayed() and btn.is_enabled():
                        btn_text = btn.text.strip()
                        # 只点击确认类按钮（排除学生票弹窗的确定按钮）
                        if btn_text in ("确定", "确认", "知道了", "好的", "继续"):
                            # 再次检查是否是学生票弹窗
                            parent = btn.find_element(By.XPATH, "./ancestor::*[contains(@class, 'dhtmlx_window') or contains(@class, 'modal') or contains(@class, 'layui-layer')]")
                            parent_text = parent.text if parent else ""
                            if "学生" in parent_text:
                                # 是学生票弹窗，跳过，不点确定
                                continue
                            btn.click()
                            self.log(f"✅ 已自动处理弹窗：{name} ({btn_text})")
                            popup_handled = True
                            self._sleep(0.5)
                            return popup_handled
            except (NoSuchElementException, StaleElementReferenceException):
                continue
            except Exception:
                continue
        
        # 尝试使用 JavaScript 处理其他弹窗
        if not popup_handled:
            try:
                js_code = """
                var buttons = document.querySelectorAll('.dhtmlx_window_active a.btn, .layui-layer-btn a, .modal-ft a.btn');
                for (var i = 0; i < buttons.length; i++) {
                    var btn = buttons[i];
                    var text = btn.innerText.trim();
                    // 检查父元素是否包含"学生"关键字
                    var parent = btn.closest('.dhtmlx_window_active, .modal, .layui-layer');
                    var parentText = parent ? parent.innerText : '';
                    if (parentText.indexOf('学生') !== -1) {
                        // 学生票弹窗，点击取消
                        if (text === '取消' || text === '否') {
                            btn.click();
                            return 'student_cancel';
                        }
                    } else {
                        // 其他弹窗，点击确定
                        if (text === '确定' || text === '确认' || text === '知道了') {
                            btn.click();
                            return 'confirmed';
                        }
                    }
                }
                return null;
                """
                result = self.driver.execute_script(js_code)
                if result == 'student_cancel':
                    self.log("✅ 已通过JS点击【取消】，选择成人票")
                    popup_handled = True
                elif result == 'confirmed':
                    self.log("✅ 已通过JS自动处理弹窗")
                    popup_handled = True
                if popup_handled:
                    self._sleep(0.5)
            except Exception:
                pass
        
        return popup_handled

    def _select_seat_preference(self, preference: str):
        count = len(parse_passenger_names(self.cfg.get("passengers", ""))) or int(self.cfg.get("passenger_count", 1))
        return self.order_page.apply_seat_preference(preference, count)

    def _signal_human_action(self, train_code: str, message: str) -> None:
        """停止自动化，把控制权交还给用户去完成核验。"""
        self.log(f"🙋 需要人工操作：{message}")
        try:
            self.driver.switch_to.window(self.driver.current_window_handle)
        except Exception:
            pass
        if self.human_action:
            try:
                self.human_action({"train_code": train_code, "title": "需要人工操作", "message": message})
            except Exception:
                pass


# ==================== 兼容旧接口 ====================
# 保持向后兼容
__all__ = [
    'StationCodeResolver',
    'PageAnalyzer', 
    'TicketMonitor',
    'QueryConfig',
    'ConfigManager',
    'SeatType',
    'TRAIN_CODE_PATTERN',
]
