"""Source registry for SR-5.1 Community Feature Radar.

Implements the ``SourceRegistry`` sketched in FEATURE_PLAN.md §10.1.5.
The registry owns the set of :class:`WatchSource` records the radar
tracks, persists them as YAML, and ships with a sensible default set
derived from the Phase-1 project list.

Design decisions:
* Pure stdlib (``json`` + optional ``yaml``). ``PyYAML`` is already a
  required dep of ClawCodex, so we use it for ergonomic round-trips,
  but fall back to JSON if the import fails (e.g. on a slim CI image).
* ``with_defaults()`` is the factory used by the CLI when no
  ``sources.yaml`` exists yet. The default list mirrors the Phase-1
  table in FEATURE_PLAN.md §10.1.2.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Iterable

from .models import WatchSource

_log = logging.getLogger(__name__)


# Default sources — keep in sync with FEATURE_PLAN.md §10.1.2.
DEFAULT_SOURCES: list[dict[str, Any]] = [
    {
        "name": "claude-code",
        "repo": "anthropics/claude-code",
        "track_releases": True,
        "changelog_path": "CHANGELOG.md",
        "notes": "上游源，核心对齐目标",
        "roadmap_keywords": ["agent", "tool", "permission", "memory", "compact"],
    },
    {
        "name": "aider",
        "repo": "paul-gauthier/aider",
        "track_releases": True,
        "release_tag_filter": r"\d+\.\d+\.\d+",
        "notes": "Python 生态最活跃的编码 Agent",
        "roadmap_keywords": ["lint", "edit", "commit", "test", "refactor"],
    },
    {
        "name": "swe-agent",
        "repo": "princeton-nlp/SWE-agent",
        "track_releases": True,
        "notes": "自动修复 GitHub issue 的标杆项目",
        "roadmap_keywords": ["issue", "patch", "test", "verify"],
    },
    {
        "name": "openhands",
        "repo": "All-Hands-AI/OpenHands",
        "track_releases": True,
        "notes": "通用 AI 软件工程 Agent",
        "roadmap_keywords": ["workspace", "agent", "sandbox", "browser"],
    },
    {
        "name": "autogen",
        "repo": "microsoft/autogen",
        "track_releases": True,
        "notes": "多 Agent 对话框架",
        "roadmap_keywords": ["multi-agent", "conversation", "group", "router"],
    },
    {
        "name": "crewai",
        "repo": "crewAIInc/crewAI",
        "track_releases": True,
        "notes": "多 Agent 编排框架",
        "roadmap_keywords": ["crew", "role", "task", "process"],
    },
    {
        "name": "langgraph",
        "repo": "langchain-ai/langgraph",
        "track_releases": True,
        "notes": "Agent 图状工作流引擎",
        "roadmap_keywords": ["graph", "state", "node", "edge", "workflow"],
    },
]


def _load_yaml_or_json(path: Path) -> Any:
    """Load a YAML or JSON document; YAML is preferred when present."""
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError:
            _log.warning(
                "PyYAML not available; cannot parse %s as YAML — aborting load",
                path,
            )
            raise
        return yaml.safe_load(text)
    return json.loads(text)


def _dump_yaml_or_json(data: Any, path: Path) -> None:
    """Persist ``data`` as YAML or JSON based on suffix."""
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError:
            _log.warning("PyYAML not available; falling back to JSON for %s", path)
            json_path = path.with_suffix(".json")
            json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            return
        path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


class SourceRegistry:
    """Manage :class:`WatchSource` records persisted on disk.

    The registry is intentionally simple: a name→WatchSource dict backed
    by a single YAML file. ``load()`` returns the populated dict for
    fluent chaining.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._sources: dict[str, WatchSource] = {}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> dict[str, WatchSource]:
        """Load sources from ``self.path``.

        Returns the populated dict. If the file is missing, the registry
        stays empty; callers should use :meth:`with_defaults` or
        :meth:`add` to populate it.
        """
        self._sources = {}
        if not self.path.exists():
            return self._sources
        try:
            raw = _load_yaml_or_json(self.path)
        except Exception as exc:  # noqa: BLE001 — user-data, surface in CLI
            _log.warning("failed to read %s: %s", self.path, exc)
            return self._sources

        items: Iterable[dict[str, Any]]
        if isinstance(raw, dict) and isinstance(raw.get("sources"), list):
            items = raw["sources"]
        elif isinstance(raw, list):
            items = raw
        else:
            _log.warning("unexpected sources file shape in %s; expected list", self.path)
            return self._sources

        for item in items:
            try:
                src = WatchSource.from_dict(item)
            except ValueError as exc:
                _log.warning("skipping invalid source entry %r: %s", item, exc)
                continue
            self._sources[src.name] = src
        return self._sources

    def save(self) -> None:
        """Persist the registry to ``self.path``.

        Creates parent directories on demand. Writes ``{"sources": [...]}``
        for YAML and a bare list for JSON, matching what :meth:`load`
        accepts.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        items = [src.to_dict() for src in self._sources.values()]
        suffix = self.path.suffix.lower()
        if suffix in {".yaml", ".yml"}:
            payload: Any = {"sources": items}
        else:
            payload = items
        _dump_yaml_or_json(payload, self.path)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add(self, source: WatchSource) -> None:
        """Insert or replace a source by name."""
        self._sources[source.name] = source

    def remove(self, name: str) -> bool:
        """Remove a source by name. Returns True when present."""
        return self._sources.pop(name, None) is not None

    def get(self, name: str) -> WatchSource | None:
        return self._sources.get(name)

    def list(self) -> list[WatchSource]:
        return list(self._sources.values())

    def names(self) -> list[str]:
        return list(self._sources.keys())

    def __len__(self) -> int:
        return len(self._sources)

    def __contains__(self, name: str) -> bool:
        return name in self._sources

    # ------------------------------------------------------------------
    # Defaults
    # ------------------------------------------------------------------

    @classmethod
    def with_defaults(
        cls,
        path: Path | str | None = None,
        *,
        extras: Iterable[WatchSource] | None = None,
    ) -> "SourceRegistry":
        """Build a registry pre-populated with the Phase-1 default sources.

        ``extras`` lets callers layer local sources on top without
        overriding the defaults. ``path`` is optional; passing it lets
        the same registry be saved later without rewiring.
        """
        reg = cls(path if path is not None else Path("sources.yaml"))
        for item in DEFAULT_SOURCES:
            try:
                reg.add(WatchSource.from_dict(item))
            except ValueError as exc:
                _log.warning("default source rejected: %s", exc)
        for extra in extras or ():
            reg.add(extra)
        return reg


# ---------------------------------------------------------------------------
# Convenience: locate the user config directory
# ---------------------------------------------------------------------------


def default_registry_path() -> Path:
    """Return ``~/.clawcodex/community-radar/sources.yaml``.

    Honours ``$CLAWCODEX_HOME`` when set (matches the convention used
    elsewhere in ClawCodex so tests and containers can override it).
    """
    base = os.environ.get("CLAWCODEX_HOME")
    root = Path(base) if base else Path.home() / ".clawcodex"
    return root / "community-radar" / "sources.yaml"