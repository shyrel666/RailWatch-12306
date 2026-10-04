"""In-memory phase measurements; callers choose when to persist diagnostics."""
import time


class PhaseTiming:
    def __init__(self):
        self.started = self.last = time.monotonic()
        self.current = None
        self.steps = []
        self.finished = False

    def step(self, name=None):
        if self.finished:
            return
        now = time.monotonic()
        if self.current is not None:
            self.steps.append({"id": self.current, "start_ms": round((self.last - self.started) * 1000, 3),
                               "duration_ms": round((now - self.last) * 1000, 3)})
        self.current, self.last = name, now

    def finish(self):
        self.step()
        self.finished = True
        return self.steps
