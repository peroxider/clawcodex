from __future__ import annotations

import json
import builtins
from pathlib import Path

import pytest

from clawcodex_ext.logical_kanban.audit import InMemoryAuditLog
from clawcodex_ext.logical_kanban.decomposer import DecompositionPlan, ProposedTask
from clawcodex_ext.logical_kanban.external_config import (
    ConfigConflictError,
    ExternalConfigImporter,
)
from clawcodex_ext.logical_kanban.external_config_lint import lint_all
from clawcodex_ext.logical_kanban.method_library import (
    get_method,
    reset_method_registry,
    save_method_library,
)
from clawcodex_ext.logical_kanban.operation_schema import (
    OperationSchema,
    get_operation_schema,
    reset_operation_registry,
)
from clawcodex_ext.logical_kanban.ontology_graph import (
    get_registered_ontology,
    load_ontology_turtle,
    reset_ontology_registry,
)
from clawcodex_ext.logical_kanban.rule_engine import validate_external_config_references


ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples" / "external-configs"


@pytest.fixture(autouse=True)
def _reset_registries() -> None:
    reset_method_registry(include_seeds=True)
    reset_operation_registry()
    reset_ontology_registry()
    yield
    reset_method_registry(include_seeds=True)
    reset_operation_registry()
    reset_ontology_registry()


def _task(task_id: str, *, assumptions=(), assertions=()) -> ProposedTask:
    return ProposedTask(
        proposed_task_id=task_id,
        subject=task_id,
        description="",
        active_form="",
        acceptance_criteria=("ok",),
        blocked_by=(),
        lkb_metadata={"assumptions": list(assumptions), "assertions": list(assertions)},
    )


def _plan(*tasks: ProposedTask) -> DecompositionPlan:
    return DecompositionPlan(
        decomposition_run_id="D-f154",
        goal="test",
        tasks=tasks,
        dependencies=(),
        assumptions=(),
        ambiguity_report=None,
        validation_run=None,
    )


def test_import_directory_manifest_registers_all_kinds() -> None:
    importer = ExternalConfigImporter()
    results = importer.import_directory(EXAMPLES / "k8s-deploy")

    assert {result.kind for result in results} == {
        "ontology",
        "operation_schema",
        "method_library",
    }
    assert get_method("M-deploy-canary-001") is not None
    assert get_operation_schema("OP-canary-deploy") is not None
    ontology = get_registered_ontology()
    assert ontology is not None
    assert "Deployment" in ontology.classes


def test_lint_only_does_not_register() -> None:
    importer = ExternalConfigImporter(lint_only=True)
    result = importer.import_file(EXAMPLES / "security-fix" / "operations.json")

    assert result.imported is False
    assert result.kind == "operation_schema"
    assert get_operation_schema("OP-apply-patch") is None


def test_conflict_requires_force(tmp_path: Path) -> None:
    src = EXAMPLES / "data-engineering" / "operations.json"
    importer = ExternalConfigImporter()
    importer.import_file(src)

    with pytest.raises(ConfigConflictError):
        importer.import_file(src)

    forced = ExternalConfigImporter(force=True).import_file(src)
    assert forced.success is True


def test_rejects_dangerous_json_key(tmp_path: Path) -> None:
    path = tmp_path / "ops.json"
    path.write_text(json.dumps({"operations": [{"__class__": "bad"}]}), encoding="utf-8")

    with pytest.raises(ValueError, match="forbidden key"):
        ExternalConfigImporter().import_file(path)


def test_rejects_disallowed_file_type(tmp_path: Path) -> None:
    path = tmp_path / "config.py"
    path.write_text("print('no')", encoding="utf-8")

    with pytest.raises(ValueError, match="not allowed"):
        ExternalConfigImporter().import_file(path)


