"""Mace4 finite countermodel adapter."""

from __future__ import annotations

from typing import Any

from .base import ExternalAtpSolverAdapter, parse_mace4_interpretation


class Mace4SolverAdapter(ExternalAtpSolverAdapter):
    engine_name = 'atp-mace4'
    binary_name = 'mace4'

    def _counterexample(self, stdout: str, stderr: str, violated_rule: str) -> dict[str, Any]:
        countermodel: dict[str, Any] = parse_mace4_interpretation(stdout)
        countermodel['violatedRule'] = violated_rule
        if stderr:
            countermodel['stderr'] = stderr[:2048]
        return countermodel
