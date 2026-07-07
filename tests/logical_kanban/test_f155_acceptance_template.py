from __future__ import annotations

import json
from pathlib import Path

import pytest

from clawcodex_ext.cli.lkb_method_cmd.commands import (
    _cmd_config_list,
    _cmd_export,
    _cmd_template_coverage,
    _cmd_template_list,
    _cmd_template_show,
)
from clawcodex_ext.logical_kanban.acceptance_template import (
    AcceptanceTemplate,
    AcceptanceTemplateRegistry,
    get_acceptance_template,
    list_acceptance_templates,
    load_acceptance_template_data,
    load_acceptance_template_library_layered,
    register_acceptance_template,
    reset_acceptance_template_registry,
    save_acceptance_template_library,
)
from clawcodex_ext.logical_kanban.acceptance_template_governance import (
    approve_acceptance_template,
    deprecate_acceptance_template,
    reject_acceptance_template,
    reset_acceptance_template_proposals,
    submit_acceptance_template,
)
from clawcodex_ext.logical_kanban.acceptance_template_prompt import (
    select_templates_by_goal,
    summarize_acceptance_templates,
)
from clawcodex_ext.logical_kanban.audit import InMemoryAuditLog
from clawcodex_ext.logical_kanban.decomposer import DecompositionPlan, ProposedTask
from clawcodex_ext.logical_kanban.external_config import ExternalConfigImporter
from clawcodex_ext.logical_kanban.external_config_lint import lint_acceptance_templates
from clawcodex_ext.logical_kanban.rule_engine import (
    acceptance_template_refs_for_plan,
    validate_acceptance_template_references,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_acceptance_template_registry(include_seeds=True)
    reset_acceptance_template_proposals()
    yield
    reset_acceptance_template_registry(include_seeds=True)
    reset_acceptance_template_proposals()


def _template(template_id: str = "T-custom-check-001", *, status: str = "approved") -> AcceptanceTemplate:
    return AcceptanceTemplate(
        template_id=template_id,
        description="Custom check",
        assertion_template="CustomCheck({path})",
        proof_template="custom-check {path}",
        applies_to_roles=("impl", "test"),
        status=status,  # type: ignore[arg-type]
    )


def _task(task_id: str, meta: dict[str, object]) -> ProposedTask:
    return ProposedTask(
        proposed_task_id=task_id,
        subject=task_id,
        description="",
        active_form="",
        acceptance_criteria=("ok",),
        blocked_by=(),
        lkb_metadata=meta,
    )


def _plan(*tasks: ProposedTask) -> DecompositionPlan:
    return DecompositionPlan(
        decomposition_run_id="D-f155",
        goal="add tests",
        tasks=tasks,
        dependencies=(),
        assumptions=(),
        ambiguity_report=None,
        validation_run=None,
        acceptance_template_references=acceptance_template_refs_for_plan(
            DecompositionPlan("D-inner", "", tasks, (), (), None, None)
        ),
    )


def test_template_validates_id() -> None:
    with pytest.raises(ValueError, match="T-<kebab-case>-NNN"):
        _template("bad")


def test_template_validates_role() -> None:
    with pytest.raises(ValueError, match="applies_to_roles"):
        AcceptanceTemplate(
            "T-custom-check-001",
            "bad role",
            "Ok({x})",
            applies_to_roles=("unknown",),  # type: ignore[arg-type]
        )


def test_template_validates_placeholder() -> None:
    with pytest.raises(ValueError, match="placeholder"):
        AcceptanceTemplate("T-custom-check-001", "bad", "Ok({not valid})")


def test_registry_register_get_list() -> None:
    registry = AcceptanceTemplateRegistry()
    template = _template()
    registry.register(template)
    assert registry.get(template.template_id) == template
    assert registry.list(role="impl") == (template,)


def test_registry_rejects_duplicate_without_force() -> None:
    registry = AcceptanceTemplateRegistry((_template(),))
    with pytest.raises(ValueError, match="already registered"):
        registry.register(_template())


def test_registry_force_replaces() -> None:
    registry = AcceptanceTemplateRegistry((_template(),))
    replacement = AcceptanceTemplate("T-custom-check-001", "replacement", "Other({x})")
    registry.register(replacement, force=True)
    assert registry.get("T-custom-check-001") == replacement


def test_save_load_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "templates.json"
    save_acceptance_template_library((_template(),), path)
    registry = AcceptanceTemplateRegistry()
    loaded = registry.load(path)
    assert loaded[0].template_id == "T-custom-check-001"
    assert registry.get("T-custom-check-001") is not None


def test_load_data_accepts_single_template() -> None:
    templates = load_acceptance_template_data(_template().to_dict())
    assert templates[0].template_id == "T-custom-check-001"


def test_layered_loading_user_overrides_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project_dir = project / ".lkb" / "acceptance_templates"
    user_dir = tmp_path / "cache" / "acceptance_templates"
    project_dir.mkdir(parents=True)
    user_dir.mkdir(parents=True)
    save_acceptance_template_library(
        (AcceptanceTemplate("T-layered-check-001", "project", "Project({x})"),),
        project_dir / "templates.json",
    )
    save_acceptance_template_library(
        (AcceptanceTemplate("T-layered-check-001", "user", "User({x})"),),
        user_dir / "templates.json",
    )
    loaded = load_acceptance_template_library_layered(
        project_dir=project,
        user_cache_dir=tmp_path / "cache",
    )
    assert next(t for t in loaded if t.template_id == "T-layered-check-001").description == "user"


def test_seed_registry_contains_expected_template() -> None:
    assert get_acceptance_template("T-test-passes-001") is not None


def test_module_register_adds_template() -> None:
    register_acceptance_template(_template())
    assert get_acceptance_template("T-custom-check-001") is not None


def test_list_filters_status() -> None:
    register_acceptance_template(_template("T-draft-check-001", status="draft"))
    assert "T-draft-check-001" not in {t.template_id for t in list_acceptance_templates()}
    assert "T-draft-check-001" in {
        t.template_id for t in list_acceptance_templates(status="draft")
    }


def test_governance_approve_registers_template() -> None:
    proposal_id = submit_acceptance_template(_template(status="draft"))
    approve_acceptance_template(proposal_id, reviewer="test")
    assert get_acceptance_template("T-custom-check-001").status == "approved"  # type: ignore[union-attr]


def test_governance_reject_terminal() -> None:
    proposal_id = submit_acceptance_template(_template(status="draft"))
    reject_acceptance_template(proposal_id, reason="not reusable")
    with pytest.raises(ValueError, match="terminal"):
        approve_acceptance_template(proposal_id)


def test_governance_deprecate_approved() -> None:
    register_acceptance_template(_template())
    deprecate_acceptance_template("T-custom-check-001")
    assert get_acceptance_template("T-custom-check-001").status == "deprecated"  # type: ignore[union-attr]


def test_governance_rejects_draft_deprecate() -> None:
    register_acceptance_template(_template(status="draft"))
    with pytest.raises(ValueError, match="draft"):
        deprecate_acceptance_template("T-custom-check-001")


def test_external_json_import_registers_template(tmp_path: Path) -> None:
    path = tmp_path / "templates.json"
    save_acceptance_template_library((_template(),), path)
    result = ExternalConfigImporter().import_file(path)
    assert result.kind == "acceptance_template"
    assert get_acceptance_template("T-custom-check-001") is not None


def test_external_yaml_import_registers_template(tmp_path: Path) -> None:
    path = tmp_path / "templates.yaml"
    path.write_text(
        """
kind: acceptance_template
acceptanceTemplates:
  - templateId: T-yaml-check-001
    description: YAML template
    assertionTemplate: YamlCheck({path})
    proofTemplate: yaml-check {path}
    appliesToRoles: [impl]
""",
        encoding="utf-8",
    )
    result = ExternalConfigImporter().import_file(path)
    assert result.kind == "acceptance_template"
    assert get_acceptance_template("T-yaml-check-001") is not None


def test_external_import_emits_registered_audit(tmp_path: Path) -> None:
    path = tmp_path / "templates.json"
    save_acceptance_template_library((_template(),), path)
    audit = InMemoryAuditLog()
    ExternalConfigImporter(audit_log=audit).import_file(path)
    assert audit.query(event_type="lkb_acceptance_template_registered")


def test_lint_reports_duplicate_template() -> None:
    issues = lint_acceptance_templates((_template(), _template()))
    assert any(issue.code == "acceptance_template.duplicate_id" for issue in issues)


def test_prompt_selects_relevant_template() -> None:
    selected = select_templates_by_goal(
        "run pytest tests",
        (get_acceptance_template("T-test-passes-001"),),  # type: ignore[arg-type]
    )
    assert selected[0].template_id == "T-test-passes-001"


def test_prompt_summary_under_budget() -> None:
    summary = summarize_acceptance_templates(list_acceptance_templates(), max_tokens=800)
    assert summary.estimated_tokens <= 800
    assert summary.included_template_ids


def test_rule_warns_for_missing_template() -> None:
    plan = _plan(_task("tmp-1", {"acceptance_template_id": "T-missing-check-001"}))
    issues = validate_acceptance_template_references(plan)
    assert issues[0].code == "R-METHOD-006-UNKNOWN-ACCEPTANCE-TEMPLATE"
    assert issues[0].severity == "warning"


def test_rule_accepts_known_template() -> None:
    plan = _plan(_task("tmp-1", {"acceptance_template_id": "T-test-passes-001"}))
    assert validate_acceptance_template_references(plan) == ()


def test_refs_extract_from_assertion_template_ref() -> None:
    plan = _plan(_task("tmp-1", {"assertions": ["template_ref: T-test-passes-001"]}))
    assert acceptance_template_refs_for_plan(plan) == ("T-test-passes-001",)


def test_plan_to_dict_includes_template_references() -> None:
    plan = _plan(_task("tmp-1", {"acceptance_template_id": "T-test-passes-001"}))
    assert plan.to_dict()["acceptanceTemplateReferences"] == ["T-test-passes-001"]


def test_audit_emits_template_referenced_event() -> None:
    from clawcodex_ext.logical_kanban.decomposer import TaskDecomposer

    plan = _plan(_task("tmp-1", {"acceptance_template_id": "T-test-passes-001"}))
    audit = InMemoryAuditLog()
    TaskDecomposer()._emit_audit_event(plan, audit_log=audit)
    events = audit.query(event_type="lkb_acceptance_template_referenced")
    assert events[0].payload["templateId"] == "T-test-passes-001"


def test_cli_template_list_and_show() -> None:
    assert _cmd_template_list(["--status=approved"]) == 0
    assert _cmd_template_show(["T-test-passes-001"]) == 0


def test_cli_template_coverage() -> None:
    assert _cmd_template_coverage([]) == 0


def test_cli_export_contains_templates(tmp_path: Path) -> None:
    output = tmp_path / "active.json"
    assert _cmd_export(["--format=json", str(output)]) == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert "acceptanceTemplates" in data


def test_cli_config_list_smoke() -> None:
    assert _cmd_config_list([]) == 0