def test_operation_schema_yaml_import(tmp_path: Path) -> None:
    path = tmp_path / "ops.yaml"
    path.write_text(
        """
schema_version: 1.0.0
operations:
  - operation_id: OP-yaml-load
    description: YAML import
    preconditions: [Ready(x)]
    effects: [Dataset(x)]
    version: 1.0.0
""",
        encoding="utf-8",
    )
    result = ExternalConfigImporter().import_file(path)

    assert result.success is True
    assert get_operation_schema("OP-yaml-load") is not None


def test_ontology_import_falls_back_without_rdflib(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "rdflib" or name.startswith("rdflib."):
            raise ImportError("rdflib intentionally unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    graph = load_ontology_turtle(EXAMPLES / "k8s-deploy" / "domain.ttl")

    assert "Deployment" in graph.classes
    assert "exposes" in graph.object_properties


def test_audit_event_emitted_for_import() -> None:
    audit = InMemoryAuditLog()
    importer = ExternalConfigImporter(audit_log=audit)
    importer.import_file(EXAMPLES / "security-fix" / "operations.json")

    events = audit.query(event_type="lkb_external_config_imported")
    assert len(events) == 1
    assert events[0].payload["kind"] == "operation_schema"
    assert events[0].payload["itemCount"] == 2


def test_r_method_004_unknown_operation_is_error() -> None:
    operations = (OperationSchema("OP-known", "", effects=("Patch(x)",)),)
    plan = _plan(_task("tmp-1", assumptions=("OP-missing",)))

    issues = validate_external_config_references(plan, operations=operations, ontology=None)

    assert {issue.code for issue in issues} == {"R-METHOD-004-UNKNOWN-OPERATION"}
    assert issues[0].severity == "error"


def test_r_method_005_unknown_ontology_class_is_warning() -> None:
    ExternalConfigImporter().import_file(EXAMPLES / "security-fix" / "domain.ttl")
    plan = _plan(_task("tmp-1", assertions=("UnknownClass(x)",)))

    issues = validate_external_config_references(plan, operations=(), ontology=None)

    assert {issue.code for issue in issues} == {"R-METHOD-005-UNKNOWN-ONTOLOGY-CLASS"}
    assert issues[0].severity == "warning"


def test_cross_reference_lint_reports_missing_ontology_class() -> None:
    ExternalConfigImporter(lint_only=True).import_file(EXAMPLES / "k8s-deploy" / "domain.ttl")
    ontology = get_registered_ontology()
    # lint_only intentionally avoids registry; load with normal import for this check.
    ExternalConfigImporter().import_file(EXAMPLES / "k8s-deploy" / "domain.ttl")
    ontology = get_registered_ontology()
    assert ontology is not None
    op = OperationSchema("OP-test", "", effects=("Missing(x)",))
    report = lint_all(operations=(op,), ontology=ontology)

    assert any(issue.code == "xref.operation_ontology_missing" for issue in report.issues)


def test_cli_import_list_no_entry_points() -> None:
    from clawcodex_ext.cli.lkb_method_cmd.commands import _cmd_import

    assert _cmd_import(["--list"]) == 0


def test_cli_import_directory() -> None:
    from clawcodex_ext.cli.lkb_method_cmd.commands import _cmd_import

    assert _cmd_import([str(EXAMPLES / "security-fix")]) == 0
    assert get_method("M-fix-cve-001") is not None


def test_cli_export(tmp_path: Path) -> None:
    from clawcodex_ext.cli.lkb_method_cmd.commands import _cmd_export

    output = tmp_path / "active.json"
    assert _cmd_export(["--format=json", str(output)]) == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert "methods" in data
    assert "operations" in data


def test_manifest_path_escape_rejected(tmp_path: Path) -> None:
    manifest = tmp_path / "lkb-manifest.json"
    manifest.write_text(
        json.dumps({"contents": [{"path": "../outside.json", "kind": "operation_schema"}]}),
        encoding="utf-8",
    )
    (tmp_path.parent / "outside.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="escapes"):
        ExternalConfigImporter().import_directory(tmp_path)
