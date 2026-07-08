"""lkb — Logical Kanban slash command.

Usage::

    /lkb status                  List all tasks with LKB derived status
    /lkb explain <task_id>       Show blocking reason + proof trace
    /lkb audit <task_id>         Show audit event log
    /lkb clarify                 List all pending clarifications

The command is registered as a ``LocalCommand`` with
``supports_non_interactive=False`` because it requires a live
``ToolContext`` attached to the ``CommandContext`` via
``attach_downstream_context``.
"""

from __future__ import annotations

from .registry import register_command
from .types import CommandAvailability, LocalCommand, LocalCommandResult

# ── subcommand handlers ─────────────────────────────────────────────────


def _lkb_call(args: str, ctx: object) -> LocalCommandResult:
    """Top-level dispatch for ``/lkb <subcommand> [args]``."""
    parts = args.strip().split(maxsplit=1)
    sub = parts[0].lower() if parts else "status"
    sub_args = parts[1] if len(parts) > 1 else ""

    tool_ctx = getattr(ctx, "tool_context", None)
    if tool_ctx is None:
        return LocalCommandResult(
            type="text",
            value="The /lkb command requires a tool_context (only available in TUI/REPL sessions).",
        )

    # Guard: LKB feature flag
    try:
        from clawcodex_ext.logical_kanban.flags import is_logical_kanban_enabled

        if not is_logical_kanban_enabled():
            return LocalCommandResult(
                type="text",
                value="LKB (Logical Kanban) is not currently enabled. Enable the `logical_kanban` feature flag.",
            )
    except Exception as exc:
        return LocalCommandResult(
            type="text",
            value=f"LKB module unavailable: {exc}",
        )

    switch = {
        "status": _lkb_status,
        "explain": _lkb_explain,
        "audit": _lkb_audit,
        "clarify": _lkb_clarify,
    }
    handler = switch.get(sub)
    if handler is None:
        return LocalCommandResult(type="text", value=_usage())
    try:
        return LocalCommandResult(type="text", value=handler(tool_ctx, sub_args))
    except Exception as exc:
        return LocalCommandResult(type="text", value=f"/lkb {sub} error: {exc}")


def _usage() -> str:
    return (
        "LKB usage:\n"
        "  /lkb status               List all tasks with LKB derived status\n"
        "  /lkb explain <task_id>    Show blocking reason + proof trace\n"
        "  /lkb audit <task_id>      Show audit event log\n"
        "  /lkb clarify              List all pending clarifications\n"
    )


def _text_badge(
    derived_status: str,
    *,
    blocked_by: list[str] | None = None,
    stale: list[dict] | None = None,
    validation_result: str | None = None,
) -> str:
    """Return a compact one-line status badge (emoji + English text)."""
    if validation_result == "fail":
        return "✗ Validation failed"
    if derived_status == "blocked":
        blockers = ", ".join(blocked_by or [])
        return f"▣ Blocked  ({blockers})" if blockers else "▣ Blocked"
    if stale:
        ids = ", ".join(s.get("assumptionId", "?") for s in stale[:3])
        return f"△ Stale assumption  ({ids})"
    if derived_status == "needs_recheck":
        return "◎ Needs recheck"
    return ""


def _panel(body: str, title: str) -> str:
    """Wrap *body* in an ASCII-panel with *title*."""
    lines = body.split("\n")
    width = max(len(l) for l in lines) if lines else 40
    width = min(max(width + 4, 20), 100)
    top = f"╔══ {title} " + "═" * (width - len(title) - 6) + "╗"
    bot = "╚" + "═" * (width - 1) + "╝"
    padded = [f"║  {l:<{width - 4}}  ║" for l in lines]
    return "\n".join([top] + padded + [bot])


def _lkb_status(tool_ctx, _args: str) -> str:
    """``/lkb status`` — list all tasks with LKB derived status."""
    from clawcodex_ext.logical_kanban.context_adapter import build_facts_snapshot, task_lkb_view

    snapshot = build_facts_snapshot(tool_ctx)
    task_ids = sorted(snapshot.normalized_tasks.keys())
    if not task_ids:
        return "No tasks found."

    lines: list[str] = []
    counts: dict[str, int] = {"blocked": 0, "stale": 0, "clarify": 0, "verified": 0}

    for tid in task_ids:
        state = task_lkb_view(tool_ctx, tid)
        raw = (tool_ctx.tasks.get(tid) or {}) if hasattr(tool_ctx, "tasks") else {}
        subject = ""
        if isinstance(raw, dict):
            subject = str(raw.get("subject") or raw.get("content") or tid)[:60]
        else:
            subject = tid[:60]

        ds = state.get("derivedStatus", "?")
        vr = state.get("latestValidationResult")
        blockers = state.get("blockedBy", [])
        stale_info = state.get("staleAssumptions", [])

        badge = _text_badge(
            ds,
            blocked_by=blockers,
            stale=stale_info,
            validation_result=vr,
        )

        if "Blocked" in badge:
            counts["blocked"] += 1
        if "Stale" in badge:
            counts["stale"] += 1
        if "Verified" in badge:
            counts["verified"] += 1

        status_icon = "○"
        if isinstance(raw, dict):
            s = str(raw.get("status", "") or "")
            status_icon = {"pending": "○", "in_progress": "◐", "completed": "✔"}.get(s, "○")

        lines.append(f"  {status_icon} {subject}")
        if badge:
            lines.append(f"      {badge}")
        if blockers:
            lines.append(f"      Blockers: {', '.join(blockers)}")

    lines.append("")
    lines.append(
        f"  Summary: {len(task_ids)} tasks / "
        f"{counts['blocked']} blocked / "
        f"{counts['stale']} stale assumptions"
    )
    return _panel("\n".join(lines), "LKB Task Status")


