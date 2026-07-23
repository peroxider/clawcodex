"""Atomic persist of MacroDefinition into bundle ``.clawcodex/macros/``."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from .errors import MacroConvertError
from .models import MacroDefinition, MacroRoute


def _require_yaml():
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise MacroConvertError(
            "macro_yaml_unavailable",
            "PyYAML is required to persist macro manifests",
        ) from exc
    return yaml


def macros_dir(bundle_dir: Path) -> Path:
    return Path(bundle_dir) / ".clawcodex" / "macros"


def macro_relative_manifest(name: str) -> str:
    return f".clawcodex/macros/{name}.yaml"


def macro_definition_to_dict(macro: MacroDefinition) -> dict[str, Any]:
    route = macro.routing
    return {
        "version": macro.version,
        "name": macro.name,
        "description": macro.description,
        "scope": macro.scope,
        "enabled": macro.enabled,
        "workflow": macro.workflow,
        "routing": {
            "phrases": list(route.phrases),
            "keywords": list(route.keywords),
            "negative_keywords": list(route.negative_keywords),
            "target_tool": route.target_tool or macro.name,
            "match_mode": route.match_mode,
            "selection": route.selection,
            "priority": route.priority,
            "verified": route.verified,
            "enabled": route.enabled,
            "intent_key": route.intent_key,
            "covered_tools": list(route.covered_tools),
            "unavailable_policy": route.unavailable_policy,
            "scope": route.scope,
        },
        "provenance": dict(macro.provenance),
    }


def write_macro_yaml(path: Path, macro: MacroDefinition) -> None:
    yaml = _require_yaml()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = macro_definition_to_dict(macro)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.stem}.",
        suffix=".yaml.tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def persist_macros_atomic(
    macros: list[MacroDefinition],
    bundle_dir: Path,
) -> list[Path]:
    """Write all macros or leave no partial files from this batch."""
    target_dir = macros_dir(bundle_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    try:
        for macro in macros:
            path = target_dir / f"{macro.name}.yaml"
            write_macro_yaml(path, macro)
            written.append(path)
            macro.provenance["manifest"] = macro_relative_manifest(macro.name)
        return written
    except Exception as exc:
        for path in written:
            try:
                path.unlink()
            except OSError:
                pass
        raise MacroConvertError(
            "macro_persist_failed",
            f"atomic macro persist failed: {exc}",
            manifest=str(bundle_dir),
        ) from exc
