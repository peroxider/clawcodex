"""F-143 runtime LLM-derived knowledge facts for Logical Kanban."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from clawcodex_ext.feature_gate import get_registry
from clawcodex_ext.logical_kanban import (
    AmbiguityDetector,
    CanonicalAssertion,
    InMemoryAuditLog,
    LogicalKanbanService,
    LlmFactExtractor,
    LlmKnowledgeAdapter,
    ProposedChange,
    extended_adapters,
    extract_facts,
    is_llm_facts_enabled,
)
from clawcodex_ext.logical_kanban.audit import (
    event_for_fact_dropped,
    event_for_fact_extracted,
)
from clawcodex_ext.logical_kanban.context_adapter import build_facts_snapshot
from clawcodex_ext.logical_kanban.fuzzy_types import AmbiguityKind
from clawcodex_ext.logical_kanban.glossary import BUILT_IN_GLOSSARY
from clawcodex_ext.logical_kanban.ir import pred
from clawcodex_ext.logical_kanban.ir_hash import assertion_hash
from clawcodex_ext.logical_kanban.runtime import get_logical_kanban
from clawcodex_ext.logical_kanban.solver_adapter import encode_solver_literal
from clawcodex_ext.logical_kanban.types import FactsSnapshot, Proposal
from clawcodex_ext.providers.base import ChatResponse


def _set_llm_facts(monkeypatch, enabled: bool) -> None:
    monkeypatch.setitem(get_registry()._overrides, "logical_kanban", True)
    monkeypatch.setitem(get_registry()._overrides, "LKB_LLM_FACTS", enabled)


class _StubProvider:
    """Test double that returns scripted JSON content from chat()."""

    def __init__(self, content: str, model: str = "stub-model") -> None:
        self.content = content
        self.model = model
        self.calls: list[list[Any]] = []

    def chat(self, messages: list[Any], tools: Any = None, **kwargs: Any) -> ChatResponse:
        self.calls.append(messages)
        return ChatResponse(
            content=self.content,
            model=self.model,
            usage={},
            finish_reason="stop",
        )


def _snapshot(tasks: dict[str, dict[str, Any]]) -> FactsSnapshot:
    return build_facts_snapshot(SimpleNamespace(tasks=tasks, todos=()))


def _task(
    task_id: str,
    *,
    status: str = "pending",
    blocked_by: list[str] | None = None,
    subject: str = "",
    description: str = "",
) -> dict[str, Any]:
    return {
        "id": task_id,
        "subject": subject or task_id,
        "description": description,
        "status": status,
        "blocks": [],
        "blockedBy": list(blocked_by or []),
        "metadata": {},
    }


class TestL1FactExtractor:
    def test_extract_facts_returns_glossary_bound_assertions(self, monkeypatch) -> None:
        _set_llm_facts(monkeypatch, True)
        response = json.dumps(
            {
                "facts": [
                    {
                        "predicate": "Requires",
                        "args": ["task_a", "task_x"],
                        "source": "llm_extracted",
                        "confidence": 0.6,
                    }
                ],
                "model_id": "stub-model",
            }
        )
        provider = _StubProvider(response)
        snapshot = _snapshot({"task_a": _task("task_a"), "task_x": _task("task_x")})
        facts = extract_facts(snapshot, BUILT_IN_GLOSSARY, provider=provider)

        assert len(facts) == 1
        assert facts[0].body == pred(
            "Requires",
            encode_solver_literal("task_a"),
            encode_solver_literal("task_x"),
        )

    def test_extract_facts_drops_unknown_predicate_and_audits(
        self, monkeypatch
    ) -> None:
        _set_llm_facts(monkeypatch, True)
        response = json.dumps(
            {
                "facts": [
                    {
                        "predicate": "UnknownPredicate",
                        "args": ["a", "b"],
                        "source": "llm_extracted",
                        "confidence": 0.6,
                    }
                ]
            }
        )
        provider = _StubProvider(response)
        audit_log = InMemoryAuditLog()
        snapshot = _snapshot({"a": _task("a"), "b": _task("b")})
        facts = extract_facts(
            snapshot, BUILT_IN_GLOSSARY, provider=provider
        )

        assert facts == ()
        dropped = audit_log.query(event_type="lkb_fact_dropped")
        assert len(dropped) == 0  # convenience function passes audit_log=None

    def test_extractor_emits_dropped_event_when_audit_log_provided(
        self, monkeypatch
    ) -> None:
        _set_llm_facts(monkeypatch, True)
        response = json.dumps(
            {
                "facts": [
                    {
                        "predicate": "UnknownPredicate",
                        "args": ["a"],
                        "source": "llm_extracted",
                        "confidence": 0.6,
                    }
                ]
            }
        )
        provider = _StubProvider(response)
        audit_log = InMemoryAuditLog()
        snapshot = _snapshot({"a": _task("a")})
        extractor = LlmFactExtractor(provider=provider)
        extractor.run(snapshot, BUILT_IN_GLOSSARY, audit_log=audit_log)

        dropped = audit_log.query(event_type="lkb_fact_dropped")
        assert len(dropped) == 1
        assert dropped[0].payload["reason"] == "unknown_predicate"
        assert dropped[0].payload["unknownPredicates"] == ["UnknownPredicate"]

    def test_extract_facts_is_idempotent(self, monkeypatch) -> None:
        _set_llm_facts(monkeypatch, True)
        response = json.dumps(
            {
                "facts": [
                    {
                        "predicate": "Requires",
                        "args": ["a", "b"],
                        "source": "llm_extracted",
                        "confidence": 0.6,
                    }
                ]
            }
        )
        provider = _StubProvider(response)
        audit_log = InMemoryAuditLog()
        snapshot = _snapshot({"a": _task("a"), "b": _task("b")})
        extractor = LlmFactExtractor(provider=provider)

        _first = extractor.run(snapshot, BUILT_IN_GLOSSARY, audit_log=audit_log)
        _second = extractor.run(snapshot, BUILT_IN_GLOSSARY, audit_log=audit_log)

        extracted = audit_log.query(event_type="lkb_fact_extracted")
        assert len(extracted) == 1

    def test_extract_facts_disabled_when_flag_off(self, monkeypatch) -> None:
        _set_llm_facts(monkeypatch, False)
        provider = _StubProvider('{"facts": []}')
        snapshot = _snapshot({"a": _task("a")})

        facts = extract_facts(snapshot, BUILT_IN_GLOSSARY, provider=provider)

        assert facts == ()
        assert provider.calls == []
    def test_audit_event_source_is_normalized(self, monkeypatch) -> None:
        _set_llm_facts(monkeypatch, True)
        response = json.dumps(
            {
                "facts": [
                    {
                        "predicate": "Requires",
                        "args": ["a", "b"],
                        "source": "evil_source",
                        "confidence": 0.6,
                    }
                ]
            }
        )
        provider = _StubProvider(response)
        audit_log = InMemoryAuditLog()
        snapshot = _snapshot({"a": _task("a"), "b": _task("b")})
        extractor = LlmFactExtractor(provider=provider)
        extractor.run(snapshot, BUILT_IN_GLOSSARY, audit_log=audit_log)

        extracted = audit_log.query(event_type="lkb_fact_extracted")
        assert len(extracted) == 1
        assert extracted[0].payload["source"] == "llm_extracted"

    def test_assertion_vars_are_tuple_and_repeatable(self, monkeypatch) -> None:
        _set_llm_facts(monkeypatch, True)
        response = json.dumps(
            {
                "facts": [
                    {
                        "predicate": "Requires",
                        "args": ["a", "b"],
                        "source": "llm_extracted",
                        "confidence": 0.6,
                    }
                ]
            }
        )
        provider = _StubProvider(response)
        snapshot = _snapshot({"a": _task("a"), "b": _task("b")})
        facts = extract_facts(snapshot, BUILT_IN_GLOSSARY, provider=provider)

        assert len(facts) == 1
        assertion = facts[0]
        assert isinstance(assertion.vars, tuple)
        first = assertion.to_dict()["vars"]
        second = assertion.to_dict()["vars"]
        assert len(first) == 2
        assert first == second


class TestL2KnowledgeAdapter:
    def test_adapter_unavailable_without_provider(self) -> None:
        adapter = LlmKnowledgeAdapter(provider=None)
        assert not adapter.available()

    def test_adapter_absent_from_extended_adapters_by_default(self) -> None:
        names = {adapter.name for adapter in extended_adapters()}
        assert "llm-knowledge" not in names

    def test_malformed_json_returns_unknown(self, monkeypatch) -> None:
        _set_llm_facts(monkeypatch, True)
        provider = _StubProvider("not valid json")
        adapter = LlmKnowledgeAdapter(provider=provider)
        from clawcodex_ext.logical_kanban.solver_adapter import SolverRequest

        request = SolverRequest(snapshot=_snapshot({"a": _task("a")}))
        response = adapter.solve(request)
        assert response.result == "unknown"

    def test_conservative_veto_on_fail(self, monkeypatch) -> None:
        _set_llm_facts(monkeypatch, True)
        provider = _StubProvider('{"verdict": "fail"}')
        adapter = LlmKnowledgeAdapter(provider=provider)
        from clawcodex_ext.logical_kanban.solver_adapter import SolverRequest

        request = SolverRequest(snapshot=_snapshot({"a": _task("a")}))
        response = adapter.solve(request)
        assert response.result == "fail"
        assert response.error_info is not None
        assert response.error_info["reason"] == "llm_conservative_veto"

    def test_pass_is_advisory(self, monkeypatch) -> None:
        _set_llm_facts(monkeypatch, True)
        provider = _StubProvider('{"verdict": "pass"}')
        adapter = LlmKnowledgeAdapter(provider=provider)
        from clawcodex_ext.logical_kanban.solver_adapter import SolverRequest

        request = SolverRequest(snapshot=_snapshot({"a": _task("a")}))
        response = adapter.solve(request)
        assert response.result == "pass"


class TestL3AmbiguityFallback:
    def test_llm_fallback_classifies_known_kind(self, monkeypatch) -> None:
        _set_llm_facts(monkeypatch, True)
        response = json.dumps(
            {
                "kind": "semantic_vagueness",
                "interpretations": [
                    {
                        "code": "walking",
                        "formalization": "WalkingDistance({from}, {to}, {number})",
                        "confidence": 0.6,
                    }
                ],
            }
        )
        audit_log = InMemoryAuditLog()
        detector = AmbiguityDetector(
            llm_fallback_provider=_StubProvider(response),
            audit_log=audit_log,
        )
        report = detector.detect("unmatched phrase for testing", assertion_id="A-1")

        assert report.detection_method == "llm_fallback"
        assert len(report.detected_ambiguities) == 1
        ambiguity = report.detected_ambiguities[0]
        assert ambiguity.kind == "semantic_vagueness"
        assert any(i.code == "walking" for i in ambiguity.candidate_interpretations)
        fallback_events = audit_log.query(event_type="lkb_llm_fallback_used")
        assert len(fallback_events) == 1
        assert fallback_events[0].payload["kind"] == "semantic_vagueness"

    def test_llm_fallback_rejects_free_form_kind(self, monkeypatch) -> None:
        _set_llm_facts(monkeypatch, True)
        response = json.dumps(
            {
                "kind": "made_up_kind",
                "interpretations": [
                    {
                        "code": "walking",
                        "formalization": "...",
                        "confidence": 0.6,
                    }
                ],
            }
        )
        detector = AmbiguityDetector(llm_fallback_provider=_StubProvider(response))
        with pytest.raises(ValueError):
            detector.detect("some phrase", assertion_id="A-1")

    def test_llm_fallback_noop_without_provider(self, monkeypatch) -> None:
        _set_llm_facts(monkeypatch, True)
        detector = AmbiguityDetector(llm_fallback_provider=None)
        report = detector.detect("some phrase", assertion_id="A-1")
        assert report.detection_method == "datalog_rules"
        assert report.detected_ambiguities == ()

    def test_llm_fallback_noop_when_flag_off(self, monkeypatch) -> None:
        _set_llm_facts(monkeypatch, False)
        response = json.dumps(
            {
                "kind": "semantic_vagueness",
                "interpretations": [
                    {
                        "code": "walking",
                        "formalization": "...",
                        "confidence": 0.6,
                    }
                ],
            }
        )
        detector = AmbiguityDetector(llm_fallback_provider=_StubProvider(response))
        report = detector.detect("some phrase", assertion_id="A-1")
        assert report.detection_method == "datalog_rules"
        assert report.detected_ambiguities == ()


class TestFeatureFlagBehaviour:
    def test_is_llm_facts_enabled_requires_parent_flag(self, monkeypatch) -> None:
        monkeypatch.setitem(get_registry()._overrides, "logical_kanban", False)
        monkeypatch.setitem(get_registry()._overrides, "LKB_LLM_FACTS", True)
        assert not is_llm_facts_enabled()


class TestGenericDistanceRegression:
    def test_hundred_meter_distance_passes_with_llm_fact(self, monkeypatch) -> None:
        _set_llm_facts(monkeypatch, True)
        response = json.dumps(
            {
                "facts": [
                    {
                        "predicate": "Requires",
                        "args": ["task_a", "task_x"],
                        "source": "llm_extracted",
                        "confidence": 0.7,
                    }
                ]
            }
        )
        provider = _StubProvider(response)
        ctx = SimpleNamespace(
            tasks={
                "task_a": _task("task_a", status="completed"),
                "task_x": _task(
                    "task_x",
                    status="in_progress",
                    subject="距离 100米",
                ),
            },
            todos=(),
        )
        runtime = get_logical_kanban(ctx)
        runtime.audit_log = InMemoryAuditLog()
        service = LogicalKanbanService(llm_provider=provider)

        change = ProposedChange(
            kind="transition_status",
            payload={"taskId": "task_x", "status": "completed"},
            actor="tester",
        )
        proposal, validation, commit = service.run(change, ctx)

        assert validation.result == "pass"
        assert commit.committed is True
        assert validation.proof_trace
        extracted = runtime.audit_log.query(event_type="lkb_fact_extracted")
        assert len(extracted) == 1
