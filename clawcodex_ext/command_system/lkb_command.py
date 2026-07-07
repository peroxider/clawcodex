"""lkb — Logical Kanban slash command.

Usage::

    /lkb status                  列出所有任务的 LKB 派生状态
    /lkb explain <task_id>       展示任务的阻塞原因 + proof trace
    /lkb audit <task_id>         展示审计事件日志
    /lkb clarify                 列出所有待澄清的假设

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
            value="LKB 命令需要 tool_context（仅在 TUI/REPL 会话中可用）。",
        )

    # Guard: LKB feature flag
    try:
        from clawcodex_ext.logical_kanban.flags import is_logical_kanban_enabled

        if not is_logical_kanban_enabled():
            return LocalCommandResult(
                type="text",
                value="LKB（Logical Kanban）当前未启用。请启用 feature flag `logical_kanban`。",
            )
    except Exception as exc:
        return LocalCommandResult(
            type="text",
            value=f"LKB 模块不可用: {exc}",
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
        "LKB 命令用法:\n"
        "  /lkb status              列出所有任务的 LKB 派生状态\n"
        "  /lkb explain <task_id>   展示任务的阻塞原因 + proof trace\n"
        "  /lkb audit <task_id>     展示审计事件日志\n"
        "  /lkb clarify             列出所有待澄清的假设\n"
    )


def _text_badge(
    derived_status: str,
    *,
    blocked_by: list[str] | None = None,
    stale: list[dict] | None = None,
    validation_result: str | None = None,
) -> str:
    """Return a compact one-line status badge (emoji + bilingual text)."""
    if validation_result == "fail":
        return "✗ 验证未通过 / Validation failed"
    if derived_status == "blocked":
        blockers = ", ".join(blocked_by or [])
        return f"▣ 被阻塞 / Blocked  ({blockers})" if blockers else "▣ 被阻塞 / Blocked"
    if stale:
        ids = ", ".join(s.get("assumptionId", "?") for s in stale[:3])
        return f"△ 假设已失效 / Stale assumption  ({ids})"
    if derived_status == "needs_recheck":
        return "◎ 需复查 / Needs recheck"
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
        return "当前没有任务。"

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

        if "Blocked" in badge or "被阻塞" in badge:
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
            lines.append(f"      阻塞者: {', '.join(blockers)}")

    lines.append("")
    lines.append(
        f"  汇总: {len(task_ids)} 任务 / "
        f"{counts['blocked']} 阻塞 / "
        f"{counts['stale']} 失效假设"
    )
    return _panel("\n".join(lines), "LKB 任务状态一览")


def _lkb_explain(tool_ctx, task_id: str) -> str:
    """``/lkb explain <task_id>`` — show blocked reason + proof trace."""
    task_id = task_id.strip()
    if not task_id:
        return "用法: /lkb explain <task_id>"

    from clawcodex_ext.logical_kanban.context_adapter import build_facts_snapshot, task_lkb_view
    from clawcodex_ext.logical_kanban.explain import proof_trace_summary

    _ = build_facts_snapshot(tool_ctx)  # ensure fresh snapshot
    state = task_lkb_view(tool_ctx, task_id, include_proof_trace=True)

    lines: list[str] = []
    lines.append(f"任务: {task_id}")
    lines.append(f"派生状态: {state.get('derivedStatus', '?')}")
    lines.append(f"最近验证结果: {state.get('latestValidationResult', '—')}")

    br = state.get("blockedReason")
    if br:
        lines.append(f"阻塞原因: {br}")

    br_raw = state.get("blockedBy", [])
    if br_raw:
        lines.append(f"阻塞者列表: {', '.join(br_raw)}")

    pt = state.get("proofTraceSummary", [])
    if pt:
        lines.append("证明轨迹 (proof trace):")
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
        lines.append("已失效假设:")
        for s in stale_info:
            lines.append(f"  {s.get('assumptionId')} ({s.get('field')})")

    # Latest denial detail
    denial = state.get("latestDenialReason")
    if denial and isinstance(denial, dict):
        sug = denial.get("repairSuggestions", [])
        if sug:
            lines.append("修复建议:")
            for s in sug:
                lines.append(f"  [{s.get('action')}] {s.get('message', '')}")

    return _panel("\n".join(lines), f"LKB 解释: {task_id}")


def _lkb_audit(tool_ctx, task_id: str) -> str:
    """``/lkb audit <task_id>`` — show audit events."""
    task_id = task_id.strip()
    if not task_id:
        return "用法: /lkb audit <task_id>"

    from clawcodex_ext.logical_kanban.orchestrator import read_audit_events_for_run

    events = read_audit_events_for_run(tool_ctx, task_id=task_id, limit=20)
    if not events:
        return f"任务 {task_id} 暂无 LKB 审计事件。"

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
    return _panel("\n".join(lines), f"LKB 审计: {task_id}")


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
        return "当前没有待澄清的假设。"

    lines: list[str] = []
    for tid, phrase, sev in pending:
        lines.append(f"  {tid}  \"{phrase}\"")
        lines.append(f"         严重度: {sev}  提示: 使用 /agent retry 修改任务描述来澄清")
    return _panel("\n".join(lines), "待澄清假设")


# ── command definition ──────────────────────────────────────────────────

LKB_COMMAND: LocalCommand = LocalCommand(
    name="lkb",
    description="Logical Kanban 状态查询与诊断",
    aliases=["logical-kanban"],
    availability=[CommandAvailability.CONSOLE],
    argument_hint="status | explain <task_id> | audit <task_id> | clarify",
    supports_non_interactive=False,
)
LKB_COMMAND.set_call(_lkb_call)

register_command(LKB_COMMAND)

__all__ = ["LKB_COMMAND"]
