"""Execution trace analyzer with seven-dimensional analysis."""
from __future__ import annotations
import json
import os
import logging
from typing import Any, Dict, List, Optional
from src.models import AnalysisReport, ExecutionTrace, TraceStep, StepType, SectionAnalysis, dataclass_to_dict
from src.utils import read_text, setup_logger, extract_json_from_llm, extract_clawcodex_system_sections, load_available_skills, match_skills_to_trace

logger = setup_logger("trace_analyzer")
TRACE_ANALYZER_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "prompts", "trajectory_analyzer.md")
DURATION_WARN_MS = 10000

_SECTION_ANALYSIS_PROMPT = """You are analyzing whether a specific section of the LLM system prompt needs optimization, based on an execution trace.

## Execution Trace (Failure Summary)
Task: {task_description}

{trace_summary}

Trace source: {trace_source}

## System Prompt Section: {section_id}
```
{section_content}
```

## Analysis Task
Analyze whether this system prompt section needs optimization. Consider:
1. Did the agent's behavior in the trace align with what this section instructs?
2. Did any errors, inefficiencies, or suboptimal outcomes in the trace relate to the guidance in this section?
3. Could this section be clarified, expanded, or modified to prevent similar issues?
4. Is the section clear, specific, and actionable enough?

## Requesting More Trace Detail
If the failure summary above is insufficient, you can request specific parts of the full trace.
Set "needs_full_trace": true and specify what you need in "requested_trace_sections".
Supported section specifiers:
- "step:N" ? full details of step N (input, output, tool calls, errors, thinking)
- "step:N.field" ? just one field of step N (e.g. step:2.errors, step:2.thinking)
- "steps:M-N" ? full details of steps M through N (e.g. steps:0-5)
- "steps:type=TYPE" ? all steps of a given type (e.g. steps:type=code_generation)
- "errors:all" ? all errors across all steps
- "tool_calls:all" ? all tool calls across all steps
- "thinking:all" ? all thinking blocks
- "final_output" ? the final output text
- "metrics" ? execution metrics summary

After you specify requested_trace_sections, the system will retrieve only those parts from the full trace and provide them to you in a follow-up.

## Output Format (valid JSON only)
```json
{{"needs_optimization": true, "needs_full_trace": false, "requested_trace_sections": [], "issues_found": ["issue 1"], "suggested_improvement": "concrete suggestion", "reasoning": "brief explanation"}}
```"""


_COMBINED_SECTION_PROMPT = """You are analyzing whether sections of the LLM system prompt need optimization, based on an execution trace.

## Execution Trace (Summary)
Task: {task_description}

{trace_summary}

## System Prompt Sections
{all_sections}

## Analysis Task
For each section above, analyze whether it needs optimization. Consider:
1. Did the agent's behavior in the trace align with what this section instructs?
2. Did any errors, inefficiencies, or suboptimal outcomes relate to this section?
3. Could this section be clarified or modified to prevent similar issues?

If the summary above is insufficient for a specific section, set "needs_full_trace": true
for that section and the system will provide the full trace in a follow-up.

## Output Format (valid JSON only)
```json
{{"sections": {{
  "section_id_1": {{"needs_optimization": true, "needs_full_trace": false, "issues_found": ["issue"], "suggested_improvement": "...", "reasoning": "..."}},
  "section_id_2": {{"needs_optimization": false, "needs_full_trace": true, "issues_found": [], "suggested_improvement": "", "reasoning": "..."}}
}}}}
```"""


