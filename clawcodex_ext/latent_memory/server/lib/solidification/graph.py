"""Head-aware SQLite graph projection and deterministic traversal."""

from __future__ import annotations

from typing import Any

from clawcodex_ext.latent_memory.server.lib.solidification.ledger import CrystalLedger


class GraphProjection:
    """Exposes the edge rows derived in the same transaction as each revision."""

    def __init__(self, ledger: CrystalLedger):
        self._ledger = ledger
        self._queries = 0
        self._rebuilds = 0
        self._last_error: str | None = None

    def start(self) -> None:
        # Edges are inserted in the same SQLite transaction as the revisions.
        return None

    def close(self) -> None:
        return None

    def notify(self, rev_id: int | None = None) -> None:
        if rev_id is not None:
            self._ledger.set_projection_through("graph", int(rev_id))

    def traverse(
        self,
        subject: str,
        *,
        max_depth: int = 2,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            edges = self._ledger.graph_traverse(subject, max_depth=max_depth, user_id=user_id)
            self._queries += 1
            self._last_error = None
            return {
                "subject": subject,
                "max_depth": max_depth,
                "user_id": user_id,
                "edges": edges,
                "total": len(edges),
            }
        except Exception as exc:
            self._last_error = str(exc)
            raise

    def conflicts(
        self,
        *,
        subject: str | None = None,
        predicate: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            conflicts = self._ledger.graph_conflicts(
                subject=subject, predicate=predicate, user_id=user_id
            )
            self._queries += 1
            self._last_error = None
            return {"conflicts": conflicts, "total": len(conflicts)}
        except Exception as exc:
            self._last_error = str(exc)
            raise

    def rebuild(self) -> dict[str, int]:
        result = self._ledger.rebuild_edges()
        self._rebuilds += 1
        self._last_error = None
        return result

    def state(self) -> dict[str, Any]:
        through = int(self._ledger.projection_state().get("graph", {}).get("through_rev", 0))
        return {
            "enabled": True,
            "through_rev": through,
            "lag": max(0, self._ledger.max_rev_id() - through),
            "queries": self._queries,
            "rebuilds": self._rebuilds,
            "last_error": self._last_error,
        }
