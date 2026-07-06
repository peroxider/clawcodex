"""Tests for F-144 TodoWrite fuzzy-gate coverage."""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest

from clawcodex_ext.logical_kanban import (
    Ambiguity,
    AmbiguityDetector,
    AmbiguityReport,
    LogicalKanbanService,
    ProposedChange,
    Severity,
)
from clawcodex_ext.logical_kanban.audit import get_audit_log
from clawcodex_ext.logical_kanban.fuzzy_patterns import (
    BUILT_IN_PATTERN_LIBRARY,
    FuzzyPattern,
)
from clawcodex_ext.logical_kanban.fuzzy_types import Interpretation
from clawcodex_ext.tool_system.context import ToolContext


def _dist_library_with_interps():
    """Mirror a downstream consumer's P-DIST-001 with the canonical split.

    F-148 ships the matcher-only shell in the default library; consumers
    that want the on_foot / straight_line / by_vehicle split register a
    replacement via ``FuzzyPatternLibrary.replace(...)``.  Tests use the
    same wiring.
    """
    return BUILT_IN_PATTERN_LIBRARY.replace(
        "P-DIST-001",
        FuzzyPattern(
            pattern_id="P-DIST-001",
            category="semantic_vagueness",
            severity="major",
            matcher=BUILT_IN_PATTERN_LIBRARY.patterns[0].matcher,
            interpretations=(
                Interpretation(
                    code="on_foot",
                    formalization="FootDistance({from}, {to}, {number})",
                    base_confidence=0.60,
                ),
                Interpretation(
                    code="straight_line",
                    formalization="EuclideanDistance({from}, {to}, {number})",
                    base_confidence=0.40,
                ),
                Interpretation(
                    code="by_vehicle",
                    formalization="VehicleDistance({from}, {to}, {number})",
                    base_confidence=0.00,
                ),
            ),
            clarification_prompt="您说的距离是指步行距离、直线距离还是驾车距离？",
        ),
    )


def _set_lkb(monkeypatch, enabled: bool) -> None:
    from clawcodex_ext.feature_gate import get_registry

    monkeypatch.setitem(get_registry()._overrides, "logical_kanban", enabled)


def _make_context(tmp_path: Any, session_id: str = "S-f144") -> ToolContext:
    return ToolContext(workspace_root=tmp_path, session_id=session_id)


def _legacy_todo(content: str, status: str = "pending") -> dict[str, Any]:
    return {"id": f"todo-{content[:8]}", "content": content, "status": status}


class _StubAmbiguityDetector:
    """Ambiguity detector that returns a fixed report per assertion_id."""

    def __init__(
        self,
        library: Any = None,
        *,
        llm_fallback_provider: Any = None,
        audit_log: Any = None,
    ) -> None:
        self.reports: dict[str, AmbiguityReport] = {}
        self.default = AmbiguityReport(assertion_id="default", severity="negligible")

    def add_report(self, assertion_id: str, report: AmbiguityReport) -> None:
        self.reports[assertion_id] = report

    def detect(
        self,
        text: str,
        *,
        assertion_id: str,
        context_facts: tuple[str, ...] = (),
    ) -> AmbiguityReport:
        return self.reports.get(assertion_id, self.default)


def _major_ambiguity_report(
    assertion_id: str = "A-major",
    pattern_id: str = "P-TEST-001",
    prompt: str = "请澄清此模糊表述。",
) -> AmbiguityReport:
    return AmbiguityReport(
        assertion_id=assertion_id,
        detected_ambiguities=(
            Ambiguity(
                phrase="模糊表述",
                kind="semantic_vagueness",
                severity="major",
                pattern_id=pattern_id,
                clarification_prompt=prompt,
            ),
        ),
        severity="major",
        needs_clarification=True,
    )


