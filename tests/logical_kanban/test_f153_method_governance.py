"""Tests for F-153 Method Library Growth & Governance.

Covers:
- method_proposer.py — propose_method_from_plan + validation
- method_governance.py — state machine transitions + proposal lifecycle
- method_library.py — version management (SemVer, bump, incompat)
- method_coverage.py — coverage evaluator + golden set
- CLI commands (via function call)
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import pytest

from clawcodex_ext.logical_kanban.method_library import (
    AcceptanceTemplate,
    EngineeringMethod,
    METHOD_LIBRARY,
    SubtaskTemplate,
    bump_version,
    ensure_default_dirs,
    get_all_methods,
    get_method,
    incompatible_change,
    list_methods,
    load_method_library_layered,
    register_method,
    reset_method_registry,
    load_method_library,
    save_method_library,
)
from clawcodex_ext.logical_kanban.method_proposer import (
    _check_dag_no_cycle,
    _validate_proposed_method,
    propose_method_from_plan,
)
from clawcodex_ext.logical_kanban.method_governance import (
    approve_method,
    deprecate_method,
    get_proposal,
    list_proposals,
    reject_method,
    reset_proposals,
    submit_method,
    load_proposals,
    _transition,
)
from clawcodex_ext.logical_kanban.method_coverage import MethodCoverageEvaluator
from clawcodex_ext.logical_kanban.decomposer import (
    DecompositionPlan,
    ProposedTask,
)
from clawcodex_ext.logical_kanban.fuzzy_types import AmbiguityReport


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    """Reset the method registry and proposal store before each test."""
    reset_method_registry(include_seeds=True)
    reset_proposals()


def _subtask(
    template_id: str,
    role: str = "impl",
    subject: str = "Do {thing}",
    description: str = "Implement {thing}",
    acceptance: str = "",
    default_blocked_by: tuple[str, ...] = (),
) -> SubtaskTemplate:
    return SubtaskTemplate(
        template_id=template_id,
        role=role,
        subject_template=subject,
        description_template=description,
        acceptance_template=acceptance,
        default_blocked_by=default_blocked_by,
    )


def _make_accepted() -> AcceptanceTemplate:
    return AcceptanceTemplate(assertion_template="{thing} works")


def _make_draft_method(
    method_id: str = "M-001",
    pattern: str = "add_api_endpoint",
    status: str = "draft",
) -> EngineeringMethod:
    return EngineeringMethod(
        method_id=method_id,
        pattern=pattern,
        description="Test method",
        subtask_templates=(
            _subtask("ST-1", "design", "Design {thing}"),
            _subtask("ST-2", "impl", "Implement {thing}", default_blocked_by=("ST-1",)),
            _subtask("ST-3", "test", "Test {thing}", default_blocked_by=("ST-2",)),
        ),
        preconditions=("Precondition exists",),
        assumptions=("Assumption holds",),
        acceptance_template=_make_accepted(),
        version="0.1.0",
        status=status,
    )


def _make_plan(**overrides: Any) -> DecompositionPlan:
    defaults: dict[str, Any] = {
        "decomposition_run_id": "RUN-001",
        "goal": "Add JWT auth middleware",
        "tasks": (
            ProposedTask(
                proposed_task_id="T-001",
                subject="Design JWT middleware",
                description="Design the middleware architecture",
                active_form="Designing JWT middleware",
                acceptance_criteria=("Design approved",),
                blocked_by=(),
                lkb_metadata={"role": "design"},
            ),
            ProposedTask(
                proposed_task_id="T-002",
                subject="Implement JWT verification",
                description="Write the verification logic",
                active_form="Implementing JWT verification",
                acceptance_criteria=("Tests pass",),
                blocked_by=("T-001",),
                lkb_metadata={"role": "impl"},
            ),
            ProposedTask(
                proposed_task_id="T-003",
                subject="Write tests for JWT middleware",
                description="Unit and integration tests",
                active_form="Writing tests",
                acceptance_criteria=("Coverage >= 80%",),
                blocked_by=("T-002",),
                lkb_metadata={"role": "test"},
            ),
            ProposedTask(
                proposed_task_id="T-004",
                subject="Document JWT middleware usage",
                description="Write usage docs",
                active_form="Writing docs",
                acceptance_criteria=("Docs reviewed",),
                blocked_by=(),
                lkb_metadata={"role": "docs"},
            ),
        ),
        "dependencies": (("T-001", "T-002"), ("T-002", "T-003")),
        "assumptions": ("Auth service is available",),
        "ambiguity_report": None,
        "validation_run": None,
        "method_references": ("add_middleware",),
    }
    defaults.update(overrides)
    return DecompositionPlan(**defaults)


# ===================================================================
# Phase 1 — proposer
# ===================================================================


class TestMethodProposer:
    def test_propose_from_valid_plan(self) -> None:
        plan = _make_plan()
        method = propose_method_from_plan(
            plan,
            method_id="M-101",
            pattern="add_middleware",
            description="Auto-proposed JWT middleware method",
        )
        assert method.method_id == "M-101"
        assert method.status == "draft"
        assert method.version == "0.1.0"
        assert len(method.subtask_templates) >= 3
        assert method.acceptance_template is not None
        assert method.acceptance_template.assertion_template
        assert len(method.preconditions) == 1
        assert method.preconditions[0] == "Auth service is available"

    def test_propose_from_empty_plan_raises(self) -> None:
        plan = _make_plan(tasks=())
        with pytest.raises(ValueError, match="zero tasks"):
            propose_method_from_plan(
                plan, method_id="M-102", pattern="test", description=""
            )

    def test_validate_proposed_method_requires_3_subtasks(self) -> None:
        method = EngineeringMethod(
            method_id="M-103",
            pattern="foo",
            description="Too few subtasks",
            subtask_templates=(
                _subtask("ST-1", "impl", "Do work"),
            ),
            preconditions=("Pre",),
            assumptions=("Assumption",),
            acceptance_template=_make_accepted(),
            version="0.1.0",
            status="draft",
        )
        with pytest.raises(ValueError, match="at least 3"):
            _validate_proposed_method(method)

    def test_validate_requires_acceptance(self) -> None:
        method = EngineeringMethod(
            method_id="M-104",
            pattern="foo",
            description="No acceptance",
            subtask_templates=(
                _subtask("ST-1", "impl", "A"),
                _subtask("ST-2", "test", "B"),
                _subtask("ST-3", "docs", "C"),
            ),
            preconditions=("Pre",),
            assumptions=("Assumption",),
            acceptance_template=None,
            version="0.1.0",
            status="draft",
        )
        with pytest.raises(ValueError, match="acceptance criterion"):
            _validate_proposed_method(method)

    def test_validate_requires_preconditions(self) -> None:
        method = EngineeringMethod(
            method_id="M-105",
            pattern="foo",
            description="No preconditions",
            subtask_templates=(
                _subtask("ST-1", "impl", "A"),
                _subtask("ST-2", "test", "B"),
                _subtask("ST-3", "docs", "C"),
            ),
            preconditions=(),
            assumptions=(),
            acceptance_template=_make_accepted(),
            version="0.1.0",
            status="draft",
        )
        with pytest.raises(ValueError, match="non-empty preconditions"):
            _validate_proposed_method(method)

    def test_dag_cycle_detection(self) -> None:
        """A blocked_by cycle should raise."""
        method = EngineeringMethod(
            method_id="M-106",
            pattern="cyclic",
            description="Has a cycle",
            subtask_templates=(
                _subtask("ST-1", "impl", "A", default_blocked_by=("ST-3",)),
                _subtask("ST-2", "test", "B", default_blocked_by=("ST-1",)),
                _subtask("ST-3", "docs", "C", default_blocked_by=("ST-2",)),
            ),
            preconditions=("Pre",),
            assumptions=("A",),
            acceptance_template=_make_accepted(),
            version="0.1.0",
            status="draft",
        )
        with pytest.raises(ValueError, match="cycle"):
            _check_dag_no_cycle(method)

    def test_valid_dag_passes(self) -> None:
        """A valid DAG should not raise."""
        method = EngineeringMethod(
            method_id="M-107",
            pattern="daggy",
            description="Valid DAG",
            subtask_templates=(
                _subtask("ST-1", "design", "Design", default_blocked_by=()),
                _subtask("ST-2", "impl", "Impl", default_blocked_by=("ST-1",)),
                _subtask("ST-3", "test", "Test", default_blocked_by=("ST-2",)),
            ),
            preconditions=("Pre",),
            assumptions=("A",),
            acceptance_template=_make_accepted(),
            version="0.1.0",
            status="draft",
        )
        _validate_proposed_method(method)


# ===================================================================
# Phase 2 — governance state machine
# ===================================================================


class TestGovernance:
    def test_submit_draft_creates_proposal(self) -> None:
        method = _make_draft_method("M-201", "add_middleware")
        pid = submit_method(method)
        assert pid.startswith("P-")
        proposal = get_proposal(pid)
        assert proposal is not None
        assert proposal.status == "draft"

    def test_submit_non_draft_raises(self) -> None:
        method = _make_draft_method("M-202", status="approved")
        with pytest.raises(ValueError, match="Only draft"):
            submit_method(method)

    def test_approve_method(self) -> None:
        method = _make_draft_method("M-203", "add_middleware")
        pid = submit_method(method)
        approve_method(pid, reviewer="alice")
        proposal = get_proposal(pid)
        assert proposal is not None
        assert proposal.status == "approved"

    def test_approve_registers_method(self) -> None:
        method = _make_draft_method("M-204", "add_middleware")
        pid = submit_method(method)
        approve_method(pid, reviewer="bob")
        assert get_method("M-204") is not None

    def test_reject_method(self) -> None:
        method = _make_draft_method("M-205", "add_middleware")
        pid = submit_method(method)
        reject_method(pid, reviewer="bob", reason="Duplicate pattern")
        proposal = get_proposal(pid)
        assert proposal is not None
        assert proposal.status == "rejected"

    def test_reject_requires_reason(self) -> None:
        method = _make_draft_method("M-206", pattern="add_middleware")
        pid = submit_method(method)
        with pytest.raises(ValueError, match="non-empty reason"):
            reject_method(pid, reviewer="bob", reason="")

    def test_deprecate_approved_method(self) -> None:
        method = _make_draft_method("M-207", "add_middleware")
        pid = submit_method(method)
        approve_method(pid, reviewer="alice")
        deprecate_method("M-207", replacement_id="M-208", reviewer="alice")
        m = get_method("M-207")
        assert m is not None
        assert m.status == "deprecated"

    def test_deprecate_nonexistent_raises(self) -> None:
        with pytest.raises(ValueError, match="not found"):
            deprecate_method("M-NONEXIST")

    # --- Forbidden transitions ---

    def test_approved_reject_forbidden(self) -> None:
        method = _make_draft_method("M-210", "add_middleware")
        pid = submit_method(method)
        approve_method(pid, reviewer="alice")
        with pytest.raises(ValueError, match="deprecate"):
            reject_method(pid, reviewer="alice", reason="no")

    def test_rejected_is_terminal(self) -> None:
        method = _make_draft_method("M-211", "add_middleware")
        pid = submit_method(method)
        reject_method(pid, reviewer="alice", reason="Bad pattern")
        with pytest.raises(ValueError, match="terminal state"):
            approve_method(pid, reviewer="alice")

    def test_draft_deprecate_forbidden(self) -> None:
        method = _make_draft_method("M-212", "add_middleware")
        pid = submit_method(method)
        proposal = get_proposal(pid)
        assert proposal is not None
        with pytest.raises(ValueError, match="reject"):
            _transition(proposal, "deprecate")

    def test_list_proposals(self) -> None:
        m1 = _make_draft_method("M-220", "add_middleware")
        m2 = _make_draft_method("M-221", "fix_performance")
        pid1 = submit_method(m1)
        pid2 = submit_method(m2)
        all_props = list_proposals()
        assert len(all_props) >= 2

        draft_props = list_proposals(status="draft")
        assert len(draft_props) >= 2

    def test_submit_duplicate_method_id_to_registry_raises(self) -> None:
        """Approving then submitting same id should raise."""
        m1 = _make_draft_method("M-230", "add_middleware")
        m2 = _make_draft_method("M-230", "other")
        pid = submit_method(m1)
        approve_method(pid, reviewer="test")
        # Now the method is in the registry — second submit should fail
        with pytest.raises(ValueError, match="already exists"):
            submit_method(m2)


# ===================================================================
# Phase 3 — version management
# ===================================================================


class TestVersionManagement:
    def test_parse_valid_semver(self) -> None:
        from clawcodex_ext.logical_kanban.method_library import _parse_semver
        assert _parse_semver("0.1.0") == (0, 1, 0)
        assert _parse_semver("1.0.0") == (1, 0, 0)
        assert _parse_semver("2.3.4") == (2, 3, 4)

    def test_bump_major(self) -> None:
        method = _make_draft_method("M-301", "add_middleware", status="approved")
        bumped = bump_version(method, "major")
        assert bumped.version == "1.0.0"
        assert bumped.method_id == "M-301"
        assert bumped.status == "approved"

    def test_bump_minor(self) -> None:
        method = _make_draft_method("M-302", "add_middleware", status="approved")
        bumped = bump_version(method, "minor")
        assert bumped.version == "0.2.0"

    def test_bump_patch(self) -> None:
        method = _make_draft_method("M-303", "add_middleware", status="approved")
        bumped = bump_version(method, "patch")
        assert bumped.version == "0.1.1"

    def test_bump_repeated(self) -> None:
        method = _make_draft_method("M-304", "add_middleware", status="approved")
        v1 = bump_version(method, "minor")
        v2 = bump_version(v1, "minor")
        assert v2.version == "0.3.0"

    def test_incompatible_major_change(self) -> None:
        assert incompatible_change("0.1.0", "1.0.0") is True
        assert incompatible_change("1.0.0", "2.0.0") is True

    def test_compatible_change(self) -> None:
        assert incompatible_change("1.0.0", "1.1.0") is False
        assert incompatible_change("1.0.0", "1.0.1") is False
        assert incompatible_change("2.0.0", "2.0.0") is False


# ===================================================================
# Phase 5 — coverage evaluator
# ===================================================================


class TestMethodCoverage:
    def test_empty_golden_set(self) -> None:
        evaluator = MethodCoverageEvaluator()
        report = evaluator.evaluate([])
        assert report["golden_set_size"] == 0
        assert report["hit_rate"] == 0.0

    def test_hit_rate_calculation(self) -> None:
        method = _make_draft_method("M-501", "add_middleware", status="approved")
        register_method(method)

        golden_set = [
            {"goal": "Add JWT auth", "expected_method_pattern": "add_middleware"},
        ]
        evaluator = MethodCoverageEvaluator()
        report = evaluator.evaluate(
            golden_set,
            field_references=[("M-501", "RUN-001")],
        )
        assert report["golden_set_size"] == 1
        assert report["hit_rate"] == 1.0
        assert report["top_method_usage"]["M-501"] == 1

    def test_no_hit(self) -> None:
        golden_set = [
            {"goal": "Fix perf", "expected_method_pattern": "fix_performance"},
        ]
        evaluator = MethodCoverageEvaluator()
        report = evaluator.evaluate(golden_set)
        assert report["hit_rate"] == 0.0

    def test_integrity_warning_field_event_mismatch(self) -> None:
        evaluator = MethodCoverageEvaluator()
        report = evaluator.evaluate(
            [],
            field_references=[("M-601", "RUN-001")],
            event_references=[],
        )
        assert len(report["coverage_integrity_warnings"]) == 1
        assert "missing from event" in report["coverage_integrity_warnings"][0]


# ===================================================================
# Phase 6 — layered loading
# ===================================================================


class TestLayeredLoading:
    def test_builtin_only_when_dirs_empty(self) -> None:
        result = load_method_library_layered()
        assert len(result) >= 20

    def test_user_layer_overrides_seed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            user_dir = Path(tmp) / "lkb" / "methods"
            user_dir.mkdir(parents=True)
            user_method = _make_draft_method("M-701", "add_middleware", status="approved")
            save_method_library([user_method], user_dir / "user_methods.json")
            result = load_method_library_layered(user_cache_dir=user_dir)
            found = {m.method_id: m for m in result}
            assert "M-701" in found
            assert len(result) >= len(METHOD_LIBRARY)

    def test_default_dirs_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orig_home = os.environ.get("HOME")
            os.environ["HOME"] = tmp
            try:
                ensure_default_dirs()
                base = Path(tmp) / ".cache" / "clawcodex" / "lkb"
                assert (base / "methods").is_dir()
                assert (base / "proposals").is_dir()
            finally:
                if orig_home:
                    os.environ["HOME"] = orig_home
                else:
                    del os.environ["HOME"]


# ===================================================================
# CLI command tests (via function call)
# ===================================================================


class TestCliCommands:
    def test_list_no_args(self) -> None:
        from clawcodex_ext.cli.lkb_method_cmd.commands import _cmd_list
        code = _cmd_list([])
        assert code == 0

    def test_show_existing(self) -> None:
        from clawcodex_ext.cli.lkb_method_cmd.commands import _cmd_show
        # Register a method first
        method = _make_draft_method("M-show-001", "test_pattern", status="approved")
        register_method(method)
        code = _cmd_show(["M-show-001"])
        assert code == 0

    def test_show_missing(self) -> None:
        from clawcodex_ext.cli.lkb_method_cmd.commands import _cmd_show
        code = _cmd_show(["NONEXISTENT"])
        assert code == 1

    def test_propose_requires_from_plan(self) -> None:
        from clawcodex_ext.cli.lkb_method_cmd.commands import _cmd_propose
        code = _cmd_propose([])
        assert code == 1

    def test_approve_requires_proposal_id(self) -> None:
        from clawcodex_ext.cli.lkb_method_cmd.commands import _cmd_approve
        code = _cmd_approve([])
        assert code == 1

    def test_approve_happy_path(self) -> None:
        method = _make_draft_method("M-801", "add_middleware")
        pid = submit_method(method)
        from clawcodex_ext.cli.lkb_method_cmd.commands import _cmd_approve
        code = _cmd_approve([pid, "--reviewer=test"])
        assert code == 0
        proposal = get_proposal(pid)
        assert proposal is not None
        assert proposal.status == "approved"

    def test_reject_happy_path(self) -> None:
        method = _make_draft_method("M-802", "add_middleware")
        pid = submit_method(method)
        from clawcodex_ext.cli.lkb_method_cmd.commands import _cmd_reject
        code = _cmd_reject([pid, "--reason=Duplicate", "--reviewer=test"])
        assert code == 0
        proposal = get_proposal(pid)
        assert proposal is not None
        assert proposal.status == "rejected"

    def test_reject_requires_reason_flag(self) -> None:
        method = _make_draft_method("M-803", "add_middleware")
        pid = submit_method(method)
        from clawcodex_ext.cli.lkb_method_cmd.commands import _cmd_reject
        code = _cmd_reject([pid])
        assert code == 1

    def test_deprecate_happy_path(self) -> None:
        method = _make_draft_method("M-804", "add_middleware")
        pid = submit_method(method)
        approve_method(pid, reviewer="test")
        from clawcodex_ext.cli.lkb_method_cmd.commands import _cmd_deprecate
        code = _cmd_deprecate(["M-804", "--replacement=M-new"])
        assert code == 0
        m = get_method("M-804")
        assert m is not None
        assert m.status == "deprecated"
