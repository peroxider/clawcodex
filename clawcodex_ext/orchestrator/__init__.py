"""Downstream extensions for the orchestrator layer.

These patches live here per the project's decoupling mandate: behaviour that
modifies ``extensions/orchestrator/`` runtime behaviour must be implemented
in ``clawcodex_ext/`` via monkey-patch, registry, or hook — never by editing
``extensions/`` source files.

Currently houses:

- :func:`install_stale_registry_patch` — keeps the daemon's in-memory
  ``IssueRegistry`` in sync with the on-disk JSON so that operator actions
  (e.g. ``clawcodex-dev orchestrator issue retry``) written via a separate
  CLI process become visible to the running daemon without a restart.
"""

from __future__ import annotations

from ._patch_stale_registry import install_stale_registry_patch

__all__ = ["install_stale_registry_patch"]
