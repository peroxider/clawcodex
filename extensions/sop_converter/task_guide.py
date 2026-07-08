"""Generate per-skill task routing guides for SOP-converted agents.

Builds a ``## 任务指南`` section from likely user-facing entry operations
(module-level APIs with docstrings).  The section is kept in the rendered Skill
prompt even when the large ``## Included Tools`` catalog is omitted for token
savings.
"""

from __future__ import annotations

import re

from .intent_tags import collect_intent_phrases, format_search_suggestions
from .skill_grouper import SkillSpec
from .source_parser import SourceComponent, SourceOperation

# Module stems that often host user-facing entry APIs (Python convention, not SDK-specific).
_COMMON_ENTRY_MODULE_STEMS = frozenset({"main", "app", "api", "cli", "__main__"})
# Docstring leading imperative verbs (English; matches how SDK docs are written).
_IMPERATIVE_LEAD_RE = re.compile(
    r"^(?:bring up|start|run|launch|initialize|init|create|open|load|get|set|"
    r"configure|execute|invoke|call|build|make|open|close|connect|dispatch|ensure)\b",
    re.IGNORECASE,
)
_ORCHESTRATION_NAME_PREFIXES = ("run_", "start_", "open_", "launch_", "ensure_", "invoke_")
_REGISTRY_NAME_PREFIXES = ("add_", "register_")
_INTERACTIVE_NAME_RE = re.compile(r"(?:^run_.*_cli$|^.*_cli$|cli$)", re.IGNORECASE)
_MAX_BUILD_ENTRIES = 4


def _skill_invoke_name(skill_name: str) -> str:
    if skill_name.endswith("-skill"):
        return skill_name
    return f"{skill_name}-skill"


def _intent_examples_from_doc(description: str, op_name: str) -> list[str]:
    op = SourceOperation(name=op_name, description=description)
    phrases = list(collect_intent_phrases(op))
    if not phrases:
        return [op_name.replace("_", " ")]
    return phrases[:3]


def _disambiguation_note(
    op: SourceOperation,
    peers: list[SourceOperation],
) -> str | None:
    """Note when a similarly-prefixed peer has a clearly different docstring."""
    if not op.description:
        return None
    op_prefix = op.name.split("_")[0]
    if len(op_prefix) < 3:
        return None
    op_head = op.description.strip()[:48].lower()
    for peer in peers:
        if peer.name == op.name or not peer.description:
            continue
        if not peer.name.startswith(op_prefix):
            continue
        peer_head = peer.description.strip()[:48].lower()
        if peer_head != op_head:
            return f"related API `{peer.name}` has a different purpose"
    return None


def _operation_keys(comp: SourceComponent, op: SourceOperation) -> list[str]:
    keys: list[str] = []
    if op.class_name:
        keys.append(f"{comp.name}.{op.class_name}.{op.name}")
    keys.append(f"{comp.name}.{op.name}")
    if op.file_stem:
        keys.append(f"{comp.name}.{op.file_stem}.{op.name}")
        keys.append(f"{op.file_stem}.{op.name}")
    if op.class_name:
        keys.append(f"{op.class_name}.{op.name}")
    keys.append(op.name)
    return keys


def build_operation_index(
    components: list[SourceComponent],
) -> dict[str, tuple[SourceComponent, SourceOperation]]:
    """Map tool naming conventions → (component, operation)."""
    index: dict[str, tuple[SourceComponent, SourceOperation]] = {}
    for comp in components:
        for op in comp.operations:
            for key in _operation_keys(comp, op):
                index.setdefault(key, (comp, op))
    return index


def _entry_point_score(comp: SourceComponent, op: SourceOperation) -> int:
    """Score how likely an operation is a user-facing entry point."""
    score = 0
    if op.class_name is None:
        score += 2
    if op.description:
        score += 1
    if op.has_docstring:
        score += 1
    if op.file_stem in _COMMON_ENTRY_MODULE_STEMS:
        score += 1
    if op.description and _IMPERATIVE_LEAD_RE.match(op.description.strip()):
        score += 2
    required = sum(1 for p in op.parameters if p.required and not p.name.startswith("*"))
    if required <= 3:
        score += 1
    return score


def is_entry_point(comp: SourceComponent, op: SourceOperation) -> bool:
    return _entry_point_score(comp, op) >= 4


def _extract_noun(op_name: str, prefixes: tuple[str, ...]) -> str | None:
    """Extract the entity noun after a verb prefix.

    >>> _extract_noun("run_agent", ("run_",))
    'agent'
    >>> _extract_noun("add_agents", ("add_", "register_"))
    'agents'
    >>> _extract_noun("configure", ("run_",))
    None
    """
    for prefix in prefixes:
        if op_name.startswith(prefix):
            noun = op_name[len(prefix):]
            if noun:
                return noun
    return None


