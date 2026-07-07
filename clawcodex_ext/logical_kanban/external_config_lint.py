"""Lint checks for F-154 external LKB configuration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Literal

from .method_library import EngineeringMethod
from .ontology_graph import OntologyGraph
from .operation_schema import OperationSchema, is_predicate_expression, predicate_name


Severity = Literal["error", "warning"]

_METHOD_ID_RE = re.compile(r"^M-[a-z0-9]+(?:-[a-z0-9]+)*-\d{3}$")
_OPERATION_ID_RE = re.compile(r"^OP-[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class LintIssue:
    severity: Severity
    code: str
    message: str
    field_path: str = ""
    source: str = ""
    suggestion: str = ""

    def to_dict(self) -> dict[str, str]:
        out = {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }
        if self.field_path:
            out["fieldPath"] = self.field_path
        if self.source:
            out["source"] = self.source
        if self.suggestion:
            out["suggestion"] = self.suggestion
        return out


@dataclass(frozen=True)
class LintReport:
    issues: tuple[LintIssue, ...]

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "warning")

    @property
    def ok(self) -> bool:
        return self.error_count == 0


def lint_method_library(methods: Iterable[EngineeringMethod]) -> list[LintIssue]:
    issues: list[LintIssue] = []
    seen: set[str] = set()
    for method in methods:
        if method.method_id in seen:
            issues.append(
                LintIssue("error", "method.duplicate_id", f"Duplicate method_id {method.method_id!r}")
            )
        seen.add(method.method_id)
        if not _METHOD_ID_RE.match(method.method_id):
            issues.append(
                LintIssue(
                    "warning",
                    "method.id_format",
                    f"method_id {method.method_id!r} should match M-<kebab-case>-NNN.",
                    "methodId",
                    suggestion="Use an id like M-deploy-canary-001.",
                )
            )
        if len(method.subtask_templates) < 3:
            issues.append(
                LintIssue(
                    "warning",
                    "method.too_few_subtasks",
                    f"Method {method.method_id!r} should define at least 3 subtasks.",
                    "subtaskTemplates",
                )
            )
        template_ids = {template.template_id for template in method.subtask_templates}
        for template in method.subtask_templates:
            for blocker in template.default_blocked_by:
                if blocker not in template_ids:
                    issues.append(
                        LintIssue(
                            "error",
                            "method.dangling_blocker",
                            (
                                f"Method {method.method_id!r} template "
                                f"{template.template_id!r} references unknown blocker {blocker!r}."
                            ),
                            f"subtaskTemplates.{template.template_id}.defaultBlockedBy",
                        )
                    )
    return issues


def lint_operation_schema(operations: Iterable[OperationSchema]) -> list[LintIssue]:
    issues: list[LintIssue] = []
    seen: set[str] = set()
    for operation in operations:
        if operation.operation_id in seen:
            issues.append(
                LintIssue(
                    "error",
                    "operation.duplicate_id",
                    f"Duplicate operation_id {operation.operation_id!r}.",
                    "operation_id",
                    operation.source,
                )
            )
        seen.add(operation.operation_id)
        if not _OPERATION_ID_RE.match(operation.operation_id):
            issues.append(
                LintIssue(
                    "error",
                    "operation.id_format",
                    f"operation_id {operation.operation_id!r} should match OP-<kebab-case>.",
                    "operation_id",
                    operation.source,
                    "Use an id like OP-rolling-update.",
                )
            )
        for index, predicate in enumerate((*operation.preconditions, *operation.effects)):
            if not is_predicate_expression(predicate):
                issues.append(
                    LintIssue(
                        "error",
                        "operation.predicate_format",
                        f"Predicate {predicate!r} should use Name(args) syntax.",
                        f"preconditions/effects[{index}]",
                        operation.source,
                    )
                )
    return issues


def lint_ontology(graph: OntologyGraph) -> list[LintIssue]:
    issues: list[LintIssue] = []
    if not graph.classes:
        issues.append(
            LintIssue("warning", "ontology.no_classes", "Ontology does not define owl:Class entries.", source=graph.source)
        )
    for ref in sorted(graph.domain_refs | graph.range_refs):
        if ref not in graph.classes:
            issues.append(
                LintIssue(
                    "error",
                    "ontology.unknown_class_ref",
                    f"Ontology property references undeclared class {ref!r}.",
                    "rdfs:domain/rdfs:range",
                    graph.source,
                )
            )
    return issues


def lint_cross_references(
    *,
    methods: Iterable[EngineeringMethod] = (),
    operations: Iterable[OperationSchema] = (),
    ontology: OntologyGraph | None = None,
) -> list[LintIssue]:
    issues: list[LintIssue] = []
    operation_ids = {operation.operation_id for operation in operations}
    for method in methods:
        for assumption in method.assumptions:
            for op_id in _operation_ids_in_text(assumption):
                if op_id not in operation_ids:
                    issues.append(
                        LintIssue(
                            "error",
                            "xref.method_operation_missing",
                            f"Method {method.method_id!r} references unknown operation {op_id!r}.",
                            "assumptions",
                        )
                    )
    if ontology is not None:
        for operation in operations:
            for effect in operation.effects:
                name = predicate_name(effect)
                if name and name not in ontology.classes:
                    issues.append(
                        LintIssue(
                            "warning",
                            "xref.operation_ontology_missing",
                            (
                                f"Operation {operation.operation_id!r} effect {effect!r} "
                                f"references class {name!r}, not present in ontology."
                            ),
                            "effects",
                            operation.source,
                        )
                    )
    return issues


def lint_all(
    *,
    methods: Iterable[EngineeringMethod] = (),
    operations: Iterable[OperationSchema] = (),
    ontology: OntologyGraph | None = None,
) -> LintReport:
    issues: list[LintIssue] = []
    method_tuple = tuple(methods)
    operation_tuple = tuple(operations)
    issues.extend(lint_method_library(method_tuple))
    issues.extend(lint_operation_schema(operation_tuple))
    if ontology is not None:
        issues.extend(lint_ontology(ontology))
    issues.extend(
        lint_cross_references(methods=method_tuple, operations=operation_tuple, ontology=ontology)
    )
    return LintReport(tuple(issues))


def _operation_ids_in_text(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"\bOP-[a-z0-9]+(?:-[a-z0-9]+)*\b", text))


__all__ = [
    "LintIssue",
    "LintReport",
    "lint_all",
    "lint_cross_references",
    "lint_method_library",
    "lint_ontology",
    "lint_operation_schema",
]
