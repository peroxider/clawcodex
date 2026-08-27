"""Persistent solidification layer -- the event ledger is the single source of truth.

The ledger is the single source of truth; vectors, graphs, and documents are all
rebuildable projections. Maturity is mechanically replayed from the parent chain of the
current head; rollback only moves pointers and reconciles derived projections in a targeted way.
"""

from clawcodex_ext.latent_memory.server.lib.solidification.ledger import (
    AppendResult,
    CrystalLedger,
    LedgerError,
)
from clawcodex_ext.latent_memory.server.lib.solidification.document import (
    DocumentProjection,
    render_card,
)
from clawcodex_ext.latent_memory.server.lib.solidification.graph import GraphProjection
from clawcodex_ext.latent_memory.server.lib.solidification.models import (
    Edge,
    Head,
    Lineage,
    Revision,
    RevisionInput,
    new_batch_id,
    new_crystal_id,
)
from clawcodex_ext.latent_memory.server.lib.solidification.store import (
    CommitOutcome,
    SolidificationStore,
)
from clawcodex_ext.latent_memory.server.lib.solidification.projection import (
    VectorProjection,
    qdrant_point_id,
)

__all__ = [
    "AppendResult",
    "CommitOutcome",
    "CrystalLedger",
    "DocumentProjection",
    "Edge",
    "Head",
    "GraphProjection",
    "Lineage",
    "LedgerError",
    "Revision",
    "RevisionInput",
    "SolidificationStore",
    "VectorProjection",
    "new_batch_id",
    "new_crystal_id",
    "qdrant_point_id",
    "render_card",
]
