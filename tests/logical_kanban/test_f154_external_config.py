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
    ImportResult,
)
from clawcodex_ext.logical_kanban.external_config_lint import (
    LintIssue,
    LintReport,
    lint_all,
    lint_cross_references,
    lint_method_library,
    lint_ontology,
    lint_operation_schema,
)
from clawcodex_ext.logical_kanban.method_library import (
    EngineeringMethod,
    SubtaskTemplate,
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
    OntologyGraph,
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


# ============================================================================
# Original 15 tests (kept verbatim)
# ============================================================================


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


# ============================================================================
# ~25 new tests to reach 40+ total
# ============================================================================


def test_import_method_library_json(tmp_path: Path) -> None:
    """Happy path: import a method library JSON file."""
    path = tmp_path / "methods.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "methods": [
                    {
                        "methodId": "M-add-auth-001",
                        "pattern": "add_auth",
                        "description": "Add auth middleware.",
                        "subtaskTemplates": [
                            {"templateId": "design", "role": "design", "subjectTemplate": "Plan auth"},
                            {"templateId": "impl", "role": "impl", "subjectTemplate": "Implement auth", "defaultBlockedBy": ["design"]},
                            {"templateId": "test", "role": "test", "subjectTemplate": "Test auth", "defaultBlockedBy": ["impl"]},
                        ],
                        "acceptanceTemplate": {"assertionTemplate": "AuthWorks()", "strictAcceptance": True},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = ExternalConfigImporter().import_file(path)
    assert result.success is True
    assert result.kind == "method_library"
    assert result.item_count == 1
    assert get_method("M-add-auth-001") is not None


def test_import_method_library_validation_error_reported(tmp_path: Path) -> None:
    """Method library with lint warnings still succeeds but reports issues."""
    path = tmp_path / "methods.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "methods": [
                    {
                        "methodId": "bad-method",  # violates M-<kebab-case>-NNN
                        "pattern": "bad",
                        "description": "Bad method.",
                        "subtaskTemplates": [  # only 1 subtask (< 3 triggers warning)
                            {"templateId": "only", "role": "impl", "subjectTemplate": "Do thing"},
                        ],
                        "acceptanceTemplate": {"assertionTemplate": "Done()"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = ExternalConfigImporter().import_file(path)
    assert result.success is True  # warnings don't block success
    codes = {issue.code for issue in result.lint_issues}
    assert "method.id_format" in codes
    assert "method.too_few_subtasks" in codes


def test_import_operation_schema_json_operations_key(tmp_path: Path) -> None:
    """Operation schema imported from object with 'operations' key."""
    path = tmp_path / "ops.json"
    path.write_text(
        json.dumps(
            {
                "operations": [
                    {
                        "operation_id": "OP-obj-test",
                        "description": "Object-key test",
                        "preconditions": ["Ready(x)"],
                        "effects": ["Done(x)"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    result = ExternalConfigImporter().import_file(path)
    assert result.success is True
    assert result.kind == "operation_schema"
    assert result.item_count == 1
    assert get_operation_schema("OP-obj-test") is not None


def test_import_operation_schema_json_single_object(tmp_path: Path) -> None:
    """Single operation as a dict (not wrapped in a list)."""
    path = tmp_path / "ops.json"
    path.write_text(
        json.dumps(
            {
                "operation_id": "OP-single-test",
                "description": "Single-object test",
                "preconditions": [],
                "effects": ["Done(x)"],
            }
        ),
        encoding="utf-8",
    )
    result = ExternalConfigImporter().import_file(path)
    assert result.success is True
    assert result.kind == "operation_schema"
    assert result.item_count == 1
    assert get_operation_schema("OP-single-test") is not None


def test_import_ontology_turtle_happy_path(tmp_path: Path) -> None:
    """Happy path: import a Turtle ontology file."""
    path = tmp_path / "domain.ttl"
    path.write_text(
        "@prefix ex: <https://example.com/lkb#> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "ex:Widget a owl:Class .\n"
        "ex:Gadget a owl:Class .\n"
        "ex:connects a owl:ObjectProperty ;\n"
        "  rdfs:domain ex:Widget ;\n"
        "  rdfs:range ex:Gadget .\n",
        encoding="utf-8",
    )
    result = ExternalConfigImporter().import_file(path)
    assert result.success is True
    assert result.kind == "ontology"
    assert result.item_count >= 2
    ontology = get_registered_ontology()
    assert ontology is not None
    assert "Widget" in ontology.classes
    assert "Gadget" in ontology.classes


def test_import_operation_schema_yaml_multiple(tmp_path: Path) -> None:
    """YAML file with multiple operations."""
    path = tmp_path / "ops.yaml"
    path.write_text(
        "schema_version: '1.0.0'\n"
        "operations:\n"
        "  - operation_id: OP-yaml-1\n"
        "    description: First YAML op\n"
        "    preconditions: [A(x)]\n"
        "    effects: [B(x)]\n"
        "  - operation_id: OP-yaml-2\n"
        "    description: Second YAML op\n"
        "    preconditions: [B(x)]\n"
        "    effects: [C(x)]\n",
        encoding="utf-8",
    )
    result = ExternalConfigImporter().import_file(path)
    assert result.success is True
    assert result.item_count == 2
    assert get_operation_schema("OP-yaml-1") is not None
    assert get_operation_schema("OP-yaml-2") is not None


def test_import_directory_no_manifest(tmp_path: Path) -> None:
    """Directory import without a manifest file imports each supported file."""
    (tmp_path / "ops.json").write_text(
        json.dumps({"operations": [{"operation_id": "OP-dir-test", "description": "Dir import", "effects": ["Done(x)"]}]}),
        encoding="utf-8",
    )
    (tmp_path / "notes.txt").write_text("ignore me", encoding="utf-8")
    results = ExternalConfigImporter().import_directory(tmp_path, recursive=False)
    assert len(results) == 1
    assert results[0].kind == "operation_schema"


def test_import_directory_empty(tmp_path: Path) -> None:
    """Importing an empty directory returns no results (no error)."""
    results = ExternalConfigImporter().import_directory(tmp_path)
    assert results == []


def test_corrupt_json_rejected(tmp_path: Path) -> None:
    """Corrupt JSON file raises JSONDecodeError."""
    path = tmp_path / "bad.json"
    path.write_text("{this is not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        ExternalConfigImporter().import_file(path)


def test_unknown_file_extension_rejected(tmp_path: Path) -> None:
    """Files with unsupported extensions are rejected."""
    path = tmp_path / "config.csv"
    path.write_text("a,b,c\n1,2,3", encoding="utf-8")
    with pytest.raises(ValueError, match="not allowed"):
        ExternalConfigImporter().import_file(path)


def test_security_file_size_exceeded(tmp_path: Path) -> None:
    """File exceeding max_size_bytes is rejected."""
    path = tmp_path / "big.json"
    path.write_text(json.dumps({"test": "x" * 50}), encoding="utf-8")
    with pytest.raises(ValueError, match="exceeds max size"):
        ExternalConfigImporter(max_size_bytes=10).import_file(path)


def test_security_symlink_rejected(tmp_path: Path) -> None:
    """Symlinks are not allowed."""
    real = tmp_path / "real.json"
    real.write_text(
        json.dumps([{"operation_id": "OP-real", "description": "real", "effects": ["Done(x)"]}]),
        encoding="utf-8",
    )
    link = tmp_path / "link.json"
    link.symlink_to(real)
    with pytest.raises(ValueError, match="symlink"):
        ExternalConfigImporter().import_file(link)


def test_import_result_version_populated_from_schema_version(tmp_path: Path) -> None:
    """ImportResult.version matches schema_version from the file."""
    path = tmp_path / "ops.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "operations": [{"operation_id": "OP-ver-test", "description": "v", "effects": ["Done(x)"]}],
            }
        ),
        encoding="utf-8",
    )
    result = ExternalConfigImporter().import_file(path)
    assert result.version == "2.0.0"


def test_import_result_to_dict() -> None:
    """ImportResult.to_dict() returns the expected structure."""
    issues = (LintIssue("warning", "lint.test", "A test issue"),)
    result = ImportResult(
        success=True,
        kind="operation_schema",
        item_count=3,
        lint_issues=issues,
        source="/tmp/test.json",
        version="1.0.0",
    )
    d = result.to_dict()
    assert d["success"] is True
    assert d["kind"] == "operation_schema"
    assert d["itemCount"] == 3
    assert len(d["lintIssues"]) == 1
    assert d["lintIssues"][0]["code"] == "lint.test"
    assert d["source"] == "/tmp/test.json"
    assert d["imported"] is True


# --- lint unit tests ---


def test_lint_method_library_duplicate_id() -> None:
    """Lint detects duplicate method_id entries."""
    m = EngineeringMethod(
        method_id="M-dup-test-001",
        pattern="dup",
        description="dup",
        subtask_templates=(
            SubtaskTemplate("s1", "impl", "Do 1"),
            SubtaskTemplate("s2", "impl", "Do 2"),
            SubtaskTemplate("s3", "test", "Do 3"),
        ),
    )
    issues = lint_method_library([m, m])
    codes = {i.code for i in issues}
    assert "method.duplicate_id" in codes


def test_lint_method_library_dangling_blocker() -> None:
    """Lint detects blocker referencing non-existent template_id."""
    m = EngineeringMethod(
        method_id="M-blocker-001",
        pattern="block",
        description="dangling blocker",
        subtask_templates=(
            SubtaskTemplate("s1", "impl", "Do 1"),
            SubtaskTemplate("s2", "test", "Do 2", default_blocked_by=("ghost",)),
        ),
    )
    issues = lint_method_library([m])
    codes = {i.code for i in issues}
    assert "method.dangling_blocker" in codes


def test_lint_operation_schema_duplicate_id() -> None:
    """Lint detects duplicate operation_id."""
    op = OperationSchema("OP-dup", "dup", effects=("Done(x)",))
    issues = lint_operation_schema([op, op])
    codes = {i.code for i in issues}
    assert "operation.duplicate_id" in codes


def test_lint_operation_schema_predicate_format() -> None:
    """Lint detects predicates not matching Name(args) syntax."""
    op = OperationSchema("OP-bad-pred", "bad", preconditions=("not a predicate",))
    issues = lint_operation_schema([op])
    codes = {i.code for i in issues}
    assert "operation.predicate_format" in codes


def test_lint_ontology_no_classes_is_warning() -> None:
    """Lint warns when ontology defines no classes."""
    g = OntologyGraph(
        source="test.ttl",
        classes=frozenset(),
        object_properties=frozenset(),
    )
    issues = lint_ontology(g)
    codes = {i.code for i in issues}
    assert "ontology.no_classes" in codes


def test_lint_ontology_unknown_class_ref() -> None:
    """Lint detects property referencing undeclared class."""
    g = OntologyGraph(
        source="test.ttl",
        classes=frozenset({"Known"}),
        object_properties=frozenset({"refProp"}),
        domain_refs=frozenset({"Known"}),
        range_refs=frozenset({"Missing"}),  # undeclared
    )
    issues = lint_ontology(g)
    codes = {i.code for i in issues}
    assert "ontology.unknown_class_ref" in codes


def test_lint_cross_ref_method_operation_missing() -> None:
    """Lint detects method assumption referencing unknown operation."""
    m = EngineeringMethod(
        method_id="M-xref-op-001",
        pattern="xref",
        description="cross ref test",
        assumptions=("OP-does-not-exist is required",),
        subtask_templates=(
            SubtaskTemplate("s1", "impl", "Do 1"),
            SubtaskTemplate("s2", "impl", "Do 2"),
            SubtaskTemplate("s3", "test", "Do 3"),
        ),
    )
    issues = lint_cross_references(methods=[m], operations=[], ontology=None)
    codes = {i.code for i in issues}
    assert "xref.method_operation_missing" in codes


def test_lint_cross_ref_operation_ontology_missing() -> None:
    """Lint detects operation effect referencing class not in ontology."""
    op = OperationSchema("OP-ref-test", "ref test", effects=("MissingClass(x)",))
    ontology = OntologyGraph(
        source="test.ttl",
        classes=frozenset({"Known"}),
        object_properties=frozenset(),
    )
    issues = lint_cross_references(operations=[op], ontology=ontology)
    codes = {i.code for i in issues}
    assert "xref.operation_ontology_missing" in codes


def test_lint_report_properties() -> None:
    """LintReport correctly computes error_count, warning_count, and ok."""
    issues = [
        LintIssue("error", "e1", "Error 1"),
        LintIssue("error", "e2", "Error 2"),
        LintIssue("warning", "w1", "Warning 1"),
    ]
    report = LintReport(tuple(issues))
    assert report.error_count == 2
    assert report.warning_count == 1
    assert report.ok is False

    clean = LintReport(())
    assert clean.error_count == 0
    assert clean.warning_count == 0
    assert clean.ok is True


# --- R-METHOD happy paths ---


def test_r_method_004_known_operation_no_issue() -> None:
    """R-METHOD-004: known operation produces no issue."""
    operations = (OperationSchema("OP-known", "known", effects=("Patch(x)",)),)
    plan = _plan(_task("tmp-1", assumptions=("OP-known",)))
    issues = validate_external_config_references(plan, operations=operations, ontology=None)
    assert not any(issue.code == "R-METHOD-004-UNKNOWN-OPERATION" for issue in issues)


def test_r_method_005_known_ontology_class_no_issue() -> None:
    """R-METHOD-005: known ontology class produces no issue."""
    ontology = OntologyGraph(
        source="test.ttl",
        classes=frozenset({"CVE"}),
        object_properties=frozenset(),
    )
    plan = _plan(_task("tmp-1", assertions=("CVE(x)",)))
    issues = validate_external_config_references(plan, operations=(), ontology=ontology)
    assert not any("R-METHOD-005" in issue.code for issue in issues)


# --- ontology registration edge cases ---


def test_ontology_duplicate_registration_raises(tmp_path: Path) -> None:
    """Registering the same ontology file twice without force raises."""
    path = tmp_path / "domain.ttl"
    path.write_text(
        "@prefix ex: <https://example.com/lkb#> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "ex:Dup a owl:Class .\n",
        encoding="utf-8",
    )
    importer = ExternalConfigImporter()
    importer.import_file(path)
    with pytest.raises(ValueError, match="already registered"):
        importer.import_file(path)


def test_ontology_force_overwrites(tmp_path: Path) -> None:
    """--force allows overriding the previously registered ontology."""
    path = tmp_path / "domain.ttl"
    path.write_text(
        "@prefix ex: <https://example.com/lkb#> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "ex:V1Class a owl:Class .\n",
        encoding="utf-8",
    )
    ExternalConfigImporter().import_file(path)
    # Replace with a different ontology using force
    path.write_text(
        "@prefix ex: <https://example.com/lkb#> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "ex:V2Class a owl:Class .\n",
        encoding="utf-8",
    )
    result = ExternalConfigImporter(force=True).import_file(path)
    assert result.success is True
    ontology = get_registered_ontology()
    assert ontology is not None
    assert "V2Class" in ontology.classes


# --- CLI integration tests ---


def test_cli_import_lint_only_with_errors(tmp_path: Path) -> None:
    """CLI --lint-only reports errors via exit code."""
    from clawcodex_ext.cli.lkb_method_cmd.commands import _cmd_import

    path = tmp_path / "bad_ops.json"
    path.write_text(
        json.dumps(
            {
                "operations": [
                    {"operation_id": "bad-op-id", "description": "bad", "preconditions": ["invalid pred"]}
                ]
            }
        ),
        encoding="utf-8",
    )
    # --lint-only with errors returns 2
    assert _cmd_import(["--lint-only", str(path)]) == 2


def test_cli_config_list(tmp_path: Path) -> None:
    """CLI config list returns 0 and prints something."""
    from clawcodex_ext.cli.lkb_method_cmd.commands import _cmd_config_list
    from io import StringIO
    import sys

    # Import some config first so there's something to list
    ExternalConfigImporter().import_file(EXAMPLES / "data-engineering" / "operations.json")
    old_stdout = sys.stdout
    sys.stdout = captured = StringIO()
    try:
        code = _cmd_config_list([])
        assert code == 0
        output = captured.getvalue()
        assert "operation_schema" in output
    finally:
        sys.stdout = old_stdout


def test_cli_import_recursive(tmp_path: Path) -> None:
    """CLI import --recursive imports all files in nested dirs."""
    from clawcodex_ext.cli.lkb_method_cmd.commands import _cmd_import

    sub = tmp_path / "nested"
    sub.mkdir()
    (sub / "ops.json").write_text(
        json.dumps(
            {"operations": [{"operation_id": "OP-nested-01", "description": "nested", "effects": ["Done(x)"]}]}
        ),
        encoding="utf-8",
    )
    (sub / "domain.ttl").write_text(
        "@prefix ex: <https://example.com/lkb#> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "ex:NestedClass a owl:Class .\n",
        encoding="utf-8",
    )
    assert _cmd_import(["--recursive", str(sub)]) == 0
    assert get_operation_schema("OP-nested-01") is not None
    ontology = get_registered_ontology()
    assert ontology is not None
    assert "NestedClass" in ontology.classes
