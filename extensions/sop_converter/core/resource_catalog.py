"""F-56 SOP Resource Catalog.

Persistent runtime resource handles for SOP-converted SDK tools.

The Agent-specific catalog remains the compatibility path for the existing
create-agent -> invoke-agent flow.  This module provides the generic F-56
record model and storage layer so future resource kinds (agent, session, team,
pipeline run, etc.) share the same persistence and error contract.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, Iterable

try:
    import fcntl
except Exception:  # pragma: no cover - not available on Windows
    fcntl = None

from .agent_catalog_resolver import HOME_ONLY_ENV, HOME_ROOT_ENV

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DEFAULT_HOME = Path.home() / ".clawcodex"
RESOURCE_CATALOG_FILENAME = "resource-catalog.json"

RESOURCE_CATALOG_MISSING = "resource_catalog_missing"
RESOURCE_CATALOG_AMBIGUOUS = "resource_catalog_ambiguous"
RESOURCE_PAYLOAD_INVALID = "resource_payload_invalid"
RESOURCE_MATERIALIZE_FAILED = "resource_materialize_failed"
RESOURCE_VERSION_UNSUPPORTED = "resource_version_unsupported"
RESOURCE_SECRET_MISSING = "resource_secret_missing"

_SENSITIVE_KEY_RE = re.compile(
    r"(api[_-]?key|access[_-]?token|token|secret|password|passwd|pwd)",
    re.IGNORECASE,
)
_REDACTION_PLACEHOLDER = "<redacted:env:{env_var}>"
_AGENT_REFERENCE_FIELDS = frozenset(
    {"name", "agent_name", "display_name", "alias", "aliases"}
)


class ResourceCatalogError(RuntimeError):
    """Catalog lookup failure with an F-56 machine-readable error code."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalise_resource_type(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())


def normalize_resource_type(value: str) -> str:
    """Return the canonical key used by catalogs and handler registries."""
    return _normalise_resource_type(value)


def _resource_key(resource_type: str, resource_id: str) -> str:
    return f"{_normalise_resource_type(resource_type)}:{str(resource_id).strip()}"


def _normalise_agent_reference(value: Any) -> str:
    return str(value or "").strip().casefold()


def _collect_agent_reference_names(value: Any) -> set[str]:
    """Extract explicit human-facing agent names from catalog payloads.

    This deliberately follows only name/alias fields. It avoids treating a
    model name, SDK class, or arbitrary string in a DSL as an agent reference.
    """
    names: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).casefold() in _AGENT_REFERENCE_FIELDS:
                if isinstance(child, str):
                    normalised = _normalise_agent_reference(child)
                    if normalised:
                        names.add(normalised)
                elif isinstance(child, (list, tuple, set)):
                    for item in child:
                        if isinstance(item, str):
                            normalised = _normalise_agent_reference(item)
                            if normalised:
                                names.add(normalised)
            elif isinstance(child, (dict, list, tuple)):
                names.update(_collect_agent_reference_names(child))
    elif isinstance(value, (list, tuple)):
        for item in value:
            names.update(_collect_agent_reference_names(item))
    return names


def _is_agent_record(record: ResourceRecord) -> bool:
    return "agent" in record.resource_type or isinstance(
        (record.payload or {}).get("agent_catalog_entry"), dict
    )