class TestTodoWriteFuzzyGate:
    def test_single_ambiguous_todo_is_denied(
        self,
        tmp_path: Any,
        monkeypatch: Any,
    ) -> None:
        _set_lkb(monkeypatch, True)
        ctx = _make_context(tmp_path)
        service = LogicalKanbanService()

        stub = _StubAmbiguityDetector()
        stub.add_report("todo:0", _major_ambiguity_report(pattern_id="P-TEST-001"))
        monkeypatch.setattr(
            "clawcodex_ext.logical_kanban.service.AmbiguityDetector", lambda **_: stub
        )

        change = ProposedChange(
            kind="legacy_todo_replace_all",
            payload={"todos": [_legacy_todo("模糊任务")]},
        )
        _proposal, validation, commit = service.run(change, ctx)

        assert commit.committed is False
        assert validation.result == "fail"
        assert validation.issues
        assert validation.issues[0].code == "LKB-TODOWRITE-AMBIG-001"
        assert validation.legacy_todo_ambiguities
        assert validation.legacy_todo_ambiguities[0]["todoId"] == "todo:0"
        assert validation.legacy_todo_ambiguities[0]["ambiguityCode"] == "P-TEST-001"

    def test_one_ambiguous_todo_denies_whole_batch(
        self,
        tmp_path: Any,
        monkeypatch: Any,
    ) -> None:
        _set_lkb(monkeypatch, True)
        ctx = _make_context(tmp_path)
        service = LogicalKanbanService()

        stub = _StubAmbiguityDetector()
        stub.add_report("todo:0", _major_ambiguity_report(pattern_id="P-TEST-001"))
        # todos 1-9 are clean.
        monkeypatch.setattr(
            "clawcodex_ext.logical_kanban.service.AmbiguityDetector", lambda **_: stub
        )

        todos = [_legacy_todo(f"clean-{i}") for i in range(9)]
        todos.insert(0, _legacy_todo("模糊任务"))
        change = ProposedChange(
            kind="legacy_todo_replace_all",
            payload={"todos": todos},
        )
        _proposal, validation, commit = service.run(change, ctx)

        assert commit.committed is False
        assert validation.issues[0].code == "LKB-TODOWRITE-AMBIG-001"

    def test_clean_todos_are_committed(
        self,
        tmp_path: Any,
        monkeypatch: Any,
    ) -> None:
        _set_lkb(monkeypatch, True)
        ctx = _make_context(tmp_path)
        service = LogicalKanbanService()

        stub = _StubAmbiguityDetector()
        monkeypatch.setattr(
            "clawcodex_ext.logical_kanban.service.AmbiguityDetector", lambda **_: stub
        )

        todos = [_legacy_todo(f"clean-{i}") for i in range(10)]
        change = ProposedChange(
            kind="legacy_todo_replace_all",
            payload={"todos": todos},
        )
        _proposal, validation, commit = service.run(change, ctx)

        assert commit.committed is True
        assert validation.result == "pass"
        assert validation.legacy_todo_ambiguities == ()
        assert validation.proof_trace[-1]["rule"] == "LKB-TODOWRITE-COMPAT-ALLOW"

    def test_distance_disambiguation_input_is_denied(
        self,
        tmp_path: Any,
        monkeypatch: Any,
    ) -> None:
        _set_lkb(monkeypatch, True)
        ctx = _make_context(tmp_path)
        # F-148: register the canonical on_foot / straight_line / by_vehicle
        # split as a downstream library so the F-144 fuzzy gate has material
        # to disambiguate.
        service = LogicalKanbanService(
            pattern_library=_dist_library_with_interps(),
        )

        text = "离家50米的任务，方式待定"
        change = ProposedChange(
            kind="legacy_todo_replace_all",
            payload={"todos": [{"id": "todo-dist", "content": text, "status": "pending"}]},
        )
        _proposal, validation, commit = service.run(change, ctx)

        assert commit.committed is False
        assert validation.issues[0].code == "LKB-TODOWRITE-AMBIG-001"
        assert validation.repair_suggestions
        assert validation.repair_suggestions[0].message == (
            "您说的距离是指步行距离、直线距离还是驾车距离？"
        )

    def test_audit_event_emitted_per_denied_todo(
        self,
        tmp_path: Any,
        monkeypatch: Any,
    ) -> None:
        _set_lkb(monkeypatch, True)
        ctx = _make_context(tmp_path)
        service = LogicalKanbanService()

        stub = _StubAmbiguityDetector()
        stub.add_report(
            "todo:0",
            _major_ambiguity_report(pattern_id="P-TEST-001", prompt="prompt-0"),
        )
        stub.add_report(
            "todo:2",
            _major_ambiguity_report(pattern_id="P-TEST-002", prompt="prompt-2"),
        )
        monkeypatch.setattr(
            "clawcodex_ext.logical_kanban.service.AmbiguityDetector", lambda **_: stub
        )

        todos = [
            _legacy_todo("模糊-0"),
            _legacy_todo("clean-1"),
            _legacy_todo("模糊-2"),
        ]
        service.run(
            ProposedChange(kind="legacy_todo_replace_all", payload={"todos": todos}),
            ctx,
        )

        events = get_audit_log(ctx).query(event_type="lkb_legacy_todo_ambiguity")
        assert len(events) == 2
        payloads = [e.payload for e in events]
        assert {p["todoId"] for p in payloads} == {"todo:0", "todo:2"}

    def test_clean_batch_emits_zero_ambiguity_events(
        self,
        tmp_path: Any,
        monkeypatch: Any,
    ) -> None:
        _set_lkb(monkeypatch, True)
        ctx = _make_context(tmp_path)
        service = LogicalKanbanService()

        stub = _StubAmbiguityDetector()
        monkeypatch.setattr(
            "clawcodex_ext.logical_kanban.service.AmbiguityDetector", lambda **_: stub
        )

        todos = [_legacy_todo(f"clean-{i}") for i in range(5)]
        service.run(
            ProposedChange(kind="legacy_todo_replace_all", payload={"todos": todos}),
            ctx,
        )

        events = get_audit_log(ctx).query(event_type="lkb_legacy_todo_ambiguity")
        assert len(events) == 0

    def test_no_ambiguity_detection_when_lkb_disabled(
        self,
        tmp_path: Any,
        monkeypatch: Any,
    ) -> None:
        _set_lkb(monkeypatch, False)
        ctx = _make_context(tmp_path)
        service = LogicalKanbanService()

        calls: list[tuple[str, str]] = []

        class TrackingDetector:
            def detect(self, text: str, *, assertion_id: str, **_: Any) -> AmbiguityReport:
                calls.append((text, assertion_id))
                return AmbiguityReport(assertion_id=assertion_id, severity="negligible")

        monkeypatch.setattr(
            "clawcodex_ext.logical_kanban.service.AmbiguityDetector",
            lambda **_: TrackingDetector(),
        )

        todos = [_legacy_todo("clean-0")]
        service.run(
            ProposedChange(kind="legacy_todo_replace_all", payload={"todos": todos}),
            ctx,
        )

        assert calls == []

    def test_ten_clean_todos_under_five_milliseconds(
        self,
        tmp_path: Any,
        monkeypatch: Any,
    ) -> None:
        _set_lkb(monkeypatch, True)
        ctx = _make_context(tmp_path)
        service = LogicalKanbanService()

        stub = _StubAmbiguityDetector()
        monkeypatch.setattr(
            "clawcodex_ext.logical_kanban.service.AmbiguityDetector", lambda **_: stub
        )

        todos = [_legacy_todo(f"clean-{i}") for i in range(10)]
        change = ProposedChange(
            kind="legacy_todo_replace_all",
            payload={"todos": todos},
        )
        start = time.perf_counter()
        _proposal, validation, commit = service.run(change, ctx)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert commit.committed is True
        assert validation.result == "pass"
        assert elapsed_ms < 5.0


