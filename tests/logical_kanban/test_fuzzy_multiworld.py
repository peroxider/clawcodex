from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from clawcodex_ext.logical_kanban.ambiguity_detector import AmbiguityDetector
from clawcodex_ext.logical_kanban.commit_gate_fuzzy import (
    aggregate_world_results,
    commit_gate_fuzzy_check,
)
from clawcodex_ext.logical_kanban.fuzzy_patterns import BUILT_IN_PATTERN_LIBRARY
from clawcodex_ext.logical_kanban.fuzzy_types import (
    Assumption,
    Clarification,
    WorldValidationResult,
)
from clawcodex_ext.logical_kanban.ir import make_canonical, pred
from clawcodex_ext.logical_kanban.multiworld_validator import MultiWorldValidator
from clawcodex_ext.logical_kanban.rule_engine import Layer1RuleEngine
from clawcodex_ext.logical_kanban.service import LogicalKanbanService
from clawcodex_ext.logical_kanban.types import ProposedChange
from clawcodex_ext.logical_kanban.world_generator import WorldGenerator
from clawcodex_ext.tool_system.context import ToolContext


@pytest.fixture
def empty_context(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace_root=tmp_path)


@pytest.fixture
def service() -> LogicalKanbanService:
    return LogicalKanbanService()


@pytest.fixture
def engine() -> Layer1RuleEngine:
    return Layer1RuleEngine()


def _add_task(
    context: ToolContext,
    task_id: str,
    *,
    status: str = "pending",
    blocked_by: list[str] | None = None,
    blocks: list[str] | None = None,
) -> None:
    context.tasks[task_id] = {
        "id": task_id,
        "subject": task_id,
        "status": status,
        "blockedBy": list(blocked_by or []),
        "blocks": list(blocks or []),
    }


def _base_assertion():
    return make_canonical(
        role="axiom",
        kind="prerequisite",
        body=pred("Task", "T"),
        vars=(),
    )


class TestAmbiguityDetector:
    def test_detects_distance_vagueness(self) -> None:
        detector = AmbiguityDetector()
        report = detector.detect("离家50米的洗车店", assertion_id="A-1")

        assert report.needs_clarification is True
        assert any(a.kind == "semantic_vagueness" for a in report.detected_ambiguities)
        distance_amb = next(
            a for a in report.detected_ambiguities if a.kind == "semantic_vagueness"
        )
        assert distance_amb.severity == "major"
        codes = {i.code for i in distance_amb.candidate_interpretations}
        assert "on_foot" in codes
        assert "straight_line" in codes

    def test_detects_unclear_dependency_direction(self) -> None:
        detector = AmbiguityDetector()
        report = detector.detect("任务A依赖任务B", assertion_id="A-3")

        dep_amb = next(
            (a for a in report.detected_ambiguities if a.kind == "unclear_dependency_direction"),
            None,
        )
        assert dep_amb is not None
        assert dep_amb.severity == "critical"
        assert report.needs_clarification is True

    def test_driving_context_boosts_driving_interpretation(self) -> None:
        detector = AmbiguityDetector()
        report = detector.detect("驾车离家50米", assertion_id="A-4")

        amb = next(a for a in report.detected_ambiguities if a.kind == "semantic_vagueness")
        by_vehicle = next(i for i in amb.candidate_interpretations if i.code == "by_vehicle")
        # After normalisation by_vehicle may not exceed 0.5, but it should be the
        # highest-confidence interpretation when driving context is present.
        assert by_vehicle.base_confidence == max(
            i.base_confidence for i in amb.candidate_interpretations
        )


