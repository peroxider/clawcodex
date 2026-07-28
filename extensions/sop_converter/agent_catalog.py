"""AgentCatalog — **archival** on-disk format (no longer used by runtime).

.. deprecated::
    F-56 Phase D removed all runtime read/write of ``agent-catalog.json``.
    Canonical persistence is :mod:`extensions.sop_converter.resource_catalog`.
    This module remains only for unit tests of the historical format and
    optional offline migration helpers.

Historical storage locations (no longer consulted by ``get_resource_record``):

* ``<bundle>/.clawcodex/agent-catalog.json``
* ``$CLAWCODEX_HOME/sop-agents/<bundle_id>/agents.json``
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
from typing import Any, ClassVar

try:
    import fcntl
except Exception:  # pragma: no cover — not available on Windows
    fcntl = None

logger = logging.getLogger(__name__)


# Keys (case-insensitive) we redact from DSL/config snapshots before writing.
_SENSITIVE_KEY_RE = re.compile(
    r"(api[_-]?key|access[_-]?token|token|secret|password|passwd|pwd)",
    re.IGNORECASE,
)
_REDACTION_PLACEHOLDER = "<redacted:env:{env_var}>"


@dataclass
class AgentCatalogEntry:
    """One catalog row: agent_id → enough metadata to re-materialize the Agent.

    Attributes:
        agent_id: Stable identifier returned by the create tool. Primary key.
        sdk_source_dir: Absolute path to the SDK source root (the directory
            injected into ``sys.path`` by the wrapper script).
        dsl: Re-creatable Agent DSL/config snapshot. Sensitive values are
            redacted in :func:`AgentCatalog.upsert` before write; restored in
            :func:`_restore_dsl` at materialize time.
        model: Model name (e.g. ``"gpt-4o"``). Persisted as plain text; not
            treated as sensitive.
        provider: Provider name (e.g. ``"openai"``). Persisted as plain text.
        class_name: Python class name of the materialized Agent (e.g.
            ``"LLMAgent"``). Combined with ``module_name`` to do
            ``importlib.import_module(module_name); getattr(module, class_name)``.
        module_name: Dotted module path of the class above.
        init_kwargs: Constructor kwargs (other than the class's positional
            args). Sensitive values are redacted on write and restored at
            materialize time.
        query_arg: Name of the parameter that accepts the user query/inputs
            on the Agent's ``invoke()`` / ``run()`` method. Defaults to
            ``"query"``. Allows the invoke-existing-agent wrapper to forward
            the user query to the right kwarg.
        invoke_method: Name of the method on the materialized Agent that
            accepts the query (e.g. ``"invoke"`` or ``"run"``). Defaults to
            ``"invoke"``; ``invoke-existing-agent`` tries ``invoke`` first
            and falls back to ``run``.
        created_at: ISO-8601 timestamp of first write.
        schema_version: Catalog row format version. Bump on incompatible
            changes; consumers must refuse to materialize rows with unknown
            versions.
        sdk_version: Free-form SDK version string (e.g. ``"openjiuwen 0.4.2"``)
            for diagnostics. Not validated — informational.
        metadata: User-defined metadata (search tags, intent labels, source
            tool name, etc.). ``upsert`` merges new metadata into existing
            entries on retry.
        resource_type: §8 type-contract field. Normalized resource type this
            entry produces (e.g. ``"agentconfig"``). Empty for legacy entries;
            enables :meth:`AgentCatalog.latest_by_resource_type` lookups so
            invoke-kind tools can recover an agent without knowing the
            ``agent_id`` ahead of time — they only need the resource type
            their parameter annotation declares.
        handle_field: §8 type-contract field. Name of the field in the
            create-tool's return value that carries the stable handle
            (typically ``"agent_id"``). Recorded at create time so the
            fallback path knows which key to read from the catalog payload
            without guessing by parameter name.
    """

    agent_id: str
    sdk_source_dir: str
    dsl: dict[str, Any] = field(default_factory=dict)
    model: str = ""
    provider: str = ""
    class_name: str = ""
    module_name: str = ""
    init_kwargs: dict[str, Any] = field(default_factory=dict)
    query_arg: str = "query"
    invoke_method: str = "invoke"
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    schema_version: int = 1
    sdk_version: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    # §8 type-contract fields (default empty for backward compatibility).
    resource_type: str = ""
    handle_field: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentCatalogEntry:
        """Build an entry from a dict, ignoring unknown keys for forward compat."""
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


def _redact_value(key: str, value: Any, *, bundle_id: str | None) -> tuple[Any, str | None]:
    """Return a redacted copy of *value* if *key* is sensitive, else (value, None).

    The second element is the env-var name to restore the value at materialize
    time, or ``None`` if no redaction was applied.
    """
    if not _SENSITIVE_KEY_RE.search(key):
        return value, None
    if isinstance(value, str) and value.startswith("env:"):
        # Already a reference — leave it alone
        return value, None
    bundle_prefix = re.sub(r"[^A-Z0-9]+", "_", (bundle_id or "BUNDLE").upper())
    field_suffix = re.sub(r"[^A-Z0-9]+", "_", key.upper())
    env_var = f"CLAWCODEX_{bundle_prefix}_{field_suffix}"
    return _REDACTION_PLACEHOLDER.format(env_var=env_var), env_var


def _redact_dsl(
    dsl: dict[str, Any], *, bundle_id: str | None, env_vars: list[str]
) -> dict[str, Any]:
    """Recursively redact sensitive values in *dsl*; record env-var names."""

    def _walk(node: Any) -> Any:
        if isinstance(node, dict):
            out: dict[str, Any] = {}
            for k, v in node.items():
                if isinstance(v, (dict, list)):
                    out[k] = _walk(v)
                    continue
                redacted, env_var = _redact_value(k, v, bundle_id=bundle_id)
                out[k] = redacted
                if env_var is not None:
                    env_vars.append(env_var)
            return out
        if isinstance(node, list):
            return [_walk(item) for item in node]
        return node

    return _walk(dsl)


def _restore_dsl(dsl: dict[str, Any]) -> dict[str, Any]:
    """Restore redacted placeholders by reading from the environment."""

    def _walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: _walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_walk(item) for item in node]
        if isinstance(node, str):
            match = re.match(r"^<redacted:env:([A-Z0-9_]+)>$", node)
            if match:
                env_var = match.group(1)
                return os.environ.get(env_var, node)
        return node

    return _walk(dsl)


@dataclass
class AgentCatalog:
    """On-disk agent_id → AgentCatalogEntry index.

    Storage format (one JSON file, atomic write)::

        {
          "version": 1,
          "entries": {<agent_id>: {...AgentCatalogEntry.to_dict()...}, ...}
        }

    ``save()`` uses a unique temp file + ``os.replace`` and a path-level
    file lock (``fcntl`` on Unix) so concurrent writers from different
    wrapper subprocesses cannot corrupt the file.  It also merges with the
    latest on-disk state by default, making ``load → upsert → save`` cycles
    safe for concurrent create-only workflows.
    """

    _save_lock: ClassVar[threading.Lock] = threading.Lock()

    version: int = 1
    entries: dict[str, AgentCatalogEntry] = field(default_factory=dict)
    _removed_ids: set[str] = field(default_factory=set, repr=False)

    # -- persistence ---------------------------------------------------------

    @classmethod
    def load(cls, path: Path) -> AgentCatalog:
        """Load a catalog from *path*.

        Behaviour:

        * missing file → empty catalog (NOT an error; first-run case).
        * JSON decode error → empty catalog + warning (don't crash on
          partially-written or hand-edited files).
        * unknown version → empty catalog + warning.
        """
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning(
                "agent-catalog: %s is not valid JSON (%s); treating as empty",
                path,
                exc,
            )
            return cls()
        if not isinstance(raw, dict):
            logger.warning(
                "agent-catalog: %s top-level must be an object; treating as empty",
                path,
            )
            return cls()
        version = raw.get("version", 1)
        if version != 1:
            logger.warning(
                "agent-catalog: %s version=%s not supported by this build; "
                "treating as empty (will not overwrite on save)",
                path,
                version,
            )
            return cls(version=version)
        entries_raw = raw.get("entries", {})
        entries: dict[str, AgentCatalogEntry] = {}
        for agent_id, payload in entries_raw.items():
            if not isinstance(payload, dict):
                logger.warning(
                    "agent-catalog: skipping non-dict entry %r in %s",
                    agent_id,
                    path,
                )
                continue
            entries[agent_id] = AgentCatalogEntry.from_dict(payload)
        return cls(version=1, entries=entries)

    def save(self, path: Path, *, merge: bool = True) -> None:
        """Atomically persist the catalog to *path*.

        Uses a unique temp file (via :func:`tempfile.mkstemp`) and
        ``os.replace``, plus a path-level file lock (``fcntl`` on Unix) so
        concurrent writers from different wrapper subprocesses cannot
        corrupt the file.

        When *merge* is ``True`` (the default), entries already present on
        disk are retained and only overwritten by entries in this catalog.
        This makes concurrent ``load → upsert → save`` cycles safe for
        create-only workflows.  Pass ``merge=False`` after explicit
        deletions to avoid resurrecting removed entries.
        """
        path.parent.mkdir(parents=True, exist_ok=True)

        lock_path = path.parent / f".{path.name}.lock"
        lock_fd = open(lock_path, "a+")
        try:
            if fcntl is not None:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            else:
                self._save_lock.acquire()
            try:
                entries: dict[str, AgentCatalogEntry] = dict(self.entries)
                if merge:
                    disk = self.load(path)
                    for agent_id, entry in disk.entries.items():
                        if agent_id not in entries and agent_id not in self._removed_ids:
                            entries[agent_id] = entry
                payload = {
                    "version": self.version,
                    "entries": {
                        aid: entry.to_dict() for aid, entry in entries.items()
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

    # -- mutation ------------------------------------------------------------

    def upsert(
        self,
        entry: AgentCatalogEntry,
        *,
        bundle_id: str | None = None,
    ) -> AgentCatalogEntry:
        """Insert or merge *entry* by ``agent_id``.

        .. deprecated::
            Prefer writing :class:`~extensions.sop_converter.resource_catalog.ResourceRecord`
            via :func:`~extensions.sop_converter.resource_catalog.build_resource_record_from_create`.
            This method remains for archival unit tests of the legacy format.

        Behaviour:

        * Re-applying the same ``agent_id`` is **idempotent**: ``metadata`` is
          merged (new keys win), the entry is otherwise overwritten. This is
          the "same agent, more metadata" retry case.
        * DSL is redacted before insertion; the redacted entry is returned.
        * If the existing entry has a *different* ``schema_version`` and the
          caller is asking for the same id, the new entry wins (assumes the
          SDK was upgraded and the old entry is stale). We do not raise.
        """
        import warnings

        warnings.warn(
            "AgentCatalog.upsert is deprecated archival API; runtime uses "
            "ResourceCatalog (resource-catalog.json) only.",
            DeprecationWarning,
            stacklevel=2,
        )
        env_vars: list[str] = []
        redacted_dsl = _redact_dsl(entry.dsl, bundle_id=bundle_id, env_vars=env_vars)
        redacted_init = _redact_dsl(
            entry.init_kwargs, bundle_id=bundle_id, env_vars=env_vars
        )

        existing = self.entries.get(entry.agent_id)
        merged_meta = dict(existing.metadata) if existing else {}
        merged_meta.update(entry.metadata)
        if env_vars and "env_vars" not in merged_meta:
            merged_meta["env_vars"] = sorted(set(env_vars))

        new_entry = AgentCatalogEntry(
            agent_id=entry.agent_id,
            sdk_source_dir=entry.sdk_source_dir,
            dsl=redacted_dsl,
            model=entry.model,
            provider=entry.provider,
            class_name=entry.class_name,
            module_name=entry.module_name,
            init_kwargs=redacted_init,
            query_arg=entry.query_arg or "query",
            invoke_method=entry.invoke_method or "invoke",
            created_at=existing.created_at if existing else entry.created_at,
            schema_version=entry.schema_version,
            sdk_version=entry.sdk_version,
            metadata=merged_meta,
            resource_type=entry.resource_type,
            handle_field=entry.handle_field,
        )
        self.entries[entry.agent_id] = new_entry
        self._removed_ids.discard(entry.agent_id)
        return new_entry

    def get(self, agent_id: str) -> AgentCatalogEntry | None:
        """Look up an entry; on hit, restore redacted fields from env first."""
        entry = self.entries.get(agent_id)
        if entry is None:
            return None
        return AgentCatalogEntry(
            agent_id=entry.agent_id,
            sdk_source_dir=entry.sdk_source_dir,
            dsl=_restore_dsl(entry.dsl),
            model=entry.model,
            provider=entry.provider,
            class_name=entry.class_name,
            module_name=entry.module_name,
            init_kwargs=_restore_dsl(entry.init_kwargs),
            query_arg=entry.query_arg,
            invoke_method=entry.invoke_method,
            created_at=entry.created_at,
            schema_version=entry.schema_version,
            sdk_version=entry.sdk_version,
            metadata=dict(entry.metadata),
            resource_type=entry.resource_type,
            handle_field=entry.handle_field,
        )

    def latest_by_resource_type(self, resource_type: str) -> AgentCatalogEntry | None:
        """§8 type-contract lookup: return the most recently created entry
        whose ``resource_type`` matches.

        Matches are case-insensitive on the normalized type token.  When
        multiple entries share the same ``resource_type``, the one with the
        newest ``created_at`` wins.  Returns ``None`` when no entry matches
        or when *resource_type* is empty.
        """
        if not resource_type:
            return None
        target = resource_type.lower()
        best: AgentCatalogEntry | None = None
        for entry in self.entries.values():
            if (entry.resource_type or "").lower() != target:
                continue
            if best is None or entry.created_at > best.created_at:
                best = entry
        if best is None:
            return None
        # Restore redacted fields via get() for consistency.
        return self.get(best.agent_id)

    def delete(self, agent_id: str) -> bool:
        removed = self.entries.pop(agent_id, None) is not None
        if removed:
            self._removed_ids.add(agent_id)
        return removed

    def list_ids(self) -> list[str]:
        return sorted(self.entries.keys())


__all__ = [
    "AgentCatalogEntry",
    "AgentCatalog",
]