def _ensure_registry_chain_entries(
    selected: list[tuple[str, SourceComponent, SourceOperation]],
    skill: SkillSpec,
    index: dict[str, tuple[SourceComponent, SourceOperation]],
) -> list[tuple[str, SourceComponent, SourceOperation]]:
    """Force-include registry tools whose entity noun matches a selected runner tool.

    SDK-adaptive: no hardcoded tool names.  Any ``add_*`` / ``register_*`` tool
    whose entity noun (e.g. "agent" from ``add_agent``) appears in an
    already-selected orchestrator tool (e.g. ``run_agent`` → noun "agent")
    gets appended to the task guide.

    Plural forms match their singular root:
    ``run_agent`` (noun "agent") ↔ ``add_agents`` (noun "agents").
    """
    selected_tool_names = {tool_ref for tool_ref, _comp, _op in selected}

    # Collect nouns from selected runner / orchestrator entries.
    selected_nouns: set[str] = set()
    for _tool_ref, _comp, op in selected:
        noun = _extract_noun(op.name, _ORCHESTRATION_NAME_PREFIXES)
        if noun:
            selected_nouns.add(noun)

    if not selected_nouns:
        return selected

    # Find registry tools in allowed_tools whose noun matches a selected noun.
    for tool_ref in skill.allowed_tools:
        if tool_ref in selected_tool_names:
            continue
        resolved = _resolve_operation(tool_ref, index)
        if resolved is None:
            continue
        comp, op = resolved
        reg_noun = _extract_noun(op.name, _REGISTRY_NAME_PREFIXES)
        if reg_noun is None:
            continue
        for sn in selected_nouns:
            # Bidirectional startswith handles singular/plural: "agents" vs "agent".
            if reg_noun.startswith(sn) or sn.startswith(reg_noun):
                selected.append((tool_ref, comp, op))
                break

    return selected


def _orchestration_rank_boost(op: SourceOperation) -> int:
    """Prefer run/start/open orchestrators over build_* helpers in the same skill."""
    boost = 0
    if any(op.name.startswith(prefix) for prefix in _ORCHESTRATION_NAME_PREFIXES):
        boost += 3
    if op.name.startswith("build_"):
        boost -= 2
    if op.file_stem in _COMMON_ENTRY_MODULE_STEMS:
        boost += 2
    if _INTERACTIVE_NAME_RE.search(op.name):
        boost += 2
    return boost


def _looks_like_interactive_terminal(comp: SourceComponent, op: SourceOperation) -> bool:
    """Heuristic: CLI/TUI/REPL entry that blocks without a real TTY."""
    if op.file_stem not in _COMMON_ENTRY_MODULE_STEMS:
        return False
    if op.is_async or op.is_async_generator:
        return True
    if _INTERACTIVE_NAME_RE.search(op.name):
        return True
    desc = (op.description or "").lower()
    return any(token in desc for token in ("cli", "interactive", "repl", "tui", "stdin"))


def _required_param_names(comp: SourceComponent, op: SourceOperation) -> list[str]:
    names: list[str] = []
    for param in op.parameters:
        if param.required and not param.name.startswith("*"):
            names.append(param.name)
    if op.class_name:
        for param in comp.class_init_params.get(op.class_name, ()):
            if param.required and param.name not in names:
                names.append(param.name)
    return names


def _format_required_params_note(comp: SourceComponent, op: SourceOperation) -> str:
    names = _required_param_names(comp, op)
    if op.name == "execute_stage":
        return (
            "必填 ``stage``、``run_dir``；``config``/``adapters``/``run_id`` 可省略"
            "（从 run_dir/config.yaml 加载）。"
        )
    if not names:
        return ""
    quoted = "、".join(f"``{name}``" for name in names[:4])
    return f"必填 {quoted}。"


def _interactive_terminal_footnote() -> str:
    return (
        "交互式终端入口（TUI/REPL）。用户配置在 workspace（如 spec.yaml），"
        "勿用 SDK 源码树 tests/fixtures 下样例。"
        "Agent 内无 TTY 会超时——按「交互式终端停损」引导用户到真实终端运行。"
    )


def _task_guide_rank_key(
    comp: SourceComponent,
    op: SourceOperation,
    tool_ref: str,
) -> tuple[int, int, int, str]:
    """Sort key: higher orchestration/CLI priority, fewer build_* ties."""
    base = _entry_point_score(comp, op)
    boost = _orchestration_rank_boost(op)
    build_penalty = 1 if op.name.startswith("build_") else 0
    return (base + boost, -build_penalty, -len(tool_ref), op.name)


