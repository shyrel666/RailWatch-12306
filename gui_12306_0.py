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
from typing import Optional, List, Dict, Callable, Tuple, Any
from dataclasses import dataclass, field, replace
from enum import Enum

from railwatch_dates import expand_travel_dates
from railwatch_query import FillResult, fill_result, QueryExecutor, FILL_QUERY_FORM_JS, DISMISS_DIALOG_JS
from railwatch_row_parser import RowParser, TRAIN_CODE_PATTERN
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
from railwatch_config_contract import parse_passenger_names
from railwatch_order_page import OrderPage
from railwatch_time import ServerTimeSync, get_server_time_sync
from railwatch_verification import VerificationDetector


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
        """根据席别名称获取 td id 前缀"""
        seat_name = (seat_name or "").strip()
        for member in cls:
            cn_name, prefix = member.value
            if cn_name == seat_name:
                return prefix
        return None


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
    prepare_time: int = 2      # 提前准备秒数
    keep_alive: bool = True     # 是否开启会话保活
    passengers: str = ""       # 目标乘车人姓名，逗号分隔
    
    # 候补订单功能
    auto_alternate: bool = False  # 是否启用无票时自动候补
    alternate_deadline: str = ""  # 候补截止时间，如 "18:00"
    date_range: str = "单日"
    smart_rate: bool = True
    timer_enabled: bool = False
    target_time: str = "00:00:00"
    sale_at: str = ""
    sale_time_source: str = "manual"
    sale_time_checked_at: str = ""
    burst_window_seconds: float = 45.0
    prewarm_lead_seconds: float = 120.0
    
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
            "auto_alternate": self.auto_alternate,
            "alternate_deadline": self.alternate_deadline,
            "date_range": self.date_range,
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
            auto_alternate=data.get("auto_alternate", False),
            alternate_deadline=data.get("alternate_deadline", ""),
            date_range=data.get("date_range", "单日"),
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
    
    def save(self, config: QueryConfig) -> bool:
        """保存配置"""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config.to_dict(), f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False
    
    def load(self) -> Optional[QueryConfig]:
        """加载配置"""
        if not os.path.exists(self.config_path):
            return None
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return QueryConfig.from_dict(data)
        except Exception:
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

    def load(self) -> Dict[str, str]:
        """加载站点编码映射"""
        if self._name2code is not None:
            return self._name2code

        # 优先读缓存
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    self._name2code = json.load(f)
                self.log(f"✅ 站点编码缓存已加载：{len(self._name2code)} 条")
                return self._name2code
            except (json.JSONDecodeError, IOError) as e:
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
                js_text = urllib.request.urlopen(STATION_JS_URL, timeout=20).read().decode("utf-8", errors="ignore")
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

        # 保存缓存
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(name2code, f, ensure_ascii=False, indent=2)
            self.log(f"✅ 站点编码已缓存：{len(name2code)} 条")
        except IOError as e:
            self.log(f"⚠️ 缓存保存失败：{e}")

        return name2code

    def get_code(self, cn_name: str) -> str:
        """获取站点编码"""
        data = self.load()
        cn_name = cn_name.strip()
        
        # 精确匹配
        if cn_name in data:
            return data[cn_name]
        
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

        executor = QueryExecutor(self.driver)
        result = executor.execute(self.click_query_button, int(cfg.get("query_timeout", 40)))
        if result["status"] not in ("ok", "empty"):
            raise RuntimeError(result.get("reason") or "本轮查询未完成")
        rows = [] if result["status"] == "empty" else self._parse_rows()
        if not executor.current():
            raise RuntimeError("查询结果已失效，请重新查询")
        self.last_query = result
        return rows

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
        self.query_executor = QueryExecutor(driver, self.should_stop, self._poll_wait, lambda: self.tick()) if param_filler else None
        self.notify = notify_callback or (lambda title, msg: print(title, msg, flush=True) if title.isascii() and msg.isascii() else _safe_print(title, msg))
        self.progress = progress_callback
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
        self.travel_dates = expand_travel_dates(travel_date, str(cfg.get("date_range", "单日"))) if travel_date else []
        self.current_loop_date = ""
        # 参数同步：定时/爆发路径不依赖浏览器残留的上次查询条件
        self.param_filler = param_filler
        self.params_filled = False
        self._form_snapshot = None
        self.row_parser = RowParser(self.driver, SeatType.get_prefix)
        self._row_snapshot = None
        self.verification = VerificationDetector(self.driver, log_callback=self.log)
        self.submit_flow = SubmitFlow(
            self.driver,
            cfg,
            log_callback=self.log,
            popup_handler=self._handle_popups,
        )
        self.alternate_flow = AlternateFlow(
            self.driver,
            cfg,
            self.verification,
            log_callback=self.log,
            human_action_callback=self.human_action,
            find_alternate_button=self._find_alternate_button,
        )
        self.order_page = OrderPage(driver, self.should_stop, self._poll_wait, self._mark, log=self.log)
        self.submit_flow.order_page = self.order_page
        self.alternate_flow.order_page = self.order_page

    def _mark(self, stage, detail=None):
        if self.order_journal:
            self.order_journal.mark(self.run_id, stage, getattr(self, "_intent_id", ""), detail)

    def _execute_order(self, hit):
        train, seat, _, row, button, action = hit
        if not self.order_journal:
            self._signal_human_action(train, "订单持久化不可用，已停止自动提交")
            return True
        intent = OrderIntent.from_config(self.cfg, train, seat, "alternate" if action == "alternate" else "regular")
        route = self.row_parser.selected_route(row)
        if route:
            intent = replace(intent, from_station=route[0], to_station=route[1])
        self._intent_id = intent.intent_id
        try:
            self.order_journal.begin(self.run_id, intent, self.cfg)
        except Exception:
            self._signal_human_action(train, "无法取得订单提交权限，请先核对未完成订单和本地存储")
            return True
        if self.on_order:
            self.on_order(intent, OrderResult("submitting"))
        self._mark("no_inventory" if action == "alternate" else "inventory_found")
        result = (self.alternate_flow.try_alternate_order(row, train, seat, intent=intent)
                  if action == "alternate" else self.submit_flow.try_auto_submit(button, seat, intent=intent))
        if not isinstance(result, OrderResult):
            result = OrderResult("unknown", "提交适配器未返回可验证的订单结果")
        if action == "book" and result.status == "unknown" and result.reason == "官方提示余票不足":
            reconciled = self.order_page.reconcile(intent, navigate=True, allow_empty=True)
            if reconciled.status == "not_submitted" and reconciled.no_order:
                result = OrderResult("sold_out", "售罄且官方待支付订单已确认为空", no_order=True)
            else:
                result = reconciled
        try:
            result = self.order_journal.record(intent, result)
            self._mark("confirmed_failure" if result.can_fallback else result.status)
        except Exception:
            self._signal_human_action(train, "订单结果无法保存，请保留当前页面并核对订单，禁止重新提交")
            return True
        if self.on_order:
            self.on_order(intent, result)
        if result.can_fallback and self.auto_alternate:
            self._prefer_alternate = True
            self._fallback_date = intent.date
            self._needs_navigation = True
            return False  # Immediate next query, no normal backoff or burst-window delay.
        if result.status in ("unknown", "verification", "not_submitted", "sold_out"):
            self._signal_human_action(train, result.reason or "请检查官方订单状态")
        return True
    
    def _parse_train_targets(self) -> List[str]:
        """解析目标车次列表"""
        train_str = self.cfg.get("train_code", "").strip()
        if not train_str:
            return []
        # 支持逗号、空格、分号分隔
        trains = re.split(r"[,，;\s]+", train_str)
        return [t.strip().upper() for t in trains if t.strip()]
    
    def _parse_seat_targets(self) -> List[str]:
        """解析目标席别列表"""
        seat_str = self.cfg.get("seat_keyword", "").strip()
        if not seat_str:
            return []
        # 支持逗号、空格、分号分隔
        seats = re.split(r"[,，;\s]+", seat_str)
        return [s.strip() for s in seats if s.strip()]

    def _apply_loop_date(self, loop_count: int, force: bool = False) -> None:
        if self.date_provider:
            self.travel_dates = self.date_provider()
            if not self.travel_dates:
                raise ValueError("所有出行日期均已失效，请修改行程")
        if not self.travel_dates:
            return
        if self._prefer_alternate and self._fallback_date not in self.travel_dates:
            raise ValueError("原预订日期已失效，已停止候补回退，请核对行程")
        travel_date = self._fallback_date if self._prefer_alternate else self.travel_dates[(loop_count - 1) % len(self.travel_dates)]
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

    def run(self):
        """主监控循环（风控优化增强版）"""
        base_interval = max(1.0, _read_float(self.cfg.get("interval", 3), 3.0))
        
        if self.rate_limiter:
            self.log(f"⏱ 智能限速：基础 {self.rate_limiter.base_interval}s，±20% 浮动，范围 {self.rate_limiter.min_interval}–{self.rate_limiter.max_interval}s")
        else:
            self.log(f"⏱ 基础刷新间隔：{base_interval}s（实际将随机浮动 ±30%）")
        self.log(f"🚄 目标车次：{', '.join(self.target_trains) if self.target_trains else '不限定'}")
        self.log(f"💺 目标席别：{', '.join(self.target_seats) if self.target_seats else '不限定'}")
        self.log(f"📝 自动提交：{'开启' if self.auto_submit else '关闭'}")
        self.log(f"🔄 自动候补：{'开启' if self.auto_alternate else '关闭'}")
        self.log("监控流程：查询 → 校验结果 → 预订或首选候补 → 核对订单证据")
        self.log("受控查询；遇到核验或未知订单结果时暂停处理。")

        # 确保在查询页
        try:
            WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located((By.ID, "query_ticket"))
            )
        except TimeoutException:
            self.log("⚠️ 未检测到查询按钮：请确认当前页面是余票查询页。")
            return

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

    def _run_single_loop(self, loop_count: int, interval: float) -> bool:
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
        if not self._fill_query_params(force=navigated):
            self._sleep(interval)
            return False
        if self.should_stop():
            return True

        if self.query_executor:
            self.tick(status="querying", next_query_at=None)
            result = self.query_executor.execute(self._timed_query_click, int(self.cfg.get("query_timeout", 40)))
            self.last_query = result
            if result.get("status") in ("ok", "empty"): self._mark("query_result")
            status = result["status"]
            if status == "cancelled":
                return True
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
                self._needs_navigation = True
                self._sleep(interval)
                return False
        else:
            # Compatibility for standalone core callers without a form adapter.
            if not self.click_query_button() or not self.wait_for_rows(timeout=int(self.cfg.get("query_timeout", 40)), stop_check=self.should_stop):
                if self.rate_limiter:
                    self.rate_limiter.on_timeout()
                self._sleep(max(interval, self.rate_limiter.get_interval() if self.rate_limiter else interval))
                return False
        if self.rate_limiter:
            self.rate_limiter.on_success()

        self._row_snapshot = [] if self.last_query.get("status") == "empty" else self.row_parser.snapshot_rows(self.target_seats)
        if self.progress:
            try:
                self.progress({**self.last_query, "loop": loop_count, "date": self.current_loop_date or str(self.cfg.get("date", "")), "rows": self.row_parser.display_rows(self._row_snapshot)})
            except Exception:
                pass

        # 6) 找到席别列索引（兆底用）
        seat_col_indices = {}

        # 7) 判断是否命中
        if self.query_executor and not self.query_executor.current():
            self._needs_navigation = True
            self._sleep(interval)
            return False
        hit = None if self.last_query.get("status") == "empty" else self._find_hit_row(seat_col_indices)
        if hit:
            train_code, seat_name, seat_value, row_el, action_btn, action_type = hit
            self.log(f"🎯 命中：{train_code} | {seat_name}={seat_value}")

            if self.should_stop():
                return True
            if self.query_executor and not self.query_executor.current():
                self._needs_navigation = True
                self._sleep(interval)
                return False
            if action_type == "alternate" or (self.auto_submit and action_btn):
                return self._execute_order(hit)
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

        self.log("❌ 未命中目标票，继续监控...")
        self._sleep(interval)
        return False

    def _timed_query_click(self):
        self._mark("query_click")
        return self.click_query_button()

    def _get_seat_col_index(self, seat_keyword: str) -> Optional[int]:
        """获取席别在表头的列索引"""
        return self.row_parser.get_seat_col_index(seat_keyword)

    def _find_hit_row(self, seat_col_indices):
        """Inspect every target for cash inventory before considering one waitlist seat."""
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
            if not self._prefer_alternate:
                for _, train, snapshot in ranked:
                    row = snapshot["element"]
                    candidates = [seat for seat in self.target_seats if self.is_seat_available(snapshot["seats"].get(seat))
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
                        button = self._find_alternate_button(row, seat)
                        if button is not None:
                            return train, seat, "候补", row, button, "alternate"
            return None
        except (NoSuchElementException, StaleElementReferenceException):
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
        except (NoSuchElementException, StaleElementReferenceException):
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
