"""Generates optimization proposals from analysis reports."""
from __future__ import annotations
import json
import os
import logging
from typing import Any, Dict, List, Optional
from src.models import AnalysisReport, OptimizationProposal, ProposalType, ProposalStatus, dataclass_to_dict
from src.skill_creator import is_skill_duplicate
from src.utils import read_text, setup_logger, extract_json_from_llm, load_available_skills

logger = setup_logger("proposal_generator")
_PROMPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "prompts")
PROPOSAL_GENERATOR_PROMPT_PATH = os.path.join(_PROMPT_DIR, "proposal_generator.md")


class ProposalGenerator:
    """Generates optimization proposals based on trace analysis."""
    def __init__(self, config: Dict[str, Any], llm_caller=None) -> None:
        self.config = config
        self.llm_caller = llm_caller

    def generate(self, analysis: AnalysisReport, focus_areas: list[str] | None = None) -> List[OptimizationProposal]:
        proposals: List[OptimizationProposal] = []
        wants = set(focus_areas or ["prompt", "skill", "code"])

        # Path 1: Section-level prompt analysis (ClawCodex system prompt sections)
        if "prompt" in wants:
            section_flags = [sa for sa in analysis.section_analyses if sa.needs_optimization and sa.section_id != "_skill_extraction"]
            if section_flags:
                logger.info("Generating proposals from %d flagged section(s)", len(section_flags))
                if self.llm_caller:
                    proposals.extend(self._generate_from_sections(analysis, section_flags))
                else:
                    proposals.extend(self._generate_heuristic_from_sections(analysis, section_flags))

        # Path 2a: Skill creation (from section analysis flagged as skill_extraction)
        if "skill" in wants:
            skill_extractions = [sa for sa in analysis.section_analyses if sa.needs_optimization and sa.section_id == "_skill_extraction"]
            if skill_extractions:
                logger.info("Generating skill extraction proposals from %d candidate(s)", len(skill_extractions))
                if self.llm_caller:
                    proposals.extend(self._generate_skill_extraction_proposals(analysis, skill_extractions))
                else:
                    proposals.extend(self._generate_skill_extraction_heuristic(analysis, skill_extractions))

        # Path 2b: Skill modification (from skill_issues / skill_usage_analysis)
        if "skill" in wants:
            has_skill_issues = bool(analysis.skill_issues or analysis.skill_failure_analysis or any(s.get("skill_content") for s in analysis.skill_usage_analysis))
            if has_skill_issues:
                logger.info("Skill issues detected; generating skill proposals")
                if self.llm_caller:
                    proposals.extend(self._generate_skill_proposals_llm(analysis))
                else:
                    proposals.extend(self._generate_skill_proposals_heuristic(analysis))

        # Path 4: Fallback - only when nothing was generated AND full mode
        if not proposals and wants == {"prompt", "skill", "code"}:
            if self.llm_caller:
                return self._generate_with_llm(analysis)
            return self._generate_heuristic(analysis)

        # Filter out SKILL_ADDITION proposals for skills that already exist
        filtered = []
        existing = load_available_skills()
        for p in proposals:
            if p.proposal_type == ProposalType.SKILL_ADDITION:
                try:
                    import json as _j
                    pc = p.proposed_content
                    params = _j.loads(pc) if pc.startswith('{') else {"name": p.target, "summary": "", "trigger_condition": ""}
                except Exception:
                    params = {"name": p.target, "summary": "", "trigger_condition": ""}
                dup, match = is_skill_duplicate(params, existing)
                if dup:
                    logger.info("Skipping redundant skill proposal '%s' (similar to '%s')", p.target, match)
                    continue
            filtered.append(p)
        proposals = filtered
        return proposals

    def _generate_skill_proposals_heuristic(self, analysis: AnalysisReport) -> List[OptimizationProposal]:
        """Generate skill-related proposals from heuristic analysis data."""
        proposals: List[OptimizationProposal] = []

        for issue in analysis.skill_usage_analysis:
            msg = issue.get("issue", "")
            if "No tool calls" in msg:
                proposals.append(OptimizationProposal(
                    source_trace_id=analysis.trace_id,
                    proposal_type=ProposalType.SKILL_ADDITION,
                    target="relevant_skill",
                    current_content="No tools were used during task execution",
                    proposed_content="Add task-relevant skill to guide tool usage",
                    reason="Agent did not use any tools; a skill could help activate appropriate tooling",
                    expected_improvement="Enable effective tool usage for task execution",
                    priority=2,
                    status=ProposalStatus.PENDING,
                ))
            else:
                proposals.append(OptimizationProposal(
                    source_trace_id=analysis.trace_id,
                    proposal_type=ProposalType.SKILL_MODIFICATION,
                    target="tool_usage_skill",
                    current_content=msg[:200],
                    proposed_content=f"Review and optimize: {msg[:200]}",
                    reason="Skill usage issue detected during trace analysis",
                    expected_improvement="Improved tool selection and usage",
                    priority=2,
                    status=ProposalStatus.PENDING,
                ))

        for issue in analysis.skill_issues:
            proposals.append(OptimizationProposal(
                source_trace_id=analysis.trace_id,
                proposal_type=ProposalType.SKILL_MODIFICATION,
                target=issue.get("skill_name", "unknown_skill"),
                current_content=issue.get("current_behavior", "")[:200],
                proposed_content=issue.get("suggested_change", "")[:200],
                reason=issue.get("reason", "Skill issue detected")[:200],
                expected_improvement="Improved skill reliability",
                priority=issue.get("priority", 3),
                status=ProposalStatus.PENDING,
            ))

        return proposals

    def _generate_skill_proposals_llm(self, analysis: AnalysisReport) -> List[OptimizationProposal]:
        """Generate skill-related proposals using LLM."""
        # Extract actual skill definitions from skill_usage_analysis
        _loaded_skills = {}
        for _sua in analysis.skill_usage_analysis:
            _sc = _sua.get("skill_content")
            if _sc and isinstance(_sc, dict) and _sc.get("name"):
                _loaded_skills[_sc["name"]] = _sc
        skill_data = {
            "skill_issues": analysis.skill_issues,
            "skill_usage_analysis": analysis.skill_usage_analysis,
            "skill_failure_analysis": analysis.skill_failure_analysis,
            "loaded_skills": _loaded_skills,
            "task_description": analysis.task_description,
            "trace_errors": analysis.errors[:3],
        }
        prompt = (
            "You are generating skill optimization proposals based on execution trace analysis.\n"
            "## Skill Analysis Data\n{skill_json}\n"
            "## Requirements\n"
            "For each skill-related issue, generate a specific optimization proposal.\n"
            'Use proposal_type \"skill_addition\" for missing skills, \"skill_modification\" for improvements.\n'
            "For skill_modification proposals, current_content must be the JSON-encoded full current skill definition "
            "of the skill being modified (copy it verbatim from loaded_skills).\n"
            "For all proposals, the **proposed_content** field must be a JSON-encoded string containing a complete "
            "skill definition with the following keys:\n"
            '- "name": short skill name (snake_case)\n'
            '- "summary": one-paragraph description of what this skill does\n'
            '- "trigger_condition": when an agent should use this skill (optional)\n'
            '- "sop": array of step-by-step instructions (each step is a string)\n'
            '- "pitfalls": array of common mistakes or edge cases to watch for\n'
            "Example proposed_content value:\n"
            '`{{"name": "implement_fibonacci", "summary": "Implement fibonacci using iteration", "trigger_condition": "task asks for fibonacci", "sop": ["Understand requirements and edge cases", "Plan iterative approach", "Write the function with proper base cases", "Test with pytest"], "pitfalls": ["Recursion causes stack overflow for large n"]}}`\n'
            "Other proposal fields:\n"
            "1. target: the skill name (same as name in proposed_content)\n"
            "2. current_content: the current skill's full JSON definition (for skill_modification) or issue description (for skill_addition)\n"
            "3. reason: why this change helps\n"
            "4. expected_improvement: how this skill will help future task execution\n"
            "5. priority: 1-3\n"
            "## Output Format (valid JSON only)\n"
            '```json\n{{"proposals": [{{"target": "...", "proposal_type": "skill_addition", "current_content": "...", "proposed_content": "...", "reason": "...", "expected_improvement": "...", "priority": 2}}]}}\n```'
        ).format(skill_json=json.dumps(skill_data, ensure_ascii=False, indent=2))

        raw = self.llm_caller(prompt)
        data = extract_json_from_llm(raw)
        if data is None:
            logger.warning("Skill proposal LLM returned invalid JSON; falling back to heuristic.")
            return []

        proposals: List[OptimizationProposal] = []
        for p in data.get("proposals", []):
            pt = p.get("proposal_type", "skill_modification")
            try:
                ptype = ProposalType(pt)
            except ValueError:
                ptype = ProposalType.SKILL_MODIFICATION
            proposals.append(OptimizationProposal(
                source_trace_id=analysis.trace_id,
                proposal_type=ptype,
                target=p.get("target", "unknown"),
                current_content=p.get("current_content", ""),
                proposed_content=p.get("proposed_content", ""),
                reason=p.get("reason", ""),
                expected_improvement=p.get("expected_improvement", ""),
                priority=p.get("priority", 3),
                status=ProposalStatus.PENDING,
            ))
        return proposals

    @staticmethod
    def _generate_skill_extraction_heuristic(analysis, candidates):
        proposals = []
        for sa in candidates:
            summary = sa.suggested_improvement[:200] if sa.suggested_improvement else ""
            skill_params = {
                "name": (sa.suggested_improvement or "extracted_skill").split(".")[0].split(":")[0].strip().lower().replace(" ", "_")[:40] or "extracted_skill",
                "summary": summary,
                "trigger_condition": f"When the task involves: {sa.section_content[:100]}",
                "sop": ["Understand the task requirements",
                        "Follow the established pattern from previous successful execution",
                        "Verify the output meets requirements"],
                "pitfalls": ["Ensure similar context before applying this pattern"],
            }
            proposals.append(OptimizationProposal(
                source_trace_id=analysis.trace_id,
                proposal_type=ProposalType.SKILL_ADDITION,
                target=skill_params["name"],
                current_content=sa.section_content[:2000],
                proposed_content=json.dumps(skill_params, ensure_ascii=False),
                reason=sa.reasoning[:200] if sa.reasoning else "Successful execution pattern",
                expected_improvement="Reusable skill for similar future tasks",
                priority=2,
                status=ProposalStatus.PENDING,
            ))
        return proposals

    def _generate_skill_extraction_proposals(self, analysis, candidates):
        prompt = (
            "You are converting execution trace analysis into a reusable skill definition.\n"
            "## Skill Extraction Candidate\n"
            "{candidate_json}\n"
            "## Requirements\n"
            "Generate one skill_addition proposal.\n"
            "The **proposed_content** field must be a JSON-encoded string containing a complete "
            "skill definition with the following keys:\n"
            '- "name": short skill name (snake_case)\n'
            '- "summary": one-paragraph description of what this skill does\n'
            '- "trigger_condition": when an agent should use this skill (optional)\n'
            '- "sop": array of step-by-step instructions (each step is a string)\n'
            '- "pitfalls": array of common mistakes or edge cases to watch for\n'
            "Example proposed_content value:\n"
            '`{{"name": "implement_fibonacci", "summary": "Implement fibonacci using iteration", '
            '"trigger_condition": "task asks for fibonacci", '
            '"sop": ["Understand requirements and edge cases", "Plan iterative approach", '
            '"Write the function with proper base cases", "Test with pytest"], '
            '"pitfalls": ["Recursion causes stack overflow for large n"]}}`\n'
            "Other proposal fields:\n"
            "1. target: the skill name (same as name in proposed_content)\n"
            "2. current_content: the task description that was executed\n"
            "3. reason: why this pattern is worth encoding as a skill\n"
            "4. expected_improvement: how this skill will help future task execution\n"
            "5. priority: 1-3\n"
            "## Output Format (valid JSON only)\n"
            '```json\n{{"proposals": [{{"target": "skill_name", "proposal_type": "skill_addition", '
            '"current_content": "...", "proposed_content": "{\\"name\\": ...}", '
            '"reason": "...", "expected_improvement": "...", "priority": 2}}]}}\n```'
        ).format(candidate_json=json.dumps(
            [{"section_id": sa.section_id, "task": sa.section_content[:300],
              "improvement": sa.suggested_improvement[:500], "reasoning": sa.reasoning[:200]}
             for sa in candidates],
            ensure_ascii=False, indent=2,
        ))

        raw = self.llm_caller(prompt)
        data = extract_json_from_llm(raw)
        if data is None:
            logger.warning("Skill extraction LLM returned invalid JSON; falling back to heuristic")
            return self._generate_skill_extraction_heuristic(analysis, candidates)

        proposals = []
        for p in data.get("proposals", []):
            raw_content = p.get("proposed_content", "{}")
            try:
                skill_params = json.loads(raw_content)
                if not isinstance(skill_params, dict) or not skill_params.get("name"):
                    raise ValueError("Missing name in skill params")
            except (json.JSONDecodeError, ValueError, TypeError):
                logger.warning("Invalid skill params JSON in proposal; wrapping as summary")
                skill_params = {"name": p.get("target", "extracted_skill"),
                                "summary": raw_content[:300], "sop": [], "pitfalls": []}
            proposals.append(OptimizationProposal(
                source_trace_id=analysis.trace_id,
                proposal_type=ProposalType.SKILL_ADDITION,
                target=p.get("target", skill_params.get("name", "extracted_skill")),
                current_content=p.get("current_content", ""),
                proposed_content=json.dumps(skill_params, ensure_ascii=False),
                reason=p.get("reason", ""),
                expected_improvement=p.get("expected_improvement", ""),
                priority=p.get("priority", 2),
                status=ProposalStatus.PENDING,
            ))
        return proposals

    def _generate_from_sections(self, analysis, flagged):
        sections_json = json.dumps(
            [{"section_id": sa.section_id, "section_content": sa.section_content[:2000],
              "issues_found": sa.issues_found, "suggested_improvement": sa.suggested_improvement,
              "reasoning": sa.reasoning} for sa in flagged],
            ensure_ascii=False, indent=2,
        )
        prompt = (
            "You are generating targeted optimization proposals for specific ClawCodex system prompt sections.\n"
            "## Sections Flagged for Optimization\n{sections_json}\n"
            "## Requirements\n"
            "For each flagged section, generate one optimization proposal. Each proposal must include:\n"
            "1. target: the section_id\n"
            "2. current_content: the EXACT text snippet being replaced (copy verbatim from section_content)\n"
            "3. proposed_content: the FULL replacement text for the section (the complete new section content, not just changed lines)\n"
            "4. reason: why this change helps\n"
            "5. expected_improvement: expected effect\n"
            "6. priority: 1-3\n"
            "## IMPORTANT: Python Syntax Constraint\n"
            "The section content is a Python string constant in prompt_assembly.py. proposed_content must be a BARE string value (no Python quotes, triple quotes, commas, or parentheses). Just the plain text.\n"
            "## Output Format (valid JSON only)\n"
            '```json\n{{"proposals": [{{"target": "section_id", "current_content": "...", '
            '"proposed_content": "...", "reason": "...", "expected_improvement": "...", '
            '"priority": 2}}]}}\n```'
        ).format(sections_json=sections_json)

        raw = self.llm_caller(prompt)
        data = extract_json_from_llm(raw)
        if data is None:
            return self._generate_heuristic_from_sections(analysis, flagged)

        proposals = []
        for p in data.get("proposals", []):
            proposals.append(OptimizationProposal(
                source_trace_id=analysis.trace_id,
                proposal_type=ProposalType.PROMPT_OPTIMIZATION,
                target=p.get("target", p.get("section_id", "unknown")),
                current_content=p.get("current_content", ""),
                proposed_content=p.get("proposed_content", ""),
                reason=p.get("reason", ""),
                expected_improvement=p.get("expected_improvement", ""),
                priority=p.get("priority", 3),
                status=ProposalStatus.PENDING,
            ))
        return proposals

    @staticmethod
    def _generate_heuristic_from_sections(analysis, flagged):
        proposals = []
        for sa in flagged:
            proposals.append(OptimizationProposal(
                source_trace_id=analysis.trace_id,
                proposal_type=ProposalType.PROMPT_OPTIMIZATION,
                target=sa.section_id,
                current_content=sa.section_content[:2000],
                proposed_content=sa.section_content[:2000],
                reason="; ".join(sa.issues_found) if sa.issues_found else "Flagged by section analysis",
                expected_improvement="Improved alignment between system prompt and agent behavior",
                priority=2,
                status=ProposalStatus.PENDING,
            ))
        return proposals

    def _generate_with_llm(self, analysis):
        prompt_template = read_text(PROPOSAL_GENERATOR_PROMPT_PATH)
        if not prompt_template:
            return self._generate_heuristic(analysis)

        prompt = prompt_template.replace("{analysis_report_json}", json.dumps(dataclass_to_dict(analysis), ensure_ascii=False, indent=2))
        prompt = prompt.replace("{current_prompts}", "trajectory_analyzer.md, proposal_generator.md, evaluator.md")
        prompt = prompt.replace("{current_skills}", "(empty)")
        prompt = prompt.replace("{current_config}", json.dumps(self.config, ensure_ascii=False, indent=2))

        raw = self.llm_caller(prompt)
        data = extract_json_from_llm(raw)
        if data is None:
            return self._generate_heuristic(analysis)

        proposals = []
        for p in data.get("proposals", []):
            pt = p.get("proposal_type", "prompt_optimization")
            try:
                ptype = ProposalType(pt)
            except ValueError:
                ptype = ProposalType.PROMPT_OPTIMIZATION
            proposals.append(OptimizationProposal(
                source_trace_id=analysis.trace_id,
                proposal_type=ptype,
                target=p.get("target", ""),
                current_content=p.get("current_content", ""),
                proposed_content=p.get("proposed_content", ""),
                reason=p.get("reason", ""),
                expected_improvement=p.get("expected_improvement", ""),
                priority=p.get("priority", 3),
                status=ProposalStatus.PENDING,
            ))
        return proposals

    def _generate_heuristic(self, analysis):
        proposals = []
        for err in analysis.errors:
            err_text = err if isinstance(err, str) else err.get("description", str(err))
            proposals.append(OptimizationProposal(
                source_trace_id=analysis.trace_id,
                proposal_type=ProposalType.PROMPT_OPTIMIZATION,
                target="agent_prompt",
                current_content="",
                proposed_content="Add error handling for: " + err_text[:200],
                reason="Error detected during analysis",
                expected_improvement="Reduce error rate",
                priority=3,
            ))
        if analysis.efficiency_issues:
            eff_parts = []
            for eff in analysis.efficiency_issues:
                t = eff if isinstance(eff, str) else eff.get("issue", str(eff))
                if t and t not in eff_parts:
                    eff_parts.append(t)
            eff_summary = "; ".join(eff_parts[:8])
            if len(eff_parts) > 8:
                eff_summary += " (+" + str(len(eff_parts) - 8) + " more)"
            proposals.append(OptimizationProposal(
                source_trace_id=analysis.trace_id,
                proposal_type=ProposalType.WORKFLOW_OPTIMIZATION,
                target="execution_workflow",
                current_content="",
                proposed_content="Optimize: " + eff_summary[:500],
                reason=str(len(analysis.efficiency_issues)) + " efficiency issue(s) detected",
                expected_improvement="Reduce redundant steps",
                priority=3,
            ))
        return proposals

    def _generate_plugin_proposals(self, analysis):
        """Generate plugin code proposals via LLM."""
        if not self.llm_caller:
            return []
        plugin_data = {
            "uncovered_error_patterns": analysis.uncovered_error_patterns,
            "hook_opportunities": analysis.hook_opportunities,
        }
        if not plugin_data["uncovered_error_patterns"] and not plugin_data["hook_opportunities"]:
            return []

        prompt = (
            "You are generating ClawCodex plugin code based on execution trace analysis.\n"
            "## Available Hook Phases (register via register_loop_hook)\n"
            "1. pre_llm (requires feature gate HOOK_PRE_LLM)\n"
            "   def fn(messages, system_prompt, *, state, params) -> (messages, system_prompt)\n"
            "   Can modify: LLM input messages and system prompt\n"
            "2. post_llm (unconditional)\n"
            "   def fn(assistant_messages, tool_use_blocks, *, state, params)\n"
            "     -> (assistant_messages, tool_use_blocks)\n"
            "   Can modify: LLM response and tool call blocks\n"
            "3. pre_tool (unconditional)\n"
            "   def fn(tool_use_blocks, *, state, params) -> (tool_use_blocks,)\n"
            "   Can modify: tool calls before execution\n"
            "4. post_tool (unconditional)\n"
            "   def fn(tool_results, *, state, params) -> (tool_results,)\n"
            "   Can modify: tool execution results\n"
            "5. on_turn_end (unconditional, fire-and-forget)\n"
            "   def fn(state, *, params) -> None\n"
            "   Can do: inspection, logging (cannot modify data flow)\n"
            "## Available Recovery Strategy (register via register_recovery_strategy)\n"
            "RecoveryContext fields: state, last_message, config, params, messages, assistant_messages, error_type\n"
            "Signature: def fn(ctx) -> (QueryState | None, list[Message]) | None\n"
            "## Plugin Analysis Data\n{data_json}\n"
            "## Requirements\n"
            "For each detected issue, propose one plugin. Each plugin must be a complete .py file.\n"
            "Output structured JSON with the following fields per proposal:\n"
            '  - hook_type: "loop_hook" or "recovery_strategy"\n'
            "  - phase: one of the phase names above (only for loop_hook)\n"
            "  - hook_name: short snake_case name for this hook/strategy\n"
            "  - priority: int (lower = runs first, default 10)\n"
            "  - code_body: the Python function body (indented, including def line)\n"
            "  - reason: why this change helps\n"
            "  - expected_improvement: expected effect\n"
            "## Output Format (valid JSON only)\n"
            'json\n{{"proposals": [{{'
            '"hook_type": "loop_hook", "phase": "post_tool", '
            '"hook_name": "retry_on_failure", "priority": 10, '
            '"code_body": "def retry_on_failure(tool_results, *, state, params):\\n    ...", '
            '"reason": "...", "expected_improvement": "..."'
            "}}]}}\n`\n"
        ).format(data_json=json.dumps(plugin_data, ensure_ascii=False, indent=2))

        raw = self.llm_caller(prompt)
        data = extract_json_from_llm(raw)
        if data is None:
            return []

        proposals = []
        for p in data.get("proposals", []):
            hook_type = p.get("hook_type", "loop_hook")
            hook_name = p.get("hook_name", "unnamed")
            phase = p.get("phase", "")
            code_body = p.get("code_body", "")
            reason = p.get("reason", "")
            priority = p.get("priority", 10)
            expected = p.get("expected_improvement", "")

            fparts = ["# Auto-generated plugin: " + hook_name]
            if hook_type == "recovery_strategy":
                fparts.append("from clawcodex_ext.query.recovery_strategies import register_recovery_strategy, RecoveryContext")
            else:
                fparts.append("from clawcodex_ext.query.hook_registry import register_loop_hook")
            fparts.append("")
            fparts.append(code_body)
            fparts.append("")
            if hook_type == "recovery_strategy":
                fparts.append('register_recovery_strategy("' + hook_name + '", ' + hook_name + ', priority=' + str(priority) + ')')
            else:
                fparts.append('register_loop_hook("' + hook_name + '", ' + hook_name + ', "' + phase + '", priority=' + str(priority) + ')')
            fparts.append("")
            full_code = "\n".join(fparts)

            target_name = "plugin_" + hook_name
            proposals.append(OptimizationProposal(
                source_trace_id=analysis.trace_id,
                proposal_type=ProposalType.PLUGIN_GENERATION,
                target=target_name,
                current_content="",
                proposed_content=full_code,
                reason=reason,
                expected_improvement=expected,
                priority=priority,
            ))

        return proposals
