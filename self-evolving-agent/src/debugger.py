'''"Auto-debug: diagnose failed optimization proposals and generate corrected versions."'''

from __future__ import annotations
import json
import logging
import sys
from typing import Any, Dict, List, Optional

from src.models import (
    ExecutionTrace,
    OptimizationProposal,
    ProposalType,
    ProposalStatus,
)
from src.utils import extract_json_from_llm, setup_logger

logger = setup_logger("proposal_debugger")


class ProposalDebugger:
    """Diagnose why optimized execution failed and generate corrected proposals."""
    def __init__(self, llm_caller: Optional[Any] = None) -> None:
        self.llm_caller = llm_caller

    def debug(self, proposals, old_trace, new_trace):
        errors = self._collect_error_summary(new_trace)
        if not errors:
            sys.stderr.write('  [Auto-Debug] 无需debug（新版本未产生错误）\\n')
            logger.info("No errors found; nothing to debug.")
            return None
        if not self.llm_caller:
            sys.stderr.write('  [Auto-Debug] 无法debug（没有LLM调用器）\\n')
            logger.info("No llm_caller; skipping debug.")
            return None
        sys.stderr.write('  [Auto-Debug] 正在debug中...（分析失败原因）\\n')
        prompt = self._build_debug_prompt(proposals, old_trace, new_trace, errors)
        raw = self.llm_caller(prompt)
        data = extract_json_from_llm(raw)
        if data is None:
            sys.stderr.write('  [Auto-Debug] LLM输出无效，跳过debug\\n')
            logger.warning("LLM returned invalid JSON.")
            return None
        corrected = self._build_corrected_proposals(data, proposals)
        if not corrected:
            sys.stderr.write('  [Auto-Debug] 未生成有效修正方案\\n')
            logger.info("No usable corrections.")
            return None
        print(f"  [Auto-Debug] 生成了 {len(corrected)} 个修正方案", flush=True)
        logger.info("Generated %d corrected proposal(s)", len(corrected))
        return corrected

    @staticmethod
    def _collect_error_summary(trace):
        errors = []
        for step in trace.steps:
            for err in (step.errors or []):
                if err and err.strip():
                    errors.append({"step_index": step.step_index, "step_type": step.step_type.value, "action": step.action[:120], "error": err[:300]})
        return errors

    @staticmethod
    def _build_debug_prompt(proposals, old_trace, new_trace, errors):
        proposal_lines = []
        for p in proposals:
            proposal_lines.append(json.dumps({"proposal_type": p.proposal_type.value, "target": p.target, "current_content": p.current_content[:200], "proposed_content": p.proposed_content[:500], "reason": p.reason[:200]}, ensure_ascii=False))
        old_metrics = old_trace.execution_metrics
        new_metrics = new_trace.execution_metrics
        error_lines = json.dumps(errors[:20], ensure_ascii=False, indent=2)
        NL = chr(10)
        return (
            "# Debug Failed Optimization" + NL + NL
            + "An optimization proposal was applied but the re-execution introduced errors. "
            + "Diagnose root cause and produce corrected content." + NL + NL
            + "## Original Proposals" + NL + "```json" + NL
            + NL.join(proposal_lines) + NL + "```" + NL + NL
            + "## Original Execution" + NL
            + f"Steps: {old_metrics.total_steps}, Errors: {old_metrics.error_count}, Score: {old_metrics.overall_score:.2f}" + NL + NL
            + "## Failed Re-execution" + NL
            + f"Steps: {new_metrics.total_steps}, Errors: {new_metrics.error_count}, Score: {new_metrics.overall_score:.2f}" + NL + NL
            + "## Errors in Failed Execution" + NL + "```json" + NL
            + error_lines + NL + "```" + NL + NL
            + "## Instructions" + NL
            + "CRITICAL: The bug was introduced by the proposed changes in the original proposal." + NL
            + "Focus ONLY on fixing bugs in the proposed_content (syntax errors, wrong format, broken logic)." + NL
            + "Keep the original intention, structure, and approach unchanged." + NL
            + "1. Compare proposed_content with current_content to identify what was changed." + NL
            + "2. Fix ONLY the bugs that caused the failure (missing quotes, unbalanced braces, etc.)." + NL
            + "3. Do NOT rewrite or improve beyond fixing the bug." + NL
            + "4. If proposal is fine and errors are unrelated, include it unchanged (copy proposed_content as-is)." + NL
            + "5. Ensure fixed content has valid syntax (balanced quotes, braces, brackets)." + NL + NL
            + "## Output Format (valid JSON only)" + NL
            + chr(34) + "corrected_proposals" + chr(34) + ": [" + NL
            + "  {" + chr(34) + "target" + chr(34) + ": " + chr(34) + "original target" + chr(34) + "," + NL
            + "   " + chr(34) + "proposed_content" + chr(34) + ": " + chr(34) + "corrected content" + chr(34) + "}" + NL
            + "]" + NL
        )

    @staticmethod
    def _build_corrected_proposals(data, originals):
        raw_list = data.get("corrected_proposals", [])
        if not raw_list:
            return []
        original_map = {p.target: p for p in originals}
        corrected = []
        for item in raw_list:
            target = item.get("target", "")
            content = item.get("proposed_content", "")
            if not target or not content.strip():
                continue
            orig = original_map.get(target)
            if orig is None:
                continue
            if content.strip() == orig.proposed_content.strip():
                continue
            corrected.append(OptimizationProposal(
                source_trace_id=orig.source_trace_id,
                proposal_type=orig.proposal_type,
                target=target,
                current_content=orig.current_content,
                proposed_content=content,
                reason="Auto-debug fix: " + orig.reason,
                expected_improvement=orig.expected_improvement,
                priority=orig.priority,
                status=ProposalStatus.PENDING,
            ))
        return corrected