def _select_task_guide_entries(
    ranked: list[tuple[tuple[int, int, int, str], str, SourceComponent, SourceOperation]],
    *,
    max_entries: int,
) -> list[tuple[str, SourceComponent, SourceOperation]]:
    """Pick top entries, capping low-value ``build_*`` rows."""
    selected: list[tuple[str, SourceComponent, SourceOperation]] = []
    build_count = 0
    for _key, tool_ref, comp, op in ranked:
        if len(selected) >= max_entries:
            break
        if op.name.startswith("build_"):
            if build_count >= _MAX_BUILD_ENTRIES:
                continue
            build_count += 1
        selected.append((tool_ref, comp, op))
    return selected


def _build_row_summary(
    comp: SourceComponent,
    op: SourceOperation,
    peers: list[SourceOperation],
    *,
    tool_deps_index: dict | None = None,
) -> str:
    summary = (op.description or op.name).strip()
    summary = re.split(r"[。\n]", summary, maxsplit=1)[0].strip()
    if len(summary) > 100:
        summary = summary[:97] + "..."
    note = _disambiguation_note(op, peers)
    if note:
        summary = f"{summary}（{note}）"
    params_note = _format_required_params_note(comp, op)
    if params_note:
        summary = f"{summary}{params_note}"
    # Cross-tool order: ORCHESTRATION_ROUTES.md + x-sop-dependencies — not task guide.
    if _looks_like_interactive_terminal(comp, op):
        summary = f"{summary}{_interactive_terminal_footnote()}"
    return summary


def _kebab_terminal_candidates(tool_ref: str) -> list[str]:
    """Derive snake_case operation name suffixes from a kebab tool id."""
    if "-" not in tool_ref:
        return []
    parts = tool_ref.split("-")
    candidates: list[str] = []
    for n in range(1, min(6, len(parts) + 1)):
        candidate = "_".join(parts[-n:])
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _resolve_operation(
    tool_ref: str,
    index: dict[str, tuple[SourceComponent, SourceOperation]],
) -> tuple[SourceComponent, SourceOperation] | None:
    if tool_ref in index:
        return index[tool_ref]
    for candidate in _kebab_terminal_candidates(tool_ref):
        if candidate in index:
            return index[candidate]
        for key, pair in index.items():
            _comp, op = pair
            if op.name == candidate:
                return pair
    terminal = tool_ref.rsplit("-", 1)[-1] if "-" in tool_ref else tool_ref
    snake = tool_ref.replace("-", "_")
    for probe in (terminal, snake):
        if probe in index:
            return index[probe]
    for key, pair in index.items():
        if key.endswith(f".{snake}") or key.endswith(f".{terminal}"):
            return pair
        _comp, op = pair
        if op.name == snake or op.name == terminal:
            return pair
    return None


def _composite_task_guide_rows(skill: SkillSpec) -> list[tuple[str, str, str, str]]:
    """Composite macro tools promoted at the top of agent_teams task guides."""
    try:
        from .composite_tools.registry import composite_task_guide_rows
    except ImportError:
        return []

    skill_key = skill.name.removesuffix("-skill")
    if skill_key != "agent_teams":
        if "start-team-session" not in skill.allowed_tools:
            return []

    rows: list[tuple[str, str, str, str]] = []
    for entry in composite_task_guide_rows():
        tool = entry["tool"]
        if skill_key != "agent_teams" and tool not in skill.allowed_tools:
            continue
        rows.append((entry["intent"], tool, entry["search"], entry["note"]))
    return rows


