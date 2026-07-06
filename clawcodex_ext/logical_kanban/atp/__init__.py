"""External ATP adapters for Logical Kanban F-142."""

from __future__ import annotations

from .base import (
    ExternalAtpSolverAdapter,
    parse_mace4_interpretation,
    parse_szs_status,
)
from .mace4 import Mace4SolverAdapter
from .prover9 import Prover9SolverAdapter
from .vampire import VampireSolverAdapter

__all__ = [
    'ExternalAtpSolverAdapter',
    'Mace4SolverAdapter',
    'Prover9SolverAdapter',
    'VampireSolverAdapter',
    'parse_mace4_interpretation',
    'parse_szs_status',
]