class TraceAnalyzer:
    """Analyzes execution traces to identify issues."""

    def __init__(self, config: Dict[str, Any], llm_caller=None) -> None:
        self.config = config
        self.llm_caller = llm_caller

    def analyze(self, trace: ExecutionTrace, transcript_path: str = None) -> AnalysisReport:
        report = self._analyze_structured(trace)
        report.section_analyses = self._analyze_sections(trace, report, transcript_path=transcript_path)
        if any(sa.needs_optimization for sa in report.section_analyses):
            report.needs_optimization = True
            issues = [sa.section_id for sa in report.section_analyses if sa.needs_optimization]
            report.section_analyses_summary = "Sections needing optimization: " + ", ".join(issues)
        elif self.llm_caller:
            llm_report = self._analyze_with_llm(trace)
            report.needs_optimization = report.needs_optimization or llm_report.needs_optimization
        return report

    def _read_transcript_sections(self, transcript_path: str, requested: list[str]) -> str:
        """Read specific sections from raw transcript JSONL file.
        
        Supports the same section specifiers as _extract_trace_sections:
        - "step:N" -> full details of step N
        - "steps:M-N" -> steps M through N
        - "errors:all" -> all errors across all steps
        - "tool_calls:all" -> all tool calls
        - "thinking:all" -> all thinking blocks
        - "final_output" -> final output text
        """
        if not os.path.isfile(transcript_path):
            return "[transcript file not found]"
        import json as _json
        lines = []
        with open(transcript_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                lines.append(raw_line)
        
        # Determine which lines to include based on requested sections
        want_all = "errors:all" in requested or "tool_calls:all" in requested or "thinking:all" in requested
        result_parts = []
        
        if want_all:
            # Include all non-administrative lines
            result_parts.append(f"Full transcript ({len(lines)} lines):")
            for i, line in enumerate(lines):
                entry = _json.loads(line)
                etype = entry.get("type", "")
                if etype in ("session_init", "session_snapshot", "cost_block"):
                    continue
                role = entry.get("role", "?")
                uuid_s = str(entry.get("uuid", ""))[:8]
                duration = entry.get("duration_ms", 0)
                stop = entry.get("stop_reason", "")
                entry_summary = f"[{i}] role={role} uuid={uuid_s}"
                if duration:
                    entry_summary += f" duration={duration}ms"
                if stop:
                    entry_summary += f" stop_reason={stop}"
                
                # Extract errors
                if "errors:all" in requested:
                    err_val = entry.get("apiError") or entry.get("error") or ""
                    if err_val:
                        entry_summary += f" ERROR={str(err_val)[:100]}"
                
                # Extract tool calls
                if "tool_calls:all" in requested:
                    blocks = entry.get("content", [])
                    if isinstance(blocks, list):
                        for blk in blocks:
                            if blk.get("type") == "tool_use":
                                entry_summary += f" tool_use={blk.get('name','?')}(id={str(blk.get('id',''))[:8]})"
                
                # Extract thinking
                if "thinking:all" in requested:
                    blocks = entry.get("content", [])
                    if isinstance(blocks, list):
                        for blk in blocks:
                            if blk.get("type") == "text":
                                txt = blk.get("text", "")
                                entry_summary += f" thinking={txt[:100]}"
                
                result_parts.append(entry_summary)
        else:
            # Parse numeric step ranges
            step_nums = set()
            for rq in requested:
                if rq.startswith("step:") and ":" not in rq[5:]:
                    try:
                        step_nums.add(int(rq[5:]))
                    except ValueError:
                        pass
                elif rq.startswith("steps:") and "-" in rq:
                    parts_r = rq[6:].split("-")
                    if len(parts_r) == 2:
                        try:
                            for sn in range(int(parts_r[0]), int(parts_r[1]) + 1):
                                step_nums.add(sn)
                        except ValueError:
                            pass
            
            lines_to_show = list(step_nums) if step_nums else list(range(len(lines)))
            for i in sorted(lines_to_show):
                if i < len(lines):
                    entry = _json.loads(lines[i])
                    etype = entry.get("type", "")
                    if etype in ("session_init", "session_snapshot", "cost_block"):
                        continue
                    result_parts.append(f"[{i}] " + _json.dumps(entry, ensure_ascii=False)[:500])
        
        if "final_output" in requested and lines:
            last_entry = _json.loads(lines[-1])
            blocks = last_entry.get("content", [])
            if isinstance(blocks, list):
                for blk in blocks:
                    if blk.get("type") == "text":
                        result_parts.append(f"FINAL OUTPUT: {blk.get('text','')[:300]}")
        
        return "\n".join(result_parts)

    def _analyze_sections(self, trace: ExecutionTrace, heuristic: AnalysisReport, transcript_path: str = None) -> list[SectionAnalysis]:
        """Analyze all ClawCodex system prompt sections in one LLM call.

        Sends all sections + failure trace summary in a single prompt.
        If LLM requests full trace for specific sections, only those get a follow-up.
        """
        if not heuristic.needs_optimization:
            return self._evaluate_skill_extraction(trace)
        if not self.llm_caller:
            return []
        sections = extract_clawcodex_system_sections()
        if not sections:
            logger.warning("No ClawCodex sections extracted; skipping section analysis.")
            return []
        failure_trace = self._build_failure_trace(trace)
        all_sec_lines = []
        for k in sorted(sections.keys()):
            all_sec_lines.append("### " + k + "\n" + sections[k] + "\n")
        all_sec_text = "\n---\n".join(all_sec_lines)
        prompt = _COMBINED_SECTION_PROMPT.format(
            task_description=trace.task_description[:200],
            trace_summary=failure_trace[:2000],
            all_sections=all_sec_text,
        )
        raw = self.llm_caller(prompt)
        data = extract_json_from_llm(raw)
        fell_back = False
        if not data or not isinstance(data, dict):
            logger.warning(
                "Combined section analysis returned invalid data (len=%d, head=%r); "
                "retrying with compact sections",
                len(raw or ""),
                (raw or "")[:80],
            )
            compact_lines = [
                "### " + k + "\n" + sections[k][:300] + "\n"
                for k in sorted(sections.keys())
            ]
            retry_prompt = _COMBINED_SECTION_PROMPT.format(
                task_description=trace.task_description[:200],
                trace_summary=failure_trace[:2000],
                all_sections="\n---\n".join(compact_lines),
            )
            data = extract_json_from_llm(self.llm_caller(retry_prompt))
            if not data or not isinstance(data, dict):
                logger.warning("Compact section retry also returned invalid data; skipping section analysis.")
                return []
            fell_back = True
        all_results = data.get("sections", {})
        results = []
        full_trace_sections = {k: v for k, v in all_results.items()
                               if isinstance(v, dict) and v.get("needs_full_trace")}
        if full_trace_sections and not fell_back:
            all_requested = set()
            for k, v in all_results.items():
                rqs = v.get("requested_trace_sections", ["errors:all", "tool_calls:all"]) if isinstance(v, dict) else []
                all_requested.update(rqs)
            logger.info("LLM requested full trace sections for: %s", list(full_trace_sections.keys()))
            if transcript_path and os.path.isfile(transcript_path):
                logger.info("Transcript path found: %s", transcript_path)
                extra_trace = self._read_transcript_sections(transcript_path, sorted(all_requested))
                logger.info("Using raw transcript for full trace (%d chars)", len(extra_trace))
            else:
                logger.info("Transcript path not available (path=%s, exists=%s)", 
                           transcript_path, os.path.isfile(transcript_path) if transcript_path else "N/A")
                extra_trace = self._extract_trace_sections(trace, sorted(all_requested))
            ft_keys = sorted(full_trace_sections)
            ft_prompt = _COMBINED_SECTION_PROMPT.format(
                task_description=trace.task_description[:200],
                trace_summary=extra_trace[:2000],
                all_sections="\n---\n".join(
                    "### " + k2 + "\n" + sections.get(k2, "") + "\n" for k2 in ft_keys
                ),
            )
            ft_data = extract_json_from_llm(self.llm_caller(ft_prompt))
            ft_resolved = {}
            if isinstance(ft_data, dict):
                ft_sections = ft_data.get("sections", {})
                ft_resolved = {k2: v2 for k2, v2 in ft_sections.items()
                               if k2 in ft_keys and isinstance(v2, dict)}
            for k2 in ft_keys:
                if k2 not in ft_resolved:
                    data2 = extract_json_from_llm(self.llm_caller(_SECTION_ANALYSIS_PROMPT.format(
                        section_id=k2, section_content=sections.get(k2, ""),
                        task_description=trace.task_description[:200],
                        trace_summary=extra_trace[:2000],
                        trace_source="full_trace_pass2",
                    )))
                    if data2 and isinstance(data2, dict):
                        ft_resolved[k2] = data2
            if len(ft_resolved) < len(ft_keys):
                logger.warning("Full-trace pass resolved %d/%d sections", len(ft_resolved), len(ft_keys))
            for k2, v2 in ft_resolved.items():
                all_results[k2] = v2
        for section_id in sorted(sections.keys()):
            content = sections[section_id]
            sa_data = all_results.get(section_id, {})
            if isinstance(sa_data, dict):
                results.append(SectionAnalysis(
                    section_id=section_id,
                    section_content=content[:300],
                    needs_optimization=bool(sa_data.get("needs_optimization", False)),
                    issues_found=sa_data.get("issues_found", []),
                    suggested_improvement=sa_data.get("suggested_improvement", ""),
                    reasoning=sa_data.get("reasoning", ""),
                ))
            else:
                results.append(SectionAnalysis(
                    section_id=section_id, section_content=content[:300],
                    needs_optimization=False, issues_found=[],
                ))
        return results

    def _evaluate_skill_extraction(self, trace: ExecutionTrace) -> list[SectionAnalysis]:
        """Evaluate whether a successful trace should be extracted as a reusable skill."""
        if len(trace.steps) < 3 and not trace.final_output:
            return []

        # Check final output quality
        output = trace.final_output or ""
        has_meaningful_output = len(output) > 50

        if self.llm_caller:
            return self._evaluate_skill_extraction_llm(trace)
        elif has_meaningful_output and len(trace.steps) >= 4:
            # Heuristic: multi-step successful trace ? good skill candidate
            return [SectionAnalysis(
                section_id="_skill_extraction",
                section_content=trace.task_description[:200],
                needs_optimization=True,
                issues_found=[f"Successful {len(trace.steps)}-step execution pattern detected"],
                suggested_improvement=f"Extract as a reusable skill for {trace.task_description[:100]}",
                reasoning=f"Completed in {len(trace.steps)} steps with meaningful output; pattern likely repeatable",
            )]
        return []

    def _evaluate_skill_extraction_llm(self, trace: ExecutionTrace) -> list[SectionAnalysis]:
        """Use LLM to evaluate whether a successful trace should become a skill."""
        summary = self._build_compact_summary(trace)
        prompt = (
            "You are evaluating whether a successful execution trace represents a reusable skill pattern.\n\n"
            "## Execution Trace (Successful)\n"
            f"Task: {trace.task_description[:200]}\n\n"
            f"Trace Summary: {summary[:500]}\n\n"
            f"Final Output: {(trace.final_output or '(none)')[:400]}\n\n"
            "## What is a Skill?\n"
            "A skill is a reusable set of instructions that helps an agent efficiently handle similar tasks.\n"
            "It typically includes: a clear task description, step-by-step instructions, common pitfalls, tool patterns.\n\n"
            "## Evaluation Criteria\n"
            "1. Is this task likely to be encountered again?\n"
            "2. Is the approach general enough to be reused?\n"
            "3. Does the trace demonstrate a clear, repeatable pattern?\n"
            "4. Would extracting this as a skill save time on future similar tasks?\n\n"
            "## Output Format (valid JSON only)\n"
            '```json\n{{"should_extract_skill": true, "skill_name": "short_name", '
            '"skill_description": "brief description", "skill_steps": ["step 1", "step 2"], '
            '"reasoning": "why this is a good skill candidate"}}\n```'
        )
        raw = self.llm_caller(prompt)
        data = extract_json_from_llm(raw)
        if data and isinstance(data, dict) and data.get("should_extract_skill", False):
            steps_text = "\n".join(f"- {s}" for s in data.get("skill_steps", []))
            return [SectionAnalysis(
                section_id="_skill_extraction",
                section_content=json.dumps(data, ensure_ascii=False)[:500],
                needs_optimization=True,
                issues_found=[f"Skill opportunity: {data.get('skill_name', 'unnamed')} - {data.get('skill_description', '')[:100]}"],
                suggested_improvement=(
                    f"Name: {data.get('skill_name', 'unnamed')}\n"
                    f"Description: {data.get('skill_description', '')}\n"
                    f"Steps:\n{steps_text}"
                ),
                reasoning=data.get("reasoning", "Successful trace is a good skill candidate"),
            )]
        return []

    def _build_section_prompt(self, section_id: str, section_content: str, trace_desc: str, trace_data: str, trace_source: str) -> str:
        """Build a prompt for analyzing one ClawCodex system prompt section."""
        return _SECTION_ANALYSIS_PROMPT.format(
            task_description=trace_desc,
            trace_summary=trace_data[:1500],
            trace_source=trace_source,
            section_id=section_id,
            section_content=section_content[:2000],
        )

    @staticmethod
    def _build_failure_trace(trace: ExecutionTrace) -> str:
        """Extract failure steps in detail with thinking/tool info; summarize normal steps with key context."""
        lines = []
        lines.append(f"Task: {trace.task_description}")
        lines.append("")

        # Execution metrics summary
        m = trace.execution_metrics
        lines.append(f"Execution Metrics: {m.total_steps} steps, {m.total_duration_ms}ms total, "
                     f"{m.tool_call_count} tool calls, {m.error_count} errors")
        lines.append("")

        failure_steps = []
        normal_steps = []

        for s in trace.steps:
            is_failure = bool(s.errors) or s.duration_ms > DURATION_WARN_MS
            if is_failure:
                detail = f"  Step {s.step_index}: {s.step_type.value} dur={s.duration_ms}ms"
                # Thinking: what the agent was thinking during this step
                if s.thinking:
                    detail += f"\n    Thinking: {s.thinking[:200]}"
                if s.action:
                    detail += f"\n    Action: {s.action[:80]}"
                if s.input_data:
                    detail += f"\n    Input: {s.input_data[:300]}"
                if s.errors:
                    for err in s.errors:
                        detail += f"\n    Error: {err[:200]}"
                if s.tool_calls:
                    for tc in s.tool_calls:
                        err_info = f" error={tc.error[:100]}" if tc.error else ""
                        arg_info = f" args={str(tc.arguments)[:150]}" if tc.arguments else ""
                        res_info = f" result={tc.result[:150]}" if tc.result else ""
                        detail += f"\n    Tool: {tc.tool_name}{arg_info}{err_info}{res_info}"
                if s.output_data and not s.tool_calls:
                    detail += f"\n    Output: {s.output_data[:200]}"
                failure_steps.append(detail)
            else:
                parts = [f"  Step {s.step_index}: {s.step_type.value} dur={s.duration_ms}ms"]
                if s.thinking:
                    parts.append(f" thinking={s.thinking[:100]}")
                if s.tool_calls:
                    tc = s.tool_calls[0]
                    parts.append(f" tool={tc.tool_name}")
                    if tc.result:
                        parts.append(f" result_len={len(tc.result)}")
                normal_steps.append("".join(parts))

        if failure_steps:
            lines.append("Failure Steps (detailed):")
            lines.extend(failure_steps)
            lines.append("")

        if normal_steps:
            lines.append(f"Normal Steps ({len(normal_steps)} total):")
            lines.extend(normal_steps[:15])
            if len(normal_steps) > 15:
                lines.append(f"  ... and {len(normal_steps) - 15} more normal steps")
            lines.append("")

        if trace.final_output:
            lines.append(f"Final output (first 300 chars): {trace.final_output[:300]}")

        return "\n".join(lines)


    @staticmethod
    def _extract_trace_sections(trace: ExecutionTrace, requested: list[str]) -> str:
        """Retrieve specific parts of a full execution trace based on section specifiers.

        Supported specifiers:
        - "step:N" ? full details of step N
        - "step:N.field" ? one field of step N (errors, tool_calls, thinking, output_data, input_data)
        - "steps:M-N" ? steps M through N inclusive
        - "steps:type=TYPE" ? all steps of a given StepType
        - "errors:all" ? all errors across all steps
        - "tool_calls:all" ? all tool calls across all steps
        - "thinking:all" ? all thinking blocks
        - "final_output" ? final output text
        - "metrics" ? execution metrics summary
        """
        import re
        lines: list[str] = []
        lines.append(f"Extracted trace sections: {', '.join(requested)}")
        lines.append("")

        for spec in requested:
            spec = spec.strip()

            # step:N or step:N.field
            m = re.match(r"^step:(\d+)(?:\.(\w+))?$", spec)
            if m:
                idx = int(m.group(1))
                field = m.group(2)
                if idx < len(trace.steps):
                    s = trace.steps[idx]
                    if field:
                        val = getattr(s, field, None)
                        if val:
                            if isinstance(val, list):
                                lines.append(f"Step {idx}.{field}: {val}")
                            else:
                                lines.append(f"Step {idx}.{field}: {str(val)[:500]}")
                    else:
                        lines.append(f"Step {idx}: type={s.step_type.value}, action={s.action[:100]}")
                        if s.input_data:
                            lines.append(f"  input: {s.input_data[:300]}")
                        if s.output_data:
                            lines.append(f"  output: {s.output_data[:300]}")
                        if s.errors:
                            lines.append(f"  errors: {s.errors}")
                        if s.tool_calls:
                            for tc in s.tool_calls:
                                err = f" error={tc.error[:100]}" if tc.error else ""
                                lines.append(f"  tool_call: {tc.tool_name}({str(tc.arguments)[:200]}){err}")
                        if s.thinking:
                            lines.append(f"  thinking: {s.thinking[:300]}")
                        lines.append(f"  duration: {s.duration_ms}ms")
                else:
                    lines.append(f"Step {idx}: not found (trace has {len(trace.steps)} steps)")
                continue

            # steps:M-N
            m = re.match(r"^steps:(\d+)-(\d+)$", spec)
            if m:
                start, end = int(m.group(1)), int(m.group(2))
                for idx in range(max(0, start), min(len(trace.steps), end + 1)):
                    s = trace.steps[idx]
                    lines.append(f"Step {idx}: type={s.step_type.value}, action={s.action[:80]}, duration={s.duration_ms}ms")
                    if s.errors:
                        lines.append(f"  errors: {s.errors}")
                    if s.tool_calls:
                        for tc in s.tool_calls:
                            err = f" error={tc.error[:100]}" if tc.error else ""
                            lines.append(f"  tool_call: {tc.tool_name}({str(tc.arguments)[:150]}){err}")
                continue

            # steps:type=TYPE
            m = re.match(r"^steps:type=(\w+)$", spec)
            if m:
                target_type = m.group(1).lower()
                for idx, s in enumerate(trace.steps):
                    if s.step_type.value.lower() == target_type:
                        lines.append(f"Step {idx}: action={s.action[:80]}, duration={s.duration_ms}ms")
                        if s.errors:
                            lines.append(f"  errors: {s.errors}")
                        if s.output_data:
                            lines.append(f"  output: {s.output_data[:200]}")
                continue

            # errors:all
            if spec == "errors:all":
                for idx, s in enumerate(trace.steps):
                    if s.errors:
                        for err in s.errors:
                            lines.append(f"Step {idx} error: {err[:300]}")
                continue

            # tool_calls:all
            if spec == "tool_calls:all":
                for idx, s in enumerate(trace.steps):
                    if s.tool_calls:
                        for tc in s.tool_calls:
                            err = f" error={tc.error[:150]}" if tc.error else ""
                            lines.append(f"Step {idx} tool: {tc.tool_name}({str(tc.arguments)[:200]}){err}")
                            if tc.result:
                                lines.append(f"  result: {tc.result[:200]}")
                continue

            # thinking:all
            if spec == "thinking:all":
                for idx, s in enumerate(trace.steps):
                    if s.thinking:
                        lines.append(f"Step {idx} thinking: {s.thinking[:500]}")
                continue

            # final_output
            if spec == "final_output":
                lines.append(f"Final output: {(trace.final_output or '(none)')[:500]}")
                continue

            # metrics
            if spec == "metrics":
                m = trace.execution_metrics
                lines.append(f"Metrics: steps={m.total_steps}, duration={m.total_duration_ms}ms, errors={m.error_count}, tools={m.tool_call_count}, score={m.overall_score}")
                continue

            lines.append(f"Unknown section specifier: {spec}")

        return "\n".join(lines)

    @staticmethod
    def _build_compact_summary(trace: ExecutionTrace) -> str:
        parts = []
        for s in trace.steps:
            label = s.step_type.value
            extra = ""
            if s.errors:
                extra = " [err]"
            if s.duration_ms > 5000:
                extra += f" [{s.duration_ms}ms]"
            parts.append(f"{label}{extra}")
        return f"[{len(trace.steps)} steps] " + " -> ".join(parts[:15])

    @staticmethod
    def _summarize_findings(report: AnalysisReport) -> str:
        lines = []
        if report.errors:
            lines.append(f"Errors: {len(report.errors)}")
        if report.efficiency_issues:
            lines.append(f"Efficiency: {len(report.efficiency_issues)} issues")
        if report.duration_analysis:
            lines.append(f"Duration warnings: {len(report.duration_analysis)}")
        if report.failure_hypotheses:
            lines.append(f"Hypotheses: {len(report.failure_hypotheses)}")
        return "; ".join(lines) or "No significant issues detected."


    @staticmethod
    def _extract_trace_sections(trace: ExecutionTrace, requested: list[str]) -> str:
        """Retrieve specific parts of a full execution trace based on section specifiers.

        Supported specifiers:
        - "step:N" ? full details of step N
        - "step:N.field" ? one field of step N (errors, tool_calls, thinking, output_data, input_data)
        - "steps:M-N" ? steps M through N inclusive
        - "steps:type=TYPE" ? all steps of a given StepType
        - "errors:all" ? all errors across all steps
        - "tool_calls:all" ? all tool calls across all steps
        - "thinking:all" ? all thinking blocks
        - "final_output" ? final output text
        - "metrics" ? execution metrics summary
        """
        import re
        lines: list[str] = []
        lines.append(f"Extracted trace sections: {', '.join(requested)}")
        lines.append("")

        for spec in requested:
            spec = spec.strip()

            # step:N or step:N.field
            m = re.match(r"^step:(\d+)(?:\.(\w+))?$", spec)
            if m:
                idx = int(m.group(1))
                field = m.group(2)
                if idx < len(trace.steps):
                    s = trace.steps[idx]
                    if field:
                        val = getattr(s, field, None)
                        if val:
                            if isinstance(val, list):
                                lines.append(f"Step {idx}.{field}: {val}")
                            else:
                                lines.append(f"Step {idx}.{field}: {str(val)[:500]}")
                    else:
                        lines.append(f"Step {idx}: type={s.step_type.value}, action={s.action[:100]}")
                        if s.input_data:
                            lines.append(f"  input: {s.input_data[:300]}")
                        if s.output_data:
                            lines.append(f"  output: {s.output_data[:300]}")
                        if s.errors:
                            lines.append(f"  errors: {s.errors}")
                        if s.tool_calls:
                            for tc in s.tool_calls:
                                err = f" error={tc.error[:100]}" if tc.error else ""
                                lines.append(f"  tool_call: {tc.tool_name}({str(tc.arguments)[:200]}){err}")
                        if s.thinking:
                            lines.append(f"  thinking: {s.thinking[:300]}")
                        lines.append(f"  duration: {s.duration_ms}ms")
                else:
                    lines.append(f"Step {idx}: not found (trace has {len(trace.steps)} steps)")
                continue

            # steps:M-N
            m = re.match(r"^steps:(\d+)-(\d+)$", spec)
            if m:
                start, end = int(m.group(1)), int(m.group(2))
                for idx in range(max(0, start), min(len(trace.steps), end + 1)):
                    s = trace.steps[idx]
                    lines.append(f"Step {idx}: type={s.step_type.value}, action={s.action[:80]}, duration={s.duration_ms}ms")
                    if s.errors:
                        lines.append(f"  errors: {s.errors}")
                    if s.tool_calls:
                        for tc in s.tool_calls:
                            err = f" error={tc.error[:100]}" if tc.error else ""
                            lines.append(f"  tool_call: {tc.tool_name}({str(tc.arguments)[:150]}){err}")
                continue

            # steps:type=TYPE
            m = re.match(r"^steps:type=(\w+)$", spec)
            if m:
                target_type = m.group(1).lower()
                for idx, s in enumerate(trace.steps):
                    if s.step_type.value.lower() == target_type:
                        lines.append(f"Step {idx}: action={s.action[:80]}, duration={s.duration_ms}ms")
                        if s.errors:
                            lines.append(f"  errors: {s.errors}")
                        if s.output_data:
                            lines.append(f"  output: {s.output_data[:200]}")
                continue

            # errors:all
            if spec == "errors:all":
                for idx, s in enumerate(trace.steps):
                    if s.errors:
                        for err in s.errors:
                            lines.append(f"Step {idx} error: {err[:300]}")
                continue

            # tool_calls:all
            if spec == "tool_calls:all":
                for idx, s in enumerate(trace.steps):
                    if s.tool_calls:
                        for tc in s.tool_calls:
                            err = f" error={tc.error[:150]}" if tc.error else ""
                            lines.append(f"Step {idx} tool: {tc.tool_name}({str(tc.arguments)[:200]}){err}")
                            if tc.result:
                                lines.append(f"  result: {tc.result[:200]}")
                continue

            # thinking:all
            if spec == "thinking:all":
                for idx, s in enumerate(trace.steps):
                    if s.thinking:
                        lines.append(f"Step {idx} thinking: {s.thinking[:500]}")
                continue

            # final_output
            if spec == "final_output":
                lines.append(f"Final output: {(trace.final_output or '(none)')[:500]}")
                continue

            # metrics
            if spec == "metrics":
                m = trace.execution_metrics
                lines.append(f"Metrics: steps={m.total_steps}, duration={m.total_duration_ms}ms, errors={m.error_count}, tools={m.tool_call_count}, score={m.overall_score}")
                continue

            lines.append(f"Unknown section specifier: {spec}")

        return "\n".join(lines)

    @staticmethod
    def _build_compact_summary(trace: ExecutionTrace) -> str:
        parts = []
        for s in trace.steps:
            label = s.step_type.value
            extra = ""
            if s.errors:
                extra = " [err]"
            if s.duration_ms > 5000:
                extra += f" [{s.duration_ms}ms]"
            parts.append(f"{label}{extra}")
        return f"[{len(trace.steps)} steps] " + " -> ".join(parts[:15])

    @staticmethod
    def _summarize_findings(report: AnalysisReport) -> str:
        lines = []
        if report.errors:
            lines.append(f"Errors: {len(report.errors)}")
        if report.efficiency_issues:
            lines.append(f"Efficiency: {len(report.efficiency_issues)} issues")
        if report.duration_analysis:
            lines.append(f"Duration warnings: {len(report.duration_analysis)}")
        if report.failure_hypotheses:
            lines.append(f"Hypotheses: {len(report.failure_hypotheses)}")
        return "; ".join(lines) or "No significant issues detected."

    def _analyze_with_llm(self, trace: ExecutionTrace) -> AnalysisReport:
        prompt_template = read_text(TRACE_ANALYZER_PROMPT_PATH)
        if not prompt_template:
            logger.warning("Trajectory analyzer prompt not found; falling back to heuristic.")
            return self._analyze_structured(trace)
        trace_json = json.dumps(dataclass_to_dict(trace), ensure_ascii=False, indent=2)
        prompt = prompt_template.replace("{task_description}", trace.task_description)
        prompt = prompt_template.replace("{execution_trace_json}", trace_json)
        raw = self.llm_caller(prompt)
        data = extract_json_from_llm(raw)
        if data is None:
            logger.error("LLM returned invalid JSON for trace analysis: " + raw[:200])
            return self._analyze_structured(trace)

        heuristic = self._analyze_structured(trace)
        report = self._report_from_dict(trace.trace_id, trace.task_description, data)
        if not report.compressed_summary and heuristic.compressed_summary:
            report.compressed_summary = heuristic.compressed_summary
        if not report.failure_hypotheses and heuristic.failure_hypotheses:
            report.failure_hypotheses = heuristic.failure_hypotheses
        if not report.duration_analysis and heuristic.duration_analysis:
            report.duration_analysis = heuristic.duration_analysis
        return report

    def _report_from_dict(self, trace_id, task_desc, data):
        return AnalysisReport(
            trace_id=trace_id, task_description=task_desc,
            errors=data.get("errors", []),
            efficiency_issues=data.get("efficiency_issues", []),
            prompt_issues=data.get("prompt_issues", []),
            skill_issues=data.get("skill_issues", []),
            overall_assessment=data.get("overall_assessment", ""),
            optimization_priority=data.get("optimization_priority", ""),
            needs_optimization=bool(data.get("errors") or data.get("efficiency_issues")),
        )

    def _analyze_structured(self, trace):
        report = AnalysisReport(
            trace_id=trace.trace_id, task_description=trace.task_description,
            overall_assessment="Heuristic analysis completed.",
        )

        # Compressed summary (Chinese format)
        parts = []
        for s in trace.steps:
            label = s.step_type.value
            extra = ""
            if s.errors:
                extra = ", \u9519"
            if s.duration_ms > DURATION_WARN_MS:
                extra += f", {s.duration_ms}ms"
            parts.append(f"{label}(1\u6b65{extra})")
        compressed = f"[{len(trace.steps)}\u6b65\u538b\u7f29] " + " -> ".join(parts[:10])
        report.compressed_summary = compressed

        _ERROR_TYPE_KEYWORDS = {
            "syntax": "syntax_error", "syntaxerror": "syntax_error",
            "timeout": "timeout_error", "timeouterror": "timeout_error",
            "valueerror": "value_error", "typeerror": "type_error",
            "importerror": "import_error", "keyerror": "key_error",
            "attributeerror": "attribute_error", "indexerror": "index_error",
            "filenotfounderror": "file_not_found",
            "modulenotfounderror": "module_not_found",
            "connection": "connection_error",
        }
        def _classify_error(msg):
            lower = msg.lower().replace(" ", "").replace(":", "")
            for kw, etype in _ERROR_TYPE_KEYWORDS.items():
                if kw in lower:
                    return etype
            return "error"

        error_seen = set()
        for i, s in enumerate(trace.steps):
            for err in s.errors:
                key = err[:50]
                etype = _classify_error(err)
                if key in error_seen:
                    report.errors.append({"step_index": i, "error_type": "repeated_error", "description": err[:200]})
                else:
                    report.errors.append({"step_index": i, "error_type": etype, "description": err[:200]})
                error_seen.add(key)

        actions_seen = {}
        for i, s in enumerate(trace.steps):
            key = s.action[:40]
            if key in actions_seen:
                report.efficiency_issues.append({"step_indices": [actions_seen[key], i], "issue": "repeated action: " + key})
            actions_seen[key] = i

        for s in trace.steps:
            if s.duration_ms > DURATION_WARN_MS:
                report.duration_analysis.append({
                    "step_index": s.step_index,
                    "duration_ms": s.duration_ms,
                    "step_type": s.step_type.value,
                    "issue": f"Step {s.step_index} ({s.step_type.value}) took {s.duration_ms}ms, exceeds {DURATION_WARN_MS}ms threshold",
                })

        for i in range(len(trace.steps) - 1):
            if trace.steps[i].step_type == StepType.CODE_GENERATION and trace.steps[i+1].step_type == StepType.DEBUGGING:
                if not any("code-debug" in e.get("issue","") for e in report.efficiency_issues):
                    report.efficiency_issues.append({"step_indices": [i, i+1], "issue": "code-debug cycle at step " + str(i), "suggestion": "merge code and debug steps"})
                report.logic_errors.append({"description": "code then debug at step " + str(i)})

        if len(trace.final_output or "") < 20:
            report.prompt_effectiveness.append({"issue": "Output too short", "detail": (trace.final_output or "")[:50]})

        # Skill-vs-trace analysis: load skills from disk and match against trace
        try:
            _skills = load_available_skills()
            if _skills:
                _tool_names = []
                for _s in trace.steps:
                    for _tc in (_s.tool_calls or []):
                        if _tc.tool_name and _tc.tool_name not in _tool_names:
                            _tool_names.append(_tc.tool_name)
                _matched = match_skills_to_trace(_skills, trace.task_description, _tool_names)
                if _matched:
                    for _sn, _sm in _matched.items():
                        _sd = _sm["skill"]
                        report.skill_usage_analysis.append({
                            "issue": "Skill matched: " + _sn + " (" + _sm["match_reason"] + ")",
                            "match_score": _sm["match_score"],
                            "skill_content": _sd,
                            "suggestion": "Review skill alignment with actual agent behavior",
                        })
                    _matched_names = [str(k) for k in _matched.keys()]
                    logger.info("Skills matched to trace: " + ", ".join(_matched_names))
        except Exception as _e:
            logger.warning("Skill matching error: " + str(_e))

        # Plugin analysis: detect hook opportunities and uncovered error patterns
        _analyze_uncovered_error_patterns(trace, report)
        _analyze_hook_opportunities(trace, report)
        
        report.needs_optimization = bool(
            report.errors or report.efficiency_issues or report.duration_analysis
            or report.uncovered_error_patterns or report.loop_termination_issues
        )
        return report


# Error types already covered by built-in RecoveryStrategies
_KNOWN_ERROR_TYPES = frozenset({
    "max_output_tokens", "max_tokens",
    "prompt_too_long",
    "media_size", "image",
})

def _classify_error_type(error_str: str) -> str:
    """Classify an error string into a canonical type."""
    el = error_str.lower()
    for kw in ("max_output_tokens", "max_tokens"):
        if kw in el:
            return "max_output_tokens"
    for kw in ("prompt_too_long", "prompt is too long", "prompt_too_large"):
        if kw in el:
            return "prompt_too_long"
    for kw in ("media_size", "image_size", "image too large"):
        if kw in el:
            return "media_size"
    for kw in ("rate_limit", "rate limit", "too many requests"):
        if kw in el:
            return "rate_limit"
    for kw in ("timeout", "timed out", "time out"):
        if kw in el:
            return "timeout"
    for kw in ("permission", "denied", "not allowed", "unauthorized"):
        if kw in el:
            return "permission"
    for kw in ("connection", "network", "refused", "reset"):
        if kw in el:
            return "connection"
    return "unknown"


def _build_plugin_summary(report) -> str:
    """Build a natural-language summary of plugin-relevant analysis."""
    parts = []
    if report.uncovered_error_patterns:
        types = ", ".join(p["error_type"] for p in report.uncovered_error_patterns)
        parts.append(f"Uncovered error patterns: {types}")
    if report.hook_opportunities:
        phases = set(p["phase"] for p in report.hook_opportunities)
        parts.append(f"Hook opportunities at phases: {', '.join(sorted(phases))}")
    if report.loop_termination_issues:
        reasons = ", ".join(p["terminal_reason"] for p in report.loop_termination_issues)
        parts.append(f"Abnormal termination reasons: {reasons}")
    return "; ".join(parts)


def _analyze_uncovered_error_patterns(trace: ExecutionTrace, report: AnalysisReport) -> None:
    """Detect error types in trace not covered by existing RecoveryStrategies."""
    error_type_counts: dict[str, int] = {}
    for step in trace.steps:
        for err in step.errors:
            etype = _classify_error_type(err)
            error_type_counts[etype] = error_type_counts.get(etype, 0) + 1

    for etype, count in error_type_counts.items():
        if etype in _KNOWN_ERROR_TYPES:
            continue
        entry = {"error_type": etype, "count": count, "suggestion": "none"}
        if count >= 2:
            entry["suggestion"] = "generate_recovery_strategy"
        report.uncovered_error_patterns.append(entry)

def _analyze_hook_opportunities(trace: ExecutionTrace, report: AnalysisReport) -> None:
    """Detect patterns where a LoopHook could improve behavior."""
    # Pattern 1: repeated tool failures ? pre_tool hook
    tool_consecutive_failures: dict[str, int] = {}
    for step in trace.steps:
        for tc in (step.tool_calls or []):
            if tc.error:
                tool_consecutive_failures[tc.tool_name] = tool_consecutive_failures.get(tc.tool_name, 0) + 1
            else:
                tool_consecutive_failures[tc.tool_name] = 0

    for tool_name, count in tool_consecutive_failures.items():
        if count >= 2:
            report.hook_opportunities.append({
                "pattern": "repeated_tool_failure",
                "tool": tool_name,
                "phase": "pre_tool",
                "count": count,
            })

    # Pattern 2: tool ? error ? retry cycle >= 3 ? post_tool hook
    tool_error_cycles: dict[str, int] = {}
    for step in trace.steps:
        for tc in (step.tool_calls or []):
            if tc.error:
                tool_error_cycles[tc.tool_name] = tool_error_cycles.get(tc.tool_name, 0) + 1
    for tool_name, count in tool_error_cycles.items():
        if count >= 3:
            report.hook_opportunities.append({
                "pattern": "tool_error_cycle",
                "tool": tool_name,
                "phase": "post_tool",
                "count": count,
            })

    # Pattern 3: no tool calls ? on_turn_start hook
    has_tool = any(s.tool_calls for s in trace.steps)
    if not has_tool and len(trace.steps) >= 3:
        report.hook_opportunities.append({
            "pattern": "no_tool_calls",
            "tool": "",
            "phase": "on_turn_start",
            "count": 1,
        })

def _analyze_loop_termination(trace: ExecutionTrace, report: AnalysisReport) -> None:
    """Detect abnormal loop termination patterns from trace steps."""
    if not trace.steps:
        return

    # Gather termination indicators from last few steps
    error_found = ""
    for step in reversed(trace.steps):
        for err in step.errors:
            el = err.lower()
            if "max_output_tokens" in el or "max_tokens" in el:
                error_found = "max_output_tokens"
                break
            if "prompt_too_long" in el or "prompt is too long" in el:
                error_found = "prompt_too_long"
                break
            if "model_error" in el or "api_error" in el or "server error" in el:
                error_found = "model_error"
                break
        if error_found:
            break

    if error_found:
        report.loop_termination_issues.append({
            "terminal_reason": error_found,
            "count": 1,
            "fraction": round(1.0 / max(len(trace.steps), 1), 2),
        })

    # Check for too-few output as proxy for premature termination
    final_out = (trace.final_output or "").strip()
    if len(final_out) < 50 and len(trace.steps) > 0:
        report.loop_termination_issues.append({
            "terminal_reason": "short_output",
            "count": 1,
            "fraction": round(1.0 / max(len(trace.steps), 1), 2),
        })