def _lkb_explain(tool_ctx, task_id: str) -> str:
    """``/lkb explain <task_id>`` — show blocked reason + proof trace."""
    task_id = task_id.strip()
    if not task_id:
        return "Usage: /lkb explain <task_id>"

    from clawcodex_ext.logical_kanban.context_adapter import build_facts_snapshot, task_lkb_view
    from clawcodex_ext.logical_kanban.explain import proof_trace_summary

    _ = build_facts_snapshot(tool_ctx)  # ensure fresh snapshot
    state = task_lkb_view(tool_ctx, task_id, include_proof_trace=True)

    lines: list[str] = []
    lines.append(f"Task: {task_id}")
    lines.append(f"Derived status: {state.get('derivedStatus', '?')}")
    lines.append(f"Latest validation result: {state.get('latestValidationResult', '—')}")

    br = state.get("blockedReason")
    if br:
        lines.append(f"Blocked reason: {br}")

    br_raw = state.get("blockedBy", [])
    if br_raw:
        lines.append(f"Blocked by: {', '.join(br_raw)}")

    pt = state.get("proofTraceSummary", [])
    if pt:
        lines.append("Proof trace:")
        for step in pt:
            seq = step.get("step", "?")
            rule = step.get("rule", "?")
            premises = " + ".join(str(p) for p in step.get("premises", []))
            conclusion = step.get("conclusion", "")
            lines.append(f"  Step {seq}:")
            lines.append(f"    {premises}")
            lines.append(f"    ──[{rule}]──→ {conclusion}")

    # Stale assumptions
    stale_info = state.get("staleAssumptions", [])
    if stale_info:
        lines.append("Stale assumptions:")
        for s in stale_info:
            lines.append(f"  {s.get('assumptionId')} ({s.get('field')})")

    # Latest denial detail
    denial = state.get("latestDenialReason")
    if denial and isinstance(denial, dict):
        sug = denial.get("repairSuggestions", [])
        if sug:
            lines.append("Repair suggestions:")
            for s in sug:
                lines.append(f"  [{s.get('action')}] {s.get('message', '')}")

    return _panel("\n".join(lines), f"LKB Explain: {task_id}")


def _lkb_audit(tool_ctx, task_id: str) -> str:
    """``/lkb audit <task_id>`` — show audit events."""
    task_id = task_id.strip()
    if not task_id:
        return "Usage: /lkb audit <task_id>"

    from clawcodex_ext.logical_kanban.orchestrator import read_audit_events_for_run

    events = read_audit_events_for_run(tool_ctx, task_id=task_id, limit=20)
    if not events:
        return f"Task {task_id} has no LKB audit events."

    lines: list[str] = []
    for ev in events:
        ts = (ev.get("timestamp") or "")[11:19]  # HH:MM:SS
        etype = ev.get("eventType", "?")
        actor = ev.get("actor", "?")
        payload = ev.get("payload", {})
        lines.append(f"  [{ts}] {etype}  ({actor})")
        # Show brief payload summary for denial/commit events
        if etype in ("lkb_denial", "lkb_commit") and isinstance(payload, dict):
            result = payload.get("result", payload.get("validation_result", ""))
            if result:
                lines.append(f"         result={result}")
    return _panel("\n".join(lines), f"LKB Audit: {task_id}")


def _lkb_clarify(tool_ctx, _args: str) -> str:
    """``/lkb clarify`` — list all pending clarifications."""
    from clawcodex_ext.logical_kanban.runtime import get_logical_kanban

    runtime = get_logical_kanban(tool_ctx)
    denials = getattr(runtime, "latest_denials", {}) or {}
    pending: list[tuple[str, str, str]] = []

    for tid, denial in denials.items():
        for amb in denial.get("legacyTodoAmbiguities", []):
            phrase = amb.get("phrase", amb.get("text", ""))
            sev = amb.get("severity", "?")
            pending.append((tid, phrase, sev))

    if not pending:
        return "No pending clarifications."

    lines: list[str] = []
    for tid, phrase, sev in pending:
        lines.append(f'  {tid}  "{phrase}"')
        lines.append(
            f"          Severity: {sev}  Hint: use /agent retry to refine the task description"
        )
    return _panel("\n".join(lines), "Pending Clarifications")


# ── command definition ──────────────────────────────────────────────────

LKB_COMMAND: LocalCommand = LocalCommand(
    name="lkb",
    description="Logical Kanban status & diagnostics",
    aliases=["logical-kanban"],
    availability=[CommandAvailability.CONSOLE],
    argument_hint="status | explain <task_id> | audit <task_id> | clarify",
    supports_non_interactive=False,
)
LKB_COMMAND.set_call(_lkb_call)

register_command(LKB_COMMAND)

__all__ = ["LKB_COMMAND"]
