"""One browser task owns its cancellation, clock, and immutable input snapshot."""
from copy import deepcopy
from dataclasses import dataclass, field
import threading
import time
import uuid
from contextlib import contextmanager


class TaskCancelled(BaseException):
    """Unwind nested Selenium handlers without their broad retry catches."""


@contextmanager
def guard_browser(driver, task, tick):
    original = driver.execute
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


@dataclass
class MonitorTask:
    config: dict
    target_timestamp: float = None
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_at: float = field(default_factory=time.time)
    status: str = "preparing"
    sequence: int = 0
    next_query_at: float = None
    cancel: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread = None
    last_tick: float = field(default_factory=time.monotonic)
    last_login_check: float = float("-inf")

    def __post_init__(self):
        self.config = deepcopy(self.config)

    @property
    def active(self):
        return not self.done.is_set() or bool(self.thread and self.thread.is_alive())

    def payload(self):
        return {"run_id": self.run_id, "status": self.status, "sequence": self.sequence, "target_at": self.target_timestamp,
                "started_at": self.started_at, "next_query_at": self.next_query_at}