class TestTodoWriteAdapterExposure:
    def test_denied_payload_includes_legacy_todo_ambiguities(
        self,
        tmp_path: Any,
        monkeypatch: Any,
    ) -> None:
        from clawcodex_ext.logical_kanban.adapters import _denied_result
        from clawcodex_ext.logical_kanban.types import CommitResult, Proposal, ValidationRun

        _set_lkb(monkeypatch, True)
        proposal = Proposal(
            proposal_id="P-test",
            change=ProposedChange(
                kind="legacy_todo_replace_all",
                payload={"todos": []},
            ),
            snapshot_hash="sha256:snap",
        )
        validation = ValidationRun(
            validation_run_id="V-test",
            proposal_id="P-test",
            result="fail",
            issues=(),
            legacy_todo_ambiguities=(
                {
                    "todoId": "todo:0",
                    "ambiguityCode": "P-TEST-001",
                    "severity": "major",
                    "clarificationPrompt": "prompt",
                },
            ),
        )
        commit = CommitResult(
            committed=False,
            proposal_id="P-test",
            validation_run_id="V-test",
        )

        result = _denied_result("TodoWrite", proposal, validation, commit)
        lkb = result.output["lkb"]
        assert lkb["legacyTodoAmbiguities"][0]["todoId"] == "todo:0"
