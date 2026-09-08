"""System-clock scheduling and optional HTTP time diagnostics."""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Optional
from railwatch_dates import beijing_now

import urllib.error
import urllib.request

DEFAULT_12306_TIME_URL = "https://kyfw.12306.cn/otn/resources/login.html"
DEFAULT_SYNC_INTERVAL_SECONDS = 300.0
DEFAULT_BURST_WINDOW_SECONDS = 45.0


class ServerTimeSync:
    """Legacy name retained; HTTP Date is diagnostic, never the sale scheduler clock."""

    def __init__(
        self,
        time_url: str = DEFAULT_12306_TIME_URL,
        sync_interval: float = DEFAULT_SYNC_INTERVAL_SECONDS,
        log_callback: Optional[Callable[[str], None]] = None,
    ):
        self.time_url = time_url
        self.sync_interval = sync_interval
        self.log = log_callback or (lambda _message: None)
        self._offset_seconds: float = 0.0
        self._last_sync_monotonic: float = 0.0
        self._last_error: str = ""
        self.uncertainty_seconds = None
        self.rtt_seconds = None

    @property
    def offset_seconds(self) -> float:
        return self._offset_seconds

    @property
    def last_error(self) -> str:
        return self._last_error

    def sync(self, force: bool = False) -> float:
        now_mono = time.monotonic()
        if (
            not force
            and self._last_sync_monotonic
            and (now_mono - self._last_sync_monotonic) < self.sync_interval
        ):
            return self._offset_seconds

        try:
            request = urllib.request.Request(
                self.time_url,
                method="HEAD",
                headers={"User-Agent": "RailWatch/1.0"},
            )
            started_wall, started_mono = time.time(), time.monotonic()
            with urllib.request.urlopen(request, timeout=5) as response:
                date_header = response.headers.get("Date")
                if not date_header:
                    raise RuntimeError("12306 响应缺少 Date 头")
                server_dt = parsedate_to_datetime(date_header)
                server_ts = server_dt.timestamp()
                self.rtt_seconds = max(0.0, time.monotonic() - started_mono)
                self.uncertainty_seconds = 0.5 + self.rtt_seconds / 2
                if float(response.headers.get("Age", "0")) > 0:
                    raise RuntimeError("HTTP响应来自缓存，不能用于时间检查")
                self._offset_seconds = server_ts + 0.5 - (started_wall + self.rtt_seconds / 2)
                self._last_sync_monotonic = now_mono
                self._last_error = ""
                self.log(f"HTTP时间辅助检查：偏差 {self._offset_seconds:+.3f}s，估计不确定度 ±{self.uncertainty_seconds:.3f}s；定时使用系统时钟")
        except (urllib.error.URLError, OSError, RuntimeError, ValueError) as exc:
            self._last_error = str(exc)
            self.uncertainty_seconds = None
            if force or not self._last_sync_monotonic:
                self.log(f"服务器时间校准失败，使用本地时钟：{exc}")
            self._last_sync_monotonic = now_mono
        return self._offset_seconds

    def server_timestamp(self) -> float:
        # Hot-path clock access must never perform network I/O. HTTP Date is diagnostic only.
        return time.time()

    def server_now(self) -> datetime:
        return beijing_now(self.server_timestamp())

    def parse_target_datetime(self, target_time: str, reference: Optional[datetime] = None) -> datetime:
        reference = reference or self.server_now()
        parts = str(target_time or "00:00:00").strip().split(":")
        if len(parts) != 3:
            raise ValueError(f"目标时间格式无效：{target_time}")
        hour, minute, second = (int(part) for part in parts)
        target = reference.replace(hour=hour, minute=minute, second=second, microsecond=0)
        return target

    def is_in_burst_window(
        self,
        target_time: str,
        prepare_seconds: float,
        burst_seconds: float = DEFAULT_BURST_WINDOW_SECONDS,
    ) -> bool:
        try:
            now_ts = self.server_timestamp()
            reference = self.server_now()
            parts = str(target_time or "00:00:00").strip().split(":")
            if len(parts) != 3:
                raise ValueError(f"目标时间格式无效：{target_time}")
            hour, minute, second = (int(part) for part in parts)
            target = reference.replace(hour=hour, minute=minute, second=second, microsecond=0)
        except ValueError:
            return False
        window_start = target.timestamp() - max(0.0, prepare_seconds)
        window_end = target.timestamp() + max(0.0, burst_seconds)
        return window_start <= now_ts <= window_end

    def is_prewarm_window(
        self,
        target_time: str,
        prepare_seconds: float,
        prewarm_lead_seconds: float = 120.0,
    ) -> bool:
        """True when we should keep the query page warm before the burst window."""
        try:
            target = self.parse_target_datetime(target_time)
        except ValueError:
            return False
        now_ts = self.server_timestamp()
        prewarm_start = target.timestamp() - max(prepare_seconds, 0.0) - max(prewarm_lead_seconds, 0.0)
        burst_start = target.timestamp() - max(prepare_seconds, 0.0)
        return prewarm_start <= now_ts < burst_start


_GLOBAL_SYNC: Optional[ServerTimeSync] = None


def get_server_time_sync(log_callback: Optional[Callable[[str], None]] = None) -> ServerTimeSync:
    global _GLOBAL_SYNC
    if _GLOBAL_SYNC is None:
        _GLOBAL_SYNC = ServerTimeSync(log_callback=log_callback)
    elif log_callback is not None:
        _GLOBAL_SYNC.log = log_callback
    return _GLOBAL_SYNC


def reset_server_time_sync() -> None:
    global _GLOBAL_SYNC
    _GLOBAL_SYNC = None


def resolve_sale_timestamp(config):
    value = str(config.get("sale_at", "")).strip()
    if not value:
        raise ValueError("请核对并填写完整起售日期时间（北京时间），旧版时分秒不会自动顺延至次日。")
    try:
        target = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("起售时刻格式无效") from exc
    if target.utcoffset() != timedelta(hours=8):
        raise ValueError("起售时刻必须包含北京时间时区 +08:00")
    return target.timestamp()
