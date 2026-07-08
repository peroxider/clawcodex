"""External LKB configuration importer (F-154)."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, Literal
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .acceptance_template import (
    AcceptanceTemplate,
    load_acceptance_template_data,
    load_acceptance_template_library,
    register_acceptance_template,
)
from .audit import (
    AuditLog,
    event_for_acceptance_template_registered,
    event_for_external_config_imported,
)
from .external_config_lint import (
    LintIssue,
    lint_acceptance_templates,
    lint_method_library,
    lint_ontology,
    lint_operation_schema,
)
from .method_library import EngineeringMethod, load_method_library, register_method
from .ontology_graph import OntologyGraph, load_ontology_turtle, register_ontology_graph
from .operation_schema import (
    OperationSchema,
    load_operation_schema_data,
    register_operation_schemas,
)


ConfigKind = Literal["method_library", "operation_schema", "ontology", "acceptance_template"]
Priority = Literal["builtin", "project", "user", "explicit"]

_DEFAULT_MAX_SIZE = 10 * 1024 * 1024
_ALLOWED_SUFFIXES = {".json", ".ttl", ".yaml", ".yml"}
_DENIED_SUFFIXES = {".py", ".exe", ".so", ".dll", ".pyd"}
_FORBIDDEN_JSON_KEYS = {"__reduce__", "__class__", "__import__", "__globals__", "__subclasses__"}


@dataclass(frozen=True)
class ImportResult:
    success: bool
    kind: str
    item_count: int
    lint_issues: tuple[LintIssue, ...]
    source: str
    version: str = ""
    imported: bool = True

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.lint_issues if issue.severity == "error")

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "kind": self.kind,
            "itemCount": self.item_count,
            "lintIssues": [issue.to_dict() for issue in self.lint_issues],
            "source": self.source,
            "version": self.version,
            "imported": self.imported,
        }


class ConfigConflictError(ValueError):
    """Raised when explicit import conflicts in strict mode."""


class ExternalConfigImporter:
    def __init__(
        self,
        *,
        priority: Priority = "explicit",
        force: bool = False,
        lint_only: bool = False,
        max_size_bytes: int = _DEFAULT_MAX_SIZE,
        audit_log: AuditLog | None = None,
    ) -> None:
        self.priority = priority
        self.force = force
        self.lint_only = lint_only
        self.max_size_bytes = max_size_bytes
        self.audit_log = audit_log

    def import_file(self, path: Path) -> ImportResult:
        path = Path(path)
        self._validate_path(path)
        suffix = path.suffix.lower()
        if suffix == ".ttl":
            result = self._import_ontology(path)
        elif suffix in {".yaml", ".yml"}:
            result = self._import_yaml(path)
        elif suffix == ".json":
            result = self._import_json(path)
        else:
            raise ValueError(f"unsupported config file type: {suffix}")
        self._emit_audit(result)
        return result

    def import_directory(self, path: Path, *, recursive: bool = True) -> list[ImportResult]:
        path = Path(path)
        if not path.is_dir():
            raise ValueError(f"not a directory: {path}")
        manifest = path / "lkb-manifest.json"
        if manifest.is_file():
            return self._import_manifest(path, manifest)
        pattern = "**/*" if recursive else "*"
        results: list[ImportResult] = []
        for child in sorted(path.glob(pattern)):
            if child.is_file() and child.suffix.lower() in _ALLOWED_SUFFIXES:
                results.append(self.import_file(child))
        return results

    def import_package(self, entry_point: str) -> ImportResult:
        eps = metadata.entry_points()
        selected = eps.select(group="lkb.configs", name=entry_point)
        if not selected:
            raise ValueError(f"entry point {entry_point!r} not found in lkb.configs")
        value = selected[0].load()()
        result = self._import_object(value, source=f"entry_point:{entry_point}")
        self._emit_audit(result)
        return result

    def import_url(self, url: str) -> ImportResult:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise ValueError("only HTTPS URLs are allowed for external config import")
        request = Request(url, headers={"User-Agent": "clawcodex-lkb-importer"})
        try:
            with urlopen(request, timeout=15) as response:  # noqa: S310
                length = response.headers.get("Content-Length")
                if length and int(length) > self.max_size_bytes:
                    raise ValueError("remote config exceeds max size")
                data = response.read(self.max_size_bytes + 1)
        except URLError as exc:
            raise ValueError(f"could not fetch external config URL: {exc}") from exc
        if len(data) > self.max_size_bytes:
            raise ValueError("remote config exceeds max size")
        suffix = Path(parsed.path).suffix.lower() or ".json"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        try:
            return self.import_file(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

    @staticmethod
    def list_entry_points() -> tuple[str, ...]:
        return tuple(sorted(ep.name for ep in metadata.entry_points().select(group="lkb.configs")))

    def _import_json(self, path: Path) -> ImportResult:
        data = json.loads(path.read_text(encoding="utf-8"))
        _reject_forbidden_json_keys(data)
        kind = _detect_json_kind(data, path)
        if kind == "method_library":
            methods = load_method_library(path)
            issues = tuple(lint_method_library(methods))
            if not self.lint_only:
                for method in methods:
                    try:
                        register_method(method, force=self.force)
                    except ValueError as exc:
                        raise ConfigConflictError(str(exc)) from exc
            return ImportResult(
                success=not any(issue.severity == "error" for issue in issues),
                kind=kind,
                item_count=len(methods),
                lint_issues=issues,
                source=str(path),
                version=str(data.get("schemaVersion") or data.get("schema_version") or ""),
                imported=not self.lint_only,
            )
        if kind == "acceptance_template":
            templates = load_acceptance_template_library(path)
            issues = tuple(lint_acceptance_templates(templates))
            if not self.lint_only:
                for template in templates:
                    try:
                        register_acceptance_template(template, force=self.force)
                        self._emit_template_registered(template, str(path))
                    except ValueError as exc:
                        raise ConfigConflictError(str(exc)) from exc
            return ImportResult(
                success=not any(issue.severity == "error" for issue in issues),
                kind=kind,
                item_count=len(templates),
                lint_issues=issues,
                source=str(path),
                version=str(data.get("schemaVersion") or data.get("schema_version") or ""),
                imported=not self.lint_only,
            )
        operations = load_operation_schema_data(data, source=str(path))
        issues = tuple(lint_operation_schema(operations))
        if not self.lint_only:
            try:
                register_operation_schemas(operations, force=self.force)
            except ValueError as exc:
                raise ConfigConflictError(str(exc)) from exc
        return ImportResult(
            success=not any(issue.severity == "error" for issue in issues),
            kind="operation_schema",
            item_count=len(operations),
            lint_issues=issues,
            source=str(path),
            version=str(data.get("schema_version") or data.get("schemaVersion") or ""),
            imported=not self.lint_only,
        )

    def _import_yaml(self, path: Path) -> ImportResult:
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - dependency declared in pyproject
            raise ValueError("PyYAML is required to import YAML LKB configs") from exc
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        _reject_forbidden_json_keys(data)
        kind = _detect_yaml_kind(data, path)
        if kind == "acceptance_template":
            templates = load_acceptance_template_data(data, source=str(path))
            issues = tuple(lint_acceptance_templates(templates))
            if not self.lint_only:
                for template in templates:
                    try:
                        register_acceptance_template(template, force=self.force)
                        self._emit_template_registered(template, str(path))
                    except ValueError as exc:
                        raise ConfigConflictError(str(exc)) from exc
            return ImportResult(
                success=not any(issue.severity == "error" for issue in issues),
                kind="acceptance_template",
                item_count=len(templates),
                lint_issues=issues,
                source=str(path),
                version=str(data.get("schemaVersion") or data.get("schema_version") or "")
                if isinstance(data, dict)
                else "",
                imported=not self.lint_only,
            )
        operations = load_operation_schema_data(data, source=str(path))
        issues = tuple(lint_operation_schema(operations))
        if not self.lint_only:
            try:
                register_operation_schemas(operations, force=self.force)
            except ValueError as exc:
                raise ConfigConflictError(str(exc)) from exc
        return ImportResult(
            success=not any(issue.severity == "error" for issue in issues),
            kind="operation_schema",
            item_count=len(operations),
            lint_issues=issues,
            source=str(path),
            imported=not self.lint_only,
        )

    def _import_ontology(self, path: Path) -> ImportResult:
        graph = load_ontology_turtle(path)
        issues = tuple(lint_ontology(graph))
        if not self.lint_only:
            try:
                register_ontology_graph(graph, force=self.force)
            except ValueError as exc:
                raise ConfigConflictError(str(exc)) from exc
        return ImportResult(
            success=not any(issue.severity == "error" for issue in issues),
            kind="ontology",
            item_count=graph.item_count,
            lint_issues=issues,
            source=str(path),
            imported=not self.lint_only,
        )

    def _import_manifest(self, base: Path, manifest_path: Path) -> list[ImportResult]:
        self._validate_path(manifest_path)
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        _reject_forbidden_json_keys(data)
        contents = data.get("contents")
        if not isinstance(contents, list):
            raise ValueError("lkb-manifest.json must contain a contents array")
        results: list[ImportResult] = []
        for index, item in enumerate(contents):
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise ValueError(f"manifest contents[{index}] must contain a path")
            target = (base / item["path"]).resolve()
            if not _is_relative_to(target, base.resolve()):
                raise ValueError(f"manifest path escapes package directory: {item['path']}")
            results.append(self.import_file(target))
        return results

    def _import_object(self, value: Any, *, source: str) -> ImportResult:
        if isinstance(value, tuple) and all(isinstance(v, EngineeringMethod) for v in value):
            issues = tuple(lint_method_library(value))
            if not self.lint_only:
                for method in value:
                    register_method(method, force=self.force)
            return ImportResult(
                not any(i.severity == "error" for i in issues),
                "method_library",
                len(value),
                issues,
                source,
                imported=not self.lint_only,
            )
        if isinstance(value, AcceptanceTemplate):
            value = (value,)
        if isinstance(value, tuple) and all(isinstance(v, AcceptanceTemplate) for v in value):
            issues = tuple(lint_acceptance_templates(value))
            if not self.lint_only:
                for template in value:
                    register_acceptance_template(template, force=self.force)
                    self._emit_template_registered(template, source)
            return ImportResult(
                not any(i.severity == "error" for i in issues),
                "acceptance_template",
                len(value),
                issues,
                source,
                imported=not self.lint_only,
            )
        if isinstance(value, OperationSchema):
            value = (value,)
        if isinstance(value, tuple) and all(isinstance(v, OperationSchema) for v in value):
            issues = tuple(lint_operation_schema(value))
            if not self.lint_only:
                register_operation_schemas(value, force=self.force)
            return ImportResult(
                not any(i.severity == "error" for i in issues),
                "operation_schema",
                len(value),
                issues,
                source,
                imported=not self.lint_only,
            )
        if isinstance(value, OntologyGraph):
            issues = tuple(lint_ontology(value))
            if not self.lint_only:
                register_ontology_graph(value, force=self.force)
            return ImportResult(
                not any(i.severity == "error" for i in issues),
                "ontology",
                value.item_count,
                issues,
                source,
                imported=not self.lint_only,
            )
        raise ValueError(
            "entry point must return methods, acceptance templates, OperationSchema(s), or OntologyGraph"
        )

    def _validate_path(self, path: Path) -> None:
        suffix = path.suffix.lower()
        if suffix in _DENIED_SUFFIXES or suffix not in _ALLOWED_SUFFIXES:
            raise ValueError(f"external config file type is not allowed: {suffix}")
        if not path.is_file():
            raise ValueError(f"external config file not found: {path}")
        if path.is_symlink():
            raise ValueError("external config symlinks are not allowed")
        if path.stat().st_size > self.max_size_bytes:
            raise ValueError("external config exceeds max size")

    def _emit_audit(self, result: ImportResult) -> None:
        if self.audit_log is None:
            return
        self.audit_log.append(
            event_for_external_config_imported(
                source=result.source,
                kind=result.kind,
                version=result.version,
                item_count=result.item_count,
                lint_issue_count=len(result.lint_issues),
                lint_error_count=result.error_count,
            )
        )

    def _emit_template_registered(self, template: AcceptanceTemplate, source: str) -> None:
        if self.audit_log is None:
            return
        self.audit_log.append(
            event_for_acceptance_template_registered(
                template_id=template.template_id,
                source=source,
                version=template.version,
            )
        )


def _detect_json_kind(data: Any, path: Path) -> ConfigKind:
    if isinstance(data, dict) and isinstance(data.get("methods"), list):
        return "method_library"
    if isinstance(data, dict) and (
        data.get("kind") == "acceptance_template"
        or isinstance(data.get("acceptanceTemplates"), list)
        or isinstance(data.get("acceptance_templates"), list)
    ):
        return "acceptance_template"
    if isinstance(data, dict) and (
        "operations" in data or "operation_id" in data or "operationId" in data
    ):
        return "operation_schema"
    if isinstance(data, list):
        return "operation_schema"
    raise ValueError(f"could not detect external config kind for {path}")


def _detect_yaml_kind(data: Any, path: Path) -> ConfigKind:
    if isinstance(data, dict) and (
        data.get("kind") == "acceptance_template"
        or isinstance(data.get("acceptanceTemplates"), list)
        or isinstance(data.get("acceptance_templates"), list)
    ):
        return "acceptance_template"
    if isinstance(data, dict) and (
        "operations" in data or "operation_id" in data or "operationId" in data
    ):
        return "operation_schema"
    if isinstance(data, list):
        return "operation_schema"
    raise ValueError(f"could not detect external config kind for {path}")


def _reject_forbidden_json_keys(value: Any, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in _FORBIDDEN_JSON_KEYS:
                raise ValueError(f"forbidden key {key!r} at {path}")
            _reject_forbidden_json_keys(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_json_keys(child, path=f"{path}[{index}]")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


__all__ = [
    "ConfigConflictError",
    "ExternalConfigImporter",
    "ImportResult",
]
