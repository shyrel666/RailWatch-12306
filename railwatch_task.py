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
def guard_browser(driver, task, tick):
    original = driver.execute
    previous_cleanup = getattr(driver, "_railwatch_cleanup_execute", None)
    driver._railwatch_cleanup_execute = original
    def execute(command, params=None):
        if task.cancel.is_set():
            raise TaskCancelled()
        tick()
        result = original(command, params)
        if task.cancel.is_set():
            raise TaskCancelled()
        tick()
        return result
    driver.execute = execute
    try:
        yield
    finally:
        driver.execute = original
        driver._railwatch_cleanup_execute = previous_cleanup


@contextmanager
def browser_tab_lifecycle(driver):
    """Allow bounded tab creation/cleanup to finish even during cancellation.

    Only use for tab handles, opening a blank tab, closing our tab and restoring
    the original handle. Inventory, navigation and page actions stay guarded.
    """
    guarded = driver.execute
    raw = getattr(driver, "_railwatch_cleanup_execute", None)
    if raw is not None:
        driver.execute = raw
    try:
        yield
    finally:
        driver.execute = guarded


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

    def __post_init__(self):
        self.config = deepcopy(self.config)

    @property
    def active(self):
        return not self.done.is_set() or bool(self.thread and self.thread.is_alive())

    def payload(self):
        return {"run_id": self.run_id, "status": self.status, "sequence": self.sequence, "target_at": self.target_timestamp,
                "started_at": self.started_at, "next_query_at": self.next_query_at}