def generate_task_guide_markdown(
    skill: SkillSpec,
    components: list[SourceComponent],
    *,
    max_entries: int = 12,
    tool_deps_index: dict | None = None,
) -> str:
    """Build the ``## 任务指南`` markdown block for a skill."""
    if not skill.allowed_tools or not components:
        return ""

    index = build_operation_index(components)
    ranked: list[tuple[tuple[int, int, int, str], str, SourceComponent, SourceOperation]] = []
    seen_ops: set[str] = set()
    for tool_ref in skill.allowed_tools:
        resolved = _resolve_operation(tool_ref, index)
        if resolved is None:
            continue
        comp, op = resolved
        op_key = f"{comp.name}:{op.class_name}:{op.name}"
        if op_key in seen_ops:
            continue
        if not is_entry_point(comp, op):
            continue
        seen_ops.add(op_key)
        ranked.append((_task_guide_rank_key(comp, op, tool_ref), tool_ref, comp, op))
    ranked.sort(key=lambda item: item[0], reverse=True)

    selected = _select_task_guide_entries(ranked, max_entries=max_entries)
    selected = _ensure_registry_chain_entries(selected, skill, index)

    composite_rows = _composite_task_guide_rows(skill)
    if not selected and not composite_rows:
        return ""

    skill_name = _skill_invoke_name(skill.name)
    peer_ops = [op for _ref, _comp, op in selected]
    lines = [
        "## 任务指南",
        "",
        f"调用表中任何 SDK 工具之前，**必须先** ``Skill(skill=\"{skill_name}\")``，"
        "再按「搜索建议」调用 ``ToolSearch``，最后调用工具本身。",
        "",
        "用户用自然语言描述任务时，**先读下表**，再用表中「搜索建议」作为 "
        "`ToolSearch(query=...)` 的查询（可直接使用用户原话或同义改写）。"
        "无需让用户提供工具名。",
        "",
        "| 用户意图（示例） | 工具 | 搜索建议 | 说明 |",
        "|----------------|------|----------|------|",
    ]

    for intent, tool_ref, search, summary in composite_rows:
        lines.append(f"| {intent} | `{tool_ref}` | {search} | {summary} |")

    for tool_ref, comp, op in selected:
        intents = "；".join(_intent_examples_from_doc(op.description, op.name))
        search = format_search_suggestions(op, comp_name=comp.name)
        summary = _build_row_summary(
            comp,
            op,
            peer_ops,
            tool_deps_index=tool_deps_index,
        )
        lines.append(
            f"| {intents} | `{tool_ref}` | {search} | {summary} |"
        )

    lines.append("")
    lines.append(
        "若首次 ToolSearch 无匹配，用同义词改写后再搜一次；"
        "仍失败时阅读 Skill 的 `description` 并尝试表中其他行。"
    )
    lines.append("")
    return "\n".join(lines)


def append_task_guide_to_skill_body(
    body: str,
    skill: SkillSpec,
    components: list[SourceComponent],
    *,
    tool_deps_index: dict | None = None,
) -> str:
    """Insert task guide after the skill description block."""
    guide = generate_task_guide_markdown(
        skill,
        components,
        tool_deps_index=tool_deps_index,
    )
    if not guide:
        return body
    if "## 任务指南" in body:
        return body
    parts = body.split("\n\n", 1)
    if len(parts) == 2:
        return f"{parts[0]}\n\n{guide}\n{parts[1]}"
    return f"{body}\n\n{guide}"


def format_flat_skill_markdown(
    skill: SkillSpec,
    *,
    components: list[SourceComponent] | None = None,
    skill_suffix: str = "-skill",
    contract: object | None = None,
    bridge_tool: str | None = None,
    tool_deps_index: dict | None = None,
) -> str:
    """Format a flat ``*-skill.md`` file (frontmatter + body + optional tool list)."""
    from extensions.sop_converter.workflow_mode.generator.artifact_semantics import (
        format_io_contract_markdown,
    )

    skill_name = f"{skill.name}{skill_suffix}"
    allowed_tools = list(skill.allowed_tools)
    if bridge_tool and bridge_tool not in allowed_tools:
        allowed_tools.append(bridge_tool)
    elif contract is not None:
        bridge_candidate = "autoresearchclaw-execute-stage"
        if (
            "researchclaw-pipeline-execute-stage" in allowed_tools
            and bridge_candidate not in allowed_tools
        ):
            allowed_tools.append(bridge_candidate)

    lines = [
        "---",
        f"name: {skill_name}",
        f"description: {skill.description}",
        "user-invocable: true",
        "allowed-tools:",
    ]
    for tool in allowed_tools:
        lines.append(f"  - {tool}")
    lines.append("---")
    lines.append("")
    lines.append(f"# Skill: {skill_name}")
    lines.append("")
    lines.append(skill.description)
    lines.append("")

    if contract is not None:
        io_section = format_io_contract_markdown(contract)
        if io_section:
            lines.append(io_section)
            lines.append("")

    if components:
        guide_skill = SkillSpec(
            name=skill.name,
            description=skill.description,
            allowed_tools=allowed_tools,
        )
        guide = generate_task_guide_markdown(
            guide_skill,
            components,
            tool_deps_index=tool_deps_index,
        )
        if guide:
            lines.append(guide)

    lines.append("## Included Tools")
    for tool in allowed_tools:
        lines.append(f"- `{tool}`")
    return "\n".join(lines) + "\n"
