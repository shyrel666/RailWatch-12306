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
10) [风控优化] 人类行为模拟延迟
"""

import time
import re
import sys
import os
import json
import urllib.request
import random
from typing import Optional, List, Dict, Callable, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

from railwatch_dates import expand_travel_dates
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
            if cn_name == seat_name or cn_name in seat_name or seat_name in cn_name:
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
        """解析当前查询结果表格行 -> [{"train","raw"}]"""
        if hasattr(self, "row_parser") and self.row_parser is not None:
            return self.row_parser.parse_rows()
        try:
            table = self.driver.find_element(By.ID, QUERY_TABLE_ID)
            rows = table.find_elements(By.CSS_SELECTOR, QUERY_ROW_SELECTOR)
            results = []
            for row in rows:
                text = row.text.strip()
                if not text:
                    continue
                train_code = self.extract_train_code(text)
                if not train_code:
                    continue
                results.append({"train": train_code, "raw": text})
            return results
        except (NoSuchElementException, StaleElementReferenceException):
            return []


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
        
        # 模糊匹配：去掉"市/站"等
        for key, value in data.items():
            if cn_name in key or key in cn_name:
                self.log(f"ℹ️ 站名模糊匹配：{cn_name} -> {key}")
                return value
        
        raise ValueError(f"站名未找到：{cn_name}（请确认是 12306 支持的中文站名）")


# ==================== 页面分析器 ====================
class PageAnalyzer(BaseHandler):
    """页面分析器"""
    
    def __init__(self, driver, log_callback: Optional[Callable[[str], None]] = None, base_dir: Optional[str] = None):
        super().__init__(driver, log_callback)
        if base_dir is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        self.resolver = StationCodeResolver(base_dir, log=self.log)

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

        # 站码
        from_cn = cfg["from_station_cn"]
        to_cn = cfg["to_station_cn"]
        date = cfg["date"]

        self.log(f"🧾 自动填参：{from_cn} → {to_cn}，日期 {date}")
        
        try:
            from_code = self.resolver.get_code(from_cn)
            to_code = self.resolver.get_code(to_cn)
        except ValueError as e:
            self.log(f"❌ {e}")
            return None

        # 用 JS 一次性写入（包含隐藏字段）
        js = """
        const fromText = arguments[0];
        const fromCode = arguments[1];
        const toText = arguments[2];
        const toCode = arguments[3];
        const date = arguments[4];

        // 可见输入框
        document.querySelector('#fromStationText').value = fromText;
        document.querySelector('#toStationText').value = toText;

        // 隐藏字段（核心）
        const f = document.querySelector('#fromStation');
        const t = document.querySelector('#toStation');
        if (f) f.value = fromCode;
        if (t) t.value = toCode;

        // 日期框通常可直接赋值
        const d = document.querySelector('#train_date');
        if (d){
            d.removeAttribute('readonly');
            d.value = date;
        }

        // 触发 change/input
        const evt1 = new Event('input', {bubbles:true});
        const evt2 = new Event('change', {bubbles:true});
        document.querySelector('#fromStationText').dispatchEvent(evt1);
        document.querySelector('#fromStationText').dispatchEvent(evt2);
        document.querySelector('#toStationText').dispatchEvent(evt1);
        document.querySelector('#toStationText').dispatchEvent(evt2);
        if (d){ d.dispatchEvent(evt1); d.dispatchEvent(evt2); }
        """
        self.driver.execute_script(js, from_cn, from_code, to_cn, to_code, date)

        # 点击[查询]
        self.log("🔎 自动点击【查询】按钮...")
        if not self.click_query_button():
            self.log("❌ 点击查询按钮失败")
            return None

        # 等待结果行出现
        self.log("⏳ 等待查询结果加载...")
        query_timeout = int(cfg.get("query_timeout", 60))
        if not self.wait_for_rows(timeout=query_timeout):
            self.log("❌ 超时：没有加载出任何车次行（可能无车次/日期不对/被风控/页面结构变化）")
            return None

        rows = self._parse_rows()
        if not rows:
            self.log("⚠️ 表格出现但未解析到车次（可能页面结构变化）")
            return None

        self.log(f"✅ 解析到 {len(rows)} 条车次结果（展示前 10 条）：")
        for row in rows[:10]:
            self.log(self._format_row(row))

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
    ):
        super().__init__(driver, log_callback)
        self.cfg = cfg
        self.should_stop = stop_check or (lambda: False)
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
            self.rate_limiter = AdaptiveRateLimiter(
                base_interval=max(3.0, _read_float(cfg.get("interval", 3), 3.0)),
                min_interval=3.0,
                max_interval=30.0,
                log_callback=self.log,
            )
        travel_date = str(cfg.get("date", "")).strip()
        self.travel_dates = expand_travel_dates(travel_date, str(cfg.get("date_range", "单日"))) if travel_date else []
        self.current_loop_date = ""
        self.row_parser = RowParser(self.driver, SeatType.get_prefix)
        self.verification = VerificationDetector(self.driver, log_callback=self.log)
        self.submit_flow = SubmitFlow(
            self.driver,
            cfg,
            log_callback=self.log,
            popup_handler=self._handle_popups,
            seat_preference_handler=self._select_seat_preference,
        )
        self.alternate_flow = AlternateFlow(
            self.driver,
            cfg,
            self.verification,
            log_callback=self.log,
            human_action_callback=self.human_action,
            find_alternate_button=self._find_alternate_button,
        )
    
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
        if not self.travel_dates:
            return
        travel_date = self.travel_dates[(loop_count - 1) % len(self.travel_dates)]
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

    def run(self):
        """主监控循环（风控优化增强版）"""
        base_interval = max(1.0, _read_float(self.cfg.get("interval", 3), 3.0))
        
        self.log(f"⏱ 基础刷新间隔：{base_interval}s（实际将随机浮动 ±30%）")
        self.log(f"🚄 目标车次：{', '.join(self.target_trains) if self.target_trains else '不限定'}")
        self.log(f"💺 目标席别：{', '.join(self.target_seats) if self.target_seats else '不限定'}")
        self.log(f"📝 自动提交：{'开启' if self.auto_submit else '关闭'}")
        self.log(f"🔄 自动候补：{'开启' if self.auto_alternate else '关闭'}")
        self.log("📌 监控逻辑：刷新页面 → 自动点【查询】→ 等待结果 → 判断是否命中")
        self.log("🛡️ 风控优化：已启用随机间隔 + 人类行为模拟")

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
            except Exception as e:
                self.log(f"⚠️ 监控异常：{e}")
                if self.rate_limiter:
                    self.rate_limiter.on_error(str(e))
                time.sleep(get_random_interval(base_interval))

        self.log("⏹ 监控结束/停止")
    
    def _is_burst_mode(self, loop_count: int) -> bool:
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
        is_burst_mode = self._is_burst_mode(loop_count)

        if not is_burst_mode:
            # 1) 刷新前的随机延迟（模拟人类行为，仅在稳定监控期开启）
            human_delay(0.2, 0.8)
            
            # 针对长时间监控增加随机行为（如滚动阅读）
            if random.random() < 0.2:
                try:
                    self.driver.execute_script(f"window.scrollBy(0, {random.randint(100, 400)});")
                    time.sleep(random.uniform(0.3, 1.0))
                    self.driver.execute_script(f"window.scrollBy(0, -{random.randint(100, 400)});")
                except Exception: pass

        # 2) 决定是刷新页面还是直接查询
        # 定时冲刺已在等待阶段预热页面，第一轮直接查询以避免错过准点。
        timed_burst = bool(self.cfg.get("timer_enabled") and is_burst_mode)
        should_refresh = (loop_count % 5 == 0) if timed_burst else (loop_count == 1 or loop_count % 5 == 0)
        
        if should_refresh:
            if is_burst_mode:
                self.log(f"🚀 服务器时间冲刺 (第 {loop_count} 轮)：正在进行极速查询...")
            else:
                self.log(f"🔄 第 {loop_count} 次：深度刷新页面... (间隔: {interval:.1f}s)")
            self.driver.refresh()
            # 爆发期不等待刷新后的模拟延迟
            if not is_burst_mode: human_delay(1.0, 2.0)
        else:
            self.log(f"🔎 第 {loop_count} 次：{'极速查询' if is_burst_mode else '快速直接查询'}... (间隔: {interval:.1f}s)")

        self._apply_loop_date(loop_count, force=should_refresh)
        
        # 3) 刷新后的随机延迟
        if not is_burst_mode: human_delay(0.5, 1.2)

        # 4) 自动点击"查询"
        if is_burst_mode:
            # 爆发期：直接使用底层脚本点击，越过所有模拟逻辑，毫秒级响应
            query_success = self.click_query_button()
        else:
            # 稳定监控期：开启行为模拟，保护账号
            query_success = False
            try:
                btn = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.ID, "query_ticket"))
                )
                from selenium.webdriver.common.action_chains import ActionChains
                actions = ActionChains(self.driver)
                actions.move_to_element_with_offset(btn, random.randint(-5, 5), random.randint(-2, 2))
                actions.pause(random.uniform(0.1, 0.3))
                actions.click().perform()
                query_success = True
            except Exception:
                query_success = self.click_query_button()

        if not query_success:
            self.log("⚠️ 无法触发查询，重试中...")
            if self.rate_limiter:
                self.rate_limiter.on_error("query_failed")
            time.sleep(interval)
            return False

        # 5) 等结果加载
        query_timeout = int(self.cfg.get("query_timeout", 40))
        if not self.wait_for_rows(timeout=query_timeout, stop_check=self.should_stop):
            self.log("⚠️ 本轮未加载出车次结果，继续下一轮。")
            if self.rate_limiter:
                self.rate_limiter.on_timeout()
            time.sleep(interval)
            return False
        if self.rate_limiter:
            self.rate_limiter.on_success()

        if self.progress:
            try:
                self.progress({"loop": loop_count, "date": self.current_loop_date or str(self.cfg.get("date", "")), "rows": self._parse_rows()})
            except Exception:
                pass

        # 6) 找到席别列索引（兆底用）
        seat_col_indices = {}
        for seat in self.target_seats:
            idx = self._get_seat_col_index(seat)
            if idx is not None:
                seat_col_indices[seat] = idx

        # 7) 判断是否命中
        hit = self._find_hit_row(seat_col_indices)
        if hit:
            train_code, seat_name, seat_value, row_el, action_btn, action_type = hit
            self.log(f"🎯 命中：{train_code} | {seat_name}={seat_value}")

            # 命中：定位 + 高亮
            self._focus_and_highlight(row_el, action_btn)

            if action_type == "alternate":
                result = self.alternate_flow.try_alternate_order(row_el, train_code, seat_name)
                if result == "success":
                    title = "🎉 候补已提交"
                    message = (
                        f"命中：{train_code}\n{seat_name}：候补已提交\n\n"
                        f"请切回浏览器确认候补订单状态（如需支付定金请尽快完成）。"
                    )
                    if self.on_hit:
                        self.on_hit(
                            {
                                "train_code": train_code,
                                "seat_type": seat_name,
                                "status": "候补已提交",
                                "source": "alternate",
                                "title": title,
                                "message": message,
                            }
                        )
                    else:
                        self.notify(title, message)
                    self.log("⏸ 候补已提交，暂停自动刷新。如需继续监控，请点击【停止】再重新开始。")
                    return True
                if result == "retry":
                    # 尚未进入候补流程（候补按钮暂不可点）：继续监控，不打扰用户
                    self.log("↻ 候补暂不可用，继续监控...")
                    time.sleep(interval)
                    return False
                # 已进入候补流程：失败或需要人工核验都停止刷新，避免停留在候补页空转。
                if result == "failed":
                    self._signal_human_action(train_code, "候补未能自动完成，请在浏览器中手动检查并提交。")
                self.log("⏸ 候补流程已暂停，请在浏览器中处理后再决定是否重新监控。")
                return True

            # 有票路径
            if self.auto_submit and action_btn:
                self.submit_flow.try_auto_submit(action_btn, seat_name)
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
        time.sleep(interval)
        return False

    def _get_seat_col_index(self, seat_keyword: str) -> Optional[int]:
        """获取席别在表头的列索引"""
        return self.row_parser.get_seat_col_index(seat_keyword)

    def _find_hit_row(self, seat_col_indices: Dict[str, int]) -> Optional[Tuple[str, str, str, Any, Any, str]]:
        """
        查找命中的车次行。
        返回 6 元组：(车次号, 席别名, 席别值, 行元素, 操作按钮, 动作类型) 或 None。
        动作类型为 "book"（有票预订）或 "alternate"（候补）。
        """
        try:
            table = self.driver.find_element(By.ID, "queryLeftTable")
            rows = table.find_elements(By.CSS_SELECTOR, "tr[id^='ticket_']")

            for row in rows:
                try:
                    text = row.text.strip()
                    if not text:
                        continue

                    train_code = self.extract_train_code(text)
                    if not train_code:
                        continue

                    # 检查车次是否匹配
                    if self.target_trains and train_code not in self.target_trains:
                        continue

                    # 检查席别/候补：候补依据「行内候补按钮」是否存在，而不是席别格文字
                    book_btn = self._find_book_button(row)
                    alternate_btn = self._find_alternate_button(row) if self.auto_alternate else None

                    if self.target_seats:
                        # 指定席别：目标席别有票则预订；否则若该车次可候补则候补
                        for seat in self.target_seats:
                            seat_value = self._get_seat_value(row, seat, seat_col_indices.get(seat))
                            if self.is_seat_available(seat_value):
                                return (train_code, seat, seat_value, row, book_btn, "book")
                        if alternate_btn is not None:
                            return (train_code, "，".join(self.target_seats), "候补", row, alternate_btn, "alternate")
                    else:
                        # 不限席别：有预订按钮则预订；否则若可候补则候补
                        if book_btn is not None:
                            return (train_code, "未指定席别", "有票", row, book_btn, "book")
                        if alternate_btn is not None:
                            return (train_code, "未指定席别", "候补", row, alternate_btn, "alternate")

                except StaleElementReferenceException:
                    continue

            return None
        except (NoSuchElementException, StaleElementReferenceException):
            return None
    
    def _get_seat_value(self, row, seat_keyword: str, col_index: Optional[int]) -> Optional[str]:
        """获取席别值"""
        return self.row_parser.get_seat_value(row, seat_keyword, col_index)

    def _find_book_button(self, row) -> Optional[Any]:
        """查找预订按钮（动态定位，不硬编码）"""
        return self.row_parser.find_button(row, BOOK_BUTTON_SELECTORS)

    def _find_alternate_button(self, row) -> Optional[Any]:
        """查找候补按钮"""
        return self.row_parser.find_button(row, ALTERNATE_BUTTON_SELECTORS)

    def _focus_and_highlight(self, row_el, action_btn):
        """定位并高亮命中行与操作按钮（预订/候补）"""
        try:
            # 滚动到视图
            self.driver.execute_script(
                "arguments[0].scrollIntoView({behavior:'instant', block:'center'});",
                row_el
            )
            time.sleep(0.2)

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
                time.sleep(0.5)
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
                            time.sleep(0.5)
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
                    time.sleep(0.5)
            except Exception:
                pass
        
        return popup_handled

    def _select_seat_preference(self, preference: str):
        """
        选择座位偏好（靠窗/靠过道）- 优化版
        
        12306 座位选择说明：
        - 高铁/动车二等座：A/F 靠窗，C/D 靠过道
        - 高铁/动车一等座：A/F 靠窗，C/D 靠过道
        
        优化策略：使用单一 JS 脚本快速检测和选择，减少 Selenium 调用开销
        """
        try:
            self.log(f"🪟 尝试选择座位偏好: {preference}")
            
            # 使用统一的 JavaScript 快速检测和选择座位偏好
            # 优化：一次性完成检测和选择，避免多次 DOM 操作
            js_select_seat = r"""
            (function(preference) {
                // 辅助函数：检查是否是国籍选择框
                function isNationalitySelect(s) {
                    if (!s || !s.options || s.options.length === 0) return true;
                    var id = (s.id || '').toLowerCase();
                    var name = (s.name || '').toLowerCase();
                    if (id.includes('nationality') || id.includes('country')) return true;
                    if (name.includes('nationality') || name.includes('country')) return true;
                    var firstText = (s.options[0].text || '').toLowerCase();
                    if (firstText.includes('国籍') || firstText.includes('afghanistan') || 
                        firstText.includes('请选择国籍') || firstText.includes('country')) return true;
                    return false;
                }
                
                // 辅助函数：检查是否是席别选择框（避免误选）
                function isSeatTypeSelect(s) {
                    var id = (s.id || '').toLowerCase();
                    if (id.includes('seattype_') && id.match(/seattype_\d+/)) return true;
                    return false;
                }
                
                // 检查是否是座位偏好选择框
                function isSeatPreferenceSelect(s) {
                    if (!s.options || s.options.length < 2) return false;
                    var hasA = false, hasC = false, hasWindow = false;
                    for (var i = 0; i < s.options.length; i++) {
                        var t = s.options[i].text;
                        if (t === 'A' || t === 'F') hasA = true;
                        if (t === 'C' || t === 'D') hasC = true;
                        if (t.includes('窗') || t.includes('过道')) hasWindow = true;
                    }
                    return (hasA && hasC) || hasWindow;
                }
                
                var isWindow = preference === '靠窗优先';
                var targetChars = isWindow ? ['A', 'F'] : ['C', 'D'];
                var targetKeyword = isWindow ? '窗' : '过道';
                
                // 查找所有下拉框
                var selects = document.querySelectorAll('select');
                var selectedCount = 0;
                
                for (var i = 0; i < selects.length; i++) {
                    var s = selects[i];
                    
                    // 跳过隐藏的、国籍选择框
                    if (s.offsetParent === null) continue;
                    if (isNationalitySelect(s)) continue;
                    if (isSeatTypeSelect(s)) continue;  // 跳过席别选择框
                    if (!isSeatPreferenceSelect(s)) continue;  // 必须是座位偏好选择框
                    
                    // 遍历选项
                    for (var j = 0; j < s.options.length; j++) {
                        var opt = s.options[j];
                        var t = opt.text.trim();
                        
                        // 匹配目标座位
                        var matched = false;
                        if (targetChars.includes(t)) {
                            matched = true;
                        } else if (t.includes(targetKeyword)) {
                            matched = true;
                        }
                        
                        if (matched) {
                            s.value = opt.value;
                            s.dispatchEvent(new Event('change', {bubbles: true}));
                            selectedCount++;
                            break;
                        }
                    }
                }
                
                return selectedCount;
            })(arguments[0]);
            """
            
            try:
                selected_count = self.driver.execute_script(js_select_seat, preference)
                if selected_count and selected_count > 0:
                    self.log(f"✅ 已为 {selected_count} 位乘车人选择座位偏好: {preference}")
                    return
            except Exception:
                pass
            
            # 快速失败：如果 JS 方法失败，直接跳过，不再尝试其他慢速方法
            # 优化理由：抢票时速度优先，座位偏好不影响购票成功
            self.log(f"⚠️ 未能自动选择座位偏好，可能当前页面不支持或需要手动选择")
            self.log(f"💡 提示：您可以在提交订单后手动选择座位")
            
        except Exception as e:
            self.log(f"⚠️ 座位偏好选择异常: {e}")
    
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
