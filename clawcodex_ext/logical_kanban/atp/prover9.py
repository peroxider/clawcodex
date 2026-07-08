"""Prover9 LADR-2026 ATP adapter."""

from __future__ import annotations

from .base import ExternalAtpSolverAdapter


class Prover9SolverAdapter(ExternalAtpSolverAdapter):
    engine_name = "atp-prover9"
    binary_name = "prover9"
