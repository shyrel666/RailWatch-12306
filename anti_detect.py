"""
RailWatch browser environment and risk-control helpers.

Everything here is wired into the desktop path:
1. Launch hygiene (RailWatchBridge._ensure_driver): disable casual
   ChromeDriver automation switches only.
2. Minimal new-document script that clears navigator.webdriver / cdc_ keys.
3. RAIL_DEVICEID consistency observation (read-only, never rewrites cookies).
4. Adaptive query pacing and jittered intervals (TicketMonitor).

The browser keeps its real user agent, screen, timezone, canvas and WebGL.
This module does not bypass login, captcha, order confirmation, payment, website
rules, or service rate limits. It does not guarantee ticket availability or
successful purchase. It is intended to reduce accidental instability in normal
personal-use monitoring, not to defeat platform protections.

中文范围说明：提供合规低频个人辅助的风险控制能力；不绕过登录、验证码、订单确认、支付或网站规则。
不包含指纹伪装、UA／分辨率切换或拟人点击轨迹。
"""

import random
import time
import math
from typing import Optional, Callable

from railwatch_config_contract import redact_sensitive_text


def apply_chrome_launch_hardening(options) -> None:
    """Low-risk Chrome launch flags used by the desktop path.

    Only removes casual automation switches. Does not spoof UA, screen, WebGL,
    or canvas: those create inconsistent signals and can break official pages.
    """
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option("useAutomationExtension", False)


def build_automation_hygiene_script() -> str:
    """Minimal new-document script: hide chromedriver tells only.

    Intentionally does NOT overwrite screen, WebGL, canvas, timezone or UA.
    """
    return r"""
(() => {
  try {
    Object.defineProperty(Navigator.prototype, 'webdriver', {
      get: () => undefined,
      configurable: true,
    });
  } catch (_) {}
  try {
    if (navigator.webdriver) {
      Object.defineProperty(navigator, 'webdriver', { get: () => undefined, configurable: true });
    }
  } catch (_) {}
  try {
    for (const key of Object.getOwnPropertyNames(window)) {
      if (/^cdc_/i.test(key)) {
        try { delete window[key]; } catch (_) {}
      }
    }
  } catch (_) {}
})();
"""


def inject_automation_hygiene(driver) -> bool:
    """Install the hygiene script for subsequent navigations. Best effort."""
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": build_automation_hygiene_script(),
        })
        return True
    except Exception:
        return False


class RailDeviceIdProtector:
    """
    RAIL_DEVICEID consistency tracker.

    This app does not silently restore or rewrite 12306 cookies. It records the
    device id observed after user login and warns if the official page changes
    or clears it during a session.
    """
    
    def __init__(self, driver, log_callback: Optional[Callable[[str], None]] = None):
        self.driver = driver
        self.log = log_callback or (lambda x: print(x))
        self.saved_device_id: Optional[str] = None
    
    def get_current_device_id(self) -> Optional[str]:
        """获取当前页面的 RAIL_DEVICEID"""
        try:
            cookies = self.driver.get_cookies()
            for cookie in cookies:
                if cookie.get('name') == 'RAIL_DEVICEID':
                    return cookie.get('value')
            return None
        except Exception:
            return None
    
    def save_device_id(self) -> bool:
        """Record the current RAIL_DEVICEID after a verified user login."""
        device_id = self.get_current_device_id()
        if not device_id:
            self.log("⚠️ 未检测到 RAIL_DEVICEID。")
            return False
        self.saved_device_id = device_id
        self.log(f"💾 已记录 RAIL_DEVICEID: {redact_sensitive_text(device_id, keep_start=6, keep_end=4)}")
        return True

    def check_consistency(self) -> bool:
        """Return False if the observed device id changed after being recorded."""
        if not self.saved_device_id:
            return True
        current_id = self.get_current_device_id()
        if not current_id:
            self.log("⚠️ RAIL_DEVICEID 已缺失，请留意官方页面是否要求重新验证。")
            return False
        if current_id != self.saved_device_id:
            self.log("⚠️ RAIL_DEVICEID 已变化，请留意官方页面是否要求重新验证。")
            return False
        return True
    
    def check_and_restore(self) -> bool:
        """Deprecated compatibility wrapper. Does not restore cookies."""
        return self.check_consistency()
    
    def get_all_critical_cookies(self) -> dict:
        """获取所有关键 Cookie"""
        critical_names = ['RAIL_DEVICEID', 'RAIL_EXPIRATION', 'RAIL_OkLJUJ', '_jc_save_user']
        result = {}
        try:
            cookies = self.driver.get_cookies()
            for cookie in cookies:
                if cookie.get('name') in critical_names:
                    result[cookie['name']] = cookie['value']
        except Exception:
            pass
        return result


