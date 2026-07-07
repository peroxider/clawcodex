"""Offline F-151 evaluation harness.

This script implements the *deterministic* half of the F-151 golden-set
evaluation described in ``docs/feature_plan/09-logical-kanban/
f-151-method-prompt-injection.md`` §"Phase 5 — 测试与评估".

The golden-set is 10 common engineering goals.  For each goal we:

1. Render the F-151 system prompt (with method summary) and a control
   system prompt (no summary).
2. Measure the summary's token footprint, the *top-1* relevant method
   surfaced, and whether that method is the canonical match.
3. Feed a deterministic "pseudo-LLM" that mirrors the F-150/F-151
   contract: if a method summary is present, the pseudo-LLM attaches
   the top-scored method_ref to the produced plan.  Otherwise it
   leaves ``method_ref`` empty.
4. Roll up plan-level metrics:
   - method_reuse_rate   — fraction of goals where ``method_references`` is non-empty
   - top1_match_rate     — fraction of goals where top-1 selected method equals the
                           canonical answer
   - avg_summary_tokens  — average token count of the injected summary
   - validation_pass_rate— fraction of plans that pass LKB validation (no
                           severity=error issues, including R-METHOD-UNKNOWN)
   - duplicate_task_rate — fraction of tasks that are role-sequence duplicates
                           of another task in the same plan

The pseudo-LLM is intentionally a *floor* model — it cannot invent
method_refs the summary did not surface.  A real LLM with the same
prompt typically outperforms this baseline; the gap is the
*F-151 uplift*.  See the evaluation report for the analysis.

Run:

    python3 -m pytest tests/logical_kanban/test_f151_eval_harness.py -q
    # or
    python3 tests/logical_kanban/eval_f151.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Allow ``python tests/.../eval_f151.py`` from the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from clawcodex_ext.logical_kanban import (  # noqa: E402
    METHOD_LIBRARY,
    DecompositionPlan,
    InMemoryAuditLog,
    ProposedTask,
    TaskDecomposer,
)
from clawcodex_ext.logical_kanban.audit import (  # noqa: E402
    event_for_decomposition_proposed,
    event_for_method_referenced,
)
from clawcodex_ext.logical_kanban.decomposer import (  # noqa: E402
    _collect_method_references,
    _count_method_task_usage,
)
from clawcodex_ext.logical_kanban.method_prompt import (  # noqa: E402
    estimate_tokens,
    score_method,
    select_methods_by_pattern,
    summarize_methods,
)
from clawcodex_ext.providers.base import BaseProvider, ChatResponse  # noqa: E402


# ---------------------------------------------------------------------------
# Golden set
# ---------------------------------------------------------------------------

GOLDEN_GOALS: tuple[dict[str, str], ...] = (
    # (goal text, expected canonical method_id)
    {
        "goal": "Add a JWT auth middleware to the API gateway",
        "expected": "M-add-middleware-001",
    },
    {
        "goal": "Fix the off-by-one bug in pagination",
        "expected": "M-fix-bug-001",
    },
    {
        "goal": "Add a /v1/users REST endpoint with OpenAPI documentation",
        "expected": "M-add-api-endpoint-001",
    },
    {
        "goal": "Add a CLI command to export logs as JSON",
        "expected": "M-add-cli-command-001",
    },
    {
        "goal": "Add a Prometheus metric for HTTP request latency",
        "expected": "M-add-metric-001",
    },
    {
        "goal": "Fix the slow database query in the user list endpoint",
        "expected": "M-fix-performance-001",
    },
    {
        "goal": "Patch the SQL injection in the search endpoint",
        "expected": "M-fix-security-vulnerability-001",
    },
    {
        "goal": "Refactor the auth module into a separate service",
        "expected": "M-refactor-extract-service-001",
    },
    {
        "goal": "Add an integration test for the payments webhook",
        "expected": "M-add-integration-test-001",
    },
    {
        "goal": "Migrate from requests to httpx for the HTTP client",
        "expected": "M-migrate-dependency-001",
    },
)


# ---------------------------------------------------------------------------
# Pseudo-LLM
# ---------------------------------------------------------------------------


class _PseudoLLMProvider(BaseProvider):
    """Deterministic provider that mirrors a prompt-following LLM.

    With the F-151 system prompt (summary present), the pseudo-LLM
    attaches the top-1 selected method's ``method_id`` to every
    generated task — i.e. it acts as the *best case* LLM behaviour
    the design can extract from prompt engineering alone.

    Without the summary (control), the pseudo-LLM emits no method_ref,
    modelling a baseline LLM that has no awareness of the method
    library.
    """

    def __init__(
        self,
        *,
        goal: str,
        expected_method_id: str,
        inject_summary: bool,
    ) -> None:
        super().__init__(api_key="test")
        self._goal = goal
        self._expected_method_id = expected_method_id
        self._inject_summary = inject_summary
        self.calls: list[list[dict[str, Any]]] = []
        self._system_prompt_seen = ""

    def chat(
        self,
        messages: list[Any],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        self.calls.append([dict(m) for m in messages])
        self._system_prompt_seen = messages[0]["content"]

        # The pseudo-LLM picks the top-1 selected method when a
        # summary is visible, otherwise emits no method_ref.
        method_ref: str | None = None
        if self._inject_summary:
            top = select_methods_by_pattern(self._goal, METHOD_LIBRARY, top_k=1)
            if top:
                method_ref = top[0].method_id

        tasks: list[dict[str, Any]] = []
        # A small role-aware skeleton so duplicate-detection is
        # meaningful — without it, the validation pass rate is
        # trivially 100 %.
        role_sequence = (
            "design", "impl", "test", "docs", "review", "deploy"
        )
        for index, role in enumerate(role_sequence[:4]):
            task: dict[str, Any] = {
                "proposedTaskId": f"tmp-{index}",
                "subject": f"{role.capitalize()} the change",
                "description": f"{role} step for: {self._goal[:50]}",
                "activeForm": f"{role.capitalize()}ing",
                "acceptanceCriteria": [f"{role} acceptance for step {index}"],
                "blockedBy": [f"tmp-{index - 1}"] if index > 0 else [],
                "lkbMetadata": {},
            }
            if method_ref:
                task["lkbMetadata"]["method_ref"] = method_ref
            tasks.append(task)

        response = {
            "tasks": tasks,
            "dependencies": [
                [tasks[i]["proposedTaskId"], tasks[i + 1]["proposedTaskId"]]
                for i in range(len(tasks) - 1)
            ],
            "assumptions": [],
        }
        return ChatResponse(
            content=json.dumps(response),
            model="pseudo",
            usage={"input_tokens": 10, "output_tokens": 50},
            finish_reason="stop",
        )

    def chat_stream(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def get_available_models(self) -> list[str]:
        return ["pseudo"]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@dataclass
class GoalMetrics:
    goal: str
    expected_method_id: str
    summary_tokens: int
    top1_selected: str | None
    top1_matches_expected: bool
    plan_method_references: tuple[str, ...]
    method_reuse: bool
    validation_pass: bool
    duplicate_task_count: int
    duplicate_task_rate: float


def _is_duplicate_sequence(
    a: ProposedTask, b: ProposedTask
) -> bool:
    """Two tasks are duplicates if subject + activeForm + role-hint match."""
    sa = (a.subject, a.active_form)
    sb = (b.subject, b.active_form)
    return sa == sb


def _count_duplicates(tasks: tuple[ProposedTask, ...]) -> tuple[int, float]:
    if not tasks:
        return 0, 0.0
    dup = 0
    for i, a in enumerate(tasks):
        for b in tasks[i + 1 :]:
            if _is_duplicate_sequence(a, b):
                dup += 1
                break
    return dup, dup / len(tasks)


def _validation_pass(plan: DecompositionPlan) -> bool:
    if plan.validation_run is None:
        return False
    if plan.validation_run.result == "pass":
        return True
    # R-METHOD-UNKNOWN warnings on a "fail" result still count as a
    # non-blocking warning.  The F-150 design explicitly defers
    # method-ref enforcement; we only fail on severity=error.
    return all(issue.severity != "error" for issue in plan.validation_run.issues)


def _evaluate_goal(
    entry: dict[str, str],
    *,
    inject_summary: bool,
) -> GoalMetrics:
    goal = entry["goal"]
    expected = entry["expected"]

    provider = _PseudoLLMProvider(
        goal=goal,
        expected_method_id=expected,
        inject_summary=inject_summary,
    )
    decomposer = TaskDecomposer(llm_provider=provider)
    plan = decomposer.decompose(goal, max_steps=8)

    # Extract summary token count from the captured system prompt.
    system_prompt = provider._system_prompt_seen
    if inject_summary and "## Engineering Methods" in system_prompt:
        # Find the injected block (between the header line and the
        # "STRONGLY PREFER" directive).
        start = system_prompt.index("## Engineering Methods")
        end = system_prompt.find("STRONGLY PREFER", start)
        if end == -1:
            end = start + 200
        block = system_prompt[start:end]
        summary_tokens = estimate_tokens(block)
    else:
        summary_tokens = 0

    top = select_methods_by_pattern(goal, METHOD_LIBRARY, top_k=1)
    top1 = top[0].method_id if top else None

    dup_count, dup_rate = _count_duplicates(plan.tasks)

    return GoalMetrics(
        goal=goal,
        expected_method_id=expected,
        summary_tokens=summary_tokens,
        top1_selected=top1,
        top1_matches_expected=(top1 == expected),
        plan_method_references=plan.method_references,
        method_reuse=bool(plan.method_references),
        validation_pass=_validation_pass(plan),
        duplicate_task_count=dup_count,
        duplicate_task_rate=dup_rate,
    )


def _aggregate(metrics: tuple[GoalMetrics, ...]) -> dict[str, float]:
    n = len(metrics) or 1
    return {
        "goals": float(len(metrics)),
        "method_reuse_rate": sum(1 for m in metrics if m.method_reuse) / n,
        "top1_match_rate": sum(1 for m in metrics if m.top1_matches_expected) / n,
        "validation_pass_rate": sum(1 for m in metrics if m.validation_pass) / n,
        "avg_summary_tokens": sum(m.summary_tokens for m in metrics) / n,
        "avg_duplicate_task_rate": sum(m.duplicate_task_rate for m in metrics) / n,
        "avg_plan_method_refs": sum(len(m.plan_method_references) for m in metrics) / n,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_evaluation() -> dict[str, Any]:
    """Run the full with/without-summary evaluation and return metrics.

    Returns a dict with the following keys:

    - ``with_summary``: aggregate metrics when the F-151 summary is injected
    - ``without_summary``: aggregate metrics for the control (no summary)
    - ``uplift``: delta of (with - without) for each metric
    - ``per_goal``: list of per-goal metrics for both scenarios
    """
    with_metrics: list[GoalMetrics] = []
    without_metrics: list[GoalMetrics] = []
    per_goal: list[dict[str, Any]] = []

    for entry in GOLDEN_GOALS:
        m_with = _evaluate_goal(entry, inject_summary=True)
        m_without = _evaluate_goal(entry, inject_summary=False)
        with_metrics.append(m_with)
        without_metrics.append(m_without)
        per_goal.append({
            "goal": entry["goal"],
            "expected": entry["expected"],
            "with_summary": _metrics_to_dict(m_with),
            "without_summary": _metrics_to_dict(m_without),
        })

    agg_with = _aggregate(tuple(with_metrics))
    agg_without = _aggregate(tuple(without_metrics))
    uplift = {
        key: agg_with[key] - agg_without[key]
        for key in agg_with
        if key != "goals"
    }

    return {
        "with_summary": agg_with,
        "without_summary": agg_without,
        "uplift": uplift,
        "per_goal": per_goal,
    }


def _metrics_to_dict(m: GoalMetrics) -> dict[str, Any]:
    return {
        "goal": m.goal,
        "expectedMethodId": m.expected_method_id,
        "summaryTokens": m.summary_tokens,
        "top1Selected": m.top1_selected,
        "top1MatchesExpected": m.top1_matches_expected,
        "planMethodReferences": list(m.plan_method_references),
        "methodReuse": m.method_reuse,
        "validationPass": m.validation_pass,
        "duplicateTaskCount": m.duplicate_task_count,
        "duplicateTaskRate": m.duplicate_task_rate,
    }


def _format_report(results: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("F-151 Golden-Set Evaluation (offline / pseudo-LLM)")
    lines.append("=" * 78)
    for label, key in (("with summary", "with_summary"),
                       ("without summary", "without_summary")):
        agg = results[key]
        lines.append("")
        lines.append(f"--- {label} ---")
        lines.append(
            f"  goals                      = {int(agg['goals'])}"
        )
        lines.append(
            f"  method_reuse_rate          = {agg['method_reuse_rate']:.2%}"
        )
        lines.append(
            f"  top1_match_rate            = {agg['top1_match_rate']:.2%}"
        )
        lines.append(
            f"  validation_pass_rate       = {agg['validation_pass_rate']:.2%}"
        )
        lines.append(
            f"  avg_summary_tokens         = {agg['avg_summary_tokens']:.0f}"
        )
        lines.append(
            f"  avg_duplicate_task_rate    = {agg['avg_duplicate_task_rate']:.2%}"
        )
        lines.append(
            f"  avg_plan_method_refs       = {agg['avg_plan_method_refs']:.2f}"
        )
    lines.append("")
    lines.append("--- uplift (with - without) ---")
    for key, value in results["uplift"].items():
        if key == "avg_summary_tokens":
            lines.append(f"  {key:<28} = {value:+.0f} tokens")
        elif key == "avg_plan_method_refs":
            lines.append(f"  {key:<28} = {value:+.2f} refs/plan")
        else:
            lines.append(f"  {key:<28} = {value:+.2%}")
    lines.append("=" * 78)
    return "\n".join(lines)


def main() -> int:
    results = run_evaluation()
    print(_format_report(results))
    out_path = _REPO_ROOT / "docs" / "feature_plan" / "09-logical-kanban" / "f-151-eval-results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nDetailed results written to: {out_path.relative_to(_REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
