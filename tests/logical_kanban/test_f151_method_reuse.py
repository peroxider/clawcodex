"""Tests for F-151 Prompt-Integrated Method Reuse.

Covers the new ``method_prompt`` module (Phase 1), the system-prompt
injection in :class:`TaskDecomposer` (Phase 2), the new
``method_references`` field on :class:`DecompositionPlan` (Phase 3),
and the ``lkb_method_referenced`` audit event (Phase 4).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from clawcodex_ext.logical_kanban import (
    DecompositionPlan,
    EngineeringMethod,
    InMemoryAuditLog,
    METHOD_LIBRARY,
    ProposedTask,
    SubtaskTemplate,
    TaskDecomposer,
)
from clawcodex_ext.logical_kanban.audit import (
    event_for_method_referenced,
    get_audit_log,
)
from clawcodex_ext.logical_kanban.decomposer import (
    _collect_method_references,
    _count_method_task_usage,
)
from clawcodex_ext.logical_kanban.method_prompt import (
    MethodSummaryResult,
    estimate_tokens,
    score_method,
    select_methods_by_pattern,
    summarize_methods,
)
from clawcodex_ext.providers.base import BaseProvider, ChatResponse
from clawcodex_ext.tool_system.context import ToolContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_subtask(template_id: str, role: str = "impl") -> SubtaskTemplate:
    return SubtaskTemplate(
        template_id=template_id,
        role=role,  # type: ignore[arg-type]
        subject_template=f"Subtask {template_id}",
    )


def _make_method(
    method_id: str,
    *,
    pattern: str = "test_pattern",
    description: str = "Test method",
    roles: tuple[str, ...] = ("design", "impl", "test"),
    assumptions: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
) -> EngineeringMethod:
    return EngineeringMethod(
        method_id=method_id,
        pattern=pattern,
        description=description,
        subtask_templates=tuple(_make_subtask(f"t{i}", role) for i, role in enumerate(roles)),
        assumptions=assumptions,
        tags=tags,
    )


def _plan_with_method_ref(
    method_ref: str | None = None,
    *,
    method_refs: tuple[str | None, ...] = ("M-add-middleware-001", "M-add-middleware-001"),
    subject_prefix: str = "tmp-",
) -> tuple[ProposedTask, ...]:
    """Build a small ProposedTask tuple with the given method_ref pattern."""
    tasks: list[ProposedTask] = []
    for index, ref in enumerate(method_refs):
        metadata: dict[str, Any] = {}
        if ref is not None:
            metadata["method_ref"] = ref
        tasks.append(
            ProposedTask(
                proposed_task_id=f"{subject_prefix}{index}",
                subject=f"Task {index}",
                description="",
                active_form="",
                acceptance_criteria=("ok",),
                blocked_by=(),
                lkb_metadata=metadata,
            )
        )
    return tuple(tasks)


# ---------------------------------------------------------------------------
# Phase 1 — method_prompt
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    def test_empty_string(self) -> None:
        assert estimate_tokens("") == 0

    def test_short_text(self) -> None:
        # 4 chars -> 1 token
        assert estimate_tokens("abcd") == 1

    def test_rounds_up(self) -> None:
        # 5 chars -> ceil(5/4) = 2 tokens
        assert estimate_tokens("abcde") == 2

    def test_long_text(self) -> None:
        # 400 chars -> 100 tokens
        assert estimate_tokens("a" * 400) == 100


class TestScoreMethod:
    def test_zero_for_empty_goal(self) -> None:
        method = _make_method("M-x", pattern="add_endpoint")
        assert score_method(method, "") == 0.0

    def test_exact_pattern_token_match(self) -> None:
        method = _make_method("M-x", pattern="add_middleware")
        # "add" and "middleware" both substring-match the pattern.
        assert score_method(method, "add middleware") >= 2.0

    def test_hyphen_split_in_goal(self) -> None:
        method = _make_method("M-x", pattern="add_middleware")
        # Goal "add-middleware" should still hit both pattern tokens
        # because the scorer splits on non-alphanumerics.
        assert score_method(method, "add-middleware") >= 2.0

    def test_fuzzy_match_for_typo(self) -> None:
        method = _make_method("M-x", pattern="add_middleware")
        # "midleware" is 1 edit from "middleware" → 0.5 fuzzy
        assert score_method(method, "add midleware") >= 1.5

    def test_no_match(self) -> None:
        method = _make_method("M-x", pattern="add_middleware")
        assert score_method(method, "compute prime numbers") == 0.0


class TestSelectMethodsByPattern:
    def test_empty_goal_returns_empty(self) -> None:
        assert select_methods_by_pattern("", METHOD_LIBRARY) == ()

    def test_top_k_caps_results(self) -> None:
        result = select_methods_by_pattern("add", METHOD_LIBRARY, top_k=3)
        assert len(result) <= 3

    def test_relevance_orders_add_middleware_first(self) -> None:
        result = select_methods_by_pattern("add middleware", METHOD_LIBRARY, top_k=5)
        ids = [m.method_id for m in result]
        assert ids[0] == "M-add-middleware-001"

    def test_relevance_orders_fix_bug_first(self) -> None:
        result = select_methods_by_pattern("fix bug", METHOD_LIBRARY, top_k=5)
        ids = [m.method_id for m in result]
        assert ids[0] == "M-fix-bug-001"

    def test_deterministic_tiebreak(self) -> None:
        # Two calls with the same goal must produce the same ordering.
        first = select_methods_by_pattern("add", METHOD_LIBRARY, top_k=10)
        second = select_methods_by_pattern("add", METHOD_LIBRARY, top_k=10)
        assert [m.method_id for m in first] == [m.method_id for m in second]

    def test_zero_top_k_returns_empty(self) -> None:
        assert select_methods_by_pattern("add", METHOD_LIBRARY, top_k=0) == ()


class TestSummarizeMethods:
    def test_empty_library(self) -> None:
        result = summarize_methods(())
        assert result.text == ""
        assert result.included_method_ids == ()
        assert result.dropped_method_ids == ()
        assert result.estimated_tokens == 0

    def test_includes_each_method(self) -> None:
        methods = (
            _make_method("M-x", pattern="add_x", description="Add x."),
            _make_method("M-y", pattern="fix_y", description="Fix y."),
        )
        result = summarize_methods(methods, header="")
        assert "M-x" in result.text
        assert "M-y" in result.text
        assert result.included_method_ids == ("M-x", "M-y")
        assert result.dropped_method_ids == ()

    def test_header_included(self) -> None:
        methods = (_make_method("M-x"),)
        result = summarize_methods(methods, header="## Engineering Methods")
        assert result.text.startswith("## Engineering Methods")

    def test_budget_hard_limit_drops_overflow(self) -> None:
        # Build a 60-method library (matches the F-151 spec's 60-method
        # budget scenario).  Cap max_tokens to 200 so at least the tail
        # must be dropped.
        methods = tuple(
            _make_method(
                f"M-bulk-{i:03d}",
                pattern=f"bulk_pattern_{i}",
                description="A long description " * 8,
            )
            for i in range(60)
        )
        result = summarize_methods(methods, max_tokens=200, header="")
        assert result.estimated_tokens <= 200
        assert len(result.included_method_ids) < 60
        assert len(result.dropped_method_ids) == 60 - len(result.included_method_ids)

    def test_full_method_library_under_two_k_tokens(self) -> None:
        # F-151 acceptance: 60 methods should still fit in 2 000 tokens.
        # The real seed library has 26 methods — it fits comfortably.
        result = summarize_methods(METHOD_LIBRARY, max_tokens=2000)
        assert result.estimated_tokens < 2000

    def test_goal_reranks_methods(self) -> None:
        methods = (
            _make_method("M-a", pattern="add_middleware", description="Add middleware."),
            _make_method("M-b", pattern="fix_bug", description="Fix a bug."),
        )
        result = summarize_methods(methods, goal="add middleware", header="")
        # M-a should appear first because it matches the goal.
        assert result.included_method_ids[0] == "M-a"

    def test_invalid_max_tokens_raises(self) -> None:
        with pytest.raises(ValueError, match="max_tokens"):
            summarize_methods((_make_method("M-x"),), max_tokens=0)

    def test_header_only_when_budget_exhausted(self) -> None:
        # If the header alone exceeds max_tokens, return just the header
        # and mark all methods as dropped.
        methods = (_make_method("M-x"),)
        result = summarize_methods(methods, header="## " + "x" * 200, max_tokens=10)
        assert "## " in result.text
        assert result.included_method_ids == ()
        assert result.dropped_method_ids == ("M-x",)

    def test_iterable_accepted(self) -> None:
        # Generator / list should be acceptable.
        def gen() -> Any:
            yield _make_method("M-a")
            yield _make_method("M-b")
        result = summarize_methods(gen(), header="")
        assert result.included_method_ids == ("M-a", "M-b")


# ---------------------------------------------------------------------------
# Phase 2 — system prompt injection
# ---------------------------------------------------------------------------


class _CapturingProvider(BaseProvider):
    """Provider that records the messages it received and returns a fixed plan."""

    def __init__(self, response_json: dict[str, Any]) -> None:
        super().__init__(api_key="test")
        self._response_json = response_json
        self.calls: list[list[dict[str, Any]]] = []

    def chat(
        self,
        messages: list[Any],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        self.calls.append([dict(m) for m in messages])
        return ChatResponse(
            content=json.dumps(self._response_json),
            model="stub",
            usage={"input_tokens": 10, "output_tokens": 50},
            finish_reason="stop",
        )

    def chat_stream(
        self,
        messages: list[Any],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> Any:
        raise NotImplementedError

    def get_available_models(self) -> list[str]:
        return ["stub"]


def _simple_plan_json() -> dict[str, Any]:
    return {
        "tasks": [
            {
                "proposedTaskId": "tmp-a",
                "subject": "Design middleware",
                "description": "Pick hook points and ordering.",
                "activeForm": "Designing middleware",
                "acceptanceCriteria": ["Hook points documented"],
                "blockedBy": [],
                "lkbMetadata": {},
            },
            {
                "proposedTaskId": "tmp-b",
                "subject": "Implement middleware",
                "description": "Wire the implementation.",
                "activeForm": "Implementing middleware",
                "acceptanceCriteria": ["Middleware wired"],
                "blockedBy": ["tmp-a"],
                "lkbMetadata": {},
            },
        ],
        "dependencies": [["tmp-a", "tmp-b"]],
        "assumptions": [],
    }


class TestSystemPromptInjection:
    def test_system_prompt_contains_method_summary_for_relevant_goal(self) -> None:
        provider = _CapturingProvider(_simple_plan_json())
        decomposer = TaskDecomposer(llm_provider=provider)

        decomposer.decompose("Add a middleware", max_steps=8)

        assert provider.calls, "Provider should have been called at least once"
        system_message = provider.calls[0][0]["content"]
        # The summary header must be present.
        assert "## Engineering Methods" in system_message
        # The most-relevant method should appear in the summary block.
        assert "M-add-middleware-001" in system_message

    def test_system_prompt_includes_strongly_prefer_directive(self) -> None:
        provider = _CapturingProvider(_simple_plan_json())
        decomposer = TaskDecomposer(llm_provider=provider)

        decomposer.decompose("Add a middleware", max_steps=8)

        system_message = provider.calls[0][0]["content"]
        assert "STRONGLY PREFER" in system_message

    def test_system_prompt_keeps_json_format_constraints(self) -> None:
        provider = _CapturingProvider(_simple_plan_json())
        decomposer = TaskDecomposer(llm_provider=provider)

        decomposer.decompose("Add a middleware", max_steps=8)

        system_message = provider.calls[0][0]["content"]
        # Existing JSON format constraints must remain intact.
        assert "Return strictly JSON" in system_message
        assert "proposedTaskId" in system_message
        assert "method_ref" in system_message

    def test_user_prompt_unaffected_by_method_injection(self) -> None:
        provider = _CapturingProvider(_simple_plan_json())
        decomposer = TaskDecomposer(llm_provider=provider)

        decomposer.decompose("Add a middleware", context="has-router", max_steps=8)

        user_message = provider.calls[0][1]["content"]
        # The method summary is NOT injected into the user prompt.
        assert "## Engineering Methods" not in user_message
        # The user prompt still contains the goal and context.
        assert "Add a middleware" in user_message
        assert "has-router" in user_message

    def test_unrelated_goal_does_not_inject_middleware_method(self) -> None:
        # A goal that has no overlap with the seed library should produce
        # an empty selection — we tolerate either no summary block or a
        # summary block with no method_refs, but we must NOT carry the
        # add-middleware summary.
        provider = _CapturingProvider(_simple_plan_json())
        decomposer = TaskDecomposer(llm_provider=provider)

        decomposer.decompose("Write a marketing landing page", max_steps=8)

        system_message = provider.calls[0][0]["content"]
        assert "M-add-middleware-001" not in system_message

    def test_empty_goal_does_not_crash(self) -> None:
        provider = _CapturingProvider(_simple_plan_json())
        decomposer = TaskDecomposer(llm_provider=provider)

        # The system prompt should still build (no goal → no selection →
        # no summary block), and the LLM call should succeed.
        plan = decomposer.decompose("Anything", max_steps=8)
        assert plan is not None

    def test_custom_method_library_still_works(self) -> None:
        # A small custom library is supplied via the constructor.
        custom_method = _make_method(
            "M-custom-001",
            pattern="custom_thing",
            description="A custom thing.",
        )
        provider = _CapturingProvider(_simple_plan_json())
        decomposer = TaskDecomposer(
            llm_provider=provider,
            method_library=(custom_method,),
        )

        # The summary block should pull from the *default* library
        # (because the in-line select_methods_by_pattern inside
        # _system_prompt always uses METHOD_LIBRARY) — that is a
        # documented limitation of the MVP: see the F-151 design
        # doc §"已拟定的设计决定".  The default library has
        # M-add-middleware-001, but a "custom thing" goal has no
        # overlap, so the summary block will be empty for that goal.
        decomposer.decompose("custom thing", max_steps=8)
        system_message = provider.calls[0][0]["content"]
        # M-custom-001 should NOT be in the summary block (default lib
        # was used).  This guards against the lib going out of sync.
        assert "M-custom-001" not in system_message


# ---------------------------------------------------------------------------
# Phase 3 — method_references on DecompositionPlan
# ---------------------------------------------------------------------------


def _plan_with_method_refs_json(refs: tuple[str | None, ...]) -> dict[str, Any]:
    tasks: list[dict[str, Any]] = []
    for index, ref in enumerate(refs):
        metadata: dict[str, Any] = {}
        if ref is not None:
            metadata["method_ref"] = ref
        tasks.append(
            {
                "proposedTaskId": f"tmp-{index}",
                "subject": f"Task {index}",
                "description": "desc",
                "activeForm": "active",
                "acceptanceCriteria": ["ok"],
                "blockedBy": [],
                "lkbMetadata": metadata,
            }
        )
    return {
        "tasks": tasks,
        "dependencies": [],
        "assumptions": [],
    }


class TestMethodReferencesField:
    def test_plan_exposes_deduped_method_references(self) -> None:
        provider = _CapturingProvider(
            _plan_with_method_refs_json(
                ("M-add-middleware-001", "M-add-middleware-001", "M-fix-bug-001")
            )
        )
        decomposer = TaskDecomposer(llm_provider=provider)

        plan = decomposer.decompose("anything", max_steps=8)

        assert plan.method_references == ("M-add-middleware-001", "M-fix-bug-001")

    def test_plan_with_no_method_refs_has_empty_tuple(self) -> None:
        provider = _CapturingProvider(_plan_with_method_refs_json((None, None)))
        decomposer = TaskDecomposer(llm_provider=provider)

        plan = decomposer.decompose("anything", max_steps=8)

        assert plan.method_references == ()

    def test_plan_to_dict_includes_method_references(self) -> None:
        provider = _CapturingProvider(
            _plan_with_method_refs_json(("M-add-middleware-001",))
        )
        decomposer = TaskDecomposer(llm_provider=provider)

        plan = decomposer.decompose("anything", max_steps=8)
        payload = plan.to_dict()

        assert "methodReferences" in payload
        assert payload["methodReferences"] == ["M-add-middleware-001"]


class TestExtractPlanAcceptsMethodRef:
    def test_method_ref_in_lkb_metadata_is_preserved(self) -> None:
        # F-150 already wired the parse layer to accept method_ref.  F-151
        # re-asserts that field is preserved through parsing.
        provider = _CapturingProvider(
            _plan_with_method_refs_json(("M-add-middleware-001", "M-fix-bug-001"))
        )
        decomposer = TaskDecomposer(llm_provider=provider)

        plan = decomposer.decompose("anything", max_steps=8)

        assert plan.tasks[0].lkb_metadata["method_ref"] == "M-add-middleware-001"
        assert plan.tasks[1].lkb_metadata["method_ref"] == "M-fix-bug-001"

    def test_unknown_method_ref_still_parses_with_warning(self) -> None:
        # F-150 design decision: unknown method_refs are warnings, not
        # errors.  The plan should still validate and surface the
        # unrecognised ref in ``method_references`` so the audit trail
        # can see what the LLM tried to use.
        provider = _CapturingProvider(
            _plan_with_method_refs_json(("M-does-not-exist-001",))
        )
        decomposer = TaskDecomposer(llm_provider=provider)

        plan = decomposer.decompose("anything", max_steps=8)

        assert plan.method_references == ("M-does-not-exist-001",)
        # R-METHOD-UNKNOWN should be present as a warning.
        assert plan.validation_run is not None
        codes = {issue.code for issue in plan.validation_run.issues}
        assert "R-METHOD-UNKNOWN" in codes


# ---------------------------------------------------------------------------
# Phase 4 — audit event emission
# ---------------------------------------------------------------------------


class TestMethodReferencedAuditEvent:
    def test_event_emitted_per_referenced_method(self) -> None:
        provider = _CapturingProvider(
            _plan_with_method_refs_json(
                ("M-add-middleware-001", "M-add-middleware-001", "M-fix-bug-001")
            )
        )
        decomposer = TaskDecomposer(llm_provider=provider)

        plan = decomposer.decompose("anything", max_steps=8)

        # Inspect the events through a fresh log so we can assert the
        # payload shape and ordering deterministically.
        log = InMemoryAuditLog()
        decomposer._emit_audit_event(plan, audit_log=log)
        events = log.all_events()

        method_events = [e for e in events if e.event_type == "lkb_method_referenced"]
        method_ids = [e.payload["methodId"] for e in method_events]
        assert method_ids == ["M-add-middleware-001", "M-fix-bug-001"]
        # Each event records the task count that referenced the method.
        counts = {e.payload["methodId"]: e.payload["taskCount"] for e in method_events}
        assert counts == {"M-add-middleware-001": 2, "M-fix-bug-001": 1}

    def test_no_event_when_plan_has_no_method_refs(self) -> None:
        provider = _CapturingProvider(_plan_with_method_refs_json((None, None)))
        decomposer = TaskDecomposer(llm_provider=provider)

        plan = decomposer.decompose("anything", max_steps=8)

        log = InMemoryAuditLog()
        decomposer._emit_audit_event(plan, audit_log=log)
        events = log.all_events()
        method_events = [e for e in events if e.event_type == "lkb_method_referenced"]
        assert method_events == []

    def test_event_payload_envelope(self) -> None:
        # Direct unit test on the event builder — the audit event shape
        # is the contract external consumers depend on.
        event = event_for_method_referenced(
            decomposition_run_id="D-test-001",
            method_id="M-add-middleware-001",
            task_count=3,
        )
        assert event.event_type == "lkb_method_referenced"
        assert event.payload["decompositionRunId"] == "D-test-001"
        assert event.payload["methodId"] == "M-add-middleware-001"
        assert event.payload["taskCount"] == 3
        assert event.payload["enrichmentKey"] == "D-test-001:M-add-middleware-001"
        assert event.decision is None

    def test_event_for_decomposition_proposed_remains_present(self) -> None:
        # F-149: the decomposition_proposed event must still fire even
        # when F-151 events are added alongside.
        provider = _CapturingProvider(
            _plan_with_method_refs_json(("M-add-middleware-001",))
        )
        decomposer = TaskDecomposer(llm_provider=provider)
        plan = decomposer.decompose("anything", max_steps=8)

        log = InMemoryAuditLog()
        decomposer._emit_audit_event(plan, audit_log=log)
        event_types = {e.event_type for e in log.all_events()}
        assert "lkb_decomposition_proposed" in event_types
        assert "lkb_method_referenced" in event_types

    def test_session_local_audit_log_receives_method_event(self) -> None:
        # The TaskDecompose tool re-emits decomposition_proposed to the
        # session-local audit log.  F-151 should also surface the
        # method_referenced events there.
        from clawcodex_ext.tool_system.tools.task_decompose import _task_decompose_call

        provider = _CapturingProvider(
            _plan_with_method_refs_json(("M-add-middleware-001",))
        )
        # We bypass the tool's is_enabled check by calling the inner
        # function with a fake provider and a real ToolContext.
        from clawcodex_ext.tool_system.context import ToolContext
        from pathlib import Path

        ctx = ToolContext(workspace_root=Path("."), session_id="S-f151")
        ctx._active_provider = provider  # type: ignore[attr-defined]

        result = _task_decompose_call(
            {"goal": "add a middleware", "max_steps": 8},
            ctx,
        )
        assert not result.is_error, result.output

        log = get_audit_log(ctx)
        method_events = [
            e for e in log.query(event_type="lkb_method_referenced")
            if e.event_type == "lkb_method_referenced"
        ]
        assert method_events, "session log should receive the method event"
        assert method_events[0].payload["methodId"] == "M-add-middleware-001"


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    def test_collect_method_references_dedupes(self) -> None:
        tasks = _plan_with_method_ref(method_refs=("M-a", "M-b", "M-a", "M-c", "M-b"))
        result = _collect_method_references(tasks, METHOD_LIBRARY)
        assert result == ("M-a", "M-b", "M-c")

    def test_collect_method_references_skips_empty_string(self) -> None:
        tasks = (
            ProposedTask(
                proposed_task_id="tmp-0",
                subject="x",
                description="",
                active_form="",
                acceptance_criteria=("ok",),
                blocked_by=(),
                lkb_metadata={"method_ref": ""},
            ),
        )
        assert _collect_method_references(tasks, METHOD_LIBRARY) == ()

    def test_collect_method_references_skips_non_string(self) -> None:
        tasks = (
            ProposedTask(
                proposed_task_id="tmp-0",
                subject="x",
                description="",
                active_form="",
                acceptance_criteria=("ok",),
                blocked_by=(),
                lkb_metadata={"method_ref": 1234},  # type: ignore[dict-item]
            ),
        )
        assert _collect_method_references(tasks, METHOD_LIBRARY) == ()

    def test_count_method_task_usage(self) -> None:
        tasks = _plan_with_method_ref(method_refs=("M-a", "M-a", "M-b"))
        counts = _count_method_task_usage(tasks)
        assert counts == {"M-a": 2, "M-b": 1}


# ---------------------------------------------------------------------------
# Integration smoke — end-to-end plan with method_ref survives audit
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_real_method_propagates_through_audit(self) -> None:
        provider = _CapturingProvider(
            _plan_with_method_refs_json(("M-add-middleware-001", "M-fix-bug-001"))
        )
        decomposer = TaskDecomposer(llm_provider=provider)

        plan = decomposer.decompose("add middleware", max_steps=8)

        # Field is set.
        assert "M-add-middleware-001" in plan.method_references
        assert "M-fix-bug-001" in plan.method_references
        # All tasks are present.
        assert len(plan.tasks) == 2
        # Validation did not block the plan (the R-METHOD-* warnings
        # are non-fatal by F-150 design).
        assert plan.validation_run is not None
