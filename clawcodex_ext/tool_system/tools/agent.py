"""Agent tool — launches subagents with context isolation.

Mirrors typescript/src/tools/AgentTool/AgentTool.tsx.

Supports three modes:
1. **Sync child** — Parent waits for the agent to finish and returns the result.
2. **Async background** — Agent runs independently; parent gets an agent_id back
   immediately and can later query results via SendMessage.
3. **Fork** — Inherits parent context for prompt cache sharing (future).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from typing import Any
from uuid import uuid4

from ..build_tool import Tool, build_tool
from ..context import ToolContext
from ..errors import ToolInputError
from ..protocol import ToolResult
from ..registry import ToolRegistry

from clawcodex_ext.agent.agent_definitions import (
    AgentDefinition,
    FORK_AGENT,
    find_agent_by_type,
    get_built_in_agents,
)
from src.agent.filter_agents_by_mcp import filter_agents_by_mcp_requirements
from src.agent.load_agents_dir import get_agent_definitions_with_overrides
from src.agent.agent_tool_utils import (
    extract_partial_result,
    finalize_agent_tool,
)
from clawcodex_ext.agent.constants import (
    AGENT_TOOL_NAME,
    FORK_SUBAGENT_TYPE,
    LEGACY_AGENT_TOOL_NAME,
    ONE_SHOT_BUILTIN_AGENT_TYPES,
)
from clawcodex_ext.agent.fork_subagent import (
    build_forked_messages,
    build_worktree_notice,
    is_fork_subagent_enabled,
    is_in_fork_child,
)
from src.agent.prompt import get_agent_prompt, get_agent_system_prompt
from clawcodex_ext.agent.run_agent import RunAgentParams, run_agent

logger = logging.getLogger(__name__)


# F-88 P88-D: helper to persist Explore / Plan reports to disk after the
# one-shot agent completes. Best-effort: any I/O error is logged and
# swallowed so the user's in-session output is never disrupted by a
# report-store failure.
def _persist_agent_report(
    *,
    subagent_type: str,
    agent_id: str,
    session_id: str,
    transcript: str,
) -> None:
    """Parse ``transcript`` into a typed report and write it to disk.

    No-ops for subagent_types other than ``Explore`` / ``Plan``.
    """
    if subagent_type not in ONE_SHOT_BUILTIN_AGENT_TYPES:
        return
    try:
        from src.agent.report_store import (
            ExploreReport,
            PlanDocument,
            ReportStore,
            now_iso_utc,
        )
    except Exception:  # noqa: BLE001 — best-effort
        logger.exception("agent report import failed; skipping persist for %s", agent_id)
        return
    try:
        store = ReportStore()
        if subagent_type == "Explore":
            from src.agent.report_store import parse_critical_files

            title, summary, findings = _parse_explore_transcript(transcript)
            report = ExploreReport(
                agent_id=agent_id,
                session_id=session_id,
                title=title,
                summary=summary,
                findings=findings,
                critical_files=parse_critical_files(transcript),
                raw_markdown=transcript,
                created_at=now_iso_utc(),
            )
            store.save_explore(report)
        elif subagent_type == "Plan":
            from src.agent.report_store import parse_critical_files

            title, summary, steps = _parse_plan_transcript(transcript)
            plan = PlanDocument(
                agent_id=agent_id,
                session_id=session_id,
                title=title,
                summary=summary,
                steps=steps,
                critical_files=parse_critical_files(transcript),
                raw_markdown=transcript,
                created_at=now_iso_utc(),
            )
            store.save_plan(plan)
    except Exception:  # noqa: BLE001 — best-effort
        logger.warning("agent report persist failed for %s", agent_id, exc_info=True)


def _parse_explore_transcript(
    transcript: str,
) -> tuple[str, str, tuple[str, ...]]:
    """Best-effort: pull (title, summary, findings) from an Explore
    agent's final transcript. Anything we cannot parse returns empty
    values; never raises.
    """
    if not transcript:
        return ("Explore Report", "", ())
    title = "Explore Report"
    summary = ""
    findings: list[str] = []
    lines = transcript.splitlines()
    for line in lines:
        stripped = line.strip()
        if not title or title == "Explore Report":
            if stripped.startswith("# "):
                title = stripped[2:].strip() or "Explore Report"
                continue
        if not summary and stripped and not stripped.startswith("#"):
            summary = stripped
            continue
        bullet = stripped
        if bullet.startswith(("- ", "* ")):
            item = bullet[2:].strip()
            if item:
                findings.append(item)
    return (title, summary, tuple(findings))


def _parse_plan_transcript(
    transcript: str,
) -> tuple[str, str, tuple[str, ...]]:
    """Best-effort: pull (title, summary, steps) from a Plan agent's
    final transcript. Numbered list items become steps; bullet items
    fall through to the summary's body if no numbered list is found.
    """
    if not transcript:
        return ("Implementation Plan", "", ())
    title = "Implementation Plan"
    summary = ""
    steps: list[str] = []
    lines = transcript.splitlines()
    saw_numbered = False
    for line in lines:
        stripped = line.strip()
        if title == "Implementation Plan" and stripped.startswith("# "):
            title = stripped[2:].strip() or "Implementation Plan"
            continue
        if not summary and stripped and not stripped.startswith("#"):
            summary = stripped
            continue
        # Numbered step: "1. foo" / "1) foo" / "1: foo"
        if stripped and stripped[0].isdigit():
            for sep in (". ", ") ", ": "):
                if sep in stripped:
                    num, _, rest = stripped.partition(sep)
                    if num.rstrip(".)").isdigit() and rest:
                        steps.append(rest.strip())
                        saw_numbered = True
                        break
    if not saw_numbered:
        # Fallback: no numbered list — collect bullets as steps.
        steps = [
            stripped[2:].strip()
            for stripped in (l.strip() for l in lines)
            if stripped.startswith(("- ", "* ")) and stripped[2:].strip()
        ]
    return (title, summary, tuple(steps))


# Input schema matching typescript/src/tools/AgentTool/AgentTool.tsx
AGENT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "description": {
            "type": "string",
            "description": "A short (3-5 word) description of the task",
        },
        "prompt": {
            "type": "string",
            "description": "The task for the agent to perform",
        },
        "subagent_type": {
            "type": "string",
            "description": "The type of specialized agent to use for this task",
        },
        "model": {
            "type": "string",
            "description": (
                "Optional model override for this agent. Takes precedence over "
                "the agent definition's model frontmatter. If omitted, uses the "
                "agent definition's model, or inherits from the parent."
            ),
            "enum": ["sonnet", "opus", "haiku"],
        },
        "run_in_background": {
            "type": "boolean",
            "description": (
                "Set to true to run this agent in the background. "
                "You will be notified when it completes."
            ),
        },
        "isolation": {
            "type": "string",
            "description": (
                'Isolation mode. "worktree" creates a temporary git worktree '
                "so the agent works on an isolated copy of the repo."
            ),
            "enum": ["worktree"],
        },
        # Chapter-10 / Chunk F / WI-6.1: optional human-readable name.
        # When set, the spawned agent is reachable via
        # ``SendMessage({to: name})`` instead of the raw agent_id.
        # Mirrors TS AgentTool's ``name`` parameter; the registry
        # collision policy is enforced inside ``_launch_async_agent``.
        "name": {
            "type": "string",
            "description": (
                "Optional name for the spawned agent. Makes it addressable via "
                "SendMessage({to: name}) while running. Errors if the name is "
                "already in use by a running agent; overwrites a terminal one."
            ),
        },
    },
    "required": ["prompt"],
}


def make_agent_tool(
    registry: ToolRegistry,
    provider: Any | None = None,
    get_available_mcp_servers: Any | None = None,
) -> Tool:
    """Build the Agent tool.

    Mirrors the AgentTool definition from typescript/src/tools/AgentTool/AgentTool.tsx.

    Args:
        registry: Tool registry providing the available tool pool.
        provider: BaseProvider for API calls. If None, agent execution is a no-op
                  (useful for testing tool registration only).
        get_available_mcp_servers: Optional zero-arg callable returning the
            currently-available MCP server names. Used by the prompt builder so
            agents declaring ``required_mcp_servers`` not present in the live
            inventory are hidden from the tool description (matching the
            per-call resolver). When ``None`` the prompt advertises every
            discovered agent unfiltered.
    """

    def _get_agent_definitions(context: ToolContext) -> list[AgentDefinition]:
        """Resolve agents visible to this call.

        SDK / test callers can pre-populate ``options.agent_definitions
        ["active_agents"]`` to override discovery. Otherwise, in coordinator
        mode (``CLAUDE_CODE_COORDINATOR_MODE=true``), inject WORKER_AGENT
        so the coordinator system prompt's ``subagent_type: "worker"`` calls
        resolve. Falls through to filesystem-based discovery.
        """
        agent_defs = getattr(context.options, "agent_definitions", None)
        if agent_defs and isinstance(agent_defs, dict):
            active = agent_defs.get("active_agents")
            if active and isinstance(active, list):
                return active
        # Coordinator mode: inject WORKER_AGENT so
        # ``subagent_type: "worker"`` resolves correctly.
        from src.coordinator.mode import is_coordinator_mode

        if is_coordinator_mode():
            from src.coordinator.worker_agent import get_coordinator_agents

            return get_coordinator_agents()
        cwd = str(context.cwd or context.workspace_root)
        agents = get_agent_definitions_with_overrides(cwd)
        # Also load agents from the custom agent directory override
        # (set by ``--agent <dir>``).  The override directory has
        # higher priority: its agents *replace* project-root agents
        # with the same ``agent_type`` rather than being skipped.
        ad_override = getattr(context, "_agent_dir_override", None)
        if ad_override is not None:
            extra = get_agent_definitions_with_overrides(str(ad_override))
            extra_types = {a.agent_type for a in extra}
            # Remove project-root agents that are shadowed by the
            # bundle directory, then append the bundle's versions.
            agents = [a for a in agents if a.agent_type not in extra_types]
            agents.extend(extra)
        available_mcp = list(context.mcp_clients.keys()) if context.mcp_clients else []
        agents = filter_agents_by_mcp_requirements(agents, available_mcp)
        try:
            from extensions.sop_converter.sop_routing import refresh_domain_agent_sop_prompts

            agents = refresh_domain_agent_sop_prompts(agents)
        except ImportError:
            pass
        return agents

    def _agent_call(tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        prompt = tool_input.get("prompt", "")
        if not prompt:
            raise ToolInputError("prompt is required")

        description = tool_input.get("description", prompt[:50])
        subagent_type = tool_input.get("subagent_type")
        model = tool_input.get("model")
        run_in_background = bool(tool_input.get("run_in_background", False))
        # Chapter-10 / WI-6.1 — optional human-readable name. We
        # validate / register it AFTER agent_id is generated so the
        # collision-on-running check can compare against the registry
        # state under the registry's own atomicity guarantees.
        agent_name = tool_input.get("name")
        if agent_name is not None and not isinstance(agent_name, str):
            raise ToolInputError("name must be a string when provided")
        if isinstance(agent_name, str) and not agent_name.strip():
            agent_name = None  # treat empty/whitespace as absent

        # Resolve agent definition.
        #
        # Routing rules mirror typescript/src/tools/AgentTool/AgentTool.tsx:318-356:
        # - subagent_type provided → use it (explicit wins).
        # - subagent_type omitted, fork gate on → implicit fork via FORK_AGENT.
        # - subagent_type omitted, fork gate off → default to general-purpose.
        #
        # F-88 P88-C: BEFORE the explicit-type check, run a phrase-based
        # classifier over the prompt. If the classifier picks Explore /
        # Plan and those are available, we fill in the missing
        # ``subagent_type`` so the existing dispatch (below) selects the
        # right one-shot agent. Explicit ``subagent_type`` from the model
        # still wins because we only inject when it's absent.
        if not subagent_type:
            try:
                from src.agent.routing import (
                    GENERAL_PURPOSE_FALLBACK,
                    classify_prompt_to_subagent_type,
                )

                available_types = {a.agent_type for a in get_built_in_agents()} | {
                    GENERAL_PURPOSE_FALLBACK
                }
                routed = classify_prompt_to_subagent_type(prompt, available=available_types)
                if routed != GENERAL_PURPOSE_FALLBACK:
                    subagent_type = routed
            except Exception:  # noqa: BLE001 — routing is best-effort
                logger.exception("agent prompt routing failed; falling through to default dispatch")

        agent_definitions = _get_agent_definitions(context)

        try:
            from extensions.sop_converter.sop_routing import check_bundle_agent_delegation

            delegation_error = check_bundle_agent_delegation(
                subagent_type=subagent_type,
                prompt=prompt,
                agent_definitions=agent_definitions,
            )
            if delegation_error:
                raise ToolInputError(delegation_error)
        except ImportError:
            pass

        is_fork_path = subagent_type is None and is_fork_subagent_enabled(context)

        if is_fork_path:
            # Recursive-fork guard. Primary check: querySource on the parent's
            # options. Secondary check: scan parent messages for the fork
            # boilerplate tag. Either one trips means we are already inside a
            # fork child, so refuse to spawn another.
            parent_query_source = getattr(context.options, "query_source", None)
            if parent_query_source == f"agent:builtin:{FORK_SUBAGENT_TYPE}" or is_in_fork_child(
                context.messages
            ):
                raise ToolInputError(
                    "Fork is not available inside a forked worker. "
                    "Complete your task directly using your tools."
                )
            agent_def = FORK_AGENT
        elif subagent_type:
            agent_def = find_agent_by_type(agent_definitions, subagent_type)
            if agent_def is None:
                available = [a.agent_type for a in agent_definitions]
                raise ToolInputError(
                    f"Unknown subagent_type: {subagent_type}. Available: {', '.join(available)}"
                )
        else:
            # Default to general-purpose
            agent_def = (
                find_agent_by_type(agent_definitions, "general-purpose") or agent_definitions[0]
                if agent_definitions
                else None
            )
            if agent_def is None:
                raise ToolInputError("No agent definitions available")

        # Resolve available tools. ``registry`` is a closure variable from
        # ``make_agent_tool`` — NEVER assign to that name inside this
        # function (an assignment anywhere in the body makes it local for
        # the WHOLE function and this read raises UnboundLocalError before
        # any conditional runs). The coordinator branch below therefore
        # rebinds ``effective_registry`` instead.
        effective_registry = registry
        available_tools = effective_registry.list_tools()

        # MVP multi-agent fix: when the parent is in coordinator mode, the
        # parent's tool registry has been filtered to the coordinator's
        # restricted set. Sub-agents (workers) need the FULL tool set minus
        # INTERNAL_WORKER_TOOLS (TeamCreate/SendMessage/etc.). Build a
        # SEPARATE registry for the sub-agent so the parent's registry is
        # NOT corrupted after the sub-agent returns.
        try:
            from clawcodex_ext.coordinator.mode import (
                is_coordinator_mode,
                filter_worker_tools,
            )
            if is_coordinator_mode():
                from src.tool_system.defaults import build_default_registry
                from src.tool_system.registry import ToolRegistry
                full_registry = build_default_registry(provider=provider)
                worker_tools = filter_worker_tools(full_registry.list_tools())
                available_tools = worker_tools
                # Build a FRESH ToolRegistry for the sub-agent — do NOT
                # mutate the parent's registry.
                sub_registry = ToolRegistry()
                for t in worker_tools:
                    try:
                        sub_registry.register(t)
                    except Exception:
                        # Skip duplicates / unregisterable tools gracefully.
                        pass
                # Hand the sub-agent the fresh registry; the parent keeps
                # its own restricted ``registry`` untouched.
                effective_registry = sub_registry
                import logging as _log
                _log.getLogger(__name__).info(
                    "MVP: sub-agent receives FRESH worker registry (%d tools)",
                    len(worker_tools),
                )
        except Exception as _exc:
            import logging as _log
            _log.getLogger(__name__).warning(
                "MVP worker tool restore failed (continuing with parent set): %s",
                _exc,
            )

        # Chapter-10 / WI-1.5: prefixed task id (``a<8 base36 chars>``)
        # mirroring TS Task.ts:79-105. Replaces the legacy 32-char
        # ``uuid4().hex`` so SendMessage / TaskStop dispatch keys are
        # uniform across types.
        from clawcodex_ext.tasks_core import generate_task_id  # local import — see _launch_async_agent

        agent_id = generate_task_id("local_agent")
        start_time = time.time()
        is_async = run_in_background

        # Spawn-attribution record: the Agent tool is the ONLY place that
        # knows both the child's ``agent_id`` and the ``description`` at
        # the spawn moment. Persist the mapping so the visualizer can
        # attach each spawn bar to its exact sub-agent lane (the F-45
        # call row cannot carry the id — it's minted here, after the
        # event is emitted — and the result event only carries rendered
        # text). Best-effort; never affects the spawn.
        try:
            import json as _json
            from pathlib import Path as _Path

            workspace_root = getattr(context, "workspace_root", None)
            if workspace_root:
                _reports = _Path(workspace_root) / ".reports"
                _reports.mkdir(parents=True, exist_ok=True)
                with open(
                    _reports / "agent_spawns.ndjson", "a", encoding="utf-8"
                ) as _f:
                    _f.write(
                        _json.dumps(
                            {
                                "ts": start_time,
                                "agent_id": agent_id,
                                "description": description or "",
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
        except Exception:
            pass

        if provider is None:
            return ToolResult(
                name=AGENT_TOOL_NAME,
                output={
                    "status": "error",
                    "error": "No provider configured — agent execution unavailable.",
                },
                is_error=True,
            )

        # Fork-specific run-agent inputs.
        #
        # On the fork path:
        #   * The child inherits the parent's full conversation as
        #     ``context_messages`` so the API-request prefix matches the
        #     parent's most recent turn.
        #   * ``build_forked_messages()`` produces the trailing pair: a
        #     cloned parent assistant message plus a single user message
        #     carrying placeholder tool_results and the boilerplate-wrapped
        #     directive. This pair is passed as a single concatenated
        #     ``prompt`` (run_agent appends a UserMessage built from
        #     ``params.prompt``); to preserve the cloned-assistant block we
        #     instead route the messages via ``context_messages`` and pass
        #     the directive bytes alone as ``params.prompt``.
        #   * ``use_exact_tools`` skips ``resolve_agent_tools()`` so the
        #     child's tool array is byte-identical to the parent's.
        #   * ``query_source`` is threaded onto the child's options for the
        #     primary recursive-fork guard at the next call site.
        #   * ``parent_system_prompt`` carries the parent's resolved prompt
        #     so the fork agent's empty get_system_prompt is filled in via
        #     ``get_agent_system_prompt()``.
        fork_context_messages: list[Any] | None = None
        fork_query_source: str | None = None
        fork_use_exact_tools = False
        fork_parent_system_prompt: str | None = None
        fork_prompt = prompt

        if is_fork_path:
            from clawcodex_ext.types.messages import AssistantMessage, create_user_message

            parent_assistant: AssistantMessage | None = None
            for msg in reversed(context.messages):
                if isinstance(msg, AssistantMessage):
                    parent_assistant = msg
                    break

            forked_pair = build_forked_messages(prompt, parent_assistant)

            # Fork + worktree: append the translation notice as a trailing
            # user message so it appears as the most recent guidance the
            # child sees. Mirrors
            # ``typescript/src/tools/AgentTool/AgentTool.tsx:610-614``. The
            # notice is plain text — it does NOT contain the
            # ``<fork-boilerplate>`` tag, so the message-scan recursion guard
            # is unaffected.
            worktree_cwd = _resolve_fork_worktree_cwd(context)
            if worktree_cwd is not None:
                parent_cwd_str = str(context.cwd or context.workspace_root)
                notice_text = build_worktree_notice(parent_cwd_str, worktree_cwd)
                forked_pair = list(forked_pair) + [create_user_message(content=notice_text)]

            fork_context_messages = list(context.messages) + forked_pair
            fork_use_exact_tools = True
            fork_query_source = f"agent:builtin:{FORK_SUBAGENT_TYPE}"
            # Parent system prompt: prefers ``context.rendered_system_prompt``
            # (byte-identical to the parent's last API call) and falls back
            # to recomputing via the active agent def. See
            # ``_resolve_parent_system_prompt`` docstring for the full
            # cascade, which mirrors ``AgentTool.tsx:495-511``.
            fork_parent_system_prompt = _resolve_parent_system_prompt(context, agent_definitions)
            # ``run_agent`` will append a UserMessage built from ``prompt``
            # to whatever ``context_messages`` it receives. We have already
            # placed the directive inside ``forked_pair`` via
            # ``build_forked_messages``; pass an empty prompt so we don't
            # duplicate it.
            fork_prompt = ""

        run_params = RunAgentParams(
            parent_context=context,
            agent_definition=agent_def,
            prompt=fork_prompt,
            available_tools=available_tools,
            tool_registry=effective_registry,
            provider=provider,
            model=model,
            agent_id=agent_id,
            is_async=is_async,
            max_turns=agent_def.max_turns,
            context_messages=fork_context_messages,
            use_exact_tools=fork_use_exact_tools,
            query_source=fork_query_source,
            parent_system_prompt=fork_parent_system_prompt,
        )

        if is_async:
            return _launch_async_agent(
                run_params=run_params,
                context=context,
                agent_id=agent_id,
                description=description,
                prompt=prompt,
                agent_type=agent_def.agent_type,
                agent_name=agent_name,
            )
        else:
            return _run_sync_agent(
                run_params=run_params,
                context=context,
                agent_id=agent_id,
                start_time=start_time,
                prompt=prompt,
                description=description,
                agent_type=agent_def.agent_type,
            )

    def _run_sync_agent(
        *,
        run_params: RunAgentParams,
        context: ToolContext,
        agent_id: str,
        start_time: float,
        prompt: str,
        description: str,
        agent_type: str,
    ) -> ToolResult:
        """Run an agent synchronously and return the result.

        Ch04 / Sync-Agent-Transcript (2026-06-13): Persist the sub-agent's
        internal message transcript to disk, matching what the async path
        already does via ``TranscriptWriter``.  This ensures ``cli --resume``,
        the visualizer, and the session-analyzer can inspect sub-agent
        internals even when ``run_in_background`` was not set.

        OOM Fix 1 (2026-06-13): stream ``run_agent`` directly into the
        transcript writer. The pre-fix shape was
        ``asyncio.run(_collect_agent_messages(...))`` → ``for msg in
        agent_messages: transcript_writer.append(msg)`` in a
        ``finally`` block — the full subagent message list was held in
        memory between collection and the post-collect write loop. On
        the WSL2 3.8 GB repro, a multi-MB Explore subagent blew the
        parent RSS ceiling in that window. The new shape inlines the
        transcript append into the ``async for message in
        run_agent(run_params):`` loop so writes happen *during*
        collection; the list still carries the full transcript for
        ``finalize_agent_tool``'s tool-use count, but peak memory no
        longer sits on top of the eager list.

        Chapter-12 / WI-2.6: a ``LocalAgentTaskState`` is registered on
        ``context.runtime_tasks`` so ``TaskOutput`` /
        ``task_output_key`` resolve identically for sync and async
        agents. The full transcript path is plumbed through to
        ``finalize_agent_tool`` so a multi-MB subagent report gets
        truncated for parent-side injection while remaining recoverable
        via ``TaskOutput``.
        """
        from ..protocol import ToolResult as TR
        from clawcodex_ext.types.messages import AssistantMessage, Message
        from src.agent.transcript import TranscriptWriter, get_agent_transcript_path
        from src.bootstrap.state import get_session_id
        from src.tasks.local_agent import LocalAgentTaskState
        from clawcodex_ext.types.content_blocks import TextBlock, ToolUseBlock

        # OOM Fix 1: stream ``run_agent`` directly into the transcript
        # writer. The list still carries the full transcript for
        # ``finalize_agent_tool``'s tool-use count, but the OOM peak
        # is no worse than the generator's per-message retention.

        # Compute the sidechain transcript path so sync agents also
        # leave a persistent record (nested under the parent session).
        parent_sid = get_session_id()
        transcript_path_str: str | None = get_agent_transcript_path(
            agent_id,
            parent_session_id=parent_sid,
        )
        transcript_writer: TranscriptWriter | None = None
        if transcript_path_str:
            try:
                transcript_writer = TranscriptWriter(
                    transcript_path_str,
                    parent_session_id=parent_sid,
                )
            except Exception:
                logger.exception(
                    "sync agent transcript open failed for %s; continuing without persistence",
                    agent_id,
                )
                transcript_path_str = None  # No file → no path to surface.

        # WI-2.6: register the sync task on ``runtime_tasks`` so
        # ``TaskOutput`` / ``task_output_key`` resolve identically for
        # sync and async agents. ``output_file`` is the absolute
        # transcript path; mirrors what ``register_async_agent`` writes
        # for the async path. The state is mutated in place on success /
        # failure below.
        sync_state = LocalAgentTaskState(
            id=agent_id,
            agent_id=agent_id,
            description=description,
            prompt=prompt,
            agent_type=agent_type,
            status="running",
            start_time=start_time,
            output_file=str(transcript_path_str) if transcript_path_str else "",
            parent_session_id=parent_sid,
        )
        context.runtime_tasks.upsert(sync_state)

        messages_for_finalize: list[Message] = []
        last_assistant: AssistantMessage | None = None

        def _stream_collect() -> None:
            """Drive ``run_agent`` from a fresh event loop, streaming
            messages into ``messages_for_finalize`` and the transcript
            writer. Mutates enclosing variables via ``nonlocal``; the
            cross-thread happens-before is provided by
            ``concurrent.futures.Future.result()`` (or, in the no-loop
            case, by single-threaded sequential execution).
            """
            nonlocal last_assistant, transcript_writer
            loop = asyncio.new_event_loop()
            try:

                async def _go() -> None:
                    # The inner ``async def`` shadows ``transcript_writer``
                    # at function scope; without its own ``nonlocal`` the
                    # reassignment below would create a new local and
                    # raise ``UnboundLocalError`` on the read above.
                    nonlocal last_assistant, messages_for_finalize, transcript_writer
                    async for message in run_agent(run_params):
                        messages_for_finalize.append(message)
                        if isinstance(message, AssistantMessage):
                            last_assistant = message
                        # Live progress line — mirrors the stderr
                        # output the eager ``_collect_agent_messages``
                        # used to emit; the model can be the only
                        # consumer of ``output`` so the user must still
                        # see what the subagent is doing.
                        try:
                            content = (
                                message.content if isinstance(message, AssistantMessage) else None
                            )
                            if isinstance(content, str) and content.strip():
                                sys.stderr.write(f"  ⎿ [{agent_type}] {content.strip()[:200]}\n")
                                sys.stderr.flush()
                            elif isinstance(content, list):
                                for block in content:
                                    if isinstance(block, TextBlock) and block.text.strip():
                                        sys.stderr.write(
                                            f"  ⎿ [{agent_type}] {block.text.strip()[:200]}\n"
                                        )
                                        sys.stderr.flush()
                                    elif isinstance(block, ToolUseBlock):
                                        sys.stderr.write(
                                            _format_subagent_tool_use(
                                                agent_type,
                                                block.name,
                                                getattr(block, "input", None),
                                            )
                                        )
                                        sys.stderr.flush()
                        except Exception:
                            logger.exception(
                                "sync subagent progress line failed for %s",
                                agent_id,
                            )
                        # Persist to disk per message — the OOM Fix 1
                        # point: no post-collect write loop holds the
                        # list. Mirror of the async path's ``OSError``
                        # recovery.
                        if transcript_writer is not None:
                            try:
                                transcript_writer.append(message)
                            except OSError:
                                logger.exception(
                                    "sync agent transcript append failed for %s; "
                                    "further appends will be skipped",
                                    agent_id,
                                )
                                try:
                                    transcript_writer.close()
                                except Exception:
                                    pass
                                transcript_writer = None

                loop.run_until_complete(_go())
            finally:
                loop.close()

        run_exc: BaseException | None = None
        try:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Nested-loop safe path: drive the streaming on a
                    # worker thread with its own event loop. Mirrors
                    # the previous ``_sync_collect_agent_messages`` shape.
                    import concurrent.futures

                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        future = pool.submit(_stream_collect)
                        future.result()
                else:
                    _stream_collect()
            except RuntimeError:
                # No event loop in this thread — create one
                _stream_collect()
        except BaseException as exc:  # noqa: BLE001
            run_exc = exc
            sync_state.status = "failed"
            sync_state.error = str(exc)
            sync_state.completed_at = time.time()
            raise
        finally:
            if transcript_writer is not None:
                try:
                    transcript_writer.close()
                except Exception:
                    logger.exception(
                        "failed to close sync agent transcript for %s",
                        agent_id,
                    )

        # Finalize result. ``last_assistant_msg`` skips the second
        # ``reversed(messages_for_finalize)`` walk in
        # ``finalize_agent_tool``; ``transcript_path`` enables the
        # truncation notice to point at the sidechain file.
        metadata = {
            "start_time": start_time,
            "agent_type": agent_type,
        }
        result = finalize_agent_tool(
            messages_for_finalize,
            agent_id,
            metadata,
            last_assistant_msg=last_assistant,
            transcript_path=transcript_path_str,
        )
        del messages_for_finalize  # help refcount release the list promptly

        # Mirror the async completion path: flip the registered
        # ``LocalAgentTaskState`` to ``completed`` and snapshot the
        # truncated preview as ``result_text`` so a follow-up
        # ``TaskOutput`` call can show it without re-running.
        result_text = "\n".join(
            block.get("text", "")
            for block in result.content
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
        sync_state.status = "completed"
        sync_state.completed_at = time.time()
        sync_state.result_text = result_text

        # F-88 P88-D: persist Explore / Plan reports to disk for
        # later-session reference. Best-effort — never raises.
        if agent_type in ONE_SHOT_BUILTIN_AGENT_TYPES and result_text:
            _persist_agent_report(
                subagent_type=agent_type,
                agent_id=agent_id,
                session_id=parent_sid,
                transcript=result_text,
            )

        return TR(
            name=AGENT_TOOL_NAME,
            output={
                "status": "failed" if run_exc is not None else "completed",
                "prompt": prompt,
                "agent_id": result.agent_id,
                "agent_type": result.agent_type,
                "content": result.content,
                "total_duration_ms": result.total_duration_ms,
                "total_tokens": result.total_tokens,
                "total_tool_use_count": result.total_tool_use_count,
                "task_output_key": agent_id,
                "transcript_path": result.transcript_path,
                "truncated": result.truncated,
            },
        )

    def _launch_async_agent(
        *,
        run_params: RunAgentParams,
        context: ToolContext,
        agent_id: str,
        description: str,
        prompt: str,
        agent_type: str,
        agent_name: str | None = None,
    ) -> ToolResult:
        """Launch an agent in the background and return immediately.

        Chapter-10 layered story:
        * Chunk B / WI-1.5 — state on ``context.runtime_tasks`` as a
          typed ``LocalAgentTaskState`` (no more ``context.tasks`` /
          ``metadata._internal=True`` workaround).
        * Chunk C / WI-2.2 (gate-zero) — sidechain JSONL transcript
          opened for the lifetime of the agent run; ``output_file`` is
          its absolute path.
        * Chunk C / WI-2.3 — lifecycle goes through the named helpers
          (``register_async_agent`` / ``complete_agent_task`` /
          ``fail_agent_task``) so the registry mutations are atomic
          and consistent across spawn / kill / completion paths.
        * Chunk C / WI-2.4 — token accounting via ``ProgressTracker``;
          ``finalize_agent_tool`` reads its accumulated totals instead
          of reporting ``total_tokens=0``.
        * Chunk F / WI-6.1 — optional ``agent_name`` registers the
          spawn under ``context.agent_name_registry`` so SendMessage
          can resolve ``to: <name>``. Collision-on-running raises;
          collision-on-terminal silently overwrites.
        """
        # Local imports defer the cycle: ``src.tasks.local_agent``
        # reaches back into ``src.task_registry`` which is fine, but
        # importing them at module scope would tangle with
        # ``defaults.py``'s tool-construction order.
        from src.agent.transcript import TranscriptWriter
        from src.bootstrap.state import get_session_id
        from src.tasks.local_agent import (
            LocalAgentTaskState,
            complete_agent_task,
            fail_agent_task,
            register_async_agent,
        )
        from clawcodex_ext.tasks.progress import (
            ProgressTracker,
            update_progress_from_message,
        )
        from clawcodex_ext.services.swarm.agent_name_registry import (
            AgentNameAlreadyClaimedError,
        )
        from src.utils.task_notification import enqueue_agent_notification

        # WI-6.1 + critic C1 (Phase-7 fix): atomic check-and-claim
        # under the typed registry's RLock. The previous Phase-6
        # implementation had a TOCTOU window between the read and
        # the write; the typed ``claim_or_raise`` closes it. We do
        # the claim BEFORE the runtime_tasks write so a refused
        # spawn doesn't leak a half-constructed agent_id into the
        # runtime registry.
        if agent_name is not None:
            try:
                context.agent_name_registry.claim_or_raise(
                    agent_name,
                    agent_id,
                    context.runtime_tasks,
                )
            except AgentNameAlreadyClaimedError as exc:
                raise ToolInputError(str(exc)) from exc

        register_async_agent(
            agent_id=agent_id,
            description=description,
            prompt=prompt,
            agent_type=agent_type,
            registry=context.runtime_tasks,
            parent_session_id=get_session_id(),
        )
        # ``register_async_agent`` populated ``output_file`` with the
        # JSONL transcript path; pull it back so the writer points at
        # the same path the lifecycle helpers committed to.
        registered = context.runtime_tasks.get(agent_id)
        transcript_path = (
            registered.output_file if isinstance(registered, LocalAgentTaskState) else ""
        )

        async def _background_lifecycle() -> None:
            tracker = ProgressTracker()
            messages: list[Any] = []
            transcript: TranscriptWriter | None = None
            if transcript_path:
                try:
                    transcript = TranscriptWriter(
                        transcript_path, parent_session_id=get_session_id()
                    )
                except OSError:
                    # Transcript open failure must not abort the run —
                    # downstream Chunk D / Chunk F will degrade
                    # gracefully (no outputFile content / no auto-resume
                    # source) rather than crash.
                    logger.exception(
                        "transcript open failed for %s; continuing without disk persistence",
                        agent_id,
                    )
                    transcript = None
            try:
                try:
                    async for message in run_agent(run_params):
                        messages.append(message)
                        # Live progress accounting — feeds the post-hoc
                        # ``finalize_agent_tool`` token total via the
                        # ``progress`` keyword (WI-2.4 fallback also
                        # works if the tracker is somehow empty).
                        try:
                            update_progress_from_message(tracker, message)
                        except Exception:
                            logger.exception("progress tracker update failed for %s", agent_id)
                        # Persist to disk per WI-2.2. Synchronous IO
                        # outside the registry lock — A6/C5 contract is
                        # preserved (no ``await`` under the registry's
                        # RLock).
                        if transcript is not None:
                            try:
                                transcript.append(message)
                            except OSError:
                                logger.exception(
                                    "transcript append failed for %s; further appends will be skipped",
                                    agent_id,
                                )
                                transcript.close()
                                transcript = None

                    metadata = {
                        "start_time": time.time(),
                        "agent_type": agent_type,
                    }
                    result = finalize_agent_tool(
                        messages,
                        agent_id,
                        metadata,
                        progress=tracker,
                        transcript_path=transcript_path or None,
                    )
                    result_text = "\n".join(
                        block.get("text", "")
                        for block in result.content
                        if isinstance(block, dict) and block.get("type") == "text"
                    ).strip()
                    if not result_text:
                        result_text = "(Subagent completed with no textual output.)"

                    complete_agent_task(
                        agent_id,
                        result_text=result_text,
                        registry=context.runtime_tasks,
                    )
                    # Chunk D / WI-3.1 + WI-3.2 — enqueue a single
                    # ``<task-notification>`` envelope. Atomic check-and-
                    # set on ``state.notified`` inside the helper means
                    # a concurrent kill / fail / completion path can't
                    # produce a second envelope.
                    enqueue_agent_notification(
                        task_id=agent_id,
                        description=description,
                        status="completed",
                        output_file=transcript_path,
                        final_message=result_text,
                        usage={
                            "total_tokens": result.total_tokens,
                            "tool_uses": result.total_tool_use_count,
                            "duration_ms": result.total_duration_ms,
                        },
                        registry=context.runtime_tasks,
                    )
                    # F-88 P88-D: persist Explore / Plan reports to disk
                    # for later-session reference. Best-effort — never
                    # raises. Mirrors the sync-path hook in
                    # ``_run_sync_agent``.
                    if agent_type in ONE_SHOT_BUILTIN_AGENT_TYPES and result_text:
                        _persist_agent_report(
                            subagent_type=agent_type,
                            agent_id=agent_id,
                            session_id=get_session_id(),
                            transcript=result_text,
                        )
                    logger.info(
                        "Async agent %s (%s) finished: %d messages, %d tokens",
                        agent_id,
                        agent_type,
                        len(messages),
                        result.total_tokens,
                    )
                except Exception as exc:
                    partial = extract_partial_result(messages)
                    err_text = partial or str(exc)
                    fail_agent_task(
                        agent_id,
                        error=err_text,
                        registry=context.runtime_tasks,
                    )
                    enqueue_agent_notification(
                        task_id=agent_id,
                        description=description,
                        status="failed",
                        output_file=transcript_path,
                        error=str(exc),
                        final_message=partial,
                        registry=context.runtime_tasks,
                    )
                    logger.exception(
                        "Async agent %s (%s) failed",
                        agent_id,
                        agent_type,
                    )
            finally:
                if transcript is not None:
                    transcript.close()

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is not None:
            running_loop.create_task(_background_lifecycle())
        else:

            def _runner(_stop_event: Any) -> None:
                asyncio.run(_background_lifecycle())

            context.task_manager.start(name=f"agent:{agent_type}", target=_runner)

        return ToolResult(
            name=AGENT_TOOL_NAME,
            output={
                "status": "async_launched",
                "agent_id": agent_id,
                "agent_type": agent_type,
                "description": description,
                "prompt": prompt,
                "task_output_key": agent_id,
            },
        )

    def _agent_prompt() -> str:
        """Build the prompt for the Agent tool.

        Includes built-in agents plus any custom agents discovered on
        disk so the model sees the full set of valid ``subagent_type``
        values in the tool description. When ``get_available_mcp_servers``
        was supplied at tool construction, the MCP filter runs here too —
        otherwise the prompt advertises every discovered agent and the
        per-call resolver enforces availability at spawn time.
        """
        try:
            agents = get_agent_definitions_with_overrides(os.getcwd())
        except Exception:
            logger.exception("agent discovery failed in tool prompt; using built-ins")
            agents = list(get_built_in_agents())
        if get_available_mcp_servers is not None:
            try:
                available = list(get_available_mcp_servers() or [])
            except Exception:
                logger.exception(
                    "get_available_mcp_servers raised; treating as no MCPs "
                    "available — agents requiring MCP servers will be hidden"
                )
                available = []
            agents = filter_agents_by_mcp_requirements(agents, available)
        return get_agent_prompt(agents)

    def _map_result_to_api(result: Any, tool_use_id: str) -> dict[str, Any]:
        if not isinstance(result, dict):
            return {"type": "tool_result", "tool_use_id": tool_use_id, "content": str(result)}
        content = result.get("content", "")
        if result.get("status") == "error":
            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": result.get("error", content),
                "is_error": True,
            }
        if result.get("status") == "async_launched":
            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": (
                    "Async agent launched successfully.\n"
                    f"agent_id: {result.get('agent_id', '')}\n"
                    f"task_output_key: {result.get('task_output_key', '')}\n"
                    "Use TaskOutput with task_id equal to task_output_key to check completion."
                ),
            }
        if result.get("status") == "completed":
            text_parts: list[str] = []
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text")
                        if isinstance(text, str) and text.strip():
                            text_parts.append(text.strip())
            elif isinstance(content, str) and content.strip():
                text_parts.append(content.strip())
            rendered = (
                "\n\n".join(text_parts).strip() or "(Subagent completed with no textual output.)"
            )
            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": rendered,
            }
        return {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}

    return build_tool(
        name=AGENT_TOOL_NAME,
        input_schema=AGENT_INPUT_SCHEMA,
        call=_agent_call,
        prompt=_agent_prompt,
        description=lambda _input: "Launch a new agent to handle a task",
        aliases=(LEGACY_AGENT_TOOL_NAME,),
        map_result_to_api=_map_result_to_api,
        max_result_size_chars=200_000,
        is_destructive=lambda _input: True,
        search_hint="agent spawn subagent delegate task",
        to_auto_classifier_input=lambda input_data: (input_data or {}).get("prompt", "")[:200],
        get_activity_description=lambda input_data: (
            (input_data or {}).get("description", "Running agent") if input_data else None
        ),
    )


def _resolve_parent_system_prompt(
    context: ToolContext,
    agent_definitions: list[AgentDefinition],
) -> str | None:
    """Resolve the parent system prompt for fork children.

    Mirrors the layered fallback in
    ``typescript/src/tools/AgentTool/AgentTool.tsx:495-511``:

    1. ``context.rendered_system_prompt`` — the bytes captured from the
       parent's most recent API call. Preferred path: identical to the
       parent's cached prefix, so the fork child's API request hits the
       prompt cache without recomputing anything that might have shifted
       (chapter 9 §"The Byte-Identical Prefix Trick", Layer 1).
    2. ``context.options.custom_system_prompt`` — explicit caller
       override.
    3. The active agent definition's ``get_system_prompt()`` output —
       recompute fallback. Useful for tests and SDK callers that never
       populated the rendered field but still want a coherent prompt.
    4. ``None`` — let ``get_agent_system_prompt`` fall through to
       ``DEFAULT_AGENT_PROMPT``.

    Returns ``None`` when no candidate is available.
    """
    rendered = getattr(context, "rendered_system_prompt", None)
    if isinstance(rendered, str) and rendered.strip():
        return rendered

    custom = getattr(context.options, "custom_system_prompt", None)
    if isinstance(custom, str) and custom.strip():
        return custom

    active_type = getattr(context, "agent_type", None)
    if active_type:
        active_def = find_agent_by_type(agent_definitions, active_type)
        if active_def is not None:
            try:
                return active_def.get_system_prompt()
            except Exception:
                return None

    return None


def _resolve_fork_worktree_cwd(context: ToolContext) -> str | None:
    """Return the worktree cwd string for a fork child, or ``None``.

    Mirrors the ``isForkPath && worktreeInfo`` branch in
    ``typescript/src/tools/AgentTool/AgentTool.tsx:610-614``. Only return
    a non-None value when the active context has a worktree root that
    differs from the parent's working directory — otherwise the notice
    would be misleading ("you are operating in an isolated worktree at
    /same/path").
    """
    wt_root = getattr(context, "worktree_root", None)
    if wt_root is None:
        return None
    wt_path = str(wt_root)
    parent_cwd = str(context.cwd or context.workspace_root)
    if not wt_path or wt_path == parent_cwd:
        return None
    return wt_path


def _sync_collect_agent_messages(params: RunAgentParams) -> list[Any]:
    """Collect agent messages synchronously in a new event loop.

    Retained for ``tests/agent/test_subagent_progress_line.py``. The
    production sync path (``_run_sync_agent``) now streams messages
    directly from ``run_agent`` into the transcript writer and a
    ``messages_for_finalize`` list (OOM Fix 1, see ``_stream_collect``);
    the eager ``list[Any]`` shape this helper returns is no longer used
    in production. Remove in a follow-up if the test ever migrates to
    the streaming path.
    """
    return asyncio.run(_collect_agent_messages(params))


def _format_subagent_tool_use(agent_type: str, name: str, tool_input: Any) -> str:
    """Format one nested tool_use into the ``⎿ [type] Name(args)`` line.

    Parity gap fix: the original implementation hard-coded ``Name(...)`` which
    discards the file path / command / pattern the user needs to follow what
    the subagent is doing. TS's ``getActivityDescription`` (e.g.
    ``FileReadTool.ts:369``) renders the same input data into a per-tool
    sentence; the closest Python equivalent already exists in
    ``summarize_tool_use``, so we route through it.

    Empty summaries fall back to ``Name`` (no parens) so a tool whose summarizer
    returned nothing still produces a clean line instead of literal ``Name()``.
    """
    from src.tool_system.renderers import summarize_tool_use

    safe_input: dict[str, Any] = tool_input if isinstance(tool_input, dict) else {}
    summary = ""
    try:
        summary = summarize_tool_use(name, safe_input) or ""
    except Exception:
        # A buggy summarizer must not poison live progress output.
        summary = ""
    if summary:
        # Keep the line single-row even when summaries embed newlines (Bash
        # ``$ cmd\ncmd2``) or are pathologically long.
        flat = summary.replace("\n", " ").strip()
        if len(flat) > 200:
            flat = flat[:197] + "..."
        call = f"{name}({flat})"
    else:
        call = name
    return f"  ⎿ [{agent_type}] {call}\n"


async def _collect_agent_messages(params: RunAgentParams) -> list[Any]:
    """Collect all messages from the run_agent generator.

    Prints intermediate agent messages (explanatory text, tool use summaries)
    to stderr so the user sees progress in real-time instead of a silent wait.

    Retained for ``tests/agent/test_subagent_progress_line.py``. The
    production sync path (``_run_sync_agent``) now streams messages
    directly from ``run_agent`` into the transcript writer and a
    ``messages_for_finalize`` list (OOM Fix 1, see ``_stream_collect``);
    the eager ``list[Any]`` shape this helper returns is no longer used
    in production. The progress-line formatting is the source-of-truth
    that the streaming path mirrors inline. Remove in a follow-up if
    the test ever migrates to the streaming path.
    """
    from clawcodex_ext.types.messages import Message, AssistantMessage
    from clawcodex_ext.types.content_blocks import TextBlock, ToolUseBlock

    agent_type = getattr(params.agent_definition, "agent_type", "agent")
    messages: list[Message] = []
    async for msg in run_agent(params):
        messages.append(msg)

        # Print intermediate progress to stderr for real-time feedback
        if isinstance(msg, AssistantMessage):
            content = msg.content
            if isinstance(content, str) and content.strip():
                sys.stderr.write(f"  ⎿ [{agent_type}] {content.strip()[:200]}\n")
                sys.stderr.flush()
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, TextBlock) and block.text.strip():
                        sys.stderr.write(f"  ⎿ [{agent_type}] {block.text.strip()[:200]}\n")
                        sys.stderr.flush()
                    elif isinstance(block, ToolUseBlock):
                        sys.stderr.write(
                            _format_subagent_tool_use(
                                agent_type, block.name, getattr(block, "input", None)
                            )
                        )
                        sys.stderr.flush()
    return messages
