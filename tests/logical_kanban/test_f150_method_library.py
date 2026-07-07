"""Tests for F-150 Engineering Method Library."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from clawcodex_ext.logical_kanban import (
    AcceptanceTemplate,
    DecompositionPlan,
    EngineeringMethod,
    METHOD_LIBRARY,
    ProposedTask,
    SubtaskTemplate,
    TaskDecomposer,
    TaskDecompositionError,
    get_method,
    list_methods,
    load_method_library,
    register_method,
    reset_method_registry,
    save_method_library,
    validate_method_compliance,
)
from clawcodex_ext.logical_kanban.decomposer import _LKB_METADATA_KEYS
from clawcodex_ext.providers.base import BaseProvider, ChatResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_subtask(
    template_id: str,
    role: str = "impl",
    subject: str = "Do work",
    description: str = "",
    acceptance: str = "",
    default_blocked_by: tuple[str, ...] = (),
) -> SubtaskTemplate:
    return SubtaskTemplate(
        template_id=template_id,
        role=role,  # type: ignore[arg-type]
        subject_template=subject,
        description_template=description,
        acceptance_template=acceptance,
        default_blocked_by=default_blocked_by,
    )


def _make_method(
    method_id: str = "M-test-001",
    pattern: str = "test_pattern",
    subtasks: tuple[SubtaskTemplate, ...] | None = None,
    preconditions: tuple[str, ...] = (),
    assumptions: tuple[str, ...] = (),
    acceptance: AcceptanceTemplate | None = None,
    status: str = "approved",
) -> EngineeringMethod:
    if subtasks is None:
        subtasks = (
            _make_subtask("t1", "design", "Design"),
            _make_subtask("t2", "impl", "Implement", default_blocked_by=("t1",)),
            _make_subtask("t3", "test", "Test", default_blocked_by=("t2",)),
        )
    return EngineeringMethod(
        method_id=method_id,
        pattern=pattern,
        description="test method",
        subtask_templates=subtasks,
        preconditions=preconditions,
        assumptions=assumptions,
        acceptance_template=acceptance,
        status=status,  # type: ignore[arg-type]
    )


def _make_task(
    task_id: str,
    *,
    method_ref: str | None = None,
    assertions: tuple[str, ...] = (),
    assumptions: tuple[str, ...] = (),
    blocked_by: tuple[str, ...] = (),
    strict_acceptance: bool = False,
) -> ProposedTask:
    metadata: dict[str, Any] = {}
    if method_ref is not None:
        metadata["method_ref"] = method_ref
    if assertions:
        metadata["assertions"] = list(assertions)
    if assumptions:
        metadata["assumptions"] = list(assumptions)
    if strict_acceptance:
        metadata["strict_acceptance"] = True
    return ProposedTask(
        proposed_task_id=task_id,
        subject=task_id,
        description="",
        active_form="",
        acceptance_criteria=("ok",),
        blocked_by=blocked_by,
        lkb_metadata=metadata,
    )


def _make_plan(tasks: tuple[ProposedTask, ...], *, assumptions: tuple[str, ...] = ()) -> DecompositionPlan:
    return DecompositionPlan(
        decomposition_run_id="D-test",
        goal="test",
        tasks=tasks,
        dependencies=(),
        assumptions=assumptions,
        ambiguity_report=None,
        validation_run=None,
    )


@pytest.fixture(autouse=True)
def _isolate_registry() -> Any:
    """Each test starts with a clean method registry."""
    reset_method_registry()
    yield
    reset_method_registry()


# ---------------------------------------------------------------------------
# Data structure tests
# ---------------------------------------------------------------------------


class TestSubtaskTemplate:
    def test_minimal_creation(self) -> None:
        template = _make_subtask("a")
        assert template.template_id == "a"
        assert template.role == "impl"
        assert template.subject_template == "Do work"
        assert template.description_template == ""
        assert template.acceptance_template == ""
        assert template.default_blocked_by == ()

    def test_frozen(self) -> None:
        template = _make_subtask("a")
        with pytest.raises((AttributeError, TypeError)):
            template.template_id = "b"  # type: ignore[misc]

    def test_invalid_role_rejected(self) -> None:
        with pytest.raises(ValueError, match="role must be one of"):
            SubtaskTemplate(
                template_id="a",
                role="invalid",  # type: ignore[arg-type]
                subject_template="x",
            )

    def test_empty_template_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="template_id"):
            SubtaskTemplate(template_id="", role="impl", subject_template="x")

    def test_empty_subject_template_rejected(self) -> None:
        with pytest.raises(ValueError, match="subject_template"):
            SubtaskTemplate(template_id="a", role="impl", subject_template="")

    def test_to_dict_omits_empty_fields(self) -> None:
        template = _make_subtask("a")
        data = template.to_dict()
        assert data == {"templateId": "a", "role": "impl", "subjectTemplate": "Do work"}
        assert "descriptionTemplate" not in data
        assert "acceptanceTemplate" not in data
        assert "defaultBlockedBy" not in data


class TestAcceptanceTemplate:
    def test_minimal_creation(self) -> None:
        a = AcceptanceTemplate(assertion_template="Done()")
        assert a.assertion_template == "Done()"
        assert a.proof_template == ""
        assert a.strict_acceptance is False

    def test_strict_acceptance_set(self) -> None:
        a = AcceptanceTemplate(
            assertion_template="Tested()", proof_template="tests pass", strict_acceptance=True
        )
        assert a.strict_acceptance is True

    def test_empty_assertion_template_rejected(self) -> None:
        with pytest.raises(ValueError, match="assertion_template"):
            AcceptanceTemplate(assertion_template="")

    def test_to_dict_round_trip(self) -> None:
        a = AcceptanceTemplate(
            assertion_template="Tested()", proof_template="tests pass", strict_acceptance=True
        )
        data = a.to_dict()
        assert data == {
            "assertionTemplate": "Tested()",
            "proofTemplate": "tests pass",
            "strictAcceptance": True,
        }


class TestEngineeringMethod:
    def test_minimal_creation(self) -> None:
        method = _make_method()
        assert method.method_id == "M-test-001"
        assert method.pattern == "test_pattern"
        assert len(method.subtask_templates) == 3
        assert method.acceptance_template is None

    def test_roles_returns_unique_ordered_list(self) -> None:
        method = _make_method(
            subtasks=(
                _make_subtask("a", "design"),
                _make_subtask("b", "impl", default_blocked_by=("a",)),
                _make_subtask("c", "design"),  # duplicate role
                _make_subtask("d", "test", default_blocked_by=("b",)),
            )
        )
        assert method.roles() == ("design", "impl", "test")

    def test_subtask_by_template_id(self) -> None:
        method = _make_method()
        assert method.subtask_by_template_id("t1") is not None
        assert method.subtask_by_template_id("nope") is None

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValueError, match="status"):
            EngineeringMethod(
                method_id="x",
                pattern="x",
                description="x",
                subtask_templates=(_make_subtask("a"),),
                status="bogus",  # type: ignore[arg-type]
            )

    def test_empty_subtask_templates_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            EngineeringMethod(
                method_id="x",
                pattern="x",
                description="x",
                subtask_templates=(),
            )

    def test_to_dict_round_trip(self) -> None:
        method = _make_method(
            acceptance=AcceptanceTemplate(
                assertion_template="Done()", strict_acceptance=True
            ),
        )
        data = method.to_dict()
        assert data["methodId"] == "M-test-001"
        assert data["pattern"] == "test_pattern"
        assert data["status"] == "approved"
        assert data["acceptanceTemplate"] == {
            "assertionTemplate": "Done()",
            "proofTemplate": "",
            "strictAcceptance": True,
        }
        assert len(data["subtaskTemplates"]) == 3


# ---------------------------------------------------------------------------
# Registry API tests
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_register_and_get_method(self) -> None:
        method = _make_method(method_id="M-reg-001")
        register_method(method)
        assert get_method("M-reg-001") is method

    def test_get_method_returns_none_for_unknown(self) -> None:
        assert get_method("M-nonexistent") is None

    def test_register_rejects_duplicate_id(self) -> None:
        register_method(_make_method(method_id="M-dup-001"))
        with pytest.raises(ValueError, match="already registered"):
            register_method(_make_method(method_id="M-dup-001"))

    def test_register_rejects_dangling_default_blocked_by(self) -> None:
        bad = EngineeringMethod(
            method_id="M-bad-001",
            pattern="bad",
            description="",
            subtask_templates=(
                _make_subtask("a", default_blocked_by=("ghost",)),
                _make_subtask("b"),
            ),
        )
        with pytest.raises(ValueError, match="unknown template_id"):
            register_method(bad)

    def test_register_rejects_non_engineering_method(self) -> None:
        with pytest.raises(ValueError, match="expects an EngineeringMethod"):
            register_method("not a method")  # type: ignore[arg-type]

    def test_list_methods_filters_by_status(self) -> None:
        register_method(_make_method(method_id="M-draft-001", status="draft"))
        register_method(_make_method(method_id="M-approved-001", status="approved"))
        approved = list_methods(status="approved")
        approved_ids = {m.method_id for m in approved}
        assert "M-approved-001" in approved_ids
        assert "M-draft-001" not in approved_ids

    def test_list_methods_filters_by_pattern_prefix(self) -> None:
        register_method(_make_method(method_id="M-add-x-001", pattern="add_x"))
        register_method(_make_method(method_id="M-fix-x-001", pattern="fix_x"))
        add_only = list_methods(pattern_prefix="add_")
        add_ids = {m.method_id for m in add_only}
        assert "M-add-x-001" in add_ids
        assert "M-fix-x-001" not in add_ids

    def test_list_methods_filters_by_tag(self) -> None:
        register_method(
            _make_method(method_id="M-tagged-001", pattern="tagged_thing")
        )
        # Patch tags via a fresh method
        m = _make_method(method_id="M-tagged-002", pattern="tagged_thing2")
        register_method(m)
        # Tags default to empty so tag filter returns empty
        assert list_methods(tag="anything") == ()

    def test_list_methods_deterministic_order(self) -> None:
        # Register in non-alphabetical order
        register_method(_make_method(method_id="M-zebra-001", pattern="zebra"))
        register_method(_make_method(method_id="M-alpha-001", pattern="alpha"))
        methods = list_methods(status=None)
        # Sort key is (pattern, method_id) — alpha precedes zebra.
        custom_methods = [m for m in methods if m.method_id in {"M-alpha-001", "M-zebra-001"}]
        assert custom_methods[0].pattern == "alpha"
        assert custom_methods[1].pattern == "zebra"

    def test_list_methods_returns_tuple(self) -> None:
        result = list_methods()
        assert isinstance(result, tuple)


# ---------------------------------------------------------------------------
# Serialization tests
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_roundtrip_preserves_methods(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "methods.json"
            save_method_library(METHOD_LIBRARY, path)
            loaded = load_method_library(path)
            assert len(loaded) == len(METHOD_LIBRARY)
            assert loaded[0].method_id == METHOD_LIBRARY[0].method_id
            assert loaded[0].pattern == METHOD_LIBRARY[0].pattern
            assert len(loaded[0].subtask_templates) == len(
                METHOD_LIBRARY[0].subtask_templates
            )

    def test_save_creates_parent_directories(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "nested" / "deep" / "methods.json"
            save_method_library(METHOD_LIBRARY, path)
            assert path.exists()

    def test_save_overwrites_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "methods.json"
            path.write_text("stale content")
            save_method_library(METHOD_LIBRARY, path)
            data = json.loads(path.read_text())
            assert "methods" in data
            assert data["schemaVersion"] == "1"

    def test_load_forward_compatible_missing_optional_field(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "methods.json"
            save_method_library(METHOD_LIBRARY[:1], path)
            payload = json.loads(path.read_text())
            # Drop an optional field to simulate an older client file
            payload["methods"][0].pop("version", None)
            payload["methods"][0].pop("tags", None)
            payload["methods"][0]["acceptanceTemplate"] = None
            path.write_text(json.dumps(payload))
            loaded = load_method_library(path)
            assert loaded[0].version == "1"
            assert loaded[0].tags == ()
            assert loaded[0].acceptance_template is None

    def test_load_rejects_missing_required_field(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.json"
            path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "1",
                        "methods": [{"pattern": "x", "subtaskTemplates": []}],
                    }
                )
            )
            with pytest.raises(ValueError, match="methodId"):
                load_method_library(path)

    def test_load_rejects_invalid_status(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad_status.json"
            method = _make_method(method_id="M-bad-status")
            save_method_library((method,), path)
            payload = json.loads(path.read_text())
            payload["methods"][0]["status"] = "bogus"
            path.write_text(json.dumps(payload))
            with pytest.raises(ValueError, match="status"):
                load_method_library(path)

    def test_load_rejects_invalid_role(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad_role.json"
            method = _make_method(method_id="M-bad-role")
            save_method_library((method,), path)
            payload = json.loads(path.read_text())
            payload["methods"][0]["subtaskTemplates"][0]["role"] = "wizardry"
            path.write_text(json.dumps(payload))
            with pytest.raises(ValueError, match="role must be one of"):
                load_method_library(path)


# ---------------------------------------------------------------------------
# Seed library integrity tests
# ---------------------------------------------------------------------------


class TestSeedLibrary:
    def test_minimum_method_count(self) -> None:
        # F-150 acceptance: at least 20 seed methods.
        assert len(METHOD_LIBRARY) >= 20

    def test_all_methods_have_at_least_three_subtasks(self) -> None:
        for method in METHOD_LIBRARY:
            assert len(method.subtask_templates) >= 3, (
                f"{method.method_id} has only {len(method.subtask_templates)} subtasks"
            )

    def test_all_methods_have_acceptance_template(self) -> None:
        for method in METHOD_LIBRARY:
            assert method.acceptance_template is not None, (
                f"{method.method_id} has no acceptance template"
            )

    def test_all_default_blocked_by_resolve(self) -> None:
        for method in METHOD_LIBRARY:
            ids = {t.template_id for t in method.subtask_templates}
            for template in method.subtask_templates:
                for blocker in template.default_blocked_by:
                    assert blocker in ids, (
                        f"{method.method_id}: {template.template_id} -> "
                        f"unknown blocker {blocker}"
                    )

    def test_unique_method_ids(self) -> None:
        ids = [m.method_id for m in METHOD_LIBRARY]
        assert len(set(ids)) == len(ids)

    def test_patterns_cover_required_categories(self) -> None:
        # F-150 acceptance lists required pattern prefixes.
        required_prefixes = ["add_", "fix_", "refactor_", "migrate_"]
        patterns = {m.pattern for m in METHOD_LIBRARY}
        for prefix in required_prefixes:
            assert any(p.startswith(prefix) for p in patterns), (
                f"No seed method has pattern starting with {prefix!r}"
            )

    def test_list_methods_finds_by_pattern_prefix(self) -> None:
        # Golden-set assertions (per Phase 5 spec).
        assert any(m.pattern == "add_api_endpoint" for m in METHOD_LIBRARY)
        assert any(
            m.pattern == "fix_bug" for m in METHOD_LIBRARY
        ), "Should find add_api_endpoint and fix_bug methods"
        assert any(m.pattern.startswith("refactor_") for m in METHOD_LIBRARY)

    def test_list_methods_with_prefix_returns_subset(self) -> None:
        add_methods = list_methods(pattern_prefix="add_")
        assert all(m.pattern.startswith("add_") for m in add_methods)
        assert len(add_methods) > 0


# ---------------------------------------------------------------------------
# R-METHOD-* rule engine tests
# ---------------------------------------------------------------------------


class TestValidateMethodCompliance:
    def test_returns_empty_for_plan_without_method_refs(self) -> None:
        tasks = (
            _make_task("tmp-a"),
            _make_task("tmp-b", blocked_by=("tmp-a",)),
        )
        plan = _make_plan(tasks)
        assert validate_method_compliance(plan) == ()

    def test_returns_empty_when_method_refs_match_template(self) -> None:
        # Register a fully-specified method whose subtasks, preconditions,
        # and acceptance are all matched by the plan.
        method = _make_method(
            method_id="M-comp-001",
            preconditions=("tested_first",),
            acceptance=AcceptanceTemplate(
                assertion_template="EndpointStable({route})",
                strict_acceptance=True,
            ),
        )
        register_method(method)
        tasks = (
            _make_task(
                "tmp-a",
                method_ref="M-comp-001",
                assumptions=("tested_first",),
                assertions=("EndpointStable(/api/v1)",),
            ),
            _make_task(
                "tmp-b", method_ref="M-comp-001", blocked_by=("tmp-a",)
            ),
            _make_task(
                "tmp-c", method_ref="M-comp-001", blocked_by=("tmp-b",)
            ),
        )
        plan = _make_plan(tasks)
        issues = validate_method_compliance(plan)
        assert issues == ()

    def test_r_method_001_incomplete_triggers_warning(self) -> None:
        method = _make_method(method_id="M-incomp-001")
        register_method(method)
        tasks = (_make_task("tmp-a", method_ref="M-incomp-001"),)
        plan = _make_plan(tasks)
        issues = validate_method_compliance(plan)
        codes = {i.code for i in issues}
        assert "R-METHOD-001-INCOMPLETE" in codes

    def test_r_method_002_precondition_triggers_warning(self) -> None:
        method = _make_method(
            method_id="M-precond-001", preconditions=("database_initialized",)
        )
        register_method(method)
        tasks = (
            _make_task("tmp-a", method_ref="M-precond-001"),
            _make_task("tmp-b", method_ref="M-precond-001", blocked_by=("tmp-a",)),
            _make_task("tmp-c", method_ref="M-precond-001", blocked_by=("tmp-b",)),
        )
        plan = _make_plan(tasks)
        issues = validate_method_compliance(plan)
        codes = {i.code for i in issues}
        assert "R-METHOD-002-PRECONDITION" in codes

    def test_r_method_002_plan_assumptions_satisfy_precondition(self) -> None:
        method = _make_method(
            method_id="M-precond-002", preconditions=("route_registry_exists",)
        )
        register_method(method)
        tasks = (
            _make_task("tmp-a", method_ref="M-precond-002"),
            _make_task("tmp-b", method_ref="M-precond-002", blocked_by=("tmp-a",)),
            _make_task("tmp-c", method_ref="M-precond-002", blocked_by=("tmp-b",)),
        )
        plan = _make_plan(tasks, assumptions=("route_registry_exists",))
        issues = validate_method_compliance(plan)
        codes = {i.code for i in issues}
        assert "R-METHOD-002-PRECONDITION" not in codes

    def test_r_method_003_strict_acceptance_missing_assertion(self) -> None:
        method = _make_method(
            method_id="M-strict-001",
            acceptance=AcceptanceTemplate(
                assertion_template="ContractStable({route})",
                strict_acceptance=True,
            ),
        )
        register_method(method)
        tasks = (
            _make_task("tmp-a", method_ref="M-strict-001"),
            _make_task("tmp-b", method_ref="M-strict-001", blocked_by=("tmp-a",)),
            _make_task("tmp-c", method_ref="M-strict-001", blocked_by=("tmp-b",)),
        )
        plan = _make_plan(tasks)
        issues = validate_method_compliance(plan)
        codes = {i.code for i in issues}
        assert "R-METHOD-003-ASSERTION" in codes

    def test_r_method_003_assertion_matches_with_filled_slot(self) -> None:
        method = _make_method(
            method_id="M-strict-002",
            acceptance=AcceptanceTemplate(
                assertion_template="ContractStable({route})",
                strict_acceptance=True,
            ),
        )
        register_method(method)
        tasks = (
            _make_task(
                "tmp-a",
                method_ref="M-strict-002",
                assertions=("ContractStable(/api/v1/things)",),
            ),
            _make_task("tmp-b", method_ref="M-strict-002", blocked_by=("tmp-a",)),
            _make_task("tmp-c", method_ref="M-strict-002", blocked_by=("tmp-b",)),
        )
        plan = _make_plan(tasks)
        issues = validate_method_compliance(plan)
        codes = {i.code for i in issues}
        assert "R-METHOD-003-ASSERTION" not in codes

    def test_unknown_method_emits_r_method_unknown(self) -> None:
        tasks = (_make_task("tmp-a", method_ref="M-nope-001"),)
        plan = _make_plan(tasks)
        issues = validate_method_compliance(plan)
        codes = {i.code for i in issues}
        assert "R-METHOD-UNKNOWN" in codes

    def test_all_method_issues_are_warning_severity(self) -> None:
        # MVP: R-METHOD-* must never block commit, so severity must be
        # 'warning' across the board.
        method = _make_method(
            method_id="M-warn-001",
            preconditions=("database_initialized",),
            acceptance=AcceptanceTemplate(
                assertion_template="Done({what})",
                strict_acceptance=True,
            ),
        )
        register_method(method)
        tasks = (_make_task("tmp-a", method_ref="M-warn-001"),)
        plan = _make_plan(tasks)
        issues = validate_method_compliance(plan)
        assert issues
        for issue in issues:
            assert issue.severity == "warning", (
                f"{issue.code} should be warning, got {issue.severity}"
            )

    def test_custom_method_library_overrides_default(self) -> None:
        # A custom library that does NOT contain the referenced method
        # should produce R-METHOD-UNKNOWN even though METHOD_LIBRARY does.
        plan = _make_plan((_make_task("tmp-a", method_ref="M-add-api-endpoint-001"),))
        # Default behaviour: the registry contains the seed method, but the
        # plan is incomplete (1 task vs 4 templates, missing precondition /
        # assertion) — so R-METHOD-001/002/003 all fire as warnings.
        default_codes = {i.code for i in validate_method_compliance(plan)}
        assert "R-METHOD-001-INCOMPLETE" in default_codes
        assert "R-METHOD-002-PRECONDITION" in default_codes
        assert "R-METHOD-003-ASSERTION" in default_codes
        # Custom library that does not contain the method turns every
        # R-METHOD-* into a single R-METHOD-UNKNOWN.
        custom_issues = validate_method_compliance(plan, method_library=())
        assert {i.code for i in custom_issues} == {"R-METHOD-UNKNOWN"}

    def test_rejects_non_plan_argument(self) -> None:
        with pytest.raises(TypeError, match="expects a DecompositionPlan"):
            validate_method_compliance("not a plan")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Decomposer integration tests
# ---------------------------------------------------------------------------


class _StubProvider(BaseProvider):
    """Provider returning a fixed decomposition JSON."""

    def __init__(self, response_json: dict[str, Any]) -> None:
        super().__init__(api_key="test")
        self.response_json = response_json

    def chat(self, messages, tools=None, **kwargs):
        return ChatResponse(
            content=json.dumps(self.response_json),
            model="stub",
            usage={"input_tokens": 1, "output_tokens": 1},
            finish_reason="stop",
        )

    def chat_stream(self, messages, tools=None, **kwargs):
        raise NotImplementedError

    def get_available_models(self) -> list[str]:
        return ["stub"]


class TestDecomposerIntegration:
    def test_method_ref_is_accepted_in_lkb_metadata(self) -> None:
        # Without F-150, ``method_ref`` would have been rejected by
        # ``_reject_unknown_keys`` (F-149 hardcoded whitelist).
        plan_json = {
            "tasks": [
                {
                    "proposedTaskId": "tmp-a",
                    "subject": "Design",
                    "description": "d",
                    "activeForm": "a",
                    "acceptanceCriteria": ["ok"],
                    "blockedBy": [],
                    "lkbMetadata": {
                        "method_ref": "M-add-api-endpoint-001",
                        "assertions": ["EndpointContractStable(/api)"],
                        "assumptions": ["route_registry_exists"],
                    },
                },
            ],
            "dependencies": [],
            "assumptions": [],
        }
        decomposer = TaskDecomposer(llm_provider=_StubProvider(plan_json))
        plan = decomposer.decompose("Add endpoint", max_steps=4)
        assert plan.tasks[0].lkb_metadata["method_ref"] == "M-add-api-endpoint-001"

    def test_lkb_metadata_whitelist_includes_method_ref(self) -> None:
        # Regression: the F-149 hardcoded whitelist would reject method_ref.
        assert "method_ref" in _LKB_METADATA_KEYS

    def test_invalid_method_ref_type_rejected(self) -> None:
        plan_json = {
            "tasks": [
                {
                    "proposedTaskId": "tmp-a",
                    "subject": "x",
                    "description": "d",
                    "activeForm": "a",
                    "acceptanceCriteria": ["ok"],
                    "blockedBy": [],
                    "lkbMetadata": {"method_ref": 42},
                },
            ],
            "dependencies": [],
            "assumptions": [],
        }
        decomposer = TaskDecomposer(llm_provider=_StubProvider(plan_json), max_retries=0)
        with pytest.raises(TaskDecompositionError, match="method_ref"):
            decomposer.decompose("x", max_steps=4)

    def test_empty_method_ref_rejected(self) -> None:
        plan_json = {
            "tasks": [
                {
                    "proposedTaskId": "tmp-a",
                    "subject": "x",
                    "description": "d",
                    "activeForm": "a",
                    "acceptanceCriteria": ["ok"],
                    "blockedBy": [],
                    "lkbMetadata": {"method_ref": "   "},
                },
            ],
            "dependencies": [],
            "assumptions": [],
        }
        decomposer = TaskDecomposer(llm_provider=_StubProvider(plan_json), max_retries=0)
        with pytest.raises(TaskDecompositionError, match="method_ref"):
            decomposer.decompose("x", max_steps=4)

    def test_decomposer_accepts_method_library_kwarg(self) -> None:
        custom = _make_method(method_id="M-custom-dec-001")
        decomposer = TaskDecomposer(llm_provider=None, method_library=(custom,))
        assert decomposer.method_library == (custom,)

    def test_method_compliance_warnings_appear_in_validation_run(self) -> None:
        # A plan that references an incomplete method should emit a warning.
        plan_json = {
            "tasks": [
                {
                    "proposedTaskId": "tmp-a",
                    "subject": "Design",
                    "description": "d",
                    "activeForm": "a",
                    "acceptanceCriteria": ["ok"],
                    "blockedBy": [],
                    "lkbMetadata": {"method_ref": "M-add-api-endpoint-001"},
                },
            ],
            "dependencies": [],
            "assumptions": [],
        }
        decomposer = TaskDecomposer(llm_provider=_StubProvider(plan_json))
        plan = decomposer.decompose("Add endpoint", max_steps=4)
        assert plan.validation_run is not None
        codes = {i.code for i in plan.validation_run.issues}
        assert "R-METHOD-001-INCOMPLETE" in codes

    def test_method_compliance_warning_does_not_block_commit(self) -> None:
        # The F-150 MVP design decision: warnings do not flip the result to
        # fail.  We still expect result='pass' for a structurally valid plan
        # even when R-METHOD-* emits warnings.
        plan_json = {
            "tasks": [
                {
                    "proposedTaskId": "tmp-a",
                    "subject": "Design",
                    "description": "d",
                    "activeForm": "a",
                    "acceptanceCriteria": ["ok"],
                    "blockedBy": [],
                    "lkbMetadata": {"method_ref": "M-add-api-endpoint-001"},
                },
            ],
            "dependencies": [],
            "assumptions": [],
        }
        decomposer = TaskDecomposer(llm_provider=_StubProvider(plan_json))
        plan = decomposer.decompose("Add endpoint", max_steps=4)
        assert plan.validation_run is not None
        # Plan passes overall even though R-METHOD-* would have warned.
        assert plan.validation_run.result == "pass"


# ---------------------------------------------------------------------------
# Golden set tests (Phase 5 spec)
# ---------------------------------------------------------------------------


class TestGoldenSet:
    """5 common goals; each must surface at least one related method."""

    @pytest.mark.parametrize(
        ("goal", "expected_pattern_prefix"),
        [
            ("add middleware for rate limiting", "add_"),
            ("fix N+1 query in users endpoint", "fix_"),
            ("refactor auth module into a service", "refactor_"),
            ("add a unit test for the parser", "add_unit_test"),
            ("migrate the database to v3 schema", "migrate_"),
        ],
    )
    def test_goal_finds_related_method(
        self, goal: str, expected_pattern_prefix: str
    ) -> None:
        # Golden-set tests are advisory: we just confirm that
        # list_methods(pattern_prefix=...) returns at least one candidate
        # for each common goal category.  Downstream prompt injection
        # (F-151) is what actually steers the LLM.
        candidates = list_methods(pattern_prefix=expected_pattern_prefix)
        assert candidates, f"No seed methods for prefix {expected_pattern_prefix!r}"


# ---------------------------------------------------------------------------
# Reset helper tests
# ---------------------------------------------------------------------------


class TestResetRegistry:
    def test_reset_with_seeds_restores_default(self) -> None:
        register_method(_make_method(method_id="M-reset-001"))
        assert any(m.method_id == "M-reset-001" for m in list_methods(status=None))
        reset_method_registry(include_seeds=True)
        assert all(m.method_id != "M-reset-001" for m in list_methods(status=None))
        # Seed library is restored
        assert len(list_methods(status="approved")) >= 20

    def test_reset_without_seeds_empties_registry(self) -> None:
        reset_method_registry(include_seeds=False)
        assert list_methods(status=None) == ()