"""Catalog path resolution — L1.

Decides where to read/write the agent catalog based on:

* the active bundle (if any) — preferred location is
  ``<bundle>/.clawcodex/agent-catalog.json`` so the catalog travels with the
  bundle and is reproducible from a fresh checkout.
* a forced ``$CLAWCODEX_HOME`` fallback (set by the
  ``CLAWCODEX_CATALOG_HOME_ONLY=1`` env var) — useful for cross-session /
  cross-machine recovery when bundle-local storage is on a read-only mount.
* the bundle id (or env-supplied default) — used as the leaf name in the
  home directory fallback.

The resolver is intentionally *non-creative*: callers receive a
:class:`CatalogLocation` with both the path and the *reason* it was chosen
so error messages and debug logs can be precise.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from extensions.sop_converter.bundle_context import BundleContext

logger = logging.getLogger(__name__)


HOME_ROOT_ENV = "CLAWCODEX_HOME"
HOME_ONLY_ENV = "CLAWCODEX_CATALOG_HOME_ONLY"
DEFAULT_HOME = Path.home() / ".clawcodex"


@dataclass(frozen=True)
class CatalogLocation:
    """Resolved catalog path + provenance.

    Attributes:
        path: Absolute path where the catalog lives (or should live). The
            parent directory is **not** created automatically; callers should
            call :meth:`ensure_parent` or :meth:`mkdir` on demand.
        reason: Short string explaining why this path was chosen. Used in
            error messages and logs ("bundle-local", "home-fallback",
            "home-forced", "no-bundle").
        writable: Best-effort hint about whether the location is writable.
            ``None`` means "not checked yet"; ``True``/``False`` reflect a
            probe.
    """

    path: Path
    reason: str
    writable: bool | None = None

    def ensure_parent(self) -> None:
        """Create the parent directory if missing (idempotent)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)


def _clawcodex_home() -> Path:
    """Resolve ``$CLAWCODEX_HOME`` (defaulting to ``~/.clawcodex``)."""
    raw = os.environ.get(HOME_ROOT_ENV, "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return DEFAULT_HOME.resolve()


def _is_home_only_forced() -> bool:
    raw = os.environ.get(HOME_ONLY_ENV, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _home_fallback_path(bundle_id: str | None) -> Path:
    leaf = (bundle_id or "default").strip() or "default"
    return _clawcodex_home() / "sop-agents" / leaf / "agents.json"


def resolve_catalog_path(
    bundle: "BundleContext | Path | str | None" = None,
    *,
    bundle_id: str | None = None,
    home_only: bool | None = None,
) -> CatalogLocation:
    """Decide where the agent catalog should be persisted.

    Args:
        bundle: Either a :class:`BundleContext`, a :class:`Path` to the bundle
            directory, a string path, or ``None`` (no bundle known).
        bundle_id: Optional explicit bundle id; overrides whatever the bundle
            reports. Used when the caller has the id but not the bundle
            context (e.g. wrapper subprocess at invoke time).
        home_only: Optional override for the home-only switch. ``True``
            forces the home fallback, ``False`` prefers bundle-local,
            ``None`` reads :data:`HOME_ONLY_ENV`.

    Returns:
        :class:`CatalogLocation` with the chosen path, a reason tag, and a
        best-effort writable hint.
    """
    if home_only is None:
        home_only = _is_home_only_forced()

    bundle_path: Path | None = None
    resolved_bundle_id: str | None = bundle_id

    # Normalise: empty string → None so that the "no bundle" path uses the
    # home-directory fallback rather than resolving against CWD.
    if isinstance(bundle, str) and not bundle.strip():
        bundle = None

    if bundle is not None:
        if isinstance(bundle, (str, Path)):
            bundle_path = Path(bundle).expanduser().resolve()
            if resolved_bundle_id is None:
                resolved_bundle_id = bundle_path.name
        else:  # BundleContext
            bundle_path = Path(bundle.bundle_path).expanduser().resolve()
            if resolved_bundle_id is None:
                resolved_bundle_id = bundle.bundle_name

    if home_only or bundle_path is None:
        path = _home_fallback_path(resolved_bundle_id)
        reason = "home-forced" if home_only else "no-bundle"
        return CatalogLocation(path=path, reason=reason, writable=_probe_writable(path))

    path = bundle_path / ".clawcodex" / "agent-catalog.json"
    return CatalogLocation(path=path, reason="bundle-local", writable=_probe_writable(path))


def _probe_writable(path: Path) -> bool | None:
    """Best-effort writable probe: ``False`` on permission errors, else ``True``.

    Returns ``None`` if the parent directory does not yet exist and the
    caller hasn't asked us to create it — we don't want a read-only probe
    to fail spuriously.
    """
    parent = path.parent
    if not parent.exists():
        return None
    return os.access(parent, os.W_OK)


__all__ = [
    "CatalogLocation",
    "HOME_ROOT_ENV",
    "HOME_ONLY_ENV",
    "resolve_catalog_path",
]
