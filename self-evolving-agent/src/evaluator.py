"""A/B comparison evaluator for execution traces."""
from __future__ import annotations
import json
import os
import logging
from dataclasses import asdict
from typing import Any, Dict, List, Optional
from src.models import ComparisonResult, ExecutionTrace, dataclass_to_dict
from src.utils import read_text, setup_logger, extract_json_from_llm

logger = setup_logger("evaluator")
EVALUATOR_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "prompts", "evaluator.md")


class EvaluatorAgent:
    """Compares old vs new version execution traces."""
    def __init__(self, config: Dict[str, Any], llm_caller=None) -> None:
        self.config = config
        self.llm_caller = llm_caller
        self.threshold = float(config.get("system", {}).get("evaluation_threshold", 0.0))

    def compare_executions(self, task_description: str, old: ExecutionTrace, new: ExecutionTrace) -> ComparisonResult:
        if self.llm_caller:
            return self._evaluate_with_llm(task_description, old, new)
        return self._evaluate_heuristic(task_description, old, new)

    def _evaluate_with_llm(self, task_description: str, old: ExecutionTrace, new: ExecutionTrace) -> ComparisonResult:
        prompt_template = read_text(EVALUATOR_PROMPT_PATH)
        if not prompt_template:
            logger.warning("Evaluator prompt not found; falling back to heuristic.")
            return self._evaluate_heuristic(task_description, old, new)

        def _fmt(tr: ExecutionTrace) -> str:
            steps_text = " -> ".join(s.step_type.value for s in tr.steps[:8])
            if len(tr.steps) > 8:
                steps_text += f" ... ({len(tr.steps)} total)"
            return steps_text

        prompt = prompt_template.replace("{task_description}", task_description)
        prompt = prompt.replace("{old_version}", old.agent_version)
        prompt = prompt.replace("{old_trace_summary}", _fmt(old))
        prompt = prompt.replace("{old_output_code}", (old.final_output or "")[:2000])
        prompt = prompt.replace("{old_total_steps}", str(old.execution_metrics.total_steps))
        prompt = prompt.replace("{old_error_count}", str(old.execution_metrics.error_count))
        prompt = prompt.replace("{old_duration}", str(old.execution_metrics.total_duration_ms))
        prompt = prompt.replace("{old_iterations}", str(old.execution_metrics.code_iterations))
        prompt = prompt.replace("{new_version}", new.agent_version)
        prompt = prompt.replace("{new_trace_summary}", _fmt(new))
        prompt = prompt.replace("{new_output_code}", (new.final_output or "")[:2000])
        prompt = prompt.replace("{new_total_steps}", str(new.execution_metrics.total_steps))
        prompt = prompt.replace("{new_error_count}", str(new.execution_metrics.error_count))
        prompt = prompt.replace("{new_duration}", str(new.execution_metrics.total_duration_ms))
        prompt = prompt.replace("{new_iterations}", str(new.execution_metrics.code_iterations))

        raw = self.llm_caller(prompt)
        data = extract_json_from_llm(raw)
        if data is None:
            logger.error("Evaluator LLM returned invalid JSON: %s", raw[:200])
            return self._evaluate_heuristic(task_description, old, new)

        ca = data.get("comparison_analysis", {})
        return ComparisonResult(
            task_id=old.task_id,
            old_version=old.agent_version,
            new_version=new.agent_version,
            old_execution=old, new_execution=new,
            steps_comparison=ca.get("steps_comparison", ""),
            quality_comparison=ca.get("quality_comparison", ""),
            efficiency_comparison=ca.get("efficiency_comparison", ""),
            is_improved=data.get("is_improved", False),
            improvement_summary=data.get("improvement_summary", ""),
            evaluator_notes=json.dumps(data.get("comparison_analysis", {}), ensure_ascii=False),
            decision=data.get("decision", "reject"),
            decision_reason=data.get("decision_reason", ""),
        )

    def _evaluate_heuristic(self, task_description: str, old: ExecutionTrace, new: ExecutionTrace) -> ComparisonResult:
        old_score = old.execution_metrics.overall_score
        new_score = new.execution_metrics.overall_score
        old_err = old.execution_metrics.error_count
        new_err = new.execution_metrics.error_count
        old_steps = old.execution_metrics.total_steps
        new_steps = new.execution_metrics.total_steps

        is_improved = False
        decision = "reject"

        if old_score > 0 or new_score > 0:
            is_improved = (new_score - old_score) > self.threshold
        else:
            err_improved = new_err < old_err
            steps_improved = new_steps < old_steps
            is_improved = err_improved or (new_err == old_err and steps_improved)

        if is_improved:
            decision = "approve"

        return ComparisonResult(
            task_id=old.task_id,
            old_version=old.agent_version,
            new_version=new.agent_version,
            old_execution=old, new_execution=new,
            steps_comparison="Heuristic: old=%d, new=%d" % (old_steps, new_steps),
            quality_comparison="Heuristic: old_score=%.1f, new_score=%.1f" % (old_score, new_score),
            efficiency_comparison="Heuristic: old_err=%d, new_err=%d" % (old_err, new_err),
            is_improved=is_improved,
            improvement_summary=("Improved" if is_improved else "Not improved"),
            decision=decision,
            decision_reason="threshold=%.1f, improvement=%.1f" % (self.threshold, new_score - old_score),
        )
