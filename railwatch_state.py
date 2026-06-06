"""UI-facing state model for the RailWatch 12306 desktop product."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Mapping, Optional, Tuple


APP_DISPLAY_NAME = "RailWatch 12306"
APP_SLUG = "railwatch-12306"
APP_PAGES = ("Dashboard", "Trip Setup", "Monitor", "Settings")


class AppPhase(str, Enum):
    IDLE = "idle"
    ENVIRONMENT = "environment"
    LOGIN = "login"
    QUERY_READY = "query_ready"
    MONITORING = "monitoring"
    HIT = "hit"
    ALTERNATE = "alternate"
    ERROR = "error"


@dataclass(frozen=True)
class TicketHit:
    train_code: str
    seat_type: str
    status: str
    source: str = "regular"
    detail: str = ""

    def label(self) -> str:
        source_label = "alternate" if self.source == "alternate" else "ticket"
        return f"{self.train_code} {self.seat_type} {source_label}: {self.status}"


@dataclass(frozen=True)
class RailWatchState:
    brand_name: str = APP_DISPLAY_NAME
    data_dir_name: str = APP_SLUG
    pages: Tuple[str, ...] = APP_PAGES
    phase: AppPhase = AppPhase.IDLE
    environment_ready: bool = False
    login_ready: bool = False
    query_ready: bool = False
    monitoring: bool = False
    auto_submit_enabled: bool = False
    auto_alternate_enabled: bool = False
    risk_level: str = "notice"
    status_message: str = "Ready"
    error_message: str = ""
    current_config: Mapping[str, object] = field(default_factory=dict)
    hits: Tuple[TicketHit, ...] = field(default_factory=tuple)

    @classmethod
    def initial(cls) -> "RailWatchState":
        return cls()

    def with_environment(self, ready: bool, message: str = "") -> "RailWatchState":
        return replace(
            self,
            phase=AppPhase.ENVIRONMENT if ready else AppPhase.ERROR,
            environment_ready=ready,
            risk_level="notice" if ready else "critical",
            status_message=message or ("Environment ready" if ready else "Environment check failed"),
            error_message="" if ready else (message or "Environment check failed"),
        )

    def with_login(self, ready: bool, message: str = "") -> "RailWatchState":
        return replace(
            self,
            phase=AppPhase.LOGIN if ready else AppPhase.ERROR,
            login_ready=ready,
            risk_level="notice" if ready else "warning",
            status_message=message or ("Login ready" if ready else "Login required"),
            error_message="" if ready else (message or "Login required"),
        )

    def with_query_ready(
        self, ready: bool, config: Optional[Mapping[str, object]] = None, message: str = ""
    ) -> "RailWatchState":
        return replace(
            self,
            phase=AppPhase.QUERY_READY if ready else AppPhase.ERROR,
            query_ready=ready,
            current_config=dict(config or self.current_config),
            risk_level="notice" if ready else "warning",
            status_message=message or ("Query ready" if ready else "Query setup incomplete"),
            error_message="" if ready else (message or "Query setup incomplete"),
        )

    def with_monitoring(self, active: bool, message: str = "") -> "RailWatchState":
        next_phase = AppPhase.MONITORING if active else AppPhase.QUERY_READY
        if not active and self.phase in (AppPhase.HIT, AppPhase.ALTERNATE):
            next_phase = self.phase
        return replace(
            self,
            phase=next_phase,
            monitoring=active,
            risk_level="active" if active else "notice",
            status_message=message or ("Monitoring active" if active else "Monitoring stopped"),
            error_message="",
        )

    def with_hit(self, hit: TicketHit, message: str = "") -> "RailWatchState":
        phase = AppPhase.ALTERNATE if hit.source == "alternate" else AppPhase.HIT
        return replace(
            self,
            phase=phase,
            monitoring=True,
            hits=self.hits + (hit,),
            risk_level="success",
            status_message=message or hit.label(),
            error_message="",
        )

    def with_error(self, message: str) -> "RailWatchState":
        return replace(
            self,
            phase=AppPhase.ERROR,
            monitoring=False,
            risk_level="critical",
            status_message=message,
            error_message=message,
        )

    def with_safety(self, auto_submit: bool, auto_alternate: bool) -> "RailWatchState":
        level = "warning" if auto_submit or auto_alternate else self.risk_level
        return replace(
            self,
            auto_submit_enabled=auto_submit,
            auto_alternate_enabled=auto_alternate,
            risk_level=level,
        )

    def summary(self) -> str:
        if self.error_message:
            return self.error_message
        if self.hits:
            return self.hits[-1].label()
        return self.status_message
