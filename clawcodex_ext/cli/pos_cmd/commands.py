"""Fast-path ``clawcodex-dev pos`` CLI commands.

Usage::

    clawcodex-dev pos convert <sdk_spec> [--out <output_dir>]
        [--requirements "<requirements>"] [--name <agent_name>]
        [--strategy <strategy>] [--skills <skills_dir>]
        [--max-groups <N>] [--mapping-rules <file>]
        [--llm-provider <provider>] [--llm-model <model>]
        [--preview] [--all] [--register-tools]

    clawcodex-dev pos convert docker_build,k8s_apply \\
        --out ./.clawcodex --requirements "CI/CD pipeline" --name cicd-agent

    # Source directory auto-detection (默认筛选外部接口，加 --all 包含全部方法):
    clawcodex-dev pos convert ./src \\
        --out ./.clawcodex --strategy component --skills ./skills

Options:

    --strategy <strategy>   Grouping strategy (keyword|component|io|llm).
                            Only used when <sdk_spec> is a directory.
    --skills <skills_dir>   Output path for generated skill files.
    --all                   Include all public methods (disable external
                            interface filtering).  Default: extern-only.
    --register-tools        Register each operation as an executable Tool
                            (bash call_type + wrapper script) and persist
                            specs to ~/.clawcodex/agent-tools/.  Off by
                            default for backward compatibility.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from clawcodex_ext.cli.subcommand_registry import register

if TYPE_CHECKING:
    from extensions.pos_converter.skill_grouper import MappingRule


@register("pos")
def run_pos_command(args: list[str]) -> int:
    """Dispatch ``pos`` sub-subcommands (currently only ``convert``)."""
    if not args:
        print("usage: clawcodex pos convert <sdk_spec> [options]", file=sys.stderr)
        return 2

    command = args[0]
    rest = args[1:]

    if command == "convert":
        return _handle_convert(rest)

    print(f"Unknown pos command: {command}", file=sys.stderr)
    print("usage: clawcodex pos convert <sdk_spec> [options]", file=sys.stderr)
    return 2


def _parse_convert_args(
    args: list[str],
) -> tuple[str, str, str, str, str, str, int, str, str, str, bool, bool, bool]:
    """Parse ``pos convert`` arguments.

    Returns (sdk_spec, output_dir, requirements, agent_name, strategy, skills_dir, max_groups, mapping_rules_file, llm_provider, llm_model, preview, all_methods, register_tools).
    """
    if not args:
        print("error: missing <sdk_spec> argument", file=sys.stderr)
        print(
            "usage: clawcodex pos convert <sdk_spec> [--out <dir>] [--requirements <req>] [--name <name>] [--strategy <strategy>] [--skills <skills_dir>] [--max-groups <N>] [--mapping-rules <file>] [--llm-provider <provider>] [--llm-model <model>] [--preview] [--all]",
            file=sys.stderr,
        )
        raise SystemExit(2)

    sdk_spec = args[0]
    output_dir = ""
    requirements = ""
    agent_name = ""
    strategy = ""
    skills_dir = ""
    max_groups = 0
    mapping_rules_file = ""
    llm_provider = ""
    llm_model = ""
    preview = False
    all_methods = False
    register_tools = False

    i = 1
    while i < len(args):
        token = args[i]
        if token == "--out" and i + 1 < len(args):
            output_dir = args[i + 1]
            i += 2
        elif token == "--requirements" and i + 1 < len(args):
            requirements = args[i + 1]
            i += 2
        elif token == "--name" and i + 1 < len(args):
            agent_name = args[i + 1]
            i += 2
        elif token == "--strategy" and i + 1 < len(args):
            strategy = args[i + 1]
            i += 2
        elif token == "--skills" and i + 1 < len(args):
            skills_dir = args[i + 1]
            i += 2
        elif token == "--max-groups" and i + 1 < len(args):
            try:
                max_groups = int(args[i + 1])
            except ValueError:
                print(
                    f"error: --max-groups requires an integer, got: {args[i + 1]}", file=sys.stderr
                )
                raise SystemExit(2)
            i += 2
        elif token == "--mapping-rules" and i + 1 < len(args):
            mapping_rules_file = args[i + 1]
            i += 2
        elif token == "--llm-provider" and i + 1 < len(args):
            llm_provider = args[i + 1]
            i += 2
        elif token == "--llm-model" and i + 1 < len(args):
            llm_model = args[i + 1]
            i += 2
        elif token == "--preview":
            preview = True
            i += 1
        elif token == "--all":
            all_methods = True
            i += 1
        elif token == "--register-tools":
            register_tools = True
            i += 1
        else:
            print(f"error: unknown argument: {token}", file=sys.stderr)
            raise SystemExit(2)

    return (
        sdk_spec,
        output_dir,
        requirements,
        agent_name,
        strategy,
        skills_dir,
        max_groups,
        mapping_rules_file,
        llm_provider,
        llm_model,
        preview,
        all_methods,
        register_tools,
    )


def _handle_convert(args: list[str]) -> int:
    """Handle ``pos convert`` — convert an SOP spec into an Agent."""
    try:
        (
            sdk_spec,
            output_dir,
            requirements,
            agent_name,
            strategy,
            skills_dir,
            max_groups,
            mapping_rules_file,
            llm_provider,
            llm_model,
            preview,
            all_methods,
            register_tools,
        ) = _parse_convert_args(args)
    except SystemExit:
        return 2

    sdk_path = Path(sdk_spec)

    # Auto-detection: if sdk_spec is an existing directory, use SourceCodeParser
    if sdk_path.is_dir():
        return _handle_convert_from_source(
            sdk_path,
            output_dir,
            requirements,
            agent_name,
            strategy,
            skills_dir,
            max_groups,
            mapping_rules_file,
            llm_provider,
            llm_model,
            preview,
            all_methods,
            register_tools,
        )

    # Legacy path: sdk_spec is a comma-separated spec string
    from extensions.pos_converter.convert_pos_skill import convert_pos_to_agent

    result = convert_pos_to_agent(
        sdk_spec=sdk_spec,
        requirements=requirements,
        agent_name=agent_name,
    )

    if result["status"] == "error":
        print(f"error: {result.get('error', 'conversion failed')}", file=sys.stderr)
        return 2

    # Print summary to stdout
    print(f"✅ Converted SOP: {result['agent_type']}")
    print(f"   Description: {result['agent_description']}")
    print(f"   Model: {result.get('model', 'default')}")
    print(f"   Skills: {len(result['skills'])}")
    for skill in result["skills"]:
        print(f"     - {skill['name']} ({', '.join(skill['tools'])})")
    print(f"   Tools: {len(result.get('tools', []))}")
    print(f"   Persistence: {result['persist_status']}")

    if result.get("warnings"):
        for w in result["warnings"]:
            print(f"   Warning: {w}", file=sys.stderr)

    # If --out is specified, write the output files to the target directory
    if output_dir:
        _write_output_files(output_dir, result, sdk_spec, requirements, agent_name)

    return 0


def _handle_convert_from_source(
    sdk_path: Path,
    output_dir: str,
    requirements: str,
    agent_name: str | None,
    strategy: str,
    skills_dir: str,
    max_groups: int = 0,
    mapping_rules_file: str = "",
    llm_provider_name: str = "",
    llm_model: str = "",
    preview: bool = False,
    all_methods: bool = False,
    register_tools: bool = False,
) -> int:
    """Convert a source code directory into Agents via SourceCodeParser + grouping strategy.

    Generates one agent per grouped Skill (not per raw SourceComponent),
    plus an overview agent.  The --strategy flag controls how components
    are merged: COMPONENT_GROUP (default, 1:1), KEYWORD_MATCH, IO_RELATION,
    or LLM_SEMANTIC.

    --mapping-rules accepts a YAML/JSON file with custom MappingRule definitions
    for KEYWORD_MATCH strategy.
    --llm-provider and --llm-model control which LLM backend is used for
    LLM_SEMANTIC strategy.  When omitted, the default provider from
    ~/.clawcodex/config.json is used.
    --all includes all public methods; by default only documented external
    interfaces (docstring-required) are kept.
    """
    from extensions.pos_converter.source_parser import SourceCodeParser
    from extensions.pos_converter.skill_grouper import (
        GroupStrategy,
        group_source_components,
        SkillSpec,
        MappingRule,
        MatchType,
    )
    from extensions.pos_converter.agent_md_writer import (
        AgentMarkdownWriter,
        AgentComponentInfo,
        WorkflowStage,
    )

    parser = SourceCodeParser(str(sdk_path), extern_only=not all_methods)
    components = parser.parse()

    if not components:
        print("error: No source components found in directory", file=sys.stderr)
        return 2

    parsed_strategy = strategy.lower() if strategy else ""
    if parsed_strategy == "keyword":
        group_strategy = GroupStrategy.KEYWORD_MATCH
    elif parsed_strategy == "io":
        group_strategy = GroupStrategy.IO_RELATION
    elif parsed_strategy == "llm":
        group_strategy = GroupStrategy.LLM_SEMANTIC
    else:
        group_strategy = GroupStrategy.COMPONENT_GROUP

    custom_rules: list[MappingRule] | None = None
    if mapping_rules_file and group_strategy == GroupStrategy.KEYWORD_MATCH:
        custom_rules = _load_mapping_rules(mapping_rules_file)

    llm_provider_obj = None
    if group_strategy == GroupStrategy.LLM_SEMANTIC:
        llm_provider_obj = _create_llm_provider(llm_provider_name, llm_model)
        if llm_provider_obj is None:
            print(
                "warning: LLM_SEMANTIC requires a configured LLM provider; falling back to keyword match strategy",
                file=sys.stderr,
            )
            group_strategy = GroupStrategy.KEYWORD_MATCH

    group_result = group_source_components(
        components,
        strategy=group_strategy,
        max_io_groups=max_groups if max_groups > 0 else None,
        mapping_rules=custom_rules,
        requirements=requirements,
        llm_provider=llm_provider_obj,
    )
    grouped_skills: list[SkillSpec] = group_result.skills

    # ── Tool registration ──
    # Convert each SourceOperation into an executable Tool (bash call_type +
    # wrapper script), persist specs to ~/.clawcodex/agent-tools/, and
    # rewrite skill.allowed_tools with kebab-case names so agent markdown
    # can find them in the ToolRegistry at runtime.
    if register_tools and not preview:
        try:
            from extensions.pos_converter.tool_registry_bridge import (
                register_component_tools,
                _to_kebab_case,
            )

            registered = register_component_tools(
                components,
                str(sdk_path),
                persist=True,
            )
            # Rewrite tool names in skills to match what was actually
            # registered in the ToolRegistry.  The name_map returned by
            # register_component_tools maps every naming convention
            # (file_stem-based, grouper-based, fully-qualified) to the
            # actual kebab-case spec name.
            for skill in grouped_skills:
                skill.allowed_tools = [
                    registered.get(t, _to_kebab_case(t)) for t in skill.allowed_tools
                ]
            if registered:
                print(f"   Registered tools: {len(registered)}")
        except ImportError as exc:
            print(
                f"   Warning: tool registration skipped (missing module: {exc})",
                file=sys.stderr,
            )
        except Exception as exc:
            print(
                f"   Warning: tool registration failed: {exc}",
                file=sys.stderr,
            )

    # Build per-skill AgentComponentInfo for the overview agent.
    overview_info: list[AgentComponentInfo] = []
    for skill in grouped_skills:
        overview_info.append(
            AgentComponentInfo(
                name=f"{skill.name}-agent",
                description=skill.description,
                capabilities=skill.allowed_tools[:5],
                invoke_pattern=f"@{skill.name}-agent {{task}}",
            )
        )

    overview_count = 1 if len(overview_info) > 1 else 0
    total_agents = len(grouped_skills) + overview_count

    if preview:
        # ── Preview mode: print clean summary, skip all file writes ──
        strategy_labels = {
            "IO_RELATION": "IO_RELATION",
            "KEYWORD_MATCH": "KEYWORD_MATCH",
            "LLM_SEMANTIC": "LLM_SEMANTIC",
            "COMPONENT_GROUP": "COMPONENT_GROUP",
        }
        label = strategy_labels.get(group_strategy.name, group_strategy.name)
        print(f"[Preview] Strategy: {label}")
        if not all_methods:
            print(f"   Filter: external interfaces only (default)")
        else:
            print(f"   Filter: --all (all public methods)")
        print(f"   Source Components: {len(components)}")
        print(f"   Grouped Skills: {len(grouped_skills)}")
        print(
            f"   Agent file count: {total_agents} ({len(grouped_skills)} + {overview_count} overview)"
        )
        if len(components) != len(grouped_skills):
            reduction = 100 - int(len(grouped_skills) / len(components) * 100)
            print(f"   Agent 缩减率: {reduction}% ({len(components)} → {total_agents})")
        print(f"   Skills:")
        for skill in grouped_skills:
            sample_tools = skill.allowed_tools[:3]
            sample_str = ", ".join(sample_tools)
            if len(skill.allowed_tools) > 3:
                sample_str += ", …"
            print(f"     - {skill.name}-agent ({len(skill.allowed_tools)} tools): {sample_str}")
        if group_result.unmatched_tools:
            for w in group_result.unmatched_tools:
                print(f"   Warning: unmatched tool: {w}", file=sys.stderr)
        return 0

    # ── Normal mode: write files + print summary ──
    writer = AgentMarkdownWriter()
    if output_dir:
        out_path = Path(output_dir)
        for skill in grouped_skills:
            agent_def = {
                "name": f"{skill.name}-agent",
                "description": skill.description,
                "tools": skill.allowed_tools,
                "skills": [],
            }
            writer.write_agent(agent_def, out_path)

        # Overview agent — always generated when there are 2+ agents
        if len(overview_info) > 1:
            writer.write_overview_agent(
                name=agent_name or "clawcodex-overview",
                description=f"Overview agent for {agent_name or 'project'}",
                component_agents=overview_info,
                workflow_stages=[],
                output_dir=out_path,
            )

    # Write skills if --skills was specified
    if skills_dir:
        skills_path = Path(skills_dir)
        skills_path.mkdir(parents=True, exist_ok=True)
        for skill in grouped_skills:
            skill_file = skills_path / f"{skill.name}-skill.md"
            skill_lines = [
                "---",
                f"name: {skill.name}-skill",
                f"description: {skill.description}",
                "user-invocable: true",
                "allowed-tools:",
            ]
            for tool in skill.allowed_tools:
                skill_lines.append(f"  - {tool}")
            skill_lines.append("---")
            skill_lines.append("")
            skill_lines.append(f"# Skill: {skill.name}-skill")
            skill_lines.append("")
            skill_lines.append(skill.description)
            skill_lines.append("")
            skill_lines.append("## Included Tools")
            for tool in skill.allowed_tools:
                skill_lines.append(f"- `{tool}`")
            skill_file.write_text("\n".join(skill_lines), encoding="utf-8")
            print(f"   Skill file: {skill_file}")

    # Print summary — show actual agent count after grouping
    print(f"✅ Converted source directory to Agents: {sdk_path}")
    print(f"   Source components: {len(components)}")
    print(f"   Grouped skills (agents): {len(grouped_skills)}")
    print(f"   Strategy: {group_strategy.name}")
    if len(components) != len(grouped_skills):
        reduction = 100 - int(len(grouped_skills) / len(components) * 100)
        print(
            f"   Agent reduction: {reduction}% ({len(components)} components → {total_agents} agents)"
        )
    for i, skill in enumerate(grouped_skills):
        print(f"     Agent {i + 1}: {skill.name}-agent")
        print(f"       Description: {skill.description}")
        print(f"       Tools: {len(skill.allowed_tools)}")
    if group_result.unmatched_tools:
        for w in group_result.unmatched_tools:
            print(f"   Warning: unmatched tool: {w}", file=sys.stderr)

    return 0


def _load_mapping_rules(file_path: str) -> list[MappingRule]:
    """Load custom MappingRule definitions from a YAML or JSON file.

    Expected format (YAML):
        rules:
          - method_pattern: "docker_"
            tool_name: "docker_ops"
            skill_name: "build_image"
            description: "Docker build operations"
            match_type: "prefix"
          - method_pattern: "video_encode|video_decode"
            tool_name: "video_ops"
            skill_name: "video_processing"
            description: "Video codec operations"
            match_type: "regex"
          - method_pattern: "core"
            tool_name: "core_ops"
            skill_name: "core"
            description: "Core module operations"
            match_type: "substring"
            match_target: "comp_name"

    Expected format (JSON):
        {
          "rules": [
            {"method_pattern": "docker_", "tool_name": "docker_ops", "skill_name": "build_image", "description": "...", "match_type": "prefix"}
          ]
        }
    """
    from extensions.pos_converter.skill_grouper import MappingRule, MatchType, MatchTarget
    import json

    path = Path(file_path)
    if not path.is_file():
        print(f"error: mapping rules file not found: {file_path}", file=sys.stderr)
        raise SystemExit(2)

    raw = path.read_text(encoding="utf-8")

    try:
        if path.suffix in (".yaml", ".yml"):
            try:
                import yaml

                data = yaml.safe_load(raw)
            except ImportError:
                print(
                    "error: PyYAML not installed, use JSON format for mapping rules",
                    file=sys.stderr,
                )
                raise SystemExit(2)
        else:
            data = json.loads(raw)
    except (json.JSONDecodeError, Exception) as exc:
        print(f"error: failed to parse mapping rules file: {exc}", file=sys.stderr)
        raise SystemExit(2)

    rules_raw = data.get("rules", [])
    rules: list[MappingRule] = []
    for entry in rules_raw:
        match_type_str = entry.get("match_type", "substring")
        try:
            match_type = MatchType(match_type_str)
        except ValueError:
            match_type = MatchType.SUBSTRING
        match_target_str = entry.get("match_target", "op_name")
        try:
            match_target = MatchTarget(match_target_str)
        except ValueError:
            match_target = MatchTarget.OP_NAME
        method_pattern = entry.get("method_pattern", "")
        skill_name = entry.get("skill_name", "")
        if not method_pattern or not skill_name:
            print(
                f"warning: skipping mapping rule entry missing method_pattern or skill_name: {entry}",
                file=sys.stderr,
            )
            continue
        rules.append(
            MappingRule(
                method_pattern=method_pattern,
                tool_name=entry.get("tool_name", ""),
                skill_name=skill_name,
                description=entry.get("description", ""),
                match_type=match_type,
                match_target=match_target,
            )
        )

    return rules


def _create_llm_provider(provider_name: str, model: str) -> object | None:
    """Create an LLM provider for LLM_SEMANTIC strategy.

    Uses the project's ``build_provider_from_config`` infrastructure.
    Falls back to the default provider from config when ``provider_name``
    is empty.  Returns None when no provider can be created (missing
    API key, unknown provider, etc.).
    """
    try:
        from src.providers.runtime import build_provider_from_config
        from src.config import get_default_provider

        resolved_name = provider_name or get_default_provider()
        resolved_model = model or None
        return build_provider_from_config(resolved_name, model=resolved_model)
    except Exception as exc:
        print(f"warning: failed to create LLM provider '{provider_name}': {exc}", file=sys.stderr)
        return None


def _write_output_files(
    out_dir: str,
    result: dict,
    sdk_spec: str,
    requirements: str,
    agent_name: str,
) -> None:
    """Write agent definition + skill files to ``out_dir`` in loadable format.

    Output layout:
      ``.claude/agents/<name>.md``         — agent definition (loadable by ``@agent-<name>``)
      ``.atomcode/skills/<name>/SKILL.md``   — skill files (loadable by skill system)
      ``workflows/pos-<name>.yaml``          — orchestrator workflow (unchanged)
      ``skills/pos-<name>-<skill>/SKILL.md`` — legacy compat (deprecated)
    """
    from extensions.pos_converter.agent_md_writer import AgentMarkdownWriter

    base = Path(out_dir).resolve()
    workflows_dir = base / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)

    name = result["agent_type"]
    skill_files = result.get("skill_files", [])
    skill_names = [s["name"] for s in result["skills"]]

    # --- .claude/agents/<name>.md — loadable by @agent-name ---
    writer = AgentMarkdownWriter()
    agent_def = {
        "name": name,
        "description": result["agent_description"],
        "model": result.get("model", "default"),
        "tools": result.get("tools", []),
        "skills": skill_names,
    }
    agent_path = writer.write_agent(agent_def, base)
    print(f"   Agent: {agent_path}")

    # --- .atomcode/skills/<name>/SKILL.md — loadable by skill system ---
    skills_for_writer = []
    for skill in result["skills"]:
        skills_for_writer.append(
            {
                "name": skill["name"],
                "description": skill["description"],
                "allowed_tools": skill["tools"],
                "parameters": [],
                "source_code": "",
            }
        )
    if skills_for_writer:
        skill_paths = writer.write_skills(skills_for_writer, base)
        for sp in skill_paths:
            print(f"   Skill: {sp}")

    # --- Legacy compat: skills/pos-<name>-<skill>/SKILL.md (deprecated) ---
    # TODO: remove in next major version; users should migrate to .atomcode/skills/
    import warnings

    warnings.warn(
        "The `skills/` output directory is deprecated and will be removed "
        "in a future release. Use `.atomcode/skills/` instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    skills_dir = base / "skills"
    for skill in result["skills"]:
        skill_name = skill["name"]
        skill_dir = skills_dir / f"pos-{name}-{skill_name}"
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_path = skill_dir / "SKILL.md"
        lines = [
            "---",
            f"name: {skill_name}",
            f"description: {skill['description']}",
            "user-invocable: true",
            "allowed-tools:",
        ]
        for tool in skill["tools"]:
            lines.append(f"  - {tool}")
        lines.append("---")
        lines.append("")
        lines.append(f"# Skill: {skill_name}")
        lines.append("")
        lines.append(skill["description"])
        lines.append("")
        lines.append("## Included Tools")
        for tool in skill["tools"]:
            lines.append(f"- `{tool}`")
        skill_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"   Skill (legacy): {skill_path}")

    # --- Workflow orchestration graph (unchanged) ---
    workflow_path = workflows_dir / f"pos-{name}.yaml"
    workflow_lines = [
        f"# Workflow: {name}",
        "# Auto-generated by clawcodex pos convert",
        "",
        "nodes:",
    ]
    for skill in result["skills"]:
        workflow_lines.append(f"  - id: {skill['name']}")
        workflow_lines.append(f"    agent: {name}")
        workflow_lines.append(f"    skill: {skill['name']}")
        workflow_lines.append(f"    tools: [{', '.join(skill['tools'])}]")
    workflow_path.write_text("\n".join(workflow_lines), encoding="utf-8")
    print(f"   Workflow: {workflow_path}")

    # --- Also copy any old-format skill files from converter ---
    for src_path_str in skill_files:
        src_path = Path(src_path_str)
        if src_path.exists():
            skills_dir.mkdir(parents=True, exist_ok=True)
            dest = skills_dir / src_path.name
            if not dest.exists():
                dest.write_text(src_path.read_text(encoding="utf-8"), encoding="utf-8")
