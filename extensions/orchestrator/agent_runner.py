"""Run a single issue through ClawCodex query engine.

Port of Symphony's AgentRunner, replacing Codex JSON-RPC with QueryRunner.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from ..api.query import PhaseComplete, QueryConfig, QueryRunner
from ..api.query import SessionComplete, TextDelta, ToolCallEvent, ToolResultEvent, TurnComplete
from .approval_policy import (
    ApprovalPolicy,
    get_approval_policy,
    ToolCallEvent as PolicyToolCallEvent,
)
from extensions.orchestrator_runtime.adapters.clawcodex_compat import get_file_status
from .config.schema import AgentConfig, SandboxConfig, WorkflowConfig, WorkspaceConfig
from .debug_log import append_debug_event
from .issue import Issue
from .issue_state_cache import IssueStateCache
from .prompt_builder import PromptBuilder, resolve_python_executable
from .tool_event_log import ToolEventLog
from .workspace import Workspace

# Reuse the project's typed rate-limit error and helpers so the 429
# detection logic stays in lockstep with the rest of the codebase.
from extensions.orchestrator_runtime.adapters.clawcodex_compat import (
    RateLimitError,
    is_rate_limit_error,
)

if TYPE_CHECKING:
    from ..capabilities.agent_protocol import AgentLoopProtocol
    from ..capabilities.event_protocol import ToolEventProtocol
    from .progress_reporter import ProgressReporter

logger = logging.getLogger(__name__)

# ─── pdeath_sig helper ────────────────────────────────────────────────
# When the orchestrator is killed abruptly (SIGKILL, segfault, OOM),
# child processes (hooks, verification) become orphans. PR_SET_PDEATHSIG
# asks the kernel to deliver SIGTERM to children when the parent dies.


def _set_pdeathsig() -> None:
    """Set PR_SET_PDEATHSIG so child receives SIGTERM if parent dies."""
    try:
        import ctypes
        import signal as _signal

        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        PR_SET_PDEATHSIG = 1
        libc.prctl(PR_SET_PDEATHSIG, _signal.SIGTERM)
    except Exception:
        pass


# If the agent runs this many consecutive turns without making any
# file changes, the runner assumes it is stuck (e.g. the issue
# deliverables already exist in the base branch / workspace) and
# force-completes the session to avoid wasting API calls and retries.
_NOOP_DETECTION_MAX_TURNS = 5

# F-45: tool-event audit log rotation threshold. When events.ndjson
# exceeds this size on next append, rotate to events.ndjson.1 (single
# generation, overwrite). v2.14 will hook a cron for 7-day cleanup.
_TOOL_EVENT_LOG_ROTATE_BYTES = 50 * 1024 * 1024

# F-40 root-cause fix: after this many consecutive turns where the
# agent makes ONLY read-only tool calls (Bash, Read, Grep, …) without
# a single modifying tool call (Write / Edit / …) AND without changing
# the workspace (no new untracked or modified files), the session is
# considered stuck in an investigation spiral and terminated with
# ``session_end_reason="read_only_loop"``.  The threshold is generous
# because genuine development also involves exploration; the guard is
# meant to catch degenerate cases (F-40's 100+ Python-debug Bash calls
# that spanned multiple outer-loop turns without any code change).
_MAX_READ_ONLY_TURNS = 4

# F-40 root-cause fix: tool names that modify workspace files.
# Only Write / Edit tools count toward ``has_made_progress`` so the
# stagnation guard can distinguish "exploring the codebase" turns
# from actual code-production work.  ``Bash`` is intentionally omitted
# because it can be used for both read (ls / grep / cat) and write
# (git add / rm / mv) and trying to classify it at this level would
# require deep output analysis that is better done elsewhere.
_MODIFYING_TOOL_NAMES = frozenset(
    {
        "Write",
        "Edit",
        "FileWrite",
        "FileWriteTool",
        "FileEdit",
        "FileEditTool",
        "WriteTool",
        "EditTool",
    }
)

# F-40 root-cause fix: tool names that are read-only (exploration /
# diagnostics).  When an agent spends multiple consecutive turns
# making ONLY read-only tool calls without any modifying tool call
# and without changing the workspace, it is likely stuck in an
# investigation spiral (F-40's Python env debugging loop).  The
# stagnation guard below tracks a separate ``read_only_streak`` and
# breaks after ``max_read_only_turns`` such turns.
_READ_ONLY_TOOL_NAMES = frozenset(
    {
        "Read",
        "Bash",
        "Grep",
        "Glob",
        "WebFetch",
        "WebSearch",
        "TodoWrite",
        "TaskStop",
    }
)

# Mega-turn early-stop tuning (see the run loop). Check cadence is cheap
# (one `git status` per interval); the idle threshold must be long enough
# that a coordinator between worker waves (~1-3 min gaps observed) is not
# cut off, and short enough to save most of the wasted wall-clock before
# the run timeout.
_MEGATURN_CHECK_EVERY_S = 60.0
_MEGATURN_IDLE_STOP_S = 1800.0

_ORCHESTRATOR_INTERNAL_PATH_PREFIXES = (
    ".orchestrator_control/",
    ".run_control/",
    ".reports/",
    ".event_logs/",
)
_ORCHESTRATOR_INTERNAL_PATHS = frozenset(
    prefix.rstrip("/") for prefix in _ORCHESTRATOR_INTERNAL_PATH_PREFIXES
)


def _megaturn_idle_stop_enabled(session: Any) -> bool:
    """Swarm completion is owned by its execution-evidence gate."""
    return str(getattr(session, "run_kind", "")).strip().lower() != "swarm"


def _is_orchestrator_internal_path(path: str | None) -> bool:
    if not path:
        return False
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized in _ORCHESTRATOR_INTERNAL_PATHS or normalized.startswith(
        _ORCHESTRATOR_INTERNAL_PATH_PREFIXES,
    )


def _has_user_visible_status_changes(status_entries: list[Any]) -> bool:
    for entry in status_entries:
        paths = (
            getattr(entry, "path", None),
            getattr(entry, "original_path", None),
        )
        if any(path and not _is_orchestrator_internal_path(path) for path in paths):
            return True
    return False


@dataclass
class AgentSession:
    """One active issue run."""

    issue: Issue
    workspace: Workspace
    turn_count: int = 0
    status: str = "running"  # running, completed, failed
    output_text: str = ""
    # Lifecycle control
    paused: bool = False
    paused_at: float | None = None
    pause_reason: str = ""
    pause_resume_event: "asyncio.Event | None" = None
    # Event stream for CLI tail command
    event_queue: "asyncio.Queue | None" = None
    prompt_override: str | None = None
    # F-124: resolved pre-dispatch clarification context copied from the
    # persistent IssueRecord before the run starts.
    clarification_question: str | None = None
    clarification_answer: str | None = None
    clarification_source: str | None = None
    coordinator_mode: bool | None = None
    # F-49 Phase 1: Unix domain socket for live operator control. None if
    # the socket failed to start (or was disabled by configuration). When
    # set, the runner broadcasts every dispatched event and polls for
    # control commands at turn boundaries. Defensive: all socket ops
    # are wrapped in try/except so a broken socket never kills the
    # agent run.
    control_socket: Any | None = None
    # Public path of the listening socket. Stored on the session so the
    # Phase 2 ``attach`` CLI can discover it via the registry without
    # scanning the workspace tree.
    control_socket_path: str | None = None
    run_kind: str = "issue"
    run_id: str | None = None
    summary_comment_id: str | None = None
    tool_count: int = 0
    verification_status: str | None = None
    verification_output: str | None = None
    report_path: str | None = None
    # F-105: per-session cache for the tracker poll in ``_should_continue``.
    # Initialised by ``AgentRunner.run()`` from
    # ``agent_config.perf_should_continue_skip_turns``. When ``None`` the
    # runner falls back to the pre-F-105 behaviour of always polling.
    state_cache: "IssueStateCache | None" = None
    # F-120: list of files git left in conflict state. Populated by
    # ``Orchestrator._prepare_rebase_session`` from
    # ``IssueRecord.conflict_files`` when ``run_kind == "agent_rebase"``.
    # The prompt builder injects these into the conflict-resolution
    # prompt so the agent knows exactly which files need ``git add``
    # before ``git rebase --continue``.
    conflict_files: tuple[str, ...] | None = None
    # F-45: canonical path to ~/.clawcodex/tool-events/{run_id}/events.ndjson.
    # Set in AgentRunner.run() at session start; consumed by
    # report_writer.write() to dual-write the NDJSON to the persistent layer.
    tool_events_path: str | None = None
    # F-49 Phase 0.1: session-transcript storage for conversation recording.
    # Lazy-initialized in run() via SessionStorage. The agent_runner buffers
    # per-turn blocks here and emits exactly one AssistantMessage and (if
    # tool calls happened) one UserMessage per LLM turn at end-of-turn.
    _transcript_storage: Any | None = None
    # Accumulated assistant text in the current turn (concatenation of all
    # TextDelta events up to the first tool call OR up to SessionComplete
    # if no tool calls were emitted). Reset by _flush_turn_transcript().
    _transcript_asst_text: str = ""
    # Ordered list of ToolUseBlocks for the current turn, preserved in
    # event arrival order so the final AssistantMessage interleaves text
    # and tool_use blocks exactly as the LLM emitted them. Reset by
    # _flush_turn_transcript().
    _transcript_tool_uses: list[Any] = field(default_factory=list)
    # Pending ToolResultBlocks waiting to be paired with their ToolUseBlock
    # when the LLM turn ends. Keyed by tool_use_id so out-of-order arrivals
    # are handled correctly. Reset by _flush_turn_transcript().
    _transcript_pending_results: dict[str, Any] = field(default_factory=dict)
    # Ordered list of tool_use_ids for which results have been received
    # this turn. Used to emit the final UserMessage's ToolResultBlocks in
    # tool_use order, not arrival order. Reset by _flush_turn_transcript().
    _transcript_result_order: list[str] = field(default_factory=list)
    attempt: int = 1
    issue_attempt: int = 1
    followup_attempt: int = 1
    # 429-aware backoff bookkeeping. ``consecutive_429_count`` is
    # incremented on each rate-limit hit and reset on the next
    # successful turn. ``total_429_backoff_seconds`` is the cumulative
    # sleep time spent in in-turn backoff (visible on the dashboard
    # and useful for cost analysis). ``rate_limit_pending_turn``
    # records the turn number being re-issued after a 429 sleep so
    # the SessionComplete handler skips its turn_number increment.
    consecutive_429_count: int = 0
    total_429_backoff_seconds: float = 0.0
    rate_limit_pending_turn: int | None = None
    debug_log_path: str | None = None
    last_agent_event_at: float | None = None
    last_agent_event: str | None = None
    last_tool_name: str | None = None
    timeout_deadline_at: float | None = None
    # F-09 / F-40 root-cause fix: capture the reason the session ended
    # before the registry writeback. ``session_end_reason`` is one of
    # ``task_complete`` / ``noop_completed`` / ``budget_exhausted`` /
    # ``stagnation`` / ``loop_detected`` / ``failed`` / ``paused`` /
    # ``cancelled``; ``session_end_summary`` is a short human-readable
    # explanation surfaced in dashboard + registry.  The agent_runner
    # sets these on the appropriate exit branch so the orchestrator
    # can pass them to ``IssueRegistry.update_report`` instead of
    # silently inheriting ``status="completed"``.
    session_end_reason: str | None = None
    session_end_summary: str = ""
    # F-?? retry context: list of run_ids from previous failed attempts.
    # Populated by orchestrator._launch_issue from the registry; consumed
    # by PromptBuilder.render() to inject a hint into the agent's prompt
    # so it can Read() past transcripts.
    previous_run_ids: list[str] = field(default_factory=list)
    # F-120: file paths with conflict markers carried from
    # ``IssueRecord.conflict_files`` so the rebase-resolution prompt
    # can hand them to the agent. ``None`` for non-rebase sessions.
    conflict_files: tuple[str, ...] | None = None
    _snapshot_provider: str = ""
    _snapshot_model: str = ""

    def _save_json_snapshot(self) -> None:
        """F-49 Phase 0.4.5: write a ``src.agent.Session``-compatible
        ``.json`` snapshot so ``Session.load()`` can fast-path on
        ``--resume`` instead of replaying the full JSONL transcript.

        The snapshot is built from the JSONL transcript (which is the
        authoritative source) rather than from ``AgentSession`` fields
        that don't carry a full Conversation.  Best-effort: failures
        are logged but never propagated.

        IMPORTANT: this writes the ``{sid}.json`` file directly instead
        of calling ``CoreSession.save()`` to avoid the side-effect in
        ``save_to_session_storage()`` which overwrites the SessionStorage
        metadata (title, cwd, etc.) that ``run()`` already initialised
        via ``session._transcript_storage.init_metadata()``.
        """
        if not self.run_id:
            return
        try:
            import json as _json
            from clawcodex_ext.agent.conversation import Conversation
            from clawcodex_ext.services.session_storage import SessionStorage
            from clawcodex_ext.types.messages import message_from_dict

            storage: SessionStorage | None = getattr(self, "_transcript_storage", None)
            messages = []
            if storage is not None:
                try:
                    blocks = storage.load_messages()
                    for blk in blocks:
                        try:
                            msg = message_from_dict(blk)
                            messages.append(msg)
                        except Exception:
                            pass
                except Exception:
                    pass

            # Build cost block — mirrors Session._snapshot_cost_block()
            # in src/agent/session.py so restore_cost_state_for_session()
            # can restore bootstrap accumulators on --resume.
            cost_block: dict = {}
            try:
                import time as _time
                from clawcodex_ext.bootstrap.state import (
                    get_total_cost_usd,
                    get_total_api_duration,
                    get_total_api_duration_without_retries,
                    get_total_tool_duration,
                    get_total_lines_added,
                    get_total_lines_removed,
                    get_start_time,
                    get_model_usage,
                )

                cost_block = {
                    "total_cost_usd": get_total_cost_usd(),
                    "total_api_duration": get_total_api_duration(),
                    "total_api_duration_without_retries": get_total_api_duration_without_retries(),
                    "total_tool_duration": get_total_tool_duration(),
                    "total_lines_added": get_total_lines_added(),
                    "total_lines_removed": get_total_lines_removed(),
                    "last_duration": _time.time() - get_start_time(),
                    "model_usage": {
                        model: {
                            "input_tokens": u.input_tokens,
                            "output_tokens": u.output_tokens,
                            "cache_creation_input_tokens": u.cache_creation_input_tokens,
                            "cache_read_input_tokens": u.cache_read_input_tokens,
                            "cost_usd": u.cost_usd,
                        }
                        for model, u in get_model_usage().items()
                    },
                }
            except Exception:
                # Best-effort: cost block is optional; restore tolerates
                # missing fields with defaults of 0.
                pass

            # Write the .json snapshot directly — do NOT call
            # CoreSession.save() because it triggers
            # save_to_session_storage() which overwrites the
            # SessionStorage metadata (title, cwd) that run()
            # already initialised.
            conv = Conversation(messages=messages)
            snapshot_data = {
                "session_id": self.run_id,
                "provider": self._snapshot_provider or "",
                "model": self._snapshot_model or "",
                "conversation": conv.to_dict(),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "cost": cost_block,
            }
            session_dir = Path.home() / ".clawcodex" / "sessions" / str(self.run_id)
            session_dir.mkdir(parents=True, exist_ok=True)
            snapshot_path = session_dir / "session.json"
            with open(snapshot_path, "w", encoding="utf-8") as f:
                _json.dump(snapshot_data, f, indent=2)
        except Exception:
            logger.exception(
                "F-49 Phase 0.4.5: failed to write .json snapshot run_id=%s",
                self.run_id,
            )


@dataclass
class RetryItem:
    """Item queued for retry."""

    issue_id: str
    attempt: int
    delay_seconds: float
    identifier: str = ""
    error: str = ""
    worker_host: str | None = None
    workspace_path: str = ""
    scheduled_at: float = field(default_factory=time.time)


class AgentRunner:
    """Execute a single issue via ClawCodex QueryRunner."""

    def __init__(
        self,
        agent_config: AgentConfig,
        sandbox_config: SandboxConfig,
        workspace_cfg: WorkspaceConfig | None = None,
    ) -> None:
        self.agent_config = agent_config
        self.sandbox_config = sandbox_config
        # F-?? workspace-level python_executable resolver input. When
        # None (the default for legacy callers and unit tests) we
        # substitute an empty ``WorkspaceConfig()`` so the cascade
        # resolver still works: workspace explicit → detect → agent
        # default → "".  Production wires this from
        # ``workflow_config.workspace`` in orchestration.py.
        self.workspace_cfg: WorkspaceConfig = workspace_cfg or WorkspaceConfig()
        self.max_turns = agent_config.max_turns
        self.max_tools_per_turn = getattr(agent_config, "max_tools_per_turn", 50) or 50
        self._approval_policy: ApprovalPolicy = get_approval_policy(
            getattr(sandbox_config, "approval_policy", "never") or "never"
        )
        # Injectable sleep hook for 429 backoff. Tests monkey-patch
        # this with a recording coroutine; production paths use the
        # real ``asyncio.sleep`` so cancellation still works.
        self._sleep: Callable[[float], Awaitable[None]] = asyncio.sleep

    def _handle_tool_call(
        self,
        event: ToolCallEvent,
        session_context: dict[str, Any],
    ) -> ToolCallEvent:
        """Intercept tool call, apply approval policy.

        Returns the same event object with _approved / _deny_reason set.
        """
        # Convert to policy event type
        policy_event = PolicyToolCallEvent(
            tool_name=event.tool_name,
            params=event.params,
            tool_use_id=event.tool_use_id,
        )
        self._approval_policy.evaluate(policy_event, session_context)

        # Mirror decision back to the caller's event (src.api.query.ToolCallEvent)
        # which uses _approved / _deny_reason fields directly.
        event._approved = policy_event._approved
        event._deny_reason = policy_event._deny_reason
        return event

    @staticmethod
    def _event_to_broadcast_dict(event: Any) -> dict:
        """F-49 Phase 1: JSON-safe dict representation of a query event.

        Used by ``ControlSocket.send_event`` to broadcast to attached
        clients. Defensive: never raises; missing fields are omitted
        so a partial event still serializes cleanly.
        """
        from extensions.api.query import (
            TextDelta,
            ToolCallEvent,
            ToolResultEvent,
        )

        if isinstance(event, TextDelta):
            return {"content": str(getattr(event, "content", ""))}
        if isinstance(event, ToolCallEvent):
            return {
                "tool_name": str(getattr(event, "tool_name", "")),
                "tool_use_id": getattr(event, "tool_use_id", None),
                "params": dict(getattr(event, "params", {}) or {}),
                "approved": getattr(event, "_approved", None),
            }
        if isinstance(event, ToolResultEvent):
            return {
                "tool_name": str(getattr(event, "tool_name", "")),
                "tool_use_id": getattr(event, "tool_use_id", None),
                "result": dict(getattr(event, "result", {}) or {}),
            }
        return {}

    def _append_tool_event_log(
        self,
        event: ToolCallEvent,
        session_context: dict[str, Any],
    ) -> None:
        """Persist a per-tool decision row to events.ndjson (F-45 / F-46.0).

        Writes one NDJSON line to
        ``{workspace}/.reports/{run_id}.events.ndjson``, co-located with the
        RunReport.  Decoupled from ``permission_mode`` — all 7 modes (default
        / plan / bypassPermissions / acceptEdits / dontAsk / auto / bubble)
        write the same row shape; only the ``permission_mode`` column value
        varies.  Failures are logged and swallowed: the audit log must never
        block the agent run.

        F-46.0: writing is gated by ``session_context["audit_log"]``:
        ``none`` skips all rows, ``minimal`` only records denied decisions,
        and ``full`` records every tool call.
        """
        audit_log = session_context.get("audit_log", "full")
        if audit_log == "none":
            return
        if audit_log == "minimal" and event._approved is not False:
            # minimal = record only denied decisions.
            return
        try:
            run_id = session_context.get("run_id") or "unknown"
            workspace_path = session_context.get("workspace_path")
            if workspace_path:
                base_dir = Path(workspace_path) / ".reports"
            else:
                # Fallback: use the user-level path (non-orchestrator
                # or test contexts where workspace_path is not set).
                base_dir = Path.home() / ".clawcodex" / "tool-events"
            log_path = base_dir / f"{run_id}.events.ndjson"
            try:
                base_dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                # mkdir may fail in a sandboxed HOME; skip the rest
                # gracefully so the agent loop is never affected.
                logger.exception(
                    "tool-event log mkdir failed run_id=%s path=%s",
                    run_id,
                    base_dir,
                )
                return

            # Single-generation rotate (F-45 Sub-E decision: 50MB
            # threshold, single backup). v2.14 will add 7-day cleanup.
            try:
                if log_path.exists() and log_path.stat().st_size >= _TOOL_EVENT_LOG_ROTATE_BYTES:
                    rotated = log_path.with_name(log_path.name + ".1")
                    try:
                        rotated.unlink(missing_ok=True)
                    except Exception:
                        pass
                    log_path.replace(rotated)
            except Exception:
                # Rotation is best-effort — log and continue writing to
                # the live file. A single oversized file is still better
                # than a failed write.
                logger.exception("tool-event log rotate failed path=%s", log_path)

            row = ToolEventLog(
                tool=event.tool_name,
                params=event.params,
                approved=event._approved,
                deny_reason=event._deny_reason,
                permission_mode=session_context.get("permission_mode", "unknown"),
                turn=session_context.get("turn", 0),
                session_run_id=run_id,
                # Links this call row to its result row so the visualizer
                # can attach the spawned child's agent_id (written by the
                # supplemental agent_result row) to the right spawn.
                tool_use_id=getattr(event, "tool_use_id", None),
            )
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(row.to_json() + "\n")
            except Exception:
                logger.exception(
                    "tool-event log append failed run_id=%s path=%s",
                    run_id,
                    log_path,
                )
        except Exception:
            # Defensive outer guard: never let audit logging break the
            # agent run. The audit log is observable infrastructure, not
            # a correctness gate.
            logger.exception("tool-event log unexpected failure")

    def _append_agent_spawn_result_log(
        self,
        event: "ToolResultEvent",
        session_context: dict[str, Any],
    ) -> None:
        """Write a supplemental ``agent_result`` row for an Agent spawn.

        The spawned child's ``agent_id`` is only known when the Agent tool
        RETURNS — the call row cannot carry it. This row closes the gap:
        the visualizer joins call↔result rows on ``tool_use_id`` and gets
        an exact spawn→sub-agent attribution. Redundant with the
        ``agent_spawns.ndjson`` record written by the Agent tool itself —
        either channel alone is enough to reconstruct the spawn.
        Best-effort — never raises.
        """
        try:
            result = getattr(event, "result", None) or {}
            output = result.get("output")
            agent_id = output.get("agent_id") if isinstance(output, dict) else None
            if not agent_id:
                return
            run_id = session_context.get("run_id") or "unknown"
            workspace_path = session_context.get("workspace_path")
            if workspace_path:
                base_dir = Path(workspace_path) / ".reports"
            else:
                base_dir = Path.home() / ".clawcodex" / "tool-events"
            base_dir.mkdir(parents=True, exist_ok=True)
            log_path = base_dir / f"{run_id}.events.ndjson"
            row = ToolEventLog(
                tool="Agent",
                params={"description": output.get("description") or ""},
                approved=not result.get("is_error", False),
                deny_reason=None,
                permission_mode=session_context.get("permission_mode", "unknown"),
                turn=session_context.get("turn", 0),
                session_run_id=run_id,
                tool_use_id=getattr(event, "tool_use_id", None),
                kind="agent_result",
                agent_id=str(agent_id),
            )
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(row.to_json() + "\n")
        except Exception:
            logger.exception("agent spawn result log failed")

    def _flush_turn_transcript(self, session: AgentSession) -> None:
        """F-49 Phase 0.1: emit one AssistantMessage + (optionally) one UserMessage per turn.

        Called at end-of-turn: every ToolResultEvent (conditional on "all
        results in"), every SessionComplete, the max_turns fallthrough,
        and the 429 backoff reset. Idempotent — no-op if storage is not
        wired or buffers are empty. Defensive: never raises; callers
        wrap in try/except for logging.
        """
        if session._transcript_storage is None:
            return

        storage = session._transcript_storage
        from clawcodex_ext.types.messages import (
            create_assistant_message,
            create_user_message,
        )
        from clawcodex_ext.types.content_blocks import (
            TextBlock,
            ToolResultBlock,
        )

        # --- AssistantMessage: optional leading TextBlock then all ToolUseBlocks.
        blocks: list[Any] = []
        if session._transcript_asst_text:
            blocks.append(TextBlock(text=session._transcript_asst_text))
        blocks.extend(session._transcript_tool_uses)
        if blocks:
            storage.write_message(
                create_assistant_message(
                    content=blocks,
                    model=self.agent_config.model,
                ),
            )

        # --- UserMessage: ToolResultBlocks in tool_use order (NOT arrival order).
        # Iterate _transcript_tool_uses (preserves tool_use emission order)
        # and look up the corresponding result; this guarantees OOO arrivals
        # are still emitted in the canonical tool_use / tool_result pairing
        # order that the LLM API requires.
        if session._transcript_tool_uses:
            result_blocks: list[Any] = []
            for tool_use in session._transcript_tool_uses:
                use_id = tool_use.id
                pending = session._transcript_pending_results.get(use_id)
                if pending is None:
                    # Defensive: missing result for a tool_use. Emit a
                    # synthetic error block so the LLM transcript stays
                    # consistent on the next turn's prompt render.
                    result_blocks.append(
                        ToolResultBlock(
                            tool_use_id=use_id,
                            content="[Tool result missing — internal error]",
                            is_error=True,
                        )
                    )
                    continue
                result_blocks.append(pending)
            storage.write_message(
                create_user_message(
                    content=result_blocks,
                    origin="tool_result",
                ),
            )

        # --- Reset per-turn buffers.
        session._transcript_asst_text = ""
        session._transcript_tool_uses = []
        session._transcript_pending_results = {}
        session._transcript_result_order = []

    def _is_429_response(self, turn_output: str) -> bool:
        """Detect an upstream 429 rate limit in the accumulated turn output.

        The headless runner currently catches the provider's HTTPError
        and surfaces the message string in ``aggregate_text`` /
        ``stdout``, which the QueryRunner yields as a final ``TextDelta``
        before the ``SessionComplete(reason="exit_code=1")``. The string
        typically contains ``"Error code: 429"`` and a JSON body with
        ``"type": "rate_limit_error"``.

        Quota exhaustion is short-circuited to ``False`` — a permanent
        quota error is not helped by sleeping, and the normal failure
        path is the right place to surface it. Quota is detected by
        string match because the upstream message text mixes the
        429/rate_limit_error markers with quota-specific language
        ("exceeded your current quota", "limit: 0", or
        ``"Token Plan 主要面向个人开发者"``), and the typed
        ``is_quota_exhausted`` helper requires an exception object
        with a ``.status`` attribute that we don't have here.
        """
        if not turn_output:
            return False
        low = turn_output.lower()
        # Quota-style indicators win over rate-limit indicators. The
        # provider wraps quota in the same 429/rate_limit_error
        # envelope, so substring matching is the most robust signal
        # available without parsing the JSON body.
        # Temporary rate-limit phrasing from MiniMax that looks like quota
        # but is actually a retryable 429.  Check these FIRST so they
        # don't get caught by the broader "token plan" / "quota" match.
        temporary_rate_limit_indicators = (
            "请稍后重试",  # "please retry later"
            "当前请求量较高",  # "current request volume is high"
            "稍后重试",  # "retry later" (shorter variant)
        )
        if any(ind in turn_output for ind in temporary_rate_limit_indicators):
            # This is a temporary rate limit, not quota — fall through
            # to the 429/rate_limit_error detection below.
            pass
        else:
            quota_indicators = (
                "exceeded your current quota",
                "limit: 0",
                "token plan",  # MiniMax "Token Plan 主要面向个人开发者"
                "quota",
            )
            if any(ind in low for ind in quota_indicators):
                return False
        return (
            "error code: 429" in low
            or "rate_limit_error" in low
            or '"type": "rate_limit_error"' in low
            or "rate limit" in low
        )

    def _dispatch_sink(
        self,
        sink: Any,
        method: str,
        event: Any,
        session: "AgentSession",
    ) -> None:
        """Call ``sink.<method>(event, session)`` with logging on failure.

        A no-op shim for local-source-repo compatibility: the workspace
        has a full ProgressSink / CompositeProgressSink fan-out layer
        that this delegates to; in the local source repo the runner
        just calls back to ``sink.<method>`` directly.  Exceptions are
        caught and logged so a bad sink never crashes the agent run.
        """
        if sink is None:
            return
        try:
            getattr(sink, method)(event, session)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "progress_sink.%s dispatch failed: %s",
                method,
                exc,
            )

    def _compute_rate_limit_backoff(self, session: AgentSession) -> float:
        """Compute the next 429 backoff delay (seconds) for ``session``.

        Sequence: ``base * factor**(count-1)`` capped at
        ``rate_limit_max_backoff_ms``. A small jitter (±10% of delay)
        is added to avoid thundering-herd if the operator ever flips
        the workflow to parallel agents.
        """
        base_ms = self.agent_config.rate_limit_base_delay_ms
        max_ms = self.agent_config.rate_limit_max_backoff_ms
        factor = self.agent_config.rate_limit_exponential_factor
        count = max(1, session.consecutive_429_count)
        delay_ms = min(base_ms * (factor ** (count - 1)), max_ms)
        delay_s = delay_ms / 1000.0
        # Light jitter: up to +10% of the delay.  Keep it non-negative.
        jitter = random.uniform(0, 0.1 * delay_s) if delay_s > 0 else 0.0
        return delay_s + jitter

    async def _handle_rate_limit(
        self,
        session: AgentSession,
        turn_output: str,
        turn_number: int,
        status_dashboard: Any | None,
    ) -> str:
        """Apply 429 backoff for one cycle. Returns the new status.

        Increments ``session.consecutive_429_count``, computes the
        backoff delay, emits a ``TextDelta`` to the dashboard and
        event log, sleeps, and returns either ``"running"`` (re-issued
        the same turn) or ``"rate_limit_circuit_open"`` (circuit
        breaker tripped — caller should ``return``).
        """
        issue = session.issue
        session.consecutive_429_count += 1
        max_retries = self.agent_config.rate_limit_max_retries

        if session.consecutive_429_count > max_retries:
            session.status = "rate_limit_circuit_open"
            logger.error(
                "Rate limit circuit breaker open issue_id=%s consecutive=%d max=%d",
                issue.id,
                session.consecutive_429_count,
                max_retries,
            )
            return session.status

        delay_s = self._compute_rate_limit_backoff(session)
        session.total_429_backoff_seconds += delay_s
        notice = (
            f"\n[rate-limit] 429 detected "
            f"(attempt {session.consecutive_429_count}/{max_retries}); "
            f"sleeping {delay_s:.0f}s before retry\n"
        )
        session.output_text += notice

        # Surface to dashboard so the operator sees liveness during
        # the backoff.  Session transcript is not written here: the
        # 429 notice is transient operator-facing text, not LLM
        # conversation content.
        text_event = TextDelta(content=notice)
        if status_dashboard is not None:
            try:
                status_dashboard.on_event(text_event, session)
            except Exception:
                pass

        logger.warning(
            "Rate limit backoff issue_id=%s attempt=%d delay=%.1fs",
            issue.id,
            session.consecutive_429_count,
            delay_s,
        )

        # Mark the turn we are about to re-issue so the SessionComplete
        # handler (if it ever runs again on the same turn) skips its
        # own turn_number increment. Defensive — the current control
        # flow ``continue``s before incrementing.
        session.rate_limit_pending_turn = turn_number

        await self._sleep(delay_s)
        return "running"

    async def run(
        self,
        session: AgentSession,
        workflow: WorkflowConfig,
        status_dashboard: Any | None = None,
        tracker: Any = None,
        comment_tracker: Any | None = None,
        clarification_resolver: Any | None = None,
        progress_reporter: Any | None = None,
        diagnostics_callback: Callable[[AgentSession], None] | None = None,
    ) -> None:
        """Execute one session with coordinator mode isolated per task."""
        from clawcodex_ext.coordinator.mode import coordinator_mode_context

        explicit_mode = getattr(session, "coordinator_mode", None)
        coordinator_enabled = (
            bool(explicit_mode)
            if explicit_mode is not None
            else bool(getattr(self.agent_config, "coordinator_mode", False))
        )
        with coordinator_mode_context(coordinator_enabled):
            return await self._run_impl(
                session,
                workflow,
                status_dashboard=status_dashboard,
                tracker=tracker,
                comment_tracker=comment_tracker,
                clarification_resolver=clarification_resolver,
                progress_reporter=progress_reporter,
                diagnostics_callback=diagnostics_callback,
            )

    async def _run_impl(
        self,
        session: AgentSession,
        workflow: WorkflowConfig,
        status_dashboard: Any | None = None,
        tracker: Any = None,
        comment_tracker: Any | None = None,
        clarification_resolver: Any | None = None,
        progress_reporter: Any | None = None,
        diagnostics_callback: Callable[[AgentSession], None] | None = None,
    ) -> None:
        """Execute issue until completion or max_turns.

        Runs multi-turn continuation loop: each turn is a QueryRunner
        invocation; after each turn checks if the issue is still active
        via tracker.fetch_issue_states_by_ids and continues if so.
        """
        issue = session.issue
        workspace = session.workspace
        if session.run_id is None:
            session.run_id = self._build_run_id(session)
        # F-49 Phase 0.4.5: stash provider/model on the session so the
        # exit-callback can write the .json snapshot even when the
        # session has been partially cleaned up or the run aborted via
        # exception / early return.
        session._snapshot_provider = self.agent_config.provider or ""
        session._snapshot_model = self.agent_config.model or ""
        # F-105: initialise the per-session tracker poll cache. Built
        # once at run() start so the rest of the loop shares a single
        # instance; concurrent sessions still get their own. Setting
        # ``perf_should_continue_skip_turns=0`` on the agent config
        # disables the cache (the runner always polls).
        if session.state_cache is None:
            session.state_cache = IssueStateCache(
                stable_skip_turns=max(
                    0,
                    int(
                        getattr(
                            self.agent_config,
                            "perf_should_continue_skip_turns",
                            3,
                        )
                    ),
                )
            )
        if comment_tracker is not None and issue.id:
            await self._post_summary_placeholder(session, comment_tracker)

        # Pass delay_between_requests_ms to the query layer via env var.
        # _call_model_sync in src/query/query.py reads this to enforce a
        # minimum interval between successive provider API calls.
        delay_env = str(self.agent_config.delay_between_requests_ms)
        os.environ["CLAWCODEX_PROVIDER_REQUEST_DELAY_MS"] = delay_env
        if delay_env != "0":
            logger.info(
                "Provider request delay set to %s ms",
                delay_env,
            )

        # Coordinator mode: flip the env gate the headless entrypoint and
        # the Agent tool read (``is_coordinator_mode``). When enabled the
        # main session gets the restricted coordinator tool set (Agent /
        # SendMessage / TaskStop + lightweight reads) and is expected to
        # spawn workers via the Agent tool. This flip was lost in the
        # !52 squash-merge — restored from dfa79a7c.
        from clawcodex_ext.coordinator.mode import is_coordinator_mode

        if is_coordinator_mode():
            logger.info(
                "Coordinator mode ENABLED for issue %s — agent will get "
                "coordinator tool set and may spawn workers via Agent tool.",
                issue.id,
            )

        # Thread-local MDC: inject context so every subsequent log
        # record from this thread carries issue_id / run_id automatically.
        from .logging_setup import set_log_context

        set_log_context(
            issue_id=str(issue.id),
            run_id=str(session.run_id or ""),
            issue_identifier=str(issue.identifier),
        )
        logger.info(
            "Starting agent run issue_id=%s identifier=%s workspace=%s",
            issue.id,
            issue.identifier,
            workspace.path,
        )

        session_context = {
            "issue_id": issue.id,
            "issue_identifier": issue.identifier,
            "workspace_path": str(workspace.path),
            "workflow": workflow,
            # F-45: run_id + permission_mode are consumed by
            # _append_tool_event_log to write per-tool rows to
            # {workspace}/.reports/{run_id}.events.ndjson.
            "run_id": session.run_id,
            "permission_mode": self.agent_config.permission_mode,
            # F-46.0: audit_log level drives per-tool NDJSON filtering.
            "audit_log": self.agent_config.audit_log,
        }
        # F-45/F-46.0: stash the NDJSON path co-located with the RunReport
        # under ``{workspace}/.reports/<run_id>.events.ndjson`` so that
        # report_writer.write() can dual-write it to the persistent layer
        # (Sub-C).  Resolved here (not in the property) so the path is
        # concrete before the first event is appended.  When audit_log is
        # "none" we deliberately leave the path unset so report_writer skips
        # both the copy and the markdown line.
        if self.agent_config.audit_log != "none":
            session.tool_events_path = str(
                workspace.path / ".reports" / f"{session.run_id or 'unknown'}.events.ndjson"
            )
        else:
            session.tool_events_path = None
        session.debug_log_path = str(
            workspace.path
            / ".orchestrator_control"
            / "runs"
            / (session.run_id or "unknown")
            / "debug.ndjson"
        )
        append_debug_event(
            session.debug_log_path,
            "agent_runner.start",
            issue_id=issue.id,
            issue_identifier=issue.identifier,
            run_id=session.run_id,
            workspace=str(workspace.path),
            max_turns=self.max_turns,
            provider=self.agent_config.provider,
            permission_mode=self.agent_config.permission_mode,
        )

        turn_number = 0
        tool_count = 0
        consecutive_clean_turns = 0  # legacy workspace-dirty no-op counter
        # F-40: F-38 used a shared ``ProgressReporter`` singleton; the
        # orchestrator now passes a per-session :class:`ProgressSink`
        # via the ``progress_reporter`` kwarg. Bind it to ``sink`` so
        # the three ``_dispatch_sink`` calls (stagnation / loop /
        # no-op paths) reach a private, task-bound fan-out, and the
        # three PhaseComplete / TurnComplete / SessionComplete
        # dispatches below stay symmetric. ``sink`` is allowed to be
        # ``None`` for tests / direct call sites that don't wire a
        # reporter.
        sink = progress_reporter
        # F-?? root-cause fix: stagnation + loop guards. Independent of
        # the workspace-dirty heuristic above (which never fires when
        # the workspace has untracked files — the exact pattern observed
        # in F-09's repeated 30-min timeouts). no_work_streak counts
        # consecutive turns where the LLM produced zero tool calls AND
        # empty output. tool_signature_history tracks recent turn
        # signatures to detect repeated tool-call loops.
        no_work_streak = 0
        # F-40 root-cause fix: has_made_progress dual-threshold stagnation.
        # ``has_made_progress`` is set to True the first time the LLM
        # emits a modifying tool call (Write / Edit / …) in any turn.
        # When True, the stagnation guard requires 2× the configured
        # max_no_op_turns before triggering, because the agent has
        # already demonstrated it *can* produce useful work and the
        # empty-turn pattern is more likely a recoverable LLM tail
        # than a fundamental deadlock (as seen in F-40's run-06).
        # Stored on the session so ``_should_continue`` can read it.
        session.has_made_progress = False
        # Pre-existing bug (commit 8fb1b78): ``_dispatch_sink`` was added
        # but the ``sink`` variable was never assigned in ``run()``,
        # so stagnation/loop guard calls to ``_dispatch_sink(sink, ...)``
        # would raise ``NameError``.  Default to ``progress_reporter``
        # (None in test stubs, which ``_dispatch_sink`` treats as no-op).
        sink = progress_reporter
        # F-40 root-cause fix: read-only tool spiral detection.
        # Counts consecutive turns where the agent only made read-only
        # tool calls (Bash / Read / Grep / …) without any modifying
        # tool call (Write / Edit / …).  BashTool always produces
        # output (stdout/stderr), so ``turn_output`` is never empty
        # and cannot be used to distinguish exploration from empty
        # turns — we rely solely on the absence of modifying tools.
        # When this counter reaches ``_MAX_READ_ONLY_TURNS`` the
        # session is terminated with reason "read_only_loop".
        read_only_streak = 0
        tool_signature_history: list[str] = []
        max_no_op_turns = max(1, int(getattr(self.agent_config, "max_no_op_turns", 3) or 3))
        loop_window = max(2, int(getattr(self.agent_config, "loop_detection_window", 5) or 5))
        loop_threshold = max(2, int(getattr(self.agent_config, "loop_detection_threshold", 3) or 3))

        def update_diagnostics() -> None:
            session.tool_count = tool_count
            if diagnostics_callback is not None:
                try:
                    diagnostics_callback(session)
                except Exception:
                    logger.exception(
                        "run diagnostics callback failed issue_id=%s",
                        issue.id,
                    )

        update_diagnostics()
        try:
            while turn_number < self.max_turns:
                # Build prompt for this turn
                if turn_number == 0:
                    if session.prompt_override:
                        prompt = session.prompt_override
                        system_prompt_append = ""
                        user_prompt = prompt
                    else:
                        # Build clarification context if issue is in clarification flow
                        clarification_context = ""
                        pending_question = None
                        options = None

                        clarification_answer = getattr(session, "clarification_answer", None)
                        if clarification_answer:
                            pending_question = getattr(session, "clarification_question", None)
                            clarification_context = PromptBuilder.build_clarification_context(
                                pending_question=pending_question,
                                clarification_answer=clarification_answer,
                                answer_source=getattr(session, "clarification_source", None),
                            )

                        elif clarification_resolver is not None and issue.id:
                            get_answer = getattr(clarification_resolver, "get_answer", None)
                            resolved = get_answer(issue.id) if callable(get_answer) else None
                            if resolved and resolved.answer:
                                get_item = getattr(clarification_resolver, "get_item", None)
                                pending_item = get_item(issue.id) if callable(get_item) else None
                                pending_question = (
                                    pending_item.question if pending_item is not None else None
                                )
                                clarification_context = PromptBuilder.build_clarification_context(
                                    pending_question=pending_question,
                                    clarification_answer=resolved.answer,
                                    answer_source=resolved.source,
                                )
                            else:
                                # Review-rejection feedback is a typed one-shot
                                # instruction. Genuine clarification questions
                                # remain blocked at the dispatch gate.
                                get_pending_feedback = getattr(
                                    clarification_resolver,
                                    "get_pending_feedback",
                                    None,
                                )
                                pending_item = (
                                    get_pending_feedback(issue.id)
                                    if callable(get_pending_feedback)
                                    else None
                                )
                            if not clarification_context and pending_item is not None:
                                pending_question = pending_item.question
                                options = pending_item.options if pending_item.options else None
                                clarification_context = PromptBuilder.build_clarification_context(
                                    pending_question=pending_question,
                                    options=options,
                                )

                        system_prompt_append, user_prompt = PromptBuilder.render_parts(
                            issue,
                            clarification_context=clarification_context,
                            pending_question=pending_question,
                            options=options,
                            session=session,
                            python_executable=resolve_python_executable(
                                workspace_path=getattr(workspace, "path", None),
                                agent_cfg=self.agent_config,
                                workspace_cfg=self.workspace_cfg,
                                issue_executable=getattr(issue, "python_executable", "") or "",
                            ),
                            previous_run_ids=getattr(session, "previous_run_ids", None),
                            # F-120: inject the conflict-file list for an
                            # agent_rebase reentry run so the agent knows
                            # which files need marker resolution. Defense-
                            # in-depth: _launch_rebase_resolution also sets
                            # prompt_override via render_rebase, but this
                            # keeps the inline block working if a future
                            # caller forgets to set the override.
                            conflict_files=getattr(session, "conflict_files", None),
                        )
                    # F-?? prompt split: keep the constant workflow background
                    # in the system prompt across every turn; only the
                    # per-issue data lands in the user message.
                    session._system_prompt_append = system_prompt_append
                    session._issue_context = user_prompt  # Store for continuation
                    prompt = user_prompt
                else:
                    prompt = PromptBuilder.build_continuation_prompt(
                        turn_number=turn_number,
                        max_turns=self.max_turns,
                        issue_context=getattr(session, "_issue_context", None),
                        session=session,
                        python_executable=resolve_python_executable(
                            workspace_path=getattr(workspace, "path", None),
                            agent_cfg=self.agent_config,
                            workspace_cfg=self.workspace_cfg,
                            issue_executable=getattr(issue, "python_executable", "") or "",
                        ),
                    )
                    logger.info(
                        "Continuation turn %d/%s for issue_id=%s",
                        turn_number,
                        self.max_turns,
                        issue.id,
                    )

                # F-49 Phase 0: lazy-init SessionStorage and write user prompt
                if session.run_id:
                    if session._transcript_storage is None:
                        try:
                            from clawcodex_ext.services.session_storage import SessionStorage

                            session._transcript_storage = SessionStorage(
                                session_id=session.run_id,
                            )
                            session._transcript_storage.init_metadata(
                                model=self.agent_config.model or "",
                                cwd=str(session.workspace.path),
                                title=(
                                    f"orchestrator-{session.issue.identifier or session.issue.id}"
                                ),
                            )
                        except Exception:
                            logger.exception(
                                "Failed to init transcript storage run_id=%s",
                                session.run_id,
                            )
                    # F-49 Phase 1: start the Unix control socket. Defensive:
                    # a socket failure must NOT abort the agent run — log
                    # and leave ``control_socket = None`` so the broadcast
                    # + poll sites become no-ops.
                    if session.control_socket is None:
                        try:
                            from extensions.orchestrator.control_socket import (
                                ControlSocket,
                            )
                            from pathlib import Path as _CsPath

                            sock_dir = (
                                _CsPath(
                                    session.workspace.path,
                                )
                                / ".run_control"
                            )
                            sock_path = sock_dir / f"{session.run_id}.sock"
                            cs = ControlSocket(sock_path)
                            await cs.start()
                            session.control_socket = cs
                            session.control_socket_path = str(sock_path)
                        except Exception:
                            logger.exception(
                                "Failed to start control_socket run_id=%s",
                                session.run_id,
                            )
                            session.control_socket = None
                    if session._transcript_storage is not None:
                        try:
                            from clawcodex_ext.types.messages import create_user_message
                            from clawcodex_ext.types.content_blocks import TextBlock

                            session._transcript_storage.write_message(
                                create_user_message(
                                    content=[TextBlock(text=prompt)],
                                    origin="human",
                                )
                            )
                        except Exception:
                            logger.exception(
                                "Failed to write transcript prompt run_id=%s",
                                session.run_id,
                            )

                append_debug_event(
                    session.debug_log_path,
                    "agent_runner.turn_start",
                    issue_id=issue.id,
                    run_id=session.run_id,
                    turn=turn_number,
                    prompt_len=len(prompt),
                    output_len=len(session.output_text),
                )
                query_config = QueryConfig(
                    prompt=prompt,
                    workspace=workspace.path,
                    provider=self.agent_config.provider,
                    model=self.agent_config.model,
                    max_turns=self.max_turns,
                    permission_mode=self.agent_config.permission_mode,
                    run_id=session.run_id,
                    debug_log_path=session.debug_log_path,
                    env={
                        **(getattr(self.agent_config, "env", None) or {}),
                        "CLAUDE_CODE_COORDINATOR_MODE": ("1" if is_coordinator_mode() else "0"),
                    },
                    timeout_s=self.agent_config.run_timeout_ms / 1000.0,
                    stall_timeout_s=(
                        getattr(self.agent_config, "stall_timeout_ms", 300_000) / 1000.0
                    ),
                    stall_warn_s=(getattr(self.agent_config, "stall_warn_ms", 30_000) / 1000.0),
                    # F-?? prompt split: keep the constant workflow background
                    # in the system prompt across every turn (turn 0 sets it
                    # via render_parts; turn > 0 reads it from the session).
                    # This mirrors CCB's "rich system + short user" structure
                    # and stops the daemon from re-sending 5KB of background
                    # in every user message.
                    append_system_prompt=getattr(session, "_system_prompt_append", None),
                )
                runner = QueryRunner(query_config)

                turn_has_tool_calls = False
                turn_output = ""
                turn_has_modifying_tool = False
                # F-?? root-cause fix: per-turn tool-name accumulator feeding
                # the loop-detection signature history.
                turn_tool_names: list[str] = []
                # F-?? root-cause fix: per-turn tool call cap to prevent
                # infinite read-only exploration spirals in a single turn.
                turn_tool_count = 0
                # Track in-flight tool results so we can force a clean turn
                # boundary only after all capped calls have been answered.
                pending_tool_results = 0
                # Set once turn_tool_count reaches max_tools_per_turn.
                cap_reached = False
                # Mega-turn early-stop state. The "work appears done" check
                # in ``_should_continue`` only runs at TURN boundaries — a
                # coordinator session that delegates everything inside one
                # long turn never reaches it and idles until the run
                # timeout (observed live 2026-07-02: edits landed at 17:00,
                # timeout at 17:11). Mid-turn we cannot treat "workspace
                # has changes" as done (worker 3 of 5 leaves changes while
                # work continues), so the trigger is stricter: user-visible
                # changes exist AND the workspace has been UNCHANGED for
                # ``_MEGATURN_IDLE_STOP_S``. Checked at most once per
                # ``_MEGATURN_CHECK_EVERY_S`` on tool results.
                megaturn_next_check_at = time.monotonic() + _MEGATURN_CHECK_EVERY_S
                megaturn_ws_signature: str | None = None
                megaturn_ws_changed_at = time.monotonic()
                megaturn_stop = False

                try:
                    stream_iter = runner.stream()
                    while True:
                        try:
                            event = await stream_iter.__anext__()
                        except StopAsyncIteration:
                            break
                        event_type = type(event).__name__
                        session.last_agent_event_at = time.time()
                        session.last_agent_event = event_type
                        event_tool_name = getattr(event, "tool_name", None)
                        if event_tool_name:
                            session.last_tool_name = event_tool_name
                        event_reason = getattr(event, "reason", None)
                        append_debug_event(
                            session.debug_log_path,
                            "agent_runner.event",
                            issue_id=issue.id,
                            run_id=session.run_id,
                            type=event_type,
                            tool=event_tool_name,
                            turn=turn_number,
                            tool_count=tool_count,
                            output_len=len(session.output_text),
                            reason=event_reason,
                        )
                        if isinstance(event, TextDelta):
                            session.output_text += event.content
                            turn_output += event.content
                            update_diagnostics()
                            if status_dashboard is not None:
                                try:
                                    status_dashboard.on_event(event, session)
                                except Exception:
                                    pass

                            # Push to event queue for CLI tail
                            if session.event_queue is not None:
                                try:
                                    session.event_queue.put_nowait(event)
                                except Exception:
                                    pass

                            # F-49 Phase 1: broadcast to attached socket clients.
                            # Defensive: a broken socket must never abort the
                            # agent run, so the whole block is wrapped in
                            # try/except and guarded by ``is not None``.
                            if session.control_socket is not None:
                                try:
                                    await session.control_socket.send_event(
                                        {
                                            "type": event.__class__.__name__,
                                            "data": self._event_to_broadcast_dict(
                                                event,
                                            ),
                                        }
                                    )
                                except Exception:
                                    pass

                            # F-49 Phase 0: accumulate assistant text for transcript
                            session._transcript_asst_text += event.content

                        elif isinstance(event, ToolCallEvent):
                            turn_has_tool_calls = True
                            tool_count += 1
                            turn_tool_count += 1
                            pending_tool_results += 1
                            update_diagnostics()
                            # F-?? root-cause fix: collect tool names for the
                            # turn signature so the loop-detection guard can
                            # spot repeated tool-call patterns across turns.
                            if event.tool_name:
                                turn_tool_names.append(event.tool_name)
                            # F-40 root-cause fix: has_made_progress tracking.
                            # Once the LLM emits a modifying tool call, set the
                            # flag so the stagnation guard uses the relaxed
                            # (2×) threshold for subsequent empty turns.
                            if event.tool_name in _MODIFYING_TOOL_NAMES:
                                session.has_made_progress = True
                                turn_has_modifying_tool = True

                            # Enforce per-turn tool cap. We still process the
                            # tool call and its result so the event stream
                            # stays consistent; ``cap_reached`` forces a break
                            # once all in-flight results are consumed.
                            if turn_tool_count >= self.max_tools_per_turn:
                                cap_reached = True
                                logger.info(
                                    "Turn %s reached max_tools_per_turn=%s for issue %s; "
                                    "will force turn boundary after pending results",
                                    turn_number,
                                    self.max_tools_per_turn,
                                    issue.id,
                                )

                            # Pause support: wait for resume if session is paused
                            if session.paused and session.pause_resume_event is not None:
                                await session.pause_resume_event.wait()

                            # F-45: in headless (orchestrator) mode the api.query
                            # stream yields ToolCallEvent with _approved=None
                            # (TS upstream's ToolContext.approval_policy =
                            # "bypassPermissions" + permission_handler = None
                            # bypasses the user-prompt layer, not the policy
                            # decision layer).  The orchestrator's ApprovalPolicy
                            # is the authoritative source of "allowed vs denied";
                            # call it here so the audit log captures real
                            # decisions.  Then mirror the policy's verdict into
                            # the per-tool NDJSON bypass.
                            event = self._handle_tool_call(event, session_context)
                            # Tag session_context with the current turn so the
                            # NDJSON row carries the right `turn` value.
                            session_context["turn"] = turn_number
                            self._append_tool_event_log(event, session_context)

                            if status_dashboard is not None:
                                try:
                                    status_dashboard.on_event(event, session)
                                except Exception:
                                    pass

                            # Push to event queue for CLI tail
                            if session.event_queue is not None:
                                try:
                                    session.event_queue.put_nowait(event)
                                except Exception:
                                    pass

                            # F-49 Phase 1: broadcast to attached socket clients.
                            # Defensive: a broken socket must never abort the
                            # agent run, so the whole block is wrapped in
                            # try/except and guarded by ``is not None``.
                            if session.control_socket is not None:
                                try:
                                    await session.control_socket.send_event(
                                        {
                                            "type": event.__class__.__name__,
                                            "data": self._event_to_broadcast_dict(
                                                event,
                                            ),
                                        }
                                    )
                                except Exception:
                                    pass

                            # F-49 Phase 0.1: buffer tool_use block for end-of-turn flush.
                            # The spec requires ONE AssistantMessage per turn with N
                            # ToolUseBlocks in event arrival order; the flush is called
                            # from (a) the next ToolResultEvent, (b) SessionComplete,
                            # (c) max_turns fallthrough, (d) 429 backoff reset.
                            if session._transcript_storage is not None:
                                try:
                                    from clawcodex_ext.types.content_blocks import ToolUseBlock

                                    if event.tool_use_id:
                                        session._transcript_tool_uses.append(
                                            ToolUseBlock(
                                                id=event.tool_use_id,
                                                name=event.tool_name,
                                                input=event.params,
                                            )
                                        )
                                except Exception:
                                    logger.exception(
                                        "Failed to buffer transcript tool_use run_id=%s",
                                        session.run_id,
                                    )

                        elif isinstance(event, ToolResultEvent):
                            pending_tool_results -= 1
                            logger.debug(
                                "Tool result issue_id=%s tool=%s is_error=%s",
                                issue.id,
                                event.tool_name,
                                event.result.get("is_error", False),
                            )
                            # Spawn attribution: an Agent result may carry
                            # the spawned child's agent_id — persist it as
                            # a supplemental F-45 row (joined to the call
                            # row via tool_use_id by the visualizer).
                            if event.tool_name == "Agent":
                                self._append_agent_spawn_result_log(event, session_context)
                            if status_dashboard is not None:
                                try:
                                    status_dashboard.on_event(event, session)
                                except Exception:
                                    pass

                            # Push to event queue for CLI tail
                            if session.event_queue is not None:
                                try:
                                    session.event_queue.put_nowait(event)
                                except Exception:
                                    pass

                            # F-49 Phase 1: broadcast to attached socket clients.
                            # Defensive: a broken socket must never abort the
                            # agent run, so the whole block is wrapped in
                            # try/except and guarded by ``is not None``.
                            if session.control_socket is not None:
                                try:
                                    await session.control_socket.send_event(
                                        {
                                            "type": event.__class__.__name__,
                                            "data": self._event_to_broadcast_dict(
                                                event,
                                            ),
                                        }
                                    )
                                except Exception:
                                    pass

                            # F-49 Phase 0.1: buffer tool_result for end-of-turn flush.
                            # Keyed by tool_use_id (populated by convert_tool_event
                            # in extensions/api/query.py) so out-of-order arrivals
                            # are paired correctly. Flush at the natural end-of-
                            # tool-result point; the SessionComplete path also
                            # flushes unconditionally, so missing results get a
                            # synthetic error block.
                            if session._transcript_storage is not None and event.tool_use_id:
                                try:
                                    from clawcodex_ext.types.content_blocks import ToolResultBlock

                                    result_output = event.result.get("output", "")
                                    is_error = event.result.get("is_error", False)
                                    session._transcript_pending_results[event.tool_use_id] = (
                                        ToolResultBlock(
                                            tool_use_id=event.tool_use_id,
                                            content=(
                                                result_output
                                                if isinstance(result_output, str)
                                                else str(result_output)
                                            ),
                                            is_error=is_error,
                                        )
                                    )
                                    if event.tool_use_id not in (session._transcript_result_order):
                                        session._transcript_result_order.append(
                                            event.tool_use_id,
                                        )
                                    if len(session._transcript_result_order) >= len(
                                        session._transcript_tool_uses
                                    ):
                                        self._flush_turn_transcript(session)
                                except Exception:
                                    logger.exception(
                                        "Failed to buffer transcript tool_result run_id=%s",
                                        session.run_id,
                                    )
                            update_diagnostics()
                            if status_dashboard is not None:
                                try:
                                    status_dashboard.on_event(event, session)
                                except Exception:
                                    pass

                            # F-?? root-cause fix: if the per-turn tool cap
                            # was reached and all in-flight results have been
                            # consumed, force a turn boundary now. This breaks
                            # infinite read-only exploration spirals while
                            # keeping the transcript/event stream consistent.
                            if cap_reached and pending_tool_results <= 0:
                                logger.info(
                                    "Turn %s forced turn boundary after "
                                    "max_tools_per_turn=%s for issue %s",
                                    turn_number,
                                    self.max_tools_per_turn,
                                    issue.id,
                                )
                                # Synthesize a SessionComplete-equivalent break
                                # so the outer loop re-issues the turn prompt.
                                break

                            # Mega-turn early stop: throttled workspace-idle
                            # probe. Triggers only when user-visible changes
                            # exist AND the workspace has been unchanged for
                            # ``_MEGATURN_IDLE_STOP_S`` — the work landed and
                            # the model is churning (re-verifying, retrying
                            # blocked tools) without producing anything new.
                            if (
                                _megaturn_idle_stop_enabled(session)
                                and time.monotonic() >= megaturn_next_check_at
                            ):
                                megaturn_next_check_at = time.monotonic() + _MEGATURN_CHECK_EVERY_S
                                try:
                                    ws_path = getattr(session.workspace, "path", None)
                                    if ws_path is not None:
                                        entries = await asyncio.to_thread(
                                            get_file_status, str(ws_path)
                                        )
                                        user_entries = [
                                            entry
                                            for entry in entries
                                            if not _is_orchestrator_internal_path(
                                                getattr(entry, "path", str(entry))
                                            )
                                        ]
                                        signature = "|".join(
                                            sorted(
                                                str(getattr(entry, "path", entry))
                                                for entry in user_entries
                                            )
                                        )
                                        if signature != megaturn_ws_signature:
                                            megaturn_ws_signature = signature
                                            megaturn_ws_changed_at = time.monotonic()
                                        elif user_entries and (
                                            time.monotonic() - megaturn_ws_changed_at
                                            >= _MEGATURN_IDLE_STOP_S
                                        ):
                                            megaturn_stop = True
                                except Exception:
                                    pass  # Fail-open: probe must never kill the run
                            if megaturn_stop and pending_tool_results <= 0:
                                logger.info(
                                    "Issue %s mega-turn early stop: workspace has "
                                    "user changes and has been idle for %.0fs — "
                                    "ending session instead of waiting for the "
                                    "run timeout",
                                    issue.id,
                                    _MEGATURN_IDLE_STOP_S,
                                )
                                session.has_made_progress = True
                                session.status = "completed"
                                session.session_end_reason = "megaturn_workspace_idle"
                                session.session_end_summary = (
                                    "Workspace changes landed and stayed unchanged "
                                    f"for {int(_MEGATURN_IDLE_STOP_S)}s inside a "
                                    "single turn; session ended early."
                                )
                                append_debug_event(
                                    session.debug_log_path,
                                    "agent_runner.megaturn_early_stop",
                                    issue_id=issue.id,
                                    run_id=session.run_id,
                                    turn=turn_number,
                                    tool_count=tool_count,
                                    idle_stop_s=_MEGATURN_IDLE_STOP_S,
                                )
                                self._flush_turn_transcript(session)
                                # Explicitly close the stream so
                                # QueryRunner.stream()'s finally-abort trips
                                # the headless session NOW (not at GC).
                                try:
                                    await stream_iter.aclose()
                                except Exception:
                                    pass
                                self._dispatch_sink(
                                    sink,
                                    "on_session_complete",
                                    SessionComplete(reason="megaturn_workspace_idle"),
                                    session,
                                )
                                return

                        elif isinstance(event, SessionComplete):
                            # 429-aware backoff: detect rate limit BEFORE the
                            # normal completion handling so we can re-issue
                            # the same turn after sleeping instead of failing.
                            if self._is_429_response(turn_output):
                                new_status = await self._handle_rate_limit(
                                    session,
                                    turn_output,
                                    turn_number,
                                    status_dashboard,
                                )
                                if new_status == "rate_limit_circuit_open":
                                    return
                                # F-49 Phase 0.1: reset per-turn transcript
                                # buffers so the re-issued turn starts clean.
                                # The previous code leaked _transcript_asst_text
                                # and a stale _transcript_tool_use_id across
                                # the backoff boundary.
                                self._flush_turn_transcript(session)
                                # Reset the per-turn accumulators so the
                                # re-issued turn starts with a clean slate.
                                turn_output = ""
                                turn_has_tool_calls = False
                                # Do NOT increment turn_number; the same
                                # turn's prompt will be re-rendered below
                                # when the outer while loop iterates.
                                continue

                            # Normal completion path — increment the turn
                            # counter and emit PhaseComplete.
                            # F-49 Phase 1: drain control commands at the
                            # turn boundary. We use ``get_nowait()`` rather
                            # than the ``poll_commands()`` async generator
                            # so the runner does not block waiting for a
                            # command that may never arrive — the common case
                            # in headless / CI tests is no clients connected.
                            # Defensive: each branch wrapped so a malformed
                            # command never aborts the run.
                            if session.control_socket is not None:
                                try:
                                    _q = session.control_socket._command_queue
                                    while True:
                                        try:
                                            cmd = _q.get_nowait()
                                        except asyncio.QueueEmpty:
                                            break
                                        if cmd.cmd == "pause":
                                            session.paused = True
                                            session.pause_reason = "operator_interrupt"
                                            if session.pause_resume_event is not None:
                                                session.pause_resume_event.clear()
                                        elif cmd.cmd == "resume":
                                            if cmd.payload:
                                                session.prompt_override = cmd.payload
                                            session.paused = False
                                            if session.pause_resume_event is not None:
                                                session.pause_resume_event.set()
                                        elif cmd.cmd == "stop":
                                            session.session_end_reason = "operator_stop"
                                            session.session_end_summary = (
                                                "operator sent stop via control socket"
                                            )
                                        elif cmd.cmd == "takeover":
                                            session.session_end_reason = "operator_takeover"
                                            session.session_end_summary = (
                                                "operator requested takeover via control socket"
                                            )
                                        # inject / detach: parsed, no agent
                                        # action yet (TODO Phase 2/3).
                                except Exception:
                                    logger.exception(
                                        "control_socket.poll_commands failed",
                                    )
                            turn_number += 1
                            session.turn_count = turn_number
                            # F-49 Phase 0.1: emit any buffered turn content
                            # (AssistantMessage + optional UserMessage) and
                            # flush the storage buffer. The helper handles
                            # empty buffers idempotently.
                            if session._transcript_storage is not None:
                                try:
                                    self._flush_turn_transcript(session)
                                    session._transcript_storage.flush()
                                except Exception:
                                    logger.exception(
                                        "Failed to flush transcript run_id=%s",
                                        session.run_id,
                                    )
                            # F-49 Phase 1: stop the control socket so the
                            # .sock file is cleaned up and any attached
                            # clients see EOF. Defensive: a stop failure
                            # must not propagate out of the turn.
                            if session.control_socket is not None:
                                try:
                                    await session.control_socket.stop()
                                except Exception:
                                    logger.exception(
                                        "Failed to stop control_socket run_id=%s",
                                        session.run_id,
                                    )
                                session.control_socket = None
                            append_debug_event(
                                session.debug_log_path,
                                "agent_runner.turn_complete",
                                issue_id=issue.id,
                                run_id=session.run_id,
                                turn=turn_number,
                                reason=event.reason,
                                tool_count=tool_count,
                                output_len=len(session.output_text),
                            )

                            # Emit PhaseComplete event for progress reporting
                            phase_event = PhaseComplete(
                                phase=turn_number,
                                turn_count=turn_number,
                            )
                            if sink is not None:
                                # F-40: dispatch PhaseComplete + TurnComplete
                                # through the new protocol methods. The old
                                # ``on_event`` shim is no longer used by
                                # AgentRunner; the F-38 stub tests were
                                # already updated to record on these
                                # callbacks.
                                self._dispatch_sink(sink, "on_phase_complete", phase_event, session)
                                self._dispatch_sink(
                                    sink,
                                    "on_turn_complete",
                                    TurnComplete(turn=turn_number),
                                    session,
                                )

                            update_diagnostics()
                            if event.reason == "success":
                                # A successful turn resets the 429 backoff
                                # counter — a 429 followed by a clean run is
                                # a sign the rate window has passed.
                                session.consecutive_429_count = 0
                                session.rate_limit_pending_turn = None

                                # Check if issue is still active before declaring completion
                                # F-54 root-cause fix: pass the session so
                                # ``_should_continue`` can also check the
                                # workspace's git state and stop the
                                # continuation loop when work is done.
                                if tracker is not None and issue.id:
                                    try:
                                        is_active, refreshed_issue = await self._should_continue(
                                            issue, tracker, session
                                        )
                                    except Exception as tracker_exc:
                                        logger.warning(
                                            "Tracker poll failed for issue %s, assuming still active: %s",
                                            issue.id,
                                            tracker_exc,
                                        )
                                        is_active, refreshed_issue = True, issue
                                    if is_active and turn_number < self.max_turns:
                                        # F-?? Fix 4: include the running noop
                                        # streak in the continuation log so
                                        # operators can spot stuck-on-finished
                                        # runs from the daemon log alone
                                        # (the previous message had no
                                        # indicator that the agent was no
                                        # longer making progress).
                                        logger.info(
                                            "Issue %s still active, continuing turn %d/%d "
                                            "(noop_streak=%d/%d)",
                                            issue.id,
                                            turn_number,
                                            self.max_turns,
                                            no_work_streak,
                                            max_no_op_turns,
                                        )
                                        # F-?? root-cause fix: stagnation guard.
                                        # Counts consecutive turns where the LLM
                                        # produced zero tool calls AND empty
                                        # output — the exact pattern observed in
                                        # F-09's repeated 30-min timeouts (run-06
                                        # had 0 tool calls / 328 SessionComplete
                                        # events in a tight loop). Independent of
                                        # the workspace-dirty heuristic below,
                                        # which silently never fires when the
                                        # workspace has untracked files.
                                        if not turn_has_tool_calls and not turn_output.strip():
                                            no_work_streak += 1
                                        else:
                                            no_work_streak = 0

                                        # F-40 root-cause fix: dual-threshold.
                                        # An agent that has already made progress
                                        # (emitted at least one modifying tool
                                        # call — Write / Edit / …) is given 2× the
                                        # configured max_no_op_turns before
                                        # stagnation fires, because empty-turn
                                        # streaks after productive work are
                                        # more likely recoverable (the LLM may be
                                        # in a temporary tail loop) than true
                                        # deadlocks from a broken provider.
                                        _stagnation_threshold = (
                                            max_no_op_turns * 2
                                            if session.has_made_progress
                                            else max_no_op_turns
                                        )
                                        if no_work_streak >= _stagnation_threshold:
                                            # F-54 root-cause fix: when the
                                            # agent never emitted a single
                                            # modifying tool call (Write/Edit)
                                            # AND tool_count is 0 (SessionComplete
                                            # returned immediately without any
                                            # tool), the real reason is "LLM gave
                                            # up without doing work", not
                                            # stagnation.  Mark it as such so
                                            # the orchestrator can retry.
                                            if (
                                                not getattr(session, "has_made_progress", False)
                                                and tool_count == 0
                                            ):
                                                # F-54 root-cause fix: before
                                                # declaring ``llm_gave_up``,
                                                # verify via test_command.
                                                if getattr(
                                                    self.agent_config, "test_command", None
                                                ) and await self._run_verification(session):
                                                    session.status = "completed"
                                                    session.session_end_reason = "already_completed"
                                                    session.session_end_summary = (
                                                        "work already implemented "
                                                        "(verification passed)"
                                                    )
                                                    logger.info(
                                                        "Issue %s: work already done "
                                                        "(verification passed) — "
                                                        "marking completed",
                                                        issue.id,
                                                    )
                                                elif getattr(
                                                    self.agent_config, "test_command", None
                                                ):
                                                    session.session_end_reason = "llm_gave_up"
                                                    session.session_end_summary = (
                                                        f"LLM returned SessionComplete(success) "
                                                        f"after 0 tool calls with no code changes"
                                                    )
                                                    logger.warning(
                                                        "LLM gave up immediately issue_id=%s "
                                                        "turns=%s tools=%s — "
                                                        "SessionComplete with 0 tools",
                                                        issue.id,
                                                        turn_number,
                                                        tool_count,
                                                    )
                                                else:
                                                    session.session_end_reason = "stagnation"
                                                    session.session_end_summary = (
                                                        f"{no_work_streak} consecutive "
                                                        "turns with no tool calls and "
                                                        "empty output"
                                                    )
                                            else:
                                                session.session_end_reason = "stagnation"
                                                session.session_end_summary = (
                                                    f"{no_work_streak} consecutive "
                                                    "turns with no tool calls and "
                                                    "empty output"
                                                )
                                            logger.warning(
                                                "Stagnation detected issue_id=%s — "
                                                "%d consecutive no-op turns, "
                                                "breaking outer loop",
                                                issue.id,
                                                no_work_streak,
                                            )
                                            append_debug_event(
                                                session.debug_log_path,
                                                "agent_runner.stagnation_detected",
                                                issue_id=issue.id,
                                                run_id=session.run_id,
                                                turn=turn_number,
                                                no_work_streak=no_work_streak,
                                            )
                                            session.status = "stagnation"
                                            self._dispatch_sink(
                                                sink,
                                                "on_session_complete",
                                                SessionComplete(reason="stagnation"),
                                                session,
                                            )
                                            return

                                        # F-40 root-cause fix: read-only
                                        # tool spiral guard.  When the agent
                                        # spends multiple consecutive turns
                                        # making ONLY read-only tool calls
                                        # (Bash / Read / Grep / …) without a
                                        # single Write / Edit, it is stuck
                                        # in an investigation spiral (F-54's
                                        # turn 1-6 pattern: 230+ Bash calls,
                                        # 0 code changes).  Bash output is
                                        # always non-empty, so we do NOT
                                        # check ``turn_output`` here —
                                        # the absence of modifying tools
                                        # is the reliable indicator.
                                        if (
                                            turn_number > 0
                                            and turn_has_tool_calls
                                            and not turn_has_modifying_tool
                                        ):
                                            read_only_streak += 1
                                        else:
                                            read_only_streak = 0

                                        if read_only_streak >= _MAX_READ_ONLY_TURNS:
                                            session.session_end_reason = "read_only_loop"
                                            session.session_end_summary = (
                                                f"{read_only_streak} consecutive "
                                                "turns with only read-only tool calls "
                                                "and no code changes"
                                            )
                                            logger.warning(
                                                "Read-only tool loop detected issue_id=%s — "
                                                "%d consecutive read-only turns, "
                                                "breaking outer loop",
                                                issue.id,
                                                read_only_streak,
                                            )
                                            append_debug_event(
                                                session.debug_log_path,
                                                "agent_runner.read_only_loop_detected",
                                                issue_id=issue.id,
                                                run_id=session.run_id,
                                                turn=turn_number,
                                                read_only_streak=read_only_streak,
                                            )
                                            session.status = "read_only_loop"
                                            self._dispatch_sink(
                                                sink,
                                                "on_session_complete",
                                                SessionComplete(reason="read_only_loop"),
                                                session,
                                            )
                                            return

                                        # F-?? root-cause fix: loop guard.
                                        # Records this turn's tool-call
                                        # signature and breaks if the same
                                        # signature repeats >= threshold
                                        # times within the recent window.
                                        if turn_tool_names:
                                            signature = "|".join(sorted(turn_tool_names))
                                        else:
                                            signature = "<empty>"
                                        tool_signature_history.append(signature)
                                        if len(tool_signature_history) > loop_window:
                                            tool_signature_history = tool_signature_history[
                                                -loop_window:
                                            ]
                                        if (
                                            tool_signature_history.count(signature)
                                            >= loop_threshold
                                        ):
                                            session.session_end_reason = "loop_detected"
                                            session.session_end_summary = (
                                                f"signature {signature!r} "
                                                f"repeated "
                                                f"{tool_signature_history.count(signature)} "
                                                f"times in last {loop_window} turns"
                                            )
                                            logger.warning(
                                                "Loop detected issue_id=%s — "
                                                "signature %r repeated %d times, "
                                                "breaking outer loop",
                                                issue.id,
                                                signature,
                                                tool_signature_history.count(signature),
                                            )
                                            append_debug_event(
                                                session.debug_log_path,
                                                "agent_runner.loop_detected",
                                                issue_id=issue.id,
                                                run_id=session.run_id,
                                                turn=turn_number,
                                                signature=signature,
                                                repeat_count=(
                                                    tool_signature_history.count(signature)
                                                ),
                                            )
                                            session.status = "loop_detected"
                                            self._dispatch_sink(
                                                sink,
                                                "on_session_complete",
                                                SessionComplete(reason="loop_detected"),
                                                session,
                                            )
                                            return

                                        # No-op detection: if the agent has run multiple
                                        # consecutive turns without making any file changes,
                                        # it is likely stuck (e.g. the issue deliverables
                                        # already exist in the workspace). Force-complete
                                        # instead of wasting API calls and retry loops.
                                        workspace_path = str(session.workspace.path)
                                        dirty = bool(get_file_status(workspace_path))
                                        if dirty:
                                            consecutive_clean_turns = 0
                                        else:
                                            consecutive_clean_turns += 1
                                            if consecutive_clean_turns >= _NOOP_DETECTION_MAX_TURNS:
                                                logger.warning(
                                                    "No-op detection triggered issue_id=%s — "
                                                    "agent performed %d consecutive turns with "
                                                    "zero file changes, force-completing",
                                                    issue.id,
                                                    consecutive_clean_turns,
                                                )
                                                session.status = "completed"
                                                session.session_end_reason = "noop_completed"
                                                session.session_end_summary = (
                                                    f"{consecutive_clean_turns} "
                                                    "consecutive clean turns"
                                                )
                                                # F-40: surface the
                                                # no-op completion to the
                                                # sink as a synthetic
                                                # SessionComplete so
                                                # downstream consumers
                                                # always see a terminal
                                                # event.
                                                self._dispatch_sink(
                                                    sink,
                                                    "on_session_complete",
                                                    SessionComplete(reason="noop_completed"),
                                                    session,
                                                )
                                                return
                                        continue  # Go to next turn
                                    session.issue = refreshed_issue or session.issue
                                elif (
                                    tracker is None
                                    and turn_number < self.max_turns
                                    and session.status == "running"
                                ):
                                    if not turn_has_tool_calls and not turn_output.strip():
                                        no_work_streak += 1
                                    else:
                                        no_work_streak = 0

                                    if getattr(session, "has_made_progress", False):
                                        logger.info(
                                            "Workflow stage completed: agent signaled done "
                                            "with code changes issue_id=%s turn=%d/%d tools=%s",
                                            issue.id,
                                            turn_number,
                                            self.max_turns,
                                            tool_count,
                                        )
                                        session.status = "completed"
                                        if session.session_end_reason is None:
                                            session.session_end_reason = "task_complete"
                                            session.session_end_summary = (
                                                f"workflow stage completed after "
                                                f"{turn_number} turns, {tool_count} tools"
                                            )
                                    elif tool_count > 0:
                                        # Agent did work (read/analyze) and signaled done.
                                        # Normal for analysis stages that don't write code.
                                        logger.info(
                                            "Workflow stage completed: agent signaled done "
                                            "after analysis issue_id=%s turn=%d/%d tools=%s",
                                            issue.id,
                                            turn_number,
                                            self.max_turns,
                                            tool_count,
                                        )
                                        session.status = "completed"
                                        if session.session_end_reason is None:
                                            session.session_end_reason = "task_complete"
                                            session.session_end_summary = (
                                                f"workflow stage completed (analysis) after "
                                                f"{turn_number} turns, {tool_count} tools"
                                            )
                                    elif no_work_streak >= max_no_op_turns:
                                        if tool_count == 0:
                                            # Agent never got to work (rate-limited or stuck).
                                            # This is a failure, not a completion.
                                            logger.warning(
                                                "Agent produced 0 tool calls after %d turns "
                                                "(likely rate-limited), marking failed "
                                                "issue_id=%s",
                                                no_work_streak,
                                                issue.id,
                                            )
                                            session.status = "failed"
                                            session.session_end_reason = "rate_limited"
                                            session.session_end_summary = (
                                                f"agent never started: {no_work_streak} "
                                                f"consecutive empty turns, 0 tools"
                                            )
                                        else:
                                            logger.warning(
                                                "No-work streak reached (%d/%d) without tracker, "
                                                "force-completing issue_id=%s",
                                                no_work_streak,
                                                max_no_op_turns,
                                                issue.id,
                                            )
                                            session.status = "completed"
                                            session.session_end_reason = "noop_completed"
                                            session.session_end_summary = (
                                                f"{no_work_streak} consecutive no-work turns"
                                            )
                                    else:
                                        logger.info(
                                            "Continuing without tracker (workflow stage) "
                                            "issue_id=%s turn=%d/%d",
                                            issue.id,
                                            turn_number,
                                            self.max_turns,
                                        )
                                        continue

                                # F-?? root-cause fix: pre-existing bug
                                # that conflated "issue is no longer
                                # active" with "we ran out of turns".  When
                                # the issue is still active but
                                # ``turn_number`` has reached
                                # ``max_turns``, the right status is
                                # ``max_turns_exceeded`` and
                                # ``session_end_reason`` is
                                # ``budget_exhausted`` — the F-09 budget
                                # test depends on this distinction.
                                if (
                                    turn_number >= self.max_turns
                                    and session.status == "running"
                                    and (tracker is not None or sink is not None)
                                ):
                                    if (
                                        session.total_429_backoff_seconds > 0
                                        and not turn_has_tool_calls
                                        and not turn_output.strip()
                                    ):
                                        session.status = "completed"
                                        session.session_end_reason = "task_complete"
                                        session.session_end_summary = (
                                            "rate-limit retry completed cleanly"
                                        )
                                    else:
                                        session.status = "max_turns_exceeded"
                                        session.session_end_reason = "budget_exhausted"
                                        session.session_end_summary = (
                                            f"reached max_turns="
                                            f"{self.max_turns} after "
                                            f"{turn_number} turns"
                                        )
                                        logger.info(
                                            "Agent run reached max_turns "
                                            "issue_id=%s turns=%s/%s tools=%s",
                                            issue.id,
                                            turn_number,
                                            self.max_turns,
                                            tool_count,
                                        )
                                elif session.status == "running":
                                    # F-54 root-cause fix: distinguish real
                                    # completions from "LLM gave up without
                                    # doing work".  When the session ends
                                    # but the agent never emitted a single
                                    # modifying tool call (Write/Edit), mark
                                    # as failed with reason "llm_gave_up"
                                    # so the orchestrator can retry rather
                                    # than treating it as a clean completion.
                                    # Guard: only enter if status is still "running"
                                    # to avoid overriding "failed"/"completed" set
                                    # by the tracker-is-None or no-work-streak paths.
                                    if getattr(session, "has_made_progress", False):
                                        # Verify actual workspace changes before marking completed.
                                        # has_made_progress=True only means Write/Edit was called,
                                        # not that files actually changed (e.g. Write same content,
                                        # Edit no-op, or changes were reverted).
                                        _ws_dirty = False
                                        _ws = getattr(session, "workspace", None)
                                        if _ws is not None:
                                            _ws_path = getattr(_ws, "path", None)
                                            if _ws_path is not None:
                                                try:
                                                    import subprocess as _subprocess

                                                    _proc = _subprocess.run(
                                                        ["git", "status", "--porcelain"],
                                                        cwd=str(_ws_path),
                                                        capture_output=True,
                                                        text=True,
                                                        timeout=10,
                                                    )
                                                    _ws_dirty = bool(_proc.stdout.strip())
                                                    if not _ws_dirty:
                                                        _start_sha = getattr(
                                                            session, "start_commit_sha", None
                                                        )
                                                        if _start_sha:
                                                            _head_proc = _subprocess.run(
                                                                ["git", "rev-parse", "HEAD"],
                                                                cwd=str(_ws_path),
                                                                capture_output=True,
                                                                text=True,
                                                                timeout=10,
                                                            )
                                                            _head = _head_proc.stdout.strip()
                                                            _ws_dirty = bool(
                                                                _head and _head != _start_sha
                                                            )
                                                except Exception:
                                                    _ws_dirty = True  # fail-open
                                        if _ws_dirty:
                                            session.status = "completed"
                                            if session.session_end_reason is None:
                                                session.session_end_reason = "task_complete"
                                                session.session_end_summary = (
                                                    "issue no longer active"
                                                )
                                        else:
                                            session.status = "failed"
                                            session.session_end_reason = "no_changes_produced"
                                            session.session_end_summary = (
                                                f"Agent called Write/Edit ({tool_count} tools) "
                                                f"but workspace has no file changes"
                                            )
                                            logger.warning(
                                                "Agent reported progress but produced no file changes "
                                                "issue_id=%s turns=%s tools=%s",
                                                issue.id,
                                                turn_number,
                                                tool_count,
                                            )
                                    else:
                                        # F-54 root-cause fix: before
                                        # declaring ``llm_gave_up``, run
                                        # the workflow's ``test_command``
                                        # to check if the work was already
                                        # implemented in a previous session.
                                        # If verification passes, treat
                                        # this as a clean completion.
                                        if await self._run_verification(session):
                                            session.status = "completed"
                                            session.session_end_reason = "already_completed"
                                            session.session_end_summary = (
                                                "work already implemented (verification passed)"
                                            )
                                            logger.info(
                                                "Issue %s: work already done "
                                                "(verification passed) — "
                                                "marking completed",
                                                issue.id,
                                            )
                                        else:
                                            session.status = "failed"
                                            session.session_end_reason = "llm_gave_up"
                                            session.session_end_summary = (
                                                f"LLM returned SessionComplete(success) "
                                                f"after {tool_count} read-only tool calls "
                                                f"with no code changes"
                                            )
                                            logger.warning(
                                                "LLM gave up without writing code "
                                                "issue_id=%s turns=%s tools=%s "
                                                "has_made_progress=False",
                                                issue.id,
                                                turn_number,
                                                tool_count,
                                            )
                                    logger.info(
                                        "Agent run completed issue_id=%s turns=%s/%s tools=%s",
                                        issue.id,
                                        turn_number,
                                        self.max_turns,
                                        tool_count,
                                    )
                            else:
                                session.status = "failed"
                                if session.session_end_reason is None:
                                    # F-40: capture a per-reason end reason
                                    # so downstream sinks can distinguish
                                    # ``exit_code=N`` style failures from
                                    # clean termination paths.
                                    session.session_end_reason = f"exit_code={event.reason}"
                                    session.session_end_summary = (
                                        f"QueryRunner ended with reason={event.reason}"
                                    )
                                logger.warning(
                                    "Agent run failed issue_id=%s reason=%s",
                                    issue.id,
                                    event.reason,
                                )
                            # F-40: terminal SessionComplete is the only
                            # event the F-38 design never dispatched. The
                            # reason we record on the wire is
                            # ``session_end_reason`` (set by the success /
                            # noop / max_turns / failure paths above) so
                            # the dashboard sees a uniform
                            # ``session_{reason}`` stage.
                            if sink is not None:
                                self._dispatch_sink(
                                    sink,
                                    "on_session_complete",
                                    SessionComplete(
                                        reason=session.session_end_reason or event.reason
                                    ),
                                    session,
                                )
                            # F-49 Phase 0.1: final flush before returning.
                            # Helper handles empty buffers idempotently.
                            if session._transcript_storage is not None:
                                try:
                                    self._flush_turn_transcript(session)
                                    session._transcript_storage.flush()
                                except Exception:
                                    logger.exception(
                                        "Failed to final-flush transcript run_id=%s",
                                        session.run_id,
                                    )
                            # F-49 Phase 1: stop the control socket on the
                            # terminal SessionComplete path.
                            if session.control_socket is not None:
                                try:
                                    await session.control_socket.stop()
                                except Exception:
                                    logger.exception(
                                        "Failed to stop control_socket run_id=%s",
                                        session.run_id,
                                    )
                                session.control_socket = None
                            return
                except RateLimitError as exc:
                    # Typed fallback: if the headless runner ever propagates
                    # a RateLimitError directly (e.g. via ``await future``
                    # at extensions/api/query.py:173), treat it the same as
                    # a 429 detected in the text stream.
                    if is_rate_limit_error(exc):
                        # Synthesize a minimal turn_output so the standard
                        # detection helper recognizes the case.
                        synthetic_output = turn_output or (f"Error code: 429 - {exc!s}")
                        new_status = await self._handle_rate_limit(
                            session,
                            synthetic_output,
                            turn_number,
                            status_dashboard,
                        )
                        if new_status == "rate_limit_circuit_open":
                            return
                        # F-49 Phase 0.1: reset per-turn transcript buffers.
                        self._flush_turn_transcript(session)
                        turn_output = ""
                        turn_has_tool_calls = False
                        continue
                    # Not a 429 — re-raise to preserve existing behavior.
                    raise

                # F-?? root-cause fix: when the per-turn tool cap fires we
                # break out of the QueryRunner stream above.  Without this
                # block the outer loop would re-issue the *same* turn (turn
                # number not incremented), resetting ``turn_tool_count`` and
                # allowing another 30 tools in an infinite spiral.  Treat the
                # cap as a forced turn boundary: bump the counter, flush the
                # transcript, tear down the per-turn control socket, and move
                # on so the agent receives a continuation prompt.
                if cap_reached:
                    turn_number += 1
                    session.turn_count = turn_number
                    if session._transcript_storage is not None:
                        try:
                            self._flush_turn_transcript(session)
                            session._transcript_storage.flush()
                        except Exception:
                            logger.exception(
                                "Failed to flush transcript after cap break run_id=%s",
                                session.run_id,
                            )
                    if session.control_socket is not None:
                        try:
                            await session.control_socket.stop()
                        except Exception:
                            logger.exception(
                                "Failed to stop control_socket after cap break run_id=%s",
                                session.run_id,
                            )
                        session.control_socket = None
                    append_debug_event(
                        session.debug_log_path,
                        "agent_runner.turn_complete",
                        issue_id=issue.id,
                        run_id=session.run_id,
                        turn=turn_number,
                        reason="max_tools_per_turn",
                        tool_count=tool_count,
                        output_len=len(session.output_text),
                    )
                    continue

                # If we consumed all events without SessionComplete (shouldn't
                # happen with current QueryRunner, but be defensive), count the
                # turn anyway
                if not turn_has_tool_calls and turn_output:
                    turn_number += 1
                    session.turn_count = turn_number

            # Reached max_turns
            session.status = "max_turns_exceeded"
            session.session_end_reason = "budget_exhausted"
            session.session_end_summary = (
                f"reached max_turns={self.max_turns} after {turn_number} turns"
            )
            logger.info(
                "Agent run reached max_turns issue_id=%s turns=%s/%s tools=%s",
                issue.id,
                turn_number,
                self.max_turns,
                tool_count,
            )

            # Emit PhaseComplete event for progress reporting (max_turns path)
            phase_event = PhaseComplete(
                phase=turn_number,
                turn_count=turn_number,
            )
            if sink is not None:
                # F-40: max_turns path now dispatches BOTH PhaseComplete
                # (so the trailing phase is recorded with its progress)
                # AND SessionComplete(reason="budget_exhausted") so
                # downstream consumers always see a terminal event. The
                # ``on_session_complete`` call uses the runner's
                # ``session_end_reason`` (set above) as the wire reason.
                self._dispatch_sink(sink, "on_phase_complete", phase_event, session)
                self._dispatch_sink(
                    sink,
                    "on_turn_complete",
                    TurnComplete(turn=turn_number),
                    session,
                )
                self._dispatch_sink(
                    sink,
                    "on_session_complete",
                    SessionComplete(reason=session.session_end_reason or "budget_exhausted"),
                    session,
                )

            session.tool_count = tool_count
            # F-49 Phase 0.1: final flush before max_turns exit.
            # Helper handles empty buffers idempotently; covers the
            # "Late TextDelta flow interruption" case from the spec.
            if session._transcript_storage is not None:
                try:
                    self._flush_turn_transcript(session)
                    session._transcript_storage.flush()
                except Exception:
                    logger.exception(
                        "Failed to final-flush transcript run_id=%s",
                        session.run_id,
                    )
            # F-49 Phase 1: stop the control socket on max_turns exit.
            if session.control_socket is not None:
                try:
                    await session.control_socket.stop()
                except Exception:
                    logger.exception(
                        "Failed to stop control_socket run_id=%s",
                        session.run_id,
                    )
                session.control_socket = None
            append_debug_event(
                session.debug_log_path,
                "agent_runner.max_turns_exceeded",
                issue_id=issue.id,
                run_id=session.run_id,
                turn_count=session.turn_count,
                tool_count=session.tool_count,
                output_len=len(session.output_text),
                last_event_type=session.last_agent_event,
                last_tool=session.last_tool_name,
            )
        finally:
            # Clear MDC context so stale issue_id/run_id don't leak
            # into subsequent runs on the same thread.
            from .logging_setup import clear_log_context

            clear_log_context()
            # F-49 Phase 0.4.5: write .json snapshot on every exit path
            # (normal, early return, exception).  Best-effort; errors
            # are logged inside _save_json_snapshot().
            session._save_json_snapshot()
            # Visualizer bridge: the F-45 tool-event audit log lives in
            # ``{workspace}/.reports/{run_id}.events.ndjson`` but the
            # Multi-Session Visualizer looks for
            # ``~/.clawcodex/sessions/{run_id}/events.ndjson``. Mirror it on
            # every exit path (incl. timeout) so orchestrator runs render a
            # timeline instead of an empty session. Best-effort.
            self._export_events_for_viz(session)

    def _export_events_for_viz(self, session: AgentSession) -> None:
        """Mirror run artifacts the visualizer needs into the session dir.

        Two identity gaps keep orchestrator runs invisible in the viz:

        * The F-45 tool-event audit log lives in the workspace
          ``.reports/`` dir but ``SessionMetadataParser`` only scans
          ``~/.clawcodex/sessions/<run_id>/events.ndjson``.
        * Worker (sub-agent) transcripts nest under the HEADLESS session's
          internal uuid (``sessions/<uuid>/subagents/agent-*.jsonl``) —
          the nested resolver keys on the process-global session id, not
          the orchestrator ``run_id`` — so ``MultiAgentParser`` finds no
          sub-agent lanes for the run.

        Mirror both on every exit path (incl. timeout). Failures are
        logged and swallowed — the mirror must never affect run outcome.
        """
        try:
            run_id = session.run_id
            workspace = getattr(session, "workspace", None)
            workspace_path = getattr(workspace, "path", None)
            if not run_id or not workspace_path:
                return
            import shutil

            dst_dir = Path.home() / ".clawcodex" / "sessions" / str(run_id)
            dst_dir.mkdir(parents=True, exist_ok=True)

            src = Path(workspace_path) / ".reports" / f"{run_id}.events.ndjson"
            if src.is_file():
                shutil.copyfile(src, dst_dir / "events.ndjson")

            # Spawn-attribution records written by the Agent tool at each
            # spawn moment ({ts, agent_id, description}) — the visualizer
            # joins these onto Agent spawn bars for exact bar↔lane
            # attribution.
            spawns_src = Path(workspace_path) / ".reports" / "agent_spawns.ndjson"
            if spawns_src.is_file():
                shutil.copyfile(spawns_src, dst_dir / "agent_spawns.ndjson")

            # Worker transcript mirror. The headless run installed its
            # session id in the process-global bootstrap state; with the
            # per-issue concurrency the daemon uses this is the session
            # the workers nested under. Concurrent multi-issue daemons
            # may cross-attribute workers here — acceptable for a
            # best-effort viz bridge (files are additive and readers
            # match lanes by agent id).
            headless_sid = ""
            try:
                from src.bootstrap.state import get_session_id

                headless_sid = str(get_session_id() or "")
            except Exception:
                headless_sid = ""
            if headless_sid and headless_sid != str(run_id):
                sub_src = Path.home() / ".clawcodex" / "sessions" / headless_sid / "subagents"
                if sub_src.is_dir():
                    sub_dst = dst_dir / "subagents"
                    sub_dst.mkdir(parents=True, exist_ok=True)
                    for worker_file in sub_src.glob("agent-*.jsonl"):
                        shutil.copyfile(worker_file, sub_dst / worker_file.name)
        except Exception:
            logger.exception("viz events mirror failed run_id=%s", getattr(session, "run_id", None))

    def _build_run_id(self, session: AgentSession) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        attempt = getattr(session, "attempt", 1)
        if session.run_kind == "review_followup":
            issue_attempt = getattr(session, "issue_attempt", attempt)
            followup_attempt = getattr(session, "followup_attempt", 1)
            return f"run-{issue_attempt}-followup-{followup_attempt}-{timestamp}"
        return f"run-{attempt:02d}-{timestamp}"

    async def _post_summary_placeholder(
        self,
        session: AgentSession,
        comment_tracker: Any,
    ) -> None:
        body = "## ClawCodex Run Summary\n\n⏳ Run in progress."
        try:
            created = await comment_tracker.create_comment(session.issue.id, body)
        except Exception as exc:
            logger.warning(
                "Failed to post summary placeholder issue_id=%s: %s",
                session.issue.id,
                exc,
            )
            return
        if created is not None and getattr(created, "id", None):
            session.summary_comment_id = created.id

    async def _should_continue(
        self,
        issue: Issue,
        tracker: Any,
        session: AgentSession | None = None,
    ) -> tuple[bool, Issue]:
        """Check if the issue is still in an active state.

        F-54 root-cause fix: even when the tracker reports the issue
        as active, return False (stop) if the workspace already has
        uncommitted or committed changes that satisfy the issue, so
        the agent does not keep spinning in continuation loops after
        completing its work.

        F-105 perf optimisation: when a per-session ``IssueStateCache``
        is attached to ``session.state_cache`` and the issue state has
        been identical across ``N`` consecutive polls, skip the tracker
        HTTP call and return the cached active state. See
        ``extensions/orchestrator/issue_state_cache.py`` for the skip
        policy.
        """
        if not issue.id:
            return False, issue

        # F-105: cache lookup before the tracker round-trip. Forced-poll
        # conditions mirror the spec: never skip on the first turn, never
        # skip when the most recent snapshot reported inactive, and never
        # skip while a user-interrupt flag is set on the session.
        cache = getattr(session, "state_cache", None) if session is not None else None
        if cache is not None:
            turn = int(getattr(session, "turn_count", 0) or 0)
            user_interrupted = bool(getattr(session, "user_interrupted", False))
            recent_inactive = cache.has_recent_inactive(issue.id, turn - 1)
            if (
                turn > 0
                and not user_interrupted
                and not recent_inactive
                and cache.should_skip_poll(issue.id, turn)
            ):
                logger.debug(
                    "F-105 skip tracker poll issue=%s turn=%d cache=%s",
                    issue.id,
                    turn,
                    cache.stats(),
                )
                return True, issue

        refreshed = await tracker.fetch_issue_states_by_ids([issue.id])
        refreshed_issue = refreshed.get(issue.id)
        if refreshed_issue is None:
            return False, issue

        active_states = [s.strip().lower() for s in (getattr(tracker, "active_states", None) or [])]
        is_active = (
            refreshed_issue.state is not None
            and refreshed_issue.state.strip().lower() in active_states
        )

        # F-105: record the freshly-fetched snapshot so future calls can
        # skip the HTTP round-trip. Only record active results; an
        # inactive snapshot will force a re-poll on the next call via
        # ``has_recent_inactive``.
        if cache is not None and is_active and session is not None:
            cache.record(
                issue_id=issue.id,
                is_active=is_active,
                state=getattr(refreshed_issue, "state", None),
                observed_at_turn=int(getattr(session, "turn_count", 0) or 0),
            )

        if not is_active:
            return False, refreshed_issue

        # F-54 root-cause fix: if the tracker still says active but
        # the workspace already has real user-visible changes, trust the
        # agent's completion signal and stop the continuation loop. The
        # workspace changes will be committed by git_sync after the session
        # ends. This cannot rely only on ``session.has_made_progress``:
        # in coordinator mode the main session emits Agent/TaskStop while
        # the worker performs the Edit/Write call in the same workspace.
        #
        # Without this check, the agent enters an infinite loop:
        # LLM says "done" → tracker says "open" → another turn → repeat.
        if session is not None and getattr(session, "turn_count", 0) > 0:
            ws = getattr(session, "workspace", None)
            if ws is not None:
                ws_path = getattr(ws, "path", None)
                if ws_path is not None:
                    try:
                        _env = self._build_subprocess_env()
                        status_entries = await asyncio.to_thread(
                            get_file_status,
                            str(ws_path),
                        )
                        has_uncommitted = bool(status_entries)
                        has_user_uncommitted = _has_user_visible_status_changes(
                            status_entries,
                        )
                        head_changed = False
                        start_commit_sha = getattr(session, "start_commit_sha", None)
                        if start_commit_sha:
                            head_proc = await asyncio.to_thread(
                                self._git_capture,
                                ["git", "rev-parse", "HEAD"],
                                str(ws_path),
                                _env,
                            )
                            current_head = head_proc.stdout.strip()
                            head_changed = bool(current_head and current_head != start_commit_sha)

                        if (
                            head_changed
                            or has_user_uncommitted
                            or session.status in ("completed", "task_complete")
                        ):
                            if head_changed or has_user_uncommitted:
                                session.has_made_progress = True
                            logger.info(
                                "Issue %s work appears done in workspace "
                                "(turn_count=%d, head_changed=%s, "
                                "has_uncommitted=%s, has_user_uncommitted=%s) — "
                                "stopping continuation loop",
                                issue.id,
                                session.turn_count,
                                head_changed,
                                has_uncommitted,
                                has_user_uncommitted,
                            )
                            return False, refreshed_issue
                    except Exception:
                        pass  # Fail-open: allow continue if git check fails

        # F-54 root-cause fix: detect "fake progress" — the agent made
        # read-only tool calls and empty commits but never wrote a
        # single line of code.  When ``has_made_progress`` is False
        # AND the session has consumed multiple turns with only
        # read-only tools, stop the continuation loop so the session
        # terminates and the ``llm_gave_up`` check fires.
        tool_count = getattr(session, "tool_count", 0)
        if (
            not getattr(session, "has_made_progress", False)
            and getattr(session, "turn_count", 0) >= 2
            and tool_count > 0
        ):
            ws = getattr(session, "workspace", None)
            if ws is not None:
                ws_path = getattr(ws, "path", None)
                if ws_path is not None:
                    try:
                        # Check if recent commits have actual file
                        # changes.  If the agent made 3+ commits but
                        # ``git diff --stat`` shows nothing changed,
                        # all commits were ``--allow-empty`` — the
                        # agent is faking progress.
                        proc = await asyncio.to_thread(
                            self._git_capture,
                            ["git", "diff", "--stat", "HEAD~3..HEAD"],
                            str(ws_path),
                            self._build_subprocess_env(),
                        )
                        if proc.returncode != 0:
                            return True, refreshed_issue
                        diff_empty = not proc.stdout.strip()
                        if diff_empty:
                            logger.info(
                                "Issue %s: all recent commits are empty "
                                "(%d turns, %d tools, has_made_progress=%s) — "
                                "stopping fake-progress loop",
                                issue.id,
                                getattr(session, "turn_count", 0),
                                tool_count,
                                getattr(session, "has_made_progress", False),
                            )
                            return False, refreshed_issue
                    except Exception:
                        pass  # Fail-open

        return is_active, refreshed_issue

    def _build_subprocess_env(self) -> dict[str, str] | None:
        """Build env dict by merging workflow-configured env over daemon env.

        Returns None when no custom env is configured so callers inherit
        the parent's environment unchanged (avoids unnecessary copies).
        """
        custom_env = getattr(self.agent_config, "env", None)
        if not custom_env:
            return None
        base = os.environ.copy()
        for key, value in custom_env.items():
            if key == "PATH" and value:
                base["PATH"] = value.replace("$PATH", base.get("PATH", ""))
            else:
                base[key] = value
        return base

    @staticmethod
    def _git_capture(
        args: list[str],
        cwd: str,
        env: dict[str, str] | None,
    ) -> "subprocess.CompletedProcess[str]":
        """Run a git command capturing output (synchronous, off event loop).

        Invoked via ``asyncio.to_thread`` from async callers so the
        up-to-10s subprocess never blocks the orchestrator event loop.
        """
        return subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )

    async def _run_verification(self, session: AgentSession) -> bool:
        """Run ``agent.test_command`` in the workspace to verify the
        issue deliverables are correctly implemented.

        Returns ``True`` when the command succeeds (exit code 0) or
        when no test command is configured.  ``False`` on failure.

        F-54 root-cause fix: before marking a session as
        ``llm_gave_up``, run this check.  If the test command passes,
        the work was already done in a previous session and the
        current session is correctly detecting completion — not
        "giving up".
        """
        import asyncio

        test_cmd = getattr(self.agent_config, "test_command", None)
        if not test_cmd:
            return True  # No test command = skip verification

        ws = getattr(session, "workspace", None)
        ws_path = getattr(ws, "path", None) if ws else None
        if not ws_path:
            return False

        timeout_ms = getattr(
            getattr(self.agent_config, "verification", None),
            "timeout_ms",
            600_000,
        )
        try:
            _env = self._build_subprocess_env()
            proc = await asyncio.create_subprocess_shell(
                test_cmd,
                cwd=str(ws_path),
                preexec_fn=_set_pdeathsig,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_env,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_ms / 1000.0,
            )
            if proc.returncode == 0:
                logger.info(
                    "Verification passed for issue_id=%s — work is already implemented",
                    session.issue.id,
                )
                return True
            logger.info(
                "Verification failed for issue_id=%s (exit=%d) — work not yet done",
                session.issue.id,
                proc.returncode,
            )
            return False
        except asyncio.TimeoutError:
            logger.warning(
                "Verification timed out for issue_id=%s",
                session.issue.id,
            )
            return False
        except Exception as exc:
            logger.warning(
                "Verification error for issue_id=%s: %s",
                session.issue.id,
                exc,
            )
            return False
