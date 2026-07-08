"""Atomic YAML writer for :class:`ToolDependencyGraph`.

Falls back to a hand-rolled emitter (so the converter does not hard
require PyYAML) — the structure is shallow enough that a manual
serialiser stays readable.  Header comment documents provenance.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from .models import ToolDependencyGraph

logger = logging.getLogger(__name__)


def _ensure_yaml_available() -> bool:
    try:
        import yaml  # noqa: F401

        return True
    except ImportError:
        return False


def _yaml_dump(data: dict[str, Any]) -> str:
    try:
        import yaml

        return yaml.safe_dump(
            data, allow_unicode=True, sort_keys=False, default_flow_style=False
        )
    except ImportError:
        return json.dumps(data, indent=2, ensure_ascii=False)


def _atomic_write_text(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically (tmp + ``os.replace``).

    Falls back to a direct write if the filesystem doesn't support
    ``os.replace`` (e.g. some cross-volume scenarios).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd, tmp = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError as exc:  # pragma: no cover — defensive
        logger.warning("atomic write failed for %s (%s); falling back", path, exc)
        path.write_text(content, encoding="utf-8")


def write_tool_dependencies(
    graph: ToolDependencyGraph,
    path: str | Path,
    *,
    project_name: str = "",
) -> Path:
    """Persist ``graph`` to ``path`` as ``tool-dependencies.yaml``.

    Args:
        graph: The graph to write.
        path: Destination file path.
        project_name: Optional project label added to the header comment.

    Returns:
        The path that was written.
    """
    out = Path(path)
    header = (
        "# tool-dependencies.yaml — SOP bundle 工具生命周期依赖\n"
        "# 自动生成: extensions/sop_converter/dependency\n"
    )
    if project_name:
        header += f"# project: {project_name}\n"
    body = _yaml_dump(graph.to_dict())
    _atomic_write_text(out, header + "\n" + body)
    return out


__all__ = ["write_tool_dependencies"]
