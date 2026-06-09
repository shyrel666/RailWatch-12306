"""12306 server time calibration for punctual ticket monitoring."""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Callable, Optional

import urllib.error
import urllib.request

DEFAULT_12306_TIME_URL = "https://kyfw.12306.cn/otn/resources/login.html"
DEFAULT_SYNC_INTERVAL_SECONDS = 300.0
DEFAULT_BURST_WINDOW_SECONDS = 45.0


class ServerTimeSync:
    """Track offset between local clock and 12306 server clock (via HTTP Date header)."""

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
            with urllib.request.urlopen(request, timeout=5) as response:
                date_header = response.headers.get("Date")
                if not date_header:
                    raise RuntimeError("12306 响应缺少 Date 头")
                server_dt = parsedate_to_datetime(date_header)
                server_ts = server_dt.timestamp()
                local_ts = time.time()
                self._offset_seconds = server_ts - local_ts
                self._last_sync_monotonic = now_mono
                self._last_error = ""
                self.log(
                    f"服务器时间已校准，偏移 {self._offset_seconds:+.3f}s"
                    if abs(self._offset_seconds) >= 0.05
                    else "服务器时间与本地时钟一致"
                )
        except (urllib.error.URLError, OSError, RuntimeError, ValueError) as exc:
            self._last_error = str(exc)
            if force or not self._last_sync_monotonic:
                self.log(f"服务器时间校准失败，使用本地时钟：{exc}")
        return self._offset_seconds

    def server_timestamp(self) -> float:
        self.sync()
        return time.time() + self._offset_seconds

    def server_now(self) -> datetime:
        return datetime.fromtimestamp(self.server_timestamp())

    def parse_target_datetime(self, target_time: str, reference: Optional[datetime] = None) -> datetime:
        reference = reference or self.server_now()
        parts = str(target_time or "00:00:00").strip().split(":")
        if len(parts) != 3:
            raise ValueError(f"目标时间格式无效：{target_time}")
        hour, minute, second = (int(part) for part in parts)
        target = reference.replace(hour=hour, minute=minute, second=second, microsecond=0)
        if target <= reference:
            target = target + timedelta(days=1)
        return target

    def is_in_burst_window(
        self,
        target_time: str,
        prepare_seconds: float,
        burst_seconds: float = DEFAULT_BURST_WINDOW_SECONDS,
    ) -> bool:
        try:
            target = self.parse_target_datetime(target_time)
        except ValueError:
            return False
        now_ts = self.server_timestamp()
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
