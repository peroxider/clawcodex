"""In-memory + on-disk template registry.

The :class:`TemplateRegistry` keeps a name -> :class:`Template` map that
the rest of the system reads from. It supports three discover modes:

* **In-memory only** (the default) — :meth:`register` / :meth:`unregister`
  / :meth:`get` / :meth:`list_templates` operate on a process-local dict.
* **Single-file persistence** — if a ``store_path`` is supplied,
  :meth:`save` and :meth:`load` use the atomic :class:`TemplateStateFile`
  helper to round-trip the entire registry as a single JSON document.
* **Directory scan** — if a ``search_dir`` is supplied, :meth:`discover`
  walks the directory recursively, parses every ``*.yml`` / ``*.yaml`` /
  ``*.json`` file as a single template, and registers them.

The three modes compose: a registry can be constructed with a
``store_path``, populated via :meth:`discover` from a ``search_dir``,
and persisted back via :meth:`save`.

The registry is thread-safe (uses an ``RLock``) so a CLI command and a
background discovery task can share it without races.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from .exceptions import (
    TemplateAlreadyExistsError,
    TemplateCorruptError,
    TemplateNotFoundError,
)
from .models import Template


def _safe_parse_yaml(path: Path) -> dict[str, Any]:
    """Parse a YAML file with safe_load; wrap errors as TemplateCorruptError."""
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised in env without PyYAML
        raise TemplateCorruptError(
            f"yaml parser unavailable, cannot read {path}"
        ) from exc
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # type: ignore[attr-defined]
        raise TemplateCorruptError(f"invalid YAML in {path}: {exc}") from exc
    except OSError as exc:
        raise TemplateCorruptError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise TemplateCorruptError(
            f"{path} did not parse as a mapping (got {type(data).__name__})"
        )
    return data


def _safe_parse_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TemplateCorruptError(f"invalid JSON in {path}: {exc}") from exc
    except OSError as exc:
        raise TemplateCorruptError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise TemplateCorruptError(
            f"{path} did not parse as a JSON object (got {type(data).__name__})"
        )
    return data


class TemplateRegistry:
    """Thread-safe in-memory registry of templates."""

    def __init__(
        self,
        *,
        store_path: Path | str | None = None,
        search_dir: Path | str | None = None,
    ) -> None:
        self._templates: dict[str, Template] = {}
        self._lock = threading.RLock()
        self._store_path: Path | None = (
            Path(store_path) if store_path is not None else None
        )
        self._search_dir: Path | None = (
            Path(search_dir) if search_dir is not None else None
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def store_path(self) -> Path | None:
        return self._store_path

    @property
    def search_dir(self) -> Path | None:
        return self._search_dir

    def __len__(self) -> int:
        with self._lock:
            return len(self._templates)

    def __contains__(self, template_id: str) -> bool:
        with self._lock:
            return template_id in self._templates

    def __iter__(self) -> Iterator[str]:
        with self._lock:
            return iter(list(self._templates.keys()))

    # ------------------------------------------------------------------
    # In-memory operations
    # ------------------------------------------------------------------

    def register(self, template: Template, *, overwrite: bool = False) -> None:
        if not isinstance(template, Template):
            raise TypeError("register() expects a Template instance")
        with self._lock:
            if template.id in self._templates and not overwrite:
                raise TemplateAlreadyExistsError(
                    f"template already registered: {template.id}"
                )
            self._templates[template.id] = template

    def register_many(
        self, templates: Iterable[Template], *, overwrite: bool = False
    ) -> int:
        added = 0
        for t in templates:
            try:
                self.register(t, overwrite=overwrite)
                added += 1
            except TemplateAlreadyExistsError:
                if not overwrite:
                    continue
                raise
        return added

    def unregister(self, template_id: str) -> None:
        with self._lock:
            if template_id not in self._templates:
                raise TemplateNotFoundError(
                    f"template not registered: {template_id}"
                )
            del self._templates[template_id]

    def get(self, template_id: str) -> Template:
        with self._lock:
            try:
                return self._templates[template_id]
            except KeyError as exc:
                raise TemplateNotFoundError(
                    f"template not registered: {template_id}"
                ) from exc

    def try_get(self, template_id: str) -> Template | None:
        with self._lock:
            return self._templates.get(template_id)

    def list_templates(
        self, *, source: str | None = None
    ) -> list[Template]:
        with self._lock:
            templates = list(self._templates.values())
        if source is not None:
            templates = [t for t in templates if t.source == source]
        # Stable order for deterministic CLI output and tests.
        templates.sort(key=lambda t: t.id)
        return templates

    def list_ids(self, *, source: str | None = None) -> list[str]:
        return [t.id for t in self.list_templates(source=source)]

    def clear(self) -> None:
        with self._lock:
            self._templates.clear()

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(
        self,
        *,
        source: str | None = None,
        pattern: str = "*",
        recursive: bool = True,
        overwrite: bool = False,
    ) -> int:
        """Walk ``self.search_dir`` and register every matching template.

        Returns the number of templates successfully registered. Files
        that fail to parse are silently skipped (but a corruption error
        is logged by raising :class:`TemplateCorruptError` when
        ``strict=True``; default is lenient so a single bad file does
        not abort discovery).
        """
        if self._search_dir is None:
            raise ValueError("registry has no search_dir configured")
        if not self._search_dir.is_dir():
            return 0
        added = 0
        for path in self._iter_candidate_paths(pattern, recursive):
            try:
                data = self._parse_path(path)
            except TemplateCorruptError:
                # Lenient: skip corrupt files. Strict callers can wrap
                # this method and re-raise from their own code.
                continue
            try:
                template = Template.from_dict(data)
            except (ValueError, TypeError):
                continue
            if source is not None:
                template = Template(
                    id=template.id,
                    title=template.title,
                    description=template.description,
                    fields=dict(template.fields),
                    metadata=dict(template.metadata),
                    source=source,
                )
            try:
                self.register(template, overwrite=overwrite)
                added += 1
            except TemplateAlreadyExistsError:
                continue
        return added

    def _iter_candidate_paths(
        self, pattern: str, recursive: bool
    ) -> Iterator[Path]:
        suffixes = (".yml", ".yaml", ".json")
        if recursive:
            for path in self._search_dir.rglob(pattern):  # type: ignore[arg-type]
                if path.is_file() and path.suffix.lower() in suffixes:
                    yield path
        else:
            for path in self._search_dir.glob(pattern):  # type: ignore[arg-type]
                if path.is_file() and path.suffix.lower() in suffixes:
                    yield path

    @staticmethod
    def _parse_path(path: Path) -> dict[str, Any]:
        if path.suffix.lower() in (".yml", ".yaml"):
            return _safe_parse_yaml(path)
        return _safe_parse_json(path)


__all__ = [
    "TemplateRegistry",
]