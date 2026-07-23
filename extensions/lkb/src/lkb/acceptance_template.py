"""Top-level acceptance-template registry for Logical Kanban (F-155)."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

logger = logging.getLogger(__name__)

AcceptanceTemplateStatus = Literal["draft", "approved", "rejected", "deprecated"]

ALLOWED_ACCEPTANCE_TEMPLATE_STATUSES: frozenset[str] = frozenset(
    {"draft", "approved", "rejected", "deprecated"}
)
ALLOWED_ACCEPTANCE_TEMPLATE_ROLES: frozenset[str] = frozenset(
    {"design", "impl", "test", "docs", "review", "deploy", "integrate"}
)

_TEMPLATE_ID_RE = re.compile(r"^T-[a-z0-9]+(?:-[a-z0-9]+)*-\d{3}$")
_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_BAD_BRACE_RE = re.compile(r"\{[^}]*[^a-zA-Z0-9_}][^}]*\}|\{[0-9][^}]*\}")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

@dataclass(frozen=True)
class AcceptanceTemplate:
    """Reusable top-level acceptance criteria template.

    F-150 keeps a smaller method-local acceptance template.  This F-155
    dataclass is the independently registered top-level form; it preserves the
    same core fields while adding registry identity and governance metadata.
    """

    template_id: str
    description: str
    assertion_template: str
    proof_template: str = ""
    strict_acceptance: bool = True
    applies_to_roles: tuple[str, ...] = field(default_factory=tuple)
    version: str = "1.0.0"
    status: AcceptanceTemplateStatus = "approved"

    def __post_init__(self) -> None:
        if not isinstance(self.template_id, str) or not self.template_id.strip():
            raise ValueError("AcceptanceTemplate.template_id must be a non-empty string")
        if not _TEMPLATE_ID_RE.match(self.template_id):
            raise ValueError("AcceptanceTemplate.template_id must match T-<kebab-case>-NNN")
        if not isinstance(self.description, str):
            raise ValueError("AcceptanceTemplate.description must be a string")
        if not isinstance(self.assertion_template, str) or not self.assertion_template.strip():
            raise ValueError("AcceptanceTemplate.assertion_template must be a non-empty string")
        if not isinstance(self.proof_template, str):
            raise ValueError("AcceptanceTemplate.proof_template must be a string")
        if not isinstance(self.strict_acceptance, bool):
            raise ValueError("AcceptanceTemplate.strict_acceptance must be a boolean")
        if not isinstance(self.applies_to_roles, tuple):
            raise ValueError("AcceptanceTemplate.applies_to_roles must be a tuple")
        for role in self.applies_to_roles:
            if role not in ALLOWED_ACCEPTANCE_TEMPLATE_ROLES:
                raise ValueError(
                    f"AcceptanceTemplate.applies_to_roles entries must be one of "
                    f"{sorted(ALLOWED_ACCEPTANCE_TEMPLATE_ROLES)}; got {role!r}"
                )
        if not isinstance(self.version, str) or not _SEMVER_RE.match(self.version):
            raise ValueError("AcceptanceTemplate.version must be SemVer MAJOR.MINOR.PATCH")
        if self.status not in ALLOWED_ACCEPTANCE_TEMPLATE_STATUSES:
            raise ValueError(
                f"AcceptanceTemplate.status must be one of "
                f"{sorted(ALLOWED_ACCEPTANCE_TEMPLATE_STATUSES)}; got {self.status!r}"
            )
        _validate_placeholders(self.assertion_template, "assertion_template")
        _validate_placeholders(self.proof_template, "proof_template")

    def to_dict(self) -> dict[str, Any]:
        return {
            "templateId": self.template_id,
            "description": self.description,
            "assertionTemplate": self.assertion_template,
            "proofTemplate": self.proof_template,
            "strictAcceptance": self.strict_acceptance,
            "appliesToRoles": list(self.applies_to_roles),
            "version": self.version,
            "status": self.status,
        }

class AcceptanceTemplateRegistry:
    """Mutable registry for top-level acceptance templates."""

    def __init__(self, templates: Iterable[AcceptanceTemplate] = ()) -> None:
        self._templates: dict[str, AcceptanceTemplate] = {}
        for template in templates:
            self.register(template)

    def register(self, template: AcceptanceTemplate, *, force: bool = False) -> None:
        if not isinstance(template, AcceptanceTemplate):
            raise ValueError("register expects an AcceptanceTemplate")
        if template.template_id in self._templates and not force:
            raise ValueError(
                f"template_id {template.template_id!r} already registered; use force to replace"
            )
        self._templates[template.template_id] = template

    def get(self, template_id: str) -> AcceptanceTemplate | None:
        return self._templates.get(template_id)

    def list(
        self,
        *,
        status: str | None = "approved",
        role: str | None = None,
    ) -> tuple[AcceptanceTemplate, ...]:
        out = []
        for template in self._templates.values():
            if status is not None and template.status != status:
                continue
            if role is not None and role not in template.applies_to_roles:
                continue
            out.append(template)
        out.sort(key=lambda item: item.template_id)
        return tuple(out)

    def save(self, path: Path) -> None:
        save_acceptance_template_library(self.list(status=None), path)

    def load(self, path: Path, *, force: bool = False) -> tuple[AcceptanceTemplate, ...]:
        templates = load_acceptance_template_library(path)
        for template in templates:
            self.register(template, force=force)
        return templates

def _validate_placeholders(value: str, field_name: str) -> None:
    if not value:
        return
    if value.count("{") != value.count("}"):
        raise ValueError(f"AcceptanceTemplate.{field_name} has unbalanced placeholders")
    if _BAD_BRACE_RE.search(value):
        raise ValueError(
            f"AcceptanceTemplate.{field_name} placeholders must use {{identifier}} syntax"
        )
    for match in re.finditer(r"\{([^}]*)\}", value):
        if not _PLACEHOLDER_RE.fullmatch(match.group(0)):
            raise ValueError(
                f"AcceptanceTemplate.{field_name} placeholders must use {{identifier}} syntax"
            )

def save_acceptance_template_library(
    templates: Iterable[AcceptanceTemplate],
    path: Path,
) -> None:
    payload = {
        "schemaVersion": "1.0.0",
        "kind": "acceptance_template",
        "acceptanceTemplates": [template.to_dict() for template in templates],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

def load_acceptance_template_library(path: Path) -> tuple[AcceptanceTemplate, ...]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return load_acceptance_template_data(data, source=str(path))

def load_acceptance_template_data(data: Any, *, source: str = "") -> tuple[AcceptanceTemplate, ...]:
    if isinstance(data, dict):
        raw_templates = (
            data.get("acceptanceTemplates")
            or data.get("acceptance_templates")
            or data.get("templates")
        )
        if raw_templates is None and _looks_like_template(data):
            raw_templates = [data]
    elif isinstance(data, list):
        raw_templates = data
    else:
        raw_templates = None
    if not isinstance(raw_templates, list):
        raise ValueError("acceptance template config must contain an acceptanceTemplates array")

    out: list[AcceptanceTemplate] = []
    for index, raw in enumerate(raw_templates):
        if not isinstance(raw, dict):
            raise ValueError(f"acceptanceTemplates[{index}] must be a JSON object")
        out.append(_deserialize_acceptance_template(raw, source=source, index=index))
    return tuple(out)

def _looks_like_template(data: dict[str, Any]) -> bool:
    return any(
        key in data
        for key in ("templateId", "template_id", "assertionTemplate", "assertion_template")
    )

def _deserialize_acceptance_template(
    raw: dict[str, Any],
    *,
    source: str = "",
    index: int = 0,
) -> AcceptanceTemplate:
    template_id = raw.get("templateId") or raw.get("template_id")
    assertion_template = raw.get("assertionTemplate") or raw.get("assertion_template")
    if not isinstance(template_id, str) or not template_id:
        raise ValueError(f"acceptanceTemplates[{index}].templateId must be a non-empty string")
    if not isinstance(assertion_template, str) or not assertion_template:
        raise ValueError(
            f"acceptanceTemplates[{index}].assertionTemplate must be a non-empty string"
        )
    description = raw.get("description", "")
    if not isinstance(description, str):
        raise ValueError(f"acceptanceTemplates[{index}].description must be a string")
    proof_template = raw.get("proofTemplate") or raw.get("proof_template") or ""
    strict_acceptance = raw.get("strictAcceptance", raw.get("strict_acceptance", True))
    applies_raw = raw.get("appliesToRoles", raw.get("applies_to_roles", []))
    if not isinstance(applies_raw, list):
        raise ValueError(f"acceptanceTemplates[{index}].appliesToRoles must be a list")
    version = raw.get("version", "1.0.0")
    status = raw.get("status", "approved")
    return AcceptanceTemplate(
        template_id=template_id,
        description=description or f"Imported from {source}",
        assertion_template=assertion_template,
        proof_template=proof_template,
        strict_acceptance=strict_acceptance,
        applies_to_roles=tuple(str(role) for role in applies_raw),
        version=version,
        status=status,
    )

def default_lkb_cache_dir() -> Path:
    home = os.environ.get("HOME")
    root = Path(home) if home else Path.home()
    return root / ".cache" / "clawcodex" / "lkb"

def default_user_acceptance_templates_dir() -> Path:
    return default_lkb_cache_dir() / "acceptance_templates"

def default_project_acceptance_templates_dir(project_dir: Path | None = None) -> Path:
    root = project_dir if project_dir is not None else Path.cwd()
    return root / ".lkb" / "acceptance_templates"

def load_acceptance_template_library_layered(
    *,
    project_dir: Path | None = None,
    user_cache_dir: Path | None = None,
    explicit_paths: Iterable[Path] = (),
) -> tuple[AcceptanceTemplate, ...]:
    from .acceptance_template_seed import ACCEPTANCE_TEMPLATE_SEEDS

    seen: dict[str, AcceptanceTemplate] = {
        template.template_id: template for template in ACCEPTANCE_TEMPLATE_SEEDS
    }
    _merge_from_directory(default_project_acceptance_templates_dir(project_dir), seen)
    user_path = _templates_dir_from_cache_arg(user_cache_dir)
    _merge_from_directory(user_path, seen)
    for path in explicit_paths:
        try:
            for template in load_acceptance_template_library(Path(path)):
                seen[template.template_id] = template
        except Exception as exc:
            logger.warning("Skipping invalid explicit acceptance template file %s: %s", path, exc)
    return tuple(seen.values())

def initialize_acceptance_template_registry(
    *,
    project_dir: Path | None = None,
    user_cache_dir: Path | None = None,
    explicit_paths: Iterable[Path] = (),
) -> tuple[AcceptanceTemplate, ...]:
    templates = load_acceptance_template_library_layered(
        project_dir=project_dir,
        user_cache_dir=user_cache_dir,
        explicit_paths=explicit_paths,
    )
    _ACCEPTANCE_TEMPLATE_REGISTRY._templates.clear()
    for template in templates:
        _ACCEPTANCE_TEMPLATE_REGISTRY.register(template, force=True)
    return _ACCEPTANCE_TEMPLATE_REGISTRY.list(status=None)

def _merge_from_directory(
    directory: Path,
    seen: dict[str, AcceptanceTemplate],
) -> None:
    if not directory.is_dir():
        return
    for fpath in sorted(directory.glob("*.json")):
        try:
            templates = load_acceptance_template_library(fpath)
        except Exception as exc:
            logger.warning("Skipping invalid LKB acceptance template file %s: %s", fpath, exc)
            continue
        for template in templates:
            seen[template.template_id] = template

def _templates_dir_from_cache_arg(user_cache_dir: Path | None) -> Path:
    if user_cache_dir is None:
        return default_user_acceptance_templates_dir()
    path = Path(user_cache_dir)
    return path if path.name == "acceptance_templates" else path / "acceptance_templates"

def ensure_default_acceptance_template_dirs() -> None:
    base = default_lkb_cache_dir()
    for sub in ("acceptance_templates", "template_proposals"):
        (base / sub).mkdir(parents=True, exist_ok=True)

def register_acceptance_template(
    template: AcceptanceTemplate,
    *,
    force: bool = False,
) -> None:
    _ACCEPTANCE_TEMPLATE_REGISTRY.register(template, force=force)

def get_acceptance_template(template_id: str) -> AcceptanceTemplate | None:
    return _ACCEPTANCE_TEMPLATE_REGISTRY.get(template_id)

def list_acceptance_templates(
    *,
    status: str | None = "approved",
    role: str | None = None,
) -> tuple[AcceptanceTemplate, ...]:
    return _ACCEPTANCE_TEMPLATE_REGISTRY.list(status=status, role=role)

def get_all_acceptance_templates() -> tuple[AcceptanceTemplate, ...]:
    return _ACCEPTANCE_TEMPLATE_REGISTRY.list(status=None)

def reset_acceptance_template_registry(include_seeds: bool = True) -> None:
    _ACCEPTANCE_TEMPLATE_REGISTRY._templates.clear()
    if include_seeds:
        from .acceptance_template_seed import ACCEPTANCE_TEMPLATE_SEEDS

        for template in ACCEPTANCE_TEMPLATE_SEEDS:
            _ACCEPTANCE_TEMPLATE_REGISTRY.register(template)

_ACCEPTANCE_TEMPLATE_REGISTRY = AcceptanceTemplateRegistry()
reset_acceptance_template_registry(include_seeds=True)

__all__ = [
    "ALLOWED_ACCEPTANCE_TEMPLATE_ROLES",
    "ALLOWED_ACCEPTANCE_TEMPLATE_STATUSES",
    "AcceptanceTemplate",
    "AcceptanceTemplateRegistry",
    "AcceptanceTemplateStatus",
    "default_project_acceptance_templates_dir",
    "default_user_acceptance_templates_dir",
    "ensure_default_acceptance_template_dirs",
    "get_acceptance_template",
    "get_all_acceptance_templates",
    "initialize_acceptance_template_registry",
    "list_acceptance_templates",
    "load_acceptance_template_data",
    "load_acceptance_template_library",
    "load_acceptance_template_library_layered",
    "register_acceptance_template",
    "reset_acceptance_template_registry",
    "save_acceptance_template_library",
]