class AdaptiveRateLimiter:
    """
    智能频率调节器 - 根据服务器响应自动调整请求频率
    
    策略：
    1. 成功响应：逐步降低间隔（加速）
    2. 超时/错误：增加间隔（减速）
    3. 检测到风控：大幅增加间隔（保护）
    4. 连续五次成功后逐步恢复；随机间隔始终遵守上下限
    """
    
    def __init__(self, base_interval: float = 5.0, 
                 min_interval: float = 2.0, 
                 max_interval: float = 30.0,
                 log_callback: Optional[Callable[[str], None]] = None):
        base_interval, min_interval, max_interval = map(float, (base_interval, min_interval, max_interval))
        if not all(math.isfinite(value) and value > 0 for value in (base_interval, min_interval, max_interval)):
            raise ValueError("请求间隔必须是有限的正数")
        if min_interval > max_interval:
            raise ValueError("最小请求间隔不能大于最大请求间隔")
        self.min_interval = min_interval
        self.max_interval = max_interval
        self.base_interval = min(max(base_interval, min_interval), max_interval)
        self.current_interval = self.base_interval
        self.log = log_callback or (lambda x: print(x))
        
        # 统计数据
        self.success_streak = 0  # 连续成功次数
        self.fail_count = 0      # 失败计数
        self.total_requests = 0  # 总请求数
        self.risk_detected = False  # 是否检测到风控
        self.risk_alert_pending = False  # 一次性提醒，由监控器消费
        self.last_risk_message = ""

    def on_success(self):
        """请求成功时调用"""
        self.success_streak += 1
        self.fail_count = 0
        self.total_requests += 1

        # 连续成功5次后，逐步加速
        if self.success_streak >= 5:
            self.risk_detected = False
            self.risk_alert_pending = False
            speed_factor = 0.95  # 每次减少5%
            new_interval = self.current_interval * speed_factor
            self.current_interval = max(new_interval, self.min_interval)
            
    def on_timeout(self):
        """请求超时时调用"""
        self.success_streak = 0
        self.fail_count += 1
        self.total_requests += 1
        
        # 超时时增加间隔
        slow_factor = 1.3  # 增加30%
        new_interval = self.current_interval * slow_factor
        self.current_interval = min(new_interval, self.max_interval)
        self.log(f"⚠️ 请求超时，自动放慢至 {self.current_interval:.1f}s")
        
    def on_error(self, error_msg: str = ""):
        """请求错误时调用"""
        self.success_streak = 0
        self.fail_count += 1
        self.total_requests += 1
        
        # 检测风控关键词
        risk_keywords = ["频繁", "操作过快", "稍后再试", "验证", "网络繁忙", "系统繁忙"]
        is_risk = any(kw in error_msg for kw in risk_keywords)
        
        if is_risk:
            self.risk_detected = True
            self.risk_alert_pending = True
            self.last_risk_message = error_msg
            # 风控：大幅增加间隔
            self.current_interval = min(self.current_interval * 2.5, self.max_interval)
            self.log(f"🛡️ 检测到风控信号，自动放慢至 {self.current_interval:.1f}s")
        else:
            # 普通错误：适度增加
            slow_factor = 1.5
            new_interval = self.current_interval * slow_factor
            self.current_interval = min(new_interval, self.max_interval)
            
    def on_risk_clear(self):
        """风控解除后恢复正常速度"""
        if self.risk_detected:
            self.risk_detected = False
            self.risk_alert_pending = False
            self.current_interval = self.base_interval
            self.log(f"✅ 风控解除，恢复正常频率 {self.current_interval:.1f}s")
            
    def get_interval(self) -> float:
        """获取当前推荐的请求间隔；±20% 浮动后仍遵守配置上下限。"""
        variation = self.current_interval * 0.2
        interval = self.current_interval + random.uniform(-variation, variation)
        return min(self.max_interval, max(self.min_interval, interval))
    
    def consume_risk_alert(self) -> Optional[str]:
        """Return a pending risk message once, then clear the flag."""
        if not self.risk_alert_pending:
            return None
        self.risk_alert_pending = False
        return self.last_risk_message or "官方提示操作过快或频繁"

    def reset(self):
        """重置为初始状态"""
        self.current_interval = self.base_interval
        self.success_streak = 0
        self.fail_count = 0
        self.risk_detected = False
        self.risk_alert_pending = False
        self.last_risk_message = ""
        
    def get_stats(self) -> dict:
        """获取统计数据"""
        return {
            "current_interval": round(self.current_interval, 2),
            "base_interval": self.base_interval,
            "success_streak": self.success_streak,
            "fail_count": self.fail_count,
            "total_requests": self.total_requests,
            "risk_detected": self.risk_detected,
        }


def get_random_interval(base_interval: float) -> float:
    """刷新间隔在基础间隔上 ±30% 浮动。"""
    variation = base_interval * 0.3
    return base_interval + random.uniform(-variation, variation)


def human_delay(min_s: float = 0.3, max_s: float = 1.5):
    """操作之间的短暂随机等待。"""
    time.sleep(random.uniform(min_s, max_s))
