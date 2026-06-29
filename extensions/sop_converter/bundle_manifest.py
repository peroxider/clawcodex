"""Persist and load POS bundle metadata (SDK source root, etc.)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BUNDLE_MANIFEST_NAME = "bundle.json"
_MANIFEST_VERSION = 1


@dataclass(frozen=True)
class BundleManifest:
    """On-disk metadata for a pos-convert bundle."""

    bundle_id: str
    sdk_source_dir: Path
    version: int = _MANIFEST_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "bundle_id": self.bundle_id,
            "sdk_source_dir": str(self.sdk_source_dir.resolve()),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BundleManifest | None:
        raw_dir = data.get("sdk_source_dir")
        if not isinstance(raw_dir, str) or not raw_dir.strip():
            return None
        bundle_id = data.get("bundle_id")
        if not isinstance(bundle_id, str) or not bundle_id.strip():
            bundle_id = "unknown"
        try:
            sdk_path = Path(raw_dir).expanduser().resolve()
        except OSError:
            return None
        if not sdk_path.is_dir():
            logger.debug("bundle manifest sdk_source_dir is not a directory: %s", sdk_path)
            return None
        version = data.get("version", _MANIFEST_VERSION)
        if not isinstance(version, int):
            version = _MANIFEST_VERSION
        return cls(bundle_id=bundle_id, sdk_source_dir=sdk_path, version=version)


def manifest_path_for_bundle(bundle_path: Path) -> Path:
    return bundle_path.resolve() / BUNDLE_MANIFEST_NAME


def write_bundle_manifest(
    bundle_dir: Path,
    *,
    sdk_source_dir: Path | str,
    bundle_id: str | None = None,
) -> Path:
    """Write ``bundle.json`` under *bundle_dir* (created if missing)."""
    bundle_dir = bundle_dir.resolve()
    bundle_dir.mkdir(parents=True, exist_ok=True)
    resolved_sdk = Path(sdk_source_dir).expanduser().resolve()
    manifest = BundleManifest(
        bundle_id=bundle_id or bundle_dir.name,
        sdk_source_dir=resolved_sdk,
    )
    path = manifest_path_for_bundle(bundle_dir)
    path.write_text(json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    logger.info("Wrote bundle manifest: %s (sdk_source_dir=%s)", path, resolved_sdk)
    return path


def read_bundle_manifest(bundle_path: Path) -> BundleManifest | None:
    """Load manifest from *bundle_path* if ``bundle.json`` exists."""
    path = manifest_path_for_bundle(bundle_path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read bundle manifest %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        return None
    return BundleManifest.from_dict(data)


def resolve_sdk_source_dir(
    bundle_path: Path,
    *,
    workspace_root: Path | None = None,
) -> Path | None:
    """Resolve SDK source root from bundle dir or workspace ``.clawcodex/<name>/``."""
    bundle_path = bundle_path.resolve()
    manifest = read_bundle_manifest(bundle_path)
    if manifest is not None:
        return manifest.sdk_source_dir

    if workspace_root is not None:
        ws = workspace_root.resolve()
        alt = ws / ".clawcodex" / bundle_path.name
        if alt != bundle_path:
            manifest = read_bundle_manifest(alt)
            if manifest is not None:
                return manifest.sdk_source_dir

    return None
