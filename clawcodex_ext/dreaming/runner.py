"""Dream consolidation runner — F-100.

Mirrors the ``runForkedAgent`` shape used upstream by
``claude-code-best/src/services/autoDream/autoDream.ts`` — i.e. a
function that takes a prompt, calls back to a progress watcher for
each assistant turn, and returns a final result.

**Phase A status:** the LLM invocation is intentionally a *stub*.
The actual agent-loop integration is a follow-up that depends on
clawcodex's own agent runner (which is not exposed as a public
library API in the way ``runForkedAgent`` is in TS).

The stub preserves the contract:

* takes a ``prompt`` string + ``on_message`` callback
* emits one assistant message with empty text + zero tool calls
  (so :func:`add_dream_turn` is exercised end-to-end)
* returns a :class:`DreamRunResult` with zero usage

This lets Phase A land the state machine + service main loop with
real tests; the runner swap is a one-line change in
:func:`run_dream_consolidation` once the agent runner is exposed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

_log = logging.getLogger(__name__)

__all__ = [
    "DreamRunResult",
    "DreamRunnerUnavailable",
    "run_dream_consolidation",
]


class DreamRunnerUnavailable(RuntimeError):
    """Raised when no dream runner is configured.

    The auto-dream service catches this and treats it as a soft skip
    (the time/session gates don't depend on the runner). The manual
    ``/dream`` skill surfaces it as a user-facing error.
    """


@dataclass
class DreamRunResult:
    """Final result of a dream consolidation run.

    Mirrors the relevant fields of upstream
    ``runForkedAgent``'s return value. ``usage`` defaults to an empty
    dict so the stub has a stable shape; the real runner fills it
    with token counters.
    """

    files_touched: list[str] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    summary: str = ""


class _ProgressCallback(Protocol):
    def __call__(self, *, text: str, tool_use_count: int, touched_paths: list[str]) -> None: ...


# Indirection so the service can swap implementations at startup
# (e.g. tests install a fake; production installs the real LLM-backed
# runner once it lands).
RunnerFactory = Callable[[], Callable[[str, _ProgressCallback], DreamRunResult]]
_runner_factory: RunnerFactory | None = None


def set_dream_runner_factory(factory: RunnerFactory | None) -> None:
    """Install or clear the runner factory.

    Pass ``None`` to fall back to the built-in Phase A stub.
    """
    global _runner_factory
    _runner_factory = factory


def run_dream_consolidation(
    prompt: str,
    on_message: _ProgressCallback | None = None,
) -> DreamRunResult:
    """Run a single dream consolidation pass.

    The Phase A stub:

    1. Logs the call (so it's visible in journald / dev logs).
    2. If ``on_message`` is set, emits one no-op turn.
    3. Returns a zero-usage :class:`DreamRunResult`.

    When a factory is installed via :func:`set_dream_runner_factory`,
    the factory's callable is invoked with the prompt + a thunk
    that wraps ``on_message`` into the factory's preferred shape.
    """
    if _runner_factory is not None:
        try:
            runner = _runner_factory()
        except Exception as e:  # pragma: no cover - defensive
            _log.warning("dream runner factory failed to construct: %s", e)
            raise DreamRunnerUnavailable(str(e)) from e
        try:
            return runner(prompt, on_message)
        except DreamRunnerUnavailable:
            raise
        except Exception as e:
            _log.warning("dream runner raised: %s", e)
            raise DreamRunnerUnavailable(str(e)) from e

    # Built-in stub path.
    _log.info(
        "dream consolidation stub: prompt_len=%d%s",
        len(prompt),
        " (with on_message)" if on_message is not None else "",
    )
    if on_message is not None:
        try:
            on_message(text="", tool_use_count=0, touched_paths=[])
        except Exception:  # pragma: no cover - defensive
            _log.debug("dream on_message callback raised", exc_info=True)
    return DreamRunResult(files_touched=[], usage={}, summary="(stub run)")