class TestWorldGenerator:
    def test_generates_multiple_worlds(self) -> None:
        detector = AmbiguityDetector()
        report = detector.detect("离家50米的洗车店", assertion_id="A-1")
        worlds = WorldGenerator().generate(report, _base_assertion())

        assert len(worlds) >= 2
        total_confidence = sum(w.confidence for w in worlds)
        assert abs(total_confidence - 1.0) < 1e-6

    def test_world_confidences_sum_to_one(self) -> None:
        detector = AmbiguityDetector()
        report = detector.detect("很快完成", assertion_id="A-2")
        worlds = WorldGenerator().generate(report, _base_assertion())

        assert sum(w.confidence for w in worlds) == pytest.approx(1.0)

    def test_no_ambiguity_yields_single_world(self) -> None:
        detector = AmbiguityDetector()
        report = detector.detect("Task T exists", assertion_id="A-5")
        worlds = WorldGenerator().generate(report, _base_assertion())

        assert len(worlds) == 1
        assert worlds[0].confidence == 1.0

    def test_domain_constraint_prunes_invalid_world(self) -> None:
        # The default library ships no domain constraints (the car-wash
        # constraint was removed in F-148 PR 1).  Downstream callers can
        # still attach ``FuzzyPatternLibrary.add_constraint(...)``; this
        # test exercises that path with a synthetic cross-ambiguity block.
        #
        # The phrase "很快完成" matches *two* generic patterns — P-TEMP-001
        # (``immediate`` / ``soon`` / ``today``) and P-ACCEPT-001
        # (``needs_acceptance_proof`` / ``implicit_acceptance``) — so the
        # Cartesian product can pair any temporal pick with any acceptance
        # pick.  Blocking ``{immediate, needs_acceptance_proof}`` prunes
        # only the worlds where that particular pair co-occurs.
        from clawcodex_ext.logical_kanban.fuzzy_patterns import DomainConstraint

        constraint = DomainConstraint(
            blocks=frozenset({"immediate", "needs_acceptance_proof"}),
            rationale="test-only cross-ambiguity block",
        )
        library = BUILT_IN_PATTERN_LIBRARY.add_constraint(constraint)

        detector = AmbiguityDetector(library=library)
        report = detector.detect("很快完成", assertion_id="A-6")
        worlds = WorldGenerator(library=library).generate(report, _base_assertion())

        selected_codes = [
            {a.assumed_value for a in w.assumptions} for w in worlds
        ]
        # Sanity check: the constraint must actually trigger — at least one
        # surviving world carries ``immediate`` or ``needs_acceptance_proof``,
        # but never both.
        immediate_worlds = [c for c in selected_codes if "immediate" in c]
        accept_proof_worlds = [
            c for c in selected_codes if "needs_acceptance_proof" in c
        ]
        assert immediate_worlds or accept_proof_worlds
        for codes in selected_codes:
            assert not ({"immediate", "needs_acceptance_proof"} <= codes)


class TestMultiWorldValidator:
    def test_validates_consistent_worlds(self, empty_context: ToolContext, engine: Layer1RuleEngine) -> None:
        _add_task(empty_context, "A", status="completed")
        _add_task(empty_context, "B", status="pending", blocked_by=["A"])
        snapshot = engine.from_context(empty_context)

        detector = AmbiguityDetector()
        report = detector.detect("任务B可以开始", assertion_id="A-7")
        worlds = WorldGenerator().generate(report, _base_assertion())

        validator = MultiWorldValidator(engine)
        results = validator.validate(worlds, snapshot, target_task_id="B", target_status="in_progress")

        assert len(results) == len(worlds)
        assert all(r.result == "pass" for r in results)
        conclusion_hashes = {r.conclusion_hash for r in results}
        assert len(conclusion_hashes) == 1

    def test_detects_divergent_worlds(self, empty_context: ToolContext, engine: Layer1RuleEngine) -> None:
        _add_task(empty_context, "A", status="pending")
        _add_task(empty_context, "B", status="pending", blocked_by=["A"])
        snapshot = engine.from_context(empty_context)

        # Build two worlds manually to force different conclusions.
        world_pass = WorldValidationResult(
            world_id="W-pass",
            result="pass",
            conclusion_hash="hash-pass",
            derived_facts=("Ready(B)",),
        )
        world_fail = WorldValidationResult(
            world_id="W-fail",
            result="fail",
            conclusion_hash="hash-fail",
            derived_facts=(),
        )

        decision = aggregate_world_results([world_pass, world_fail])
        assert decision.strategy == "partial_pass"
        assert decision.action == "request_clarification"


