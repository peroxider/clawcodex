"""Vampire ATP adapter."""

from __future__ import annotations

from .base import ExternalAtpSolverAdapter


class VampireSolverAdapter(ExternalAtpSolverAdapter):
    engine_name = 'atp-vampire'
    binary_name = 'vampire'
