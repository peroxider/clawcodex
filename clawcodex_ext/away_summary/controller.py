"""Idle controller for automatic Away Summary generation."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from clawcodex_ext.away_summary.config import AwaySummaryConfig, load_away_summary_config
from clawcodex_ext.away_summary.fingerprint import (
    conversation_fingerprint,
    last_away_summary_fingerprint,
    session_turn_count,
)
from clawcodex_ext.away_summary.messages import format_away_summary_for_display
from clawcodex_ext.away_summary.service import AwaySummaryService

logger = logging.getLogger(__name__)


class TimerHandle(Protocol):
    def cancel(self) -> None: ...


class TimerFactory(Protocol):
    def call_later(self, seconds: float, callback: Callable[[], None]) -> TimerHandle: ...


class ThreadingTimerFactory:
    def call_later(self, seconds: float, callback: Callable[[], None]) -> TimerHandle:
        timer = threading.Timer(seconds, callback)
        timer.daemon = True
        timer.start()
        return timer


@dataclass
class AwaySummaryController:
    conversation: Any
    provider_getter: Callable[[], Any]
    model_getter: Callable[[], str | None]
    session_getter: Callable[[], Any | None]
    display: Callable[[str], None] | None = None
    config_loader: Callable[[], AwaySummaryConfig] = load_away_summary_config
    timer_factory: TimerFactory | None = None
    interactive: bool = True

    def __post_init__(self) -> None:
        self.timer_factory = self.timer_factory or ThreadingTimerFactory()
        self._lock = threading.RLock()
        self._timer: TimerHandle | None = None
        self._busy = False
        self._armed_fingerprint: str | None = None
        self._running = False

    def on_user_interaction(self, reason: str = "user") -> None:
        del reason
        with self._lock:
            self._cancel_locked()

    def on_run_start(self) -> None:
        with self._lock:
            self._busy = True
            self._cancel_locked()

    def on_run_finish(self) -> None:
        with self._lock:
            self._busy = False

    def on_assistant_turn_complete(self) -> None:
        with self._lock:
            self._busy = False
            if not self.interactive:
                return
            cfg = self.config_loader()
            if not cfg.enabled:
                return
            if session_turn_count(self.conversation) < cfg.min_turns:
                return
            fingerprint = conversation_fingerprint(self.conversation)
            if fingerprint == last_away_summary_fingerprint(self.conversation):
                return
            self._cancel_locked()
            self._armed_fingerprint = fingerprint
            self._timer = self.timer_factory.call_later(
                cfg.idle_seconds,
                self._on_idle_timer,
            )

    def close(self) -> None:
        with self._lock:
            self._cancel_locked()

    def _on_idle_timer(self) -> None:
        with self._lock:
            if self._busy or self._running:
                return
            cfg = self.config_loader()
            if not self.interactive or not cfg.enabled:
                return
            fingerprint = conversation_fingerprint(self.conversation)
            if fingerprint != self._armed_fingerprint:
                return
            if fingerprint == last_away_summary_fingerprint(self.conversation):
                return
            self._running = True
            self._timer = None

        try:
            service = AwaySummaryService(
                conversation=self.conversation,
                provider=self.provider_getter(),
                model=self.model_getter(),
                session=self.session_getter(),
                config=cfg,
            )
            result = service.generate(trigger="auto")
            if result.generated and self.display is not None:
                self.display(format_away_summary_for_display(result.summary))
        except Exception:
            logger.exception(
                "Away Summary failed: trigger=auto fingerprint=%s session_id=%s",
                self._armed_fingerprint,
                getattr(self.session_getter(), "session_id", ""),
            )
        finally:
            with self._lock:
                self._running = False
                self._armed_fingerprint = None

    def _cancel_locked(self) -> None:
        if self._timer is not None:
            try:
                self._timer.cancel()
            except Exception:
                pass
        self._timer = None
        self._armed_fingerprint = None