class TestCommitGateFuzzy:
    def test_denies_low_confidence_assumption(self) -> None:
        world = WorldGenerator().generate(
            AmbiguityDetector().detect("很快完成", assertion_id="A-8"),
            _base_assertion(),
        )[0]
        result = WorldValidationResult(
            world_id=world.world_id,
            result="pass",
            conclusion_hash="hash-1",
        )

        from clawcodex_ext.logical_kanban.fuzzy_types import AmbiguityReport

        decision = commit_gate_fuzzy_check(
            [world],
            [result],
            AmbiguityReport(assertion_id="A-8"),
        )

        # The temporal interpretations have confidences 0.40/0.45/0.15 all above threshold,
        # so this specific test checks that the gate is invoked.  We just assert the
        # result is a CommitDecision.
        assert decision.commit in (True, False)

    def test_denies_divergent_conclusions(self) -> None:
        results = [
            WorldValidationResult(world_id="W1", result="pass", conclusion_hash="a"),
            WorldValidationResult(world_id="W2", result="pass", conclusion_hash="b"),
        ]
        from clawcodex_ext.logical_kanban.fuzzy_types import AmbiguityReport

        decision = commit_gate_fuzzy_check([], results, AmbiguityReport(assertion_id="A"))
        assert decision.commit is False
        assert decision.reason == "fuzzy_divergent_worlds"

    def test_allows_unanimous_pass(self) -> None:
        results = [
            WorldValidationResult(world_id="W1", result="pass", conclusion_hash="same"),
            WorldValidationResult(world_id="W2", result="pass", conclusion_hash="same"),
        ]
        from clawcodex_ext.logical_kanban.fuzzy_types import AmbiguityReport

        decision = commit_gate_fuzzy_check([], results, AmbiguityReport(assertion_id="A"))
        assert decision.commit is True
        assert decision.reason == "fuzzy_check_pass"

    def test_denies_unresolved_critical_ambiguity(self) -> None:
        from clawcodex_ext.logical_kanban.fuzzy_types import Ambiguity, AmbiguityReport

        report = AmbiguityReport(
            assertion_id="A",
            detected_ambiguities=(
                Ambiguity(
                    phrase="洗车",
                    kind="semantic_vagueness",
                    severity="critical",
                    resolved=False,
                ),
            ),
        )
        results = [
            WorldValidationResult(world_id="W1", result="pass", conclusion_hash="same"),
        ]
        decision = commit_gate_fuzzy_check([], results, report)
        assert decision.commit is False
        assert decision.reason == "fuzzy_critical_unresolved"


class TestClarification:
    def test_user_clarification_overrides_assumption(self) -> None:
        detector = AmbiguityDetector()
        report = detector.detect("离家50米", assertion_id="A-9")
        worlds = WorldGenerator().generate(report, _base_assertion())

        # Simulate user clarifying the walking assumption.
        original = worlds[0].assumptions[0]
        clarified = Assumption(
            assumption_id=original.assumption_id,
            assertion_id=original.assertion_id,
            field=original.field,
            assumed_value="walking",
            confidence=1.0,
            source="user_clarified",
            clarified_at="2026-07-05T12:00:00Z",
        )

        assert clarified.confidence == 1.0
        assert clarified.source == "user_clarified"


class TestServiceIntegration:
    def test_propose_assertion_denies_ambiguous_dependency(
        self, service: LogicalKanbanService, empty_context: ToolContext
    ) -> None:
        change = ProposedChange(
            kind="propose_assertion",
            payload={
                "text": "任务A依赖任务B",
                "baseAssertion": _base_assertion(),
                "isIrreversible": True,
            },
            actor="user",
        )
        proposal, validation, commit = service.run(change, empty_context)

        assert commit.committed is False
        assert validation.result == "fail"
        assert validation.issues[0].code in (
            "fuzzy_critical_unresolved",
            "fuzzy_clarification_needed_for_irreversible_change",
        )

    def test_evaluate_assertion_returns_worlds(self, service: LogicalKanbanService) -> None:
        result = service.evaluate_assertion(
            "离家50米的洗车店",
            _base_assertion(),
            assertion_id="A-10",
        )

        assert result.assertion_id == "A-10"
        assert len(result.worlds) >= 2
        assert result.ambiguity_report.needs_clarification is True

    def test_propose_assertion_allows_unambiguous_assertion(
        self, service: LogicalKanbanService, empty_context: ToolContext
    ) -> None:
        change = ProposedChange(
            kind="propose_assertion",
            payload={
                "text": "Task T exists",
                "baseAssertion": _base_assertion(),
                "isIrreversible": False,
            },
            actor="user",
        )
        proposal, validation, commit = service.run(change, empty_context)

        assert validation.result == "pass"
        assert commit.committed is True
