"""Tolerant reader for :class:`ToolDependencyGraph`.

Corruption / version mismatch / missing fields never raise — the
runtime consumer (task guide, system prompt) prefers an empty
graph over a noisy stack trace.  A warning is logged instead.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .models import ToolDependencyGraph

logger = logging.getLogger(__name__)


def load_tool_dependencies(
    bundle_path: str | Path,
    *,
    filename: str = "tool-dependencies.yaml",
) -> ToolDependencyGraph | None:
    """Load ``tool-dependencies.yaml`` from ``bundle_path/.clawcodex/``.

    Returns ``None`` if the file does not exist.  Returns an empty
    graph (with a warning) if the file is corrupted or has an
    unsupported version.
    """
    base = Path(bundle_path)
    candidate = base / ".clawcodex" / filename
    if not candidate.exists():
        return None
    return load_graph_from_path(candidate)


def load_graph_from_path(path: str | Path) -> ToolDependencyGraph:
    """Load a graph from an explicit file path.

    Failures (parse error, IO error, unknown version) yield an
    empty :class:`ToolDependencyGraph` plus a warning.
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("tool-dependencies.yaml unreadable: %s", exc)
        return ToolDependencyGraph()
    return parse_graph_payload(text)


def parse_graph_payload(text: str) -> ToolDependencyGraph:
    """Parse the textual content of a tool-dependencies YAML file.

    Tries PyYAML first, then a hand-rolled reader for the small
    subset of YAML this project emits (top-level scalars, list of
    dicts, dict-of-dicts).  Returns an empty graph on any failure.
    """
    data = _safe_load(text)
    if data is None:
        logger.warning("tool-dependencies.yaml: empty or unparseable")
        return ToolDependencyGraph()
    if not isinstance(data, dict):
        logger.warning("tool-dependencies.yaml: top-level is not a mapping")
        return ToolDependencyGraph()
    return ToolDependencyGraph.from_dict(data)


def merge_overrides(
    graph: ToolDependencyGraph,
    override_path: str | Path,
) -> ToolDependencyGraph:
    """Load an override file and merge it into ``graph`` in place.

    Returns ``graph`` for chaining.  Missing override file is a
    no-op (no warning).  A corrupted override is logged and
    skipped.
    """
    p = Path(override_path)
    if not p.exists():
        return graph
    override = load_graph_from_path(p)
    graph.merge_overrides(override)
    return graph


def _safe_load(text: str) -> dict | list | None:
    """Parse YAML with PyYAML when available, else a minimal subset.

    The minimal subset is enough for the writer's output but is
    not a general-purpose YAML parser: it supports mappings, lists,
    scalars (str / int / float / bool / null), and ignores comments.
    """
    try:
        import yaml

        return yaml.safe_load(text)
    except ImportError:
        return _minimal_yaml_load(text)
    except Exception as exc:
        logger.warning("PyYAML parse failed: %s", exc)
        return _minimal_yaml_load(text)


def _minimal_yaml_load(text: str) -> dict | list | None:
    """Tiny indent-based YAML loader — just enough for the writer.

    Scope (deliberately limited):
    * block style mappings and sequences at column 0
    * one level of nesting (YAML is indented)
    * scalars: int / float / bool / null / str
    * comments (``# ...``) stripped from each line

    Not supported: flow style ({}, []), anchors, multi-line strings.
    """
    lines: list[tuple[int, str]] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        lines.append((indent, line.strip()))
    if not lines:
        return None
    root_indent = lines[0][0]
    return _parse_block(lines, 0, root_indent)[0]


def _parse_block(
    lines: list[tuple[int, str]], idx: int, parent_indent: int
) -> tuple[Any, int]:
    """Parse a block at indent ``parent_indent`` starting at ``lines[idx]``."""
    if idx >= len(lines):
        return None, idx
    indent, content = lines[idx]
    if indent != parent_indent:
        return None, idx
    if content.startswith("- "):
        return _parse_seq(lines, idx, parent_indent)
    return _parse_map(lines, idx, parent_indent)


def _parse_map(
    lines: list[tuple[int, str]], idx: int, parent_indent: int
) -> tuple[dict, int]:
    out: dict = {}
    while idx < len(lines):
        indent, content = lines[idx]
        if indent != parent_indent or content.startswith("- "):
            break
        if ":" not in content:
            idx += 1
            continue
        key, _, rest = content.partition(":")
        key = key.strip()
        rest = rest.strip()
        if not rest:
            # Nested block — peek the next line's indent
            nxt = idx + 1
            if nxt < len(lines) and lines[nxt][0] > parent_indent:
                child, new_idx = _parse_block(lines, nxt, lines[nxt][0])
                out[key] = child
                idx = new_idx
            else:
                out[key] = None
                idx += 1
        else:
            out[key] = _coerce(rest)
            idx += 1
    return out, idx


def _parse_seq(
    lines: list[tuple[int, str]], idx: int, parent_indent: int
) -> tuple[list, int]:
    out: list = []
    while idx < len(lines):
        indent, content = lines[idx]
        if indent != parent_indent or not content.startswith("- "):
            break
        rest = content[2:].strip()
        if not rest:
            # Nested block
            nxt = idx + 1
            if nxt < len(lines) and lines[nxt][0] > parent_indent:
                child, new_idx = _parse_block(lines, nxt, lines[nxt][0])
                out.append(child)
                idx = new_idx
            else:
                out.append(None)
                idx += 1
        elif rest.startswith("- "):
            # Inline sequence; treat as scalar for our subset
            out.append(_coerce(rest[2:].strip()))
            idx += 1
        else:
            # Possibly ``- key: value`` (start of an inline mapping)
            if ":" in rest and not rest.startswith("["):
                inline_map, new_idx = _parse_map(
                    [(indent, rest)] + lines[idx + 1 :], 0, indent
                )
                out.append(inline_map)
                idx += 1 + new_idx
            else:
                out.append(_coerce(rest))
                idx += 1
    return out, idx


def _coerce(s: str) -> Any:
    if not s:
        return ""
    low = s.lower()
    if low in ("null", "~", ""):
        return None
    if low == "true":
        return True
    if low == "false":
        return False
    # Remove surrounding quotes if any
    if (s.startswith('"') and s.endswith('"')) or (
        s.startswith("'") and s.endswith("'")
    ):
        return s[1:-1]
    # Int / float
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


__all__ = [
    "load_tool_dependencies",
    "load_graph_from_path",
    "parse_graph_payload",
    "merge_overrides",
]
