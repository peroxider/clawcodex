"""Lightweight observability metrics for Logical Kanban (F-139).

The module exposes a minimal ``emit(event, **labels)`` facade and a
``register_sink(callable)`` hook.  By default the sink is a no-op, so
instrumentation is safe to scatter through hot paths without affecting
production performance or reliability.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Stable event names persisted/aggregated by tests and future sinks.
VALIDATION_RUN = "lkb_validation_run"
COMMIT = "lkb_commit"
DENIAL = "lkb_denial"
ADAPTER_RESULT = "lkb_adapter_result"
BLOCKED_TASKS = "lkb_blocked_tasks"
STALE_ASSUMPTIONS = "lkb_stale_assumptions"
TIMEOUT = "lkb_solver_timeout"
SNAPSHOT_CACHE_HIT = "lkb_snapshot_cache_hit"
SNAPSHOT_CACHE_MISS = "lkb_snapshot_cache_miss"
LLM_FACTS_EXTRACTED = "lkb_llm_facts_extracted"
LLM_FACTS_DROPPED = "lkb_llm_facts_dropped"
LLM_FALLBACK_USED = "lkb_llm_fallback_used"

_Sink = Callable[[str, dict[str, Any]], None]

_sinks: list[_Sink] = []


def register_sink(sink: _Sink) -> None:
    """Register a callback that receives every metric event.

    Sinks are called synchronously and must not raise.  Multiple sinks are
    supported so tests can register a collecting sink without removing the
    default logging sink.
    """
    if sink not in _sinks:
        _sinks.append(sink)


def unregister_sink(sink: _Sink) -> None:
    """Remove a previously registered sink."""
    try:
        _sinks.remove(sink)
    except ValueError:
        pass


def reset_sinks() -> None:
    """Remove all sinks.  Intended for test isolation."""
    _sinks.clear()


def emit(event: str, **labels: Any) -> None:
    """Emit a metric event to every registered sink.

    Failures in individual sinks are swallowed and logged so telemetry can
    never break the validation path.
    """
    if not _sinks:
        return
    payload = dict(labels)
    payload["_event"] = event
    for sink in list(_sinks):
        try:
            sink(event, payload)
        except Exception as exc:  # pragma: no cover - defensive only
            logger.debug("LKB metrics sink %s failed: %s", sink, exc)


def record_validation_run(
    *,
    result: str,
    engine: str,
    change_kind: str,
    duration_ms: int,
    task_count: int,
    task_id: str | None = None,
    validation_run_id: str = "",
    proposal_id: str = "",
) -> None:
    """Record a completed validation run."""
    emit(
        VALIDATION_RUN,
        result=result,
        engine=engine,
        change_kind=change_kind,
        duration_ms=duration_ms,
        task_count=task_count,
        task_id=task_id,
        validation_run_id=validation_run_id,
        proposal_id=proposal_id,
    )


def record_denial(
    *,
    rule: str,
    code: str,
    change_kind: str,
    task_id: str | None = None,
    validation_run_id: str = "",
) -> None:
    """Record a denied proposal with the formal rule/code that caused it."""
    emit(
        DENIAL,
        rule=rule,
        code=code,
        change_kind=change_kind,
        task_id=task_id,
        validation_run_id=validation_run_id,
    )


def record_commit(
    *,
    committed: bool,
    change_kind: str,
    task_id: str | None = None,
    validation_run_id: str = "",
) -> None:
    """Record a commit attempt/result."""
    emit(
        COMMIT,
        committed=committed,
        change_kind=change_kind,
        task_id=task_id,
        validation_run_id=validation_run_id,
    )


def record_adapter_result(
    *,
    adapter: str,
    result: str,
    duration_ms: int,
    timeout_seconds: float,
    task_id: str | None = None,
) -> None:
    """Record the result from a single solver adapter."""
    emit(
        ADAPTER_RESULT,
        adapter=adapter,
        result=result,
        duration_ms=duration_ms,
        timeout_seconds=timeout_seconds,
        task_id=task_id,
    )


def record_timeout(
    *,
    adapter: str,
    timeout_seconds: float,
    task_id: str | None = None,
) -> None:
    """Record a solver adapter timeout."""
    emit(
        TIMEOUT,
        adapter=adapter,
        timeout_seconds=timeout_seconds,
        task_id=task_id,
    )


def record_blocked_tasks(count: int) -> None:
    """Record the number of currently blocked tasks in a snapshot."""
    emit(BLOCKED_TASKS, count=count)


def record_stale_assumptions(count: int) -> None:
    """Record the number of currently stale assumptions."""
    emit(STALE_ASSUMPTIONS, count=count)


def record_snapshot_cache_hit() -> None:
    """Record a snapshot cache hit."""
    emit(SNAPSHOT_CACHE_HIT)


def record_snapshot_cache_miss() -> None:
    """Record a snapshot cache miss."""
    emit(SNAPSHOT_CACHE_MISS)


def record_llm_facts_extracted(count: int, *, source: str = "llm_extracted") -> None:
    """Record LLM-derived facts that passed the glossary gate."""
    emit(LLM_FACTS_EXTRACTED, count=count, source=source)


def record_llm_facts_dropped(count: int, *, reason: str = "unknown_predicate") -> None:
    """Record LLM-derived facts that were dropped by the glossary gate."""
    emit(LLM_FACTS_DROPPED, count=count, reason=reason)


def record_llm_fallback_used(*, phrase: str, kind: str) -> None:
    """Record an L3 ambiguity-detector fallback to the LLM."""
    emit(LLM_FALLBACK_USED, phrase=phrase, kind=kind)


__all__ = [
    "ADAPTER_RESULT",
    "BLOCKED_TASKS",
    "COMMIT",
    "DENIAL",
    "STALE_ASSUMPTIONS",
    "SNAPSHOT_CACHE_HIT",
    "SNAPSHOT_CACHE_MISS",
    "TIMEOUT",
    "VALIDATION_RUN",
    "LLM_FACTS_EXTRACTED",
    "LLM_FACTS_DROPPED",
    "LLM_FALLBACK_USED",
    "emit",
    "record_adapter_result",
    "record_blocked_tasks",
    "record_commit",
    "record_denial",
    "record_llm_facts_dropped",
    "record_llm_facts_extracted",
    "record_llm_fallback_used",
    "record_stale_assumptions",
    "record_snapshot_cache_hit",
    "record_snapshot_cache_miss",
    "record_timeout",
    "record_validation_run",
    "register_sink",
    "reset_sinks",
    "unregister_sink",
]