def _clawcodex_home() -> Path:
    raw = os.environ.get(HOME_ROOT_ENV, "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return DEFAULT_HOME.resolve()


def _is_home_only_forced() -> bool:
    raw = os.environ.get(HOME_ONLY_ENV, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _bundle_id_from_path(bundle: Path | str | None, bundle_id: str | None) -> str:
    if bundle_id and bundle_id.strip():
        return bundle_id.strip()
    if bundle is not None:
        return Path(bundle).expanduser().resolve().name
    return "default"


def _redact_value(key: str, value: Any, *, bundle_id: str | None) -> tuple[Any, str | None]:
    if not _SENSITIVE_KEY_RE.search(key):
        return value, None
    if isinstance(value, str) and value.startswith("env:"):
        return value, None
    bundle_prefix = re.sub(r"[^A-Z0-9]+", "_", (bundle_id or "BUNDLE").upper())
    field_suffix = re.sub(r"[^A-Z0-9]+", "_", key.upper())
    env_var = f"CLAWCODEX_{bundle_prefix}_{field_suffix}"
    return _REDACTION_PLACEHOLDER.format(env_var=env_var), env_var


def _redact_tree(value: Any, *, bundle_id: str | None, env_refs: list[str]) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, child in value.items():
            if isinstance(child, (dict, list)):
                out[key] = _redact_tree(child, bundle_id=bundle_id, env_refs=env_refs)
                continue
            redacted, env_var = _redact_value(str(key), child, bundle_id=bundle_id)
            out[key] = redacted
            if env_var:
                env_refs.append(env_var)
        return out
    if isinstance(value, list):
        return [_redact_tree(item, bundle_id=bundle_id, env_refs=env_refs) for item in value]
    return value


def _restore_tree(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _restore_tree(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_restore_tree(item) for item in value]
    if isinstance(value, str):
        match = re.match(r"^<redacted:env:([A-Z0-9_]+)>$", value)
        if match:
            env_var = match.group(1)
            return os.environ.get(env_var, value)
    return value


@dataclass(frozen=True)
class ResourceCatalogLocation:
    """Resolved catalog path and provenance."""

    path: Path
    reason: str
    writable: bool | None = None

    def ensure_parent(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class CatalogExecutionContext:
    """Canonical catalog identity shared by create and workflow read paths."""

    bundle_path: Path | None = None
    bundle_id: str = ""
    home_only: bool = False

    def __post_init__(self) -> None:
        bundle_path = self.bundle_path
        if bundle_path is not None:
            bundle_path = Path(bundle_path).expanduser().resolve()
            object.__setattr__(self, "bundle_path", bundle_path)
        bundle_id = str(self.bundle_id or "").strip()
        if not bundle_id and bundle_path is not None:
            bundle_id = bundle_path.name
        object.__setattr__(self, "bundle_id", bundle_id or "default")

@dataclass
class ResourceRecord:
    """Generic runtime resource row."""

    resource_type: str
    resource_id: str
    source_tool: str
    materializer: dict[str, Any]
    invoker: dict[str, Any]
    payload: dict[str, Any]
    bundle_id: str | None = None
    schema_version: int = SCHEMA_VERSION
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    sdk: dict[str, Any] = field(default_factory=dict)
    secrets: dict[str, Any] = field(default_factory=dict)
    status: str = "active"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.resource_type = _normalise_resource_type(self.resource_type)
        self.resource_id = str(self.resource_id)

    def key(self) -> str:
        return _resource_key(self.resource_type, self.resource_id)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResourceRecord:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class ResourceCatalog:
    """On-disk ResourceRecord index.

    Storage format::

        {
          "version": 1,
          "records": {"agent:<id>": {...ResourceRecord...}}
        }
    """

    _save_lock: ClassVar[threading.Lock] = threading.Lock()

    version: int = SCHEMA_VERSION
    records: dict[str, ResourceRecord] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> ResourceCatalog:
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning("resource-catalog: %s is invalid JSON (%s)", path, exc)
            return cls()
        if not isinstance(raw, dict):
            logger.warning("resource-catalog: %s top-level must be an object", path)
            return cls()
        version = raw.get("version", SCHEMA_VERSION)
        if version != SCHEMA_VERSION:
            raise ResourceCatalogError(
                RESOURCE_VERSION_UNSUPPORTED,
                f"resource catalog {path} version={version} is unsupported; "
                f"expected {SCHEMA_VERSION}",
            )
        records_raw = raw.get("records", {})
        if not isinstance(records_raw, dict):
            logger.warning("resource-catalog: %s records must be an object", path)
            return cls()
        records: dict[str, ResourceRecord] = {}
        for key, payload in records_raw.items():
            if not isinstance(payload, dict):
                logger.warning("resource-catalog: skipping non-dict record %r", key)
                continue
            try:
                record = ResourceRecord.from_dict(payload)
            except Exception as exc:
                logger.warning("resource-catalog: skipping bad record %r (%s)", key, exc)
                continue
            records[record.key()] = record
        return cls(version=SCHEMA_VERSION, records=records)

    def save(self, path: Path, *, merge: bool = True) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.parent / f".{path.name}.lock"
        lock_fd = open(lock_path, "a+")
        try:
            if fcntl is not None:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            else:
                self._save_lock.acquire()
            try:
                records = dict(self.records)
                if merge:
                    disk = self.load(path)
                    for key, record in disk.records.items():
                        if key not in records:
                            records[key] = record
                payload = {
                    "version": self.version,
                    "records": {
                        key: record.to_dict()
                        for key, record in sorted(records.items(), key=lambda item: item[0])
                    },
                }
                fd, tmp_path_str = tempfile.mkstemp(
                    prefix=f".{path.name}.",
                    suffix=".tmp",
                    dir=str(path.parent),
                )
                tmp_path = Path(tmp_path_str)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        json.dump(payload, f, indent=2, ensure_ascii=False)
                    os.replace(tmp_path, path)
                except Exception:
                    try:
                        tmp_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    raise
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                else:
                    self._save_lock.release()
        finally:
            lock_fd.close()

    def upsert(self, record: ResourceRecord) -> ResourceRecord:
        if not record.resource_type or not record.resource_id:
            raise ValueError("resource_type and resource_id are required")
        if record.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported resource schema_version={record.schema_version}")

        env_refs: list[str] = []
        existing = self.records.get(record.key())
        secrets = dict(record.secrets or {})
        existing_env_refs = []
        if existing and isinstance(existing.secrets, dict):
            existing_env_refs = list(existing.secrets.get("env_refs") or [])
        secrets["env_refs"] = sorted(
            set(existing_env_refs)
            | set(secrets.get("env_refs") or [])
            | set(env_refs)
        )

        metadata = dict(existing.metadata) if existing else {}
        metadata.update(record.metadata or {})
        redacted = ResourceRecord(
            resource_type=record.resource_type,
            resource_id=record.resource_id,
            bundle_id=record.bundle_id,
            source_tool=record.source_tool,
            materializer=_redact_tree(
                record.materializer or {},
                bundle_id=record.bundle_id,
                env_refs=env_refs,
            ),
            invoker=_redact_tree(
                record.invoker or {},
                bundle_id=record.bundle_id,
                env_refs=env_refs,
            ),
            payload=_redact_tree(
                record.payload or {},
                bundle_id=record.bundle_id,
                env_refs=env_refs,
            ),
            sdk=_redact_tree(record.sdk or {}, bundle_id=record.bundle_id, env_refs=env_refs),
            secrets=secrets,
            status=record.status or "active",
            schema_version=record.schema_version,
            created_at=existing.created_at if existing else record.created_at,
            updated_at=_now(),
            metadata=metadata,
        )
        if env_refs:
            redacted.secrets["env_refs"] = sorted(
                set(redacted.secrets.get("env_refs") or []) | set(env_refs)
            )
        self.records[redacted.key()] = redacted
        return redacted

    def get(self, resource_type: str, resource_id: str) -> ResourceRecord | None:
        record = self.records.get(_resource_key(resource_type, resource_id))
        if record is None:
            return None
        return ResourceRecord(
            resource_type=record.resource_type,
            resource_id=record.resource_id,
            bundle_id=record.bundle_id,
            source_tool=record.source_tool,
            materializer=_restore_tree(record.materializer),
            invoker=_restore_tree(record.invoker),
            payload=_restore_tree(record.payload),
            sdk=_restore_tree(record.sdk),
            secrets=dict(record.secrets),
            status=record.status,
            schema_version=record.schema_version,
            created_at=record.created_at,
            updated_at=record.updated_at,
            metadata=dict(record.metadata),
        )

    def find_by_resource_id(
        self,
        resource_id: str,
        *,
        resource_type: str | None = None,
    ) -> list[ResourceRecord]:
        target_type = _normalise_resource_type(resource_type or "")
        matches: list[ResourceRecord] = []
        for record in self.records.values():
            if str(record.resource_id) != str(resource_id):
                continue
            if target_type and record.resource_type != target_type:
                continue
            restored = self.get(record.resource_type, record.resource_id)
            if restored is not None:
                matches.append(restored)
        return sorted(matches, key=lambda item: item.created_at, reverse=True)

    def find_by_agent_reference(
        self,
        agent_ref: str,
        *,
        resource_type: str | None = None,
    ) -> list[ResourceRecord]:
        """Resolve an agent's stable ID or persisted human-facing name.

        Stable IDs retain the existing exact-match semantics.  A name or alias
        is resolved only from explicit catalog fields such as ``dsl.name`` and
        ``metadata.aliases``.  Callers must reject multiple name matches rather
        than guessing which saved agent a user meant.
        """
        reference = str(agent_ref or "").strip()
        if not reference:
            return []

        exact = self.find_by_resource_id(reference, resource_type=resource_type)
        if exact:
            return exact

        target_type = _normalise_resource_type(resource_type or "")
        target_name = _normalise_agent_reference(reference)
        matches: list[ResourceRecord] = []
        for record in self.records.values():
            if target_type and record.resource_type != target_type:
                continue
            if not _is_agent_record(record):
                continue
            if target_name not in _collect_agent_reference_names(
                {"payload": record.payload, "metadata": record.metadata}
            ):
                continue
            restored = self.get(record.resource_type, record.resource_id)
            if restored is not None:
                matches.append(restored)
        return sorted(matches, key=lambda item: item.created_at, reverse=True)


def resolve_resource_catalog_path(
    bundle: Path | str | None = None,
    *,
    bundle_id: str | None = None,
    session_id: str | None = None,
    scope: str | None = None,
    home_only: bool | None = None,
) -> ResourceCatalogLocation:
    """Resolve one F-56 catalog path.

    ``scope`` may be ``"bundle"``, ``"user"``, ``"session"``, or ``None``.
    With ``None`` we prefer bundle-local when a bundle is available, otherwise
    user-local.  ``CLAWCODEX_CATALOG_HOME_ONLY=1`` forces user-local.
    """
    if home_only is None:
        home_only = _is_home_only_forced()
    effective_bundle_id = _bundle_id_from_path(bundle, bundle_id)
    home = _clawcodex_home()

    if scope == "session":
        sid = (session_id or "default").strip() or "default"
        path = home / "sessions" / sid / "sop-resources.json"
        return ResourceCatalogLocation(path=path, reason="session-local", writable=_probe_writable(path))

    if scope == "user" or home_only or bundle is None:
        path = home / "sop-resources" / effective_bundle_id / "catalog.json"
        reason = "user-local" if scope == "user" else ("home-forced" if home_only else "no-bundle")
        return ResourceCatalogLocation(path=path, reason=reason, writable=_probe_writable(path))

    bundle_path = Path(bundle).expanduser().resolve()
    path = bundle_path / ".clawcodex" / RESOURCE_CATALOG_FILENAME
    return ResourceCatalogLocation(path=path, reason="bundle-local", writable=_probe_writable(path))


def iter_resource_catalog_locations(
    bundle: Path | str | None = None,
    *,
    bundle_id: str | None = None,
    session_id: str | None = None,
    home_only: bool | None = None,
) -> Iterable[ResourceCatalogLocation]:
    """Yield read locations in F-56 priority order."""
    # Normalise: empty string → None so that the "no bundle" path uses the
    # home-directory fallback rather than resolving against CWD.
    if isinstance(bundle, str) and not bundle.strip():
        bundle = None
    effective_home_only = _is_home_only_forced() or bool(home_only)
    if bundle is not None and not effective_home_only:
        yield resolve_resource_catalog_path(bundle, bundle_id=bundle_id, scope="bundle")
    yield resolve_resource_catalog_path(
        bundle,
        bundle_id=bundle_id,
        scope="user",
        home_only=effective_home_only,
    )
    if session_id:
        yield resolve_resource_catalog_path(
            bundle,
            bundle_id=bundle_id,
            session_id=session_id,
            scope="session",
        )


def get_resource_record(
    resource_ref: str,
    *,
    resource_type: str,
    bundle_path: str | Path | None = None,
    bundle_id: str = "",
    catalog_context: CatalogExecutionContext | None = None,
) -> ResourceRecord:
    """Load one registered F-56 resource without assuming Agent semantics.

    Generic resources resolve by their stable ID. The built-in Agent handler
    additionally supports persisted names and the legacy AgentCatalog.
    """
    from .resource_handlers import get_resource_handler, require_resource_handler

    handler = require_resource_handler(resource_type)
    normalized_type = _normalise_resource_type(resource_type)
    agent_family = handler.resource_type == "agent"
    reference = str(resource_ref or "").strip()
    if not reference:
        raise ResourceCatalogError(
            RESOURCE_CATALOG_MISSING,
            "resource_ref is required to load a resource catalog record",
        )

    if catalog_context is not None:
        bundle_path = catalog_context.bundle_path
        bundle_id = catalog_context.bundle_id
        home_only = catalog_context.home_only
    else:
        home_only = False
    if isinstance(bundle_path, str) and not bundle_path.strip():
        bundle_path = None

    checked: list[str] = []
    for location in iter_resource_catalog_locations(
        bundle_path,
        bundle_id=bundle_id or None,
        home_only=home_only,
    ):
        checked.append(str(location.path))
        if not location.path.exists():
            continue
        catalog = ResourceCatalog.load(location.path)
        exact_type = (
            None
            if agent_family and normalized_type in {"agent", "agentconfig"}
            else resource_type
        )
        matches = catalog.find_by_resource_id(reference, resource_type=exact_type)
        if agent_family and not matches:
            matches = catalog.find_by_agent_reference(
                reference,
                resource_type=exact_type,
            )
        matches = [
            record
            for record in matches
            if get_resource_handler(record.resource_type) is handler
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            ids = ", ".join(record.resource_id for record in matches)
            raise ResourceCatalogError(
                RESOURCE_CATALOG_AMBIGUOUS,
                f"resource reference {reference!r} matches multiple records: {ids}",
            )

    try:
        if not agent_family:
            raise LookupError("legacy catalog is Agent-only")
        from .agent_catalog import AgentCatalog
        from .agent_catalog_resolver import resolve_catalog_path

        location = resolve_catalog_path(bundle_path)
        checked.append(str(location.path))
        if location.path.exists():
            legacy_catalog = AgentCatalog.load(location.path)
            entry = legacy_catalog.get(reference)
            if entry is not None:
                return agent_entry_to_resource_record(entry)
            target_name = _normalise_agent_reference(reference)
            entries = [
                candidate
                for candidate_id in legacy_catalog.list_ids()
                if (candidate := legacy_catalog.get(candidate_id)) is not None
                and target_name
                in _collect_agent_reference_names(
                    {"dsl": candidate.dsl, "metadata": candidate.metadata}
                )
            ]
            if len(entries) == 1:
                return agent_entry_to_resource_record(entries[0])
            if len(entries) > 1:
                ids = ", ".join(entry.agent_id for entry in entries)
                raise ResourceCatalogError(
                    RESOURCE_CATALOG_AMBIGUOUS,
                    f"resource reference {reference!r} matches multiple records: {ids}",
                )
    except ResourceCatalogError:
        raise
    except Exception:
        # The structured F-56 failure below is more useful than a secondary
        # compatibility-path exception.
        pass

    raise ResourceCatalogError(
        RESOURCE_CATALOG_MISSING,
        f"resource reference {reference!r} was not found; checked: {', '.join(checked)}",
    )


def get_agent_record(
    agent_id: str = "",
    *,
    agent_ref: str = "",
    bundle_path: str | Path | None = None,
    bundle_id: str = "",
    catalog_context: CatalogExecutionContext | None = None,
    resource_type: str = "",
) -> ResourceRecord:
    """Compatibility alias for the built-in Agent resource handler."""
    return get_resource_record(
        str(agent_ref or agent_id or ""),
        resource_type=resource_type or "agent",
        bundle_path=bundle_path,
        bundle_id=bundle_id,
        catalog_context=catalog_context,
    )


def _probe_writable(path: Path) -> bool | None:
    parent = path.parent
    if not parent.exists():
        return None
    return os.access(parent, os.W_OK)


def resource_error(
    code: str,
    message: str,
    *,
    resource_type: str = "",
    resource_id: str = "",
    retryable: bool = False,
    recovery: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "error",
        "error_code": code,
        "message": message,
        "retryable": retryable,
    }
    if resource_type:
        payload["resource_type"] = _normalise_resource_type(resource_type)
    if resource_id:
        payload["resource_id"] = str(resource_id)
    if recovery:
        payload["recovery"] = recovery
    payload.update(extra)
    return payload


def agent_entry_to_resource_record(
    entry: Any,
    *,
    bundle_id: str | None = None,
    source_tool: str | None = None,
) -> ResourceRecord:
    """Convert an AgentCatalogEntry-like object to a generic ResourceRecord."""
    metadata = dict(getattr(entry, "metadata", {}) or {})
    resource_type = getattr(entry, "resource_type", "") or "agent"
    handle_field = getattr(entry, "handle_field", "") or "agent_id"
    sdk_source_dir = str(getattr(entry, "sdk_source_dir", "") or "")
    agent_id = str(getattr(entry, "agent_id", "") or "")
    init_kwargs = dict(getattr(entry, "init_kwargs", {}) or {})
    entry_dict = entry.to_dict() if hasattr(entry, "to_dict") else dict(metadata)
    factory = metadata.get("factory") if isinstance(metadata.get("factory"), dict) else {}
    materializer = {
        "kind": "python_function" if factory else "python_class",
        "module": str(factory.get("module") or getattr(entry, "module_name", "") or ""),
        "init_kwargs": init_kwargs,
    }
    if factory:
        materializer["name"] = str(factory.get("name") or "")
    else:
        materializer["class_name"] = str(getattr(entry, "class_name", "") or "")
    return ResourceRecord(
        resource_type=resource_type,
        resource_id=agent_id,
        bundle_id=bundle_id,
        source_tool=source_tool or str(metadata.get("source_tool") or ""),
        materializer=materializer,
        invoker={
            "kind": "python_method",
            "method": str(getattr(entry, "invoke_method", "") or "invoke"),
            "input_param": str(getattr(entry, "query_arg", "") or "query"),
        },
        payload={
            "kind": "inline",
            "handle_field": handle_field,
            "dsl": dict(getattr(entry, "dsl", {}) or {}),
            "model": str(getattr(entry, "model", "") or ""),
            "provider": str(getattr(entry, "provider", "") or ""),
            "init_kwargs": init_kwargs,
            "agent_catalog_entry": entry_dict,
        },
        sdk={
            "source_dir": sdk_source_dir,
            "version": str(getattr(entry, "sdk_version", "") or ""),
        },
        secrets={
            "policy": "env_refs_only",
            "env_refs": list(metadata.get("env_vars") or []),
        },
        metadata=metadata,
    )


__all__ = [
    "RESOURCE_CATALOG_MISSING",
    "RESOURCE_CATALOG_AMBIGUOUS",
    "RESOURCE_MATERIALIZE_FAILED",
    "RESOURCE_PAYLOAD_INVALID",
    "RESOURCE_SECRET_MISSING",
    "RESOURCE_VERSION_UNSUPPORTED",
    "SCHEMA_VERSION",
    "CatalogExecutionContext",
    "ResourceCatalog",
    "ResourceCatalogError",
    "ResourceCatalogLocation",
    "ResourceRecord",
    "agent_entry_to_resource_record",
    "get_agent_record",
    "get_resource_record",
    "iter_resource_catalog_locations",
    "normalize_resource_type",
    "resolve_resource_catalog_path",
    "resource_error",
]
