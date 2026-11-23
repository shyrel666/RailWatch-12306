"""One browser task owns its cancellation, clock, and immutable input snapshot."""
from copy import deepcopy
from dataclasses import dataclass, field
import threading
import time
import uuid
from contextlib import contextmanager


class TaskCancelled(BaseException):
    """Unwind nested Selenium handlers without their broad retry catches."""


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
    "disconnected: not connected to devtools",
    "chrome not reachable",
)


def is_session_lost(exc: BaseException) -> bool:
    """判断异常是否表示句柄背后的浏览器会话已经不存在。"""
    if any(klass.__name__ in SESSION_LOST_EXCEPTION_NAMES for klass in type(exc).__mro__):
        return True
    message = str(exc).lower()
    return any(hint in message for hint in SESSION_LOST_MESSAGE_HINTS)


@contextmanager
def guard_browser(driver, task, tick, call_lock=None):
    original = driver.execute
    driver_dict = getattr(driver, "__dict__", {})
    previous_bypass = driver_dict.get("_railwatch_bypass_tls")
    previous_call_lock = driver_dict.get("_railwatch_call_lock")
    bypass_tls = threading.local()

    def _run(command, params=None):
        if task.cancel.is_set():
            raise TaskCancelled()
        tick()
        result = original(command, params)
        if task.cancel.is_set():
            raise TaskCancelled()
        tick()
        return result

    def execute(command, params=None):
        bypassed = getattr(bypass_tls, "depth", 0) > 0
        if call_lock is None:
            return original(command, params) if bypassed else _run(command, params)
        with call_lock:
            return original(command, params) if bypassed else _run(command, params)

    def install():
        driver._railwatch_bypass_tls = bypass_tls
        if call_lock is not None:
            driver._railwatch_call_lock = call_lock
        driver.execute = execute

    def restore():
        driver.execute = original
        if previous_bypass is None:
            driver_dict.pop("_railwatch_bypass_tls", None)
        else:
            driver._railwatch_bypass_tls = previous_bypass
        if previous_call_lock is None:
            driver_dict.pop("_railwatch_call_lock", None)
        else:
            driver._railwatch_call_lock = previous_call_lock

    if call_lock is None:
        install()
    else:
        with call_lock:
            install()
    try:
        yield
    finally:
        if call_lock is None:
            restore()
        else:
            with call_lock:
                restore()


@contextmanager
def driver_call_section(driver):
    """Serialize multi-step WebDriver operations against concurrent bridge calls."""
    lock = getattr(driver, "__dict__", {}).get("_railwatch_call_lock")
    if lock is None:
        yield
        return
    with lock:
        yield


@contextmanager
def browser_tab_lifecycle(driver):
    """Allow bounded tab creation/cleanup to finish even during cancellation.

    Only use for tab handles, opening a blank tab, closing our tab and restoring
    the original handle. Inventory, navigation and page actions stay guarded.
    Bypass state is thread-local so other threads still observe the call lock
    and cancellation checks.
    """
    with driver_call_section(driver):
        bypass_tls = getattr(driver, "__dict__", {}).get("_railwatch_bypass_tls")
        if bypass_tls is None:
            yield
            return
        depth = getattr(bypass_tls, "depth", 0)
        bypass_tls.depth = depth + 1
        try:
            yield
        finally:
            if depth == 0:
                try:
                    del bypass_tls.depth
                except AttributeError:
                    pass
            else:
                bypass_tls.depth = depth


@dataclass
class MonitorTask:
    config: dict
    target_timestamp: float = None
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_at: float = field(default_factory=time.time)
    status: str = "preparing"
    sequence: int = 0
    finish_recorded: bool = False
    next_query_at: float = None
    cancel: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread = None
    last_tick: float = field(default_factory=time.monotonic)
    last_login_check: float = float("-inf")
    sale_login_checked: bool = False
    deferred_sale_login_check: bool = False
    sale_login_rechecks: int = 0
    sale_login_retry_at: float = float("-inf")

    def __post_init__(self):
        self.config = deepcopy(self.config)

    @property
    def active(self):
        return not self.done.is_set() or bool(self.thread and self.thread.is_alive())

    def payload(self):
        return {"run_id": self.run_id, "status": self.status, "sequence": self.sequence, "target_at": self.target_timestamp,
                "started_at": self.started_at, "next_query_at": self.next_query_at}
