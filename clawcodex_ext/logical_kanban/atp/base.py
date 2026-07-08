"""Shared helpers for optional external ATP subprocess adapters."""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, ClassVar

from ..solver_adapter import (
    AtpTptpSolverAdapter,
    SolverAdapter,
    SolverRequest,
    SolverResponse,
    SolverResult,
)
from ..solver_atp import build_tptp_program
from ..solver_limits import SolverLimitError, SolverResourceLimits, run_external_solver

_SZS_RE = re.compile(r"^\s*%?\s*SZS\s+status\s+([A-Za-z_][A-Za-z0-9_]*)\b", re.MULTILINE)
_PROOF_RE = re.compile(
    r"%\s*SZS\s+output\s+start\b(?P<body>.*?)%\s*SZS\s+output\s+end\b",
    re.IGNORECASE | re.DOTALL,
)
_INTERPRETATION_RE = re.compile(
    r"%?\s*Interpretation\s*:?(?P<body>.*?)(?:\n\s*end_of_list\.|\Z)",
    re.IGNORECASE | re.DOTALL,
)


def parse_szs_status(stdout: str) -> SolverResult:
    """Map a standard SZS status line into the LKB solver result enum."""
    match = _SZS_RE.search(stdout or "")
    token = match.group(1) if match else "Unknown"
    if token == "Theorem":
        return "pass"
    if token in {"CounterSatisfiable", "Satisfiable"}:
        return "fail"
    if token in {"Timeout", "ResourceOut"}:
        return "timeout"
    if token in {"Error", "Unknown"}:
        return "error"
    return "unknown"


def parse_mace4_interpretation(stdout: str) -> dict[str, Any]:
    """Parse a Mace4 portable interpretation block into a countermodel."""
    text = stdout or ""
    match = _INTERPRETATION_RE.search(text)
    body = match.group("body") if match else text
    assignments: dict[str, Any] = {}
    tasks: dict[str, dict[str, Any]] = {}

    for raw_line in body.splitlines():
        line = raw_line.strip().strip("%").strip()
        if not line or line.startswith("%"):
            continue
        task_match = re.match(
            r"([A-Za-z_][A-Za-z0-9_]*)\(([^)]*)\)\s*(?:=|:)\s*(true|false|0|1)\s*\.?$",
            line,
            re.IGNORECASE,
        )
        if task_match:
            predicate, args_raw, value_raw = task_match.groups()
            args = tuple(arg.strip().strip('"') for arg in args_raw.split(",") if arg.strip())
            value = value_raw.lower() in {"true", "1"}
            key = f"{predicate}({', '.join(args)})"
            assignments[key] = value
            if args:
                tasks.setdefault(args[0], {})[predicate] = value
            continue
        kv_match = re.match(r"([^=:\s]+)\s*(?:=|:)\s*(.+?)\s*\.?$", line)
        if kv_match:
            assignments[kv_match.group(1)] = kv_match.group(2).strip()

    return {
        "kind": "mace4-portable-interpretation",
        "assignments": assignments,
        "tasks": tasks,
        "raw": body.strip(),
    }


def _extract_proof(stdout: str) -> tuple[str, ...]:
    match = _PROOF_RE.search(stdout or "")
    if not match:
        return ()
    return tuple(line.strip() for line in match.group("body").splitlines() if line.strip())


class ExternalAtpSolverAdapter(SolverAdapter):
    """Base class for Vampire, Prover9 and Mace4 subprocess adapters."""

    engine_name: ClassVar[str]
    binary_name: ClassVar[str]
    version_args: ClassVar[tuple[str, ...]] = ("--version",)
    default_args: ClassVar[tuple[str, ...]] = ()
    _availability_cache: ClassVar[dict[str, bool]] = {}
    _version_cache: ClassVar[dict[str, str]] = {}

    def __init__(self, *, binary: str | None = None) -> None:
        self.binary = binary or self.binary_name
        self._last_tptp_program: str | None = None

    @property
    def name(self) -> str:
        return self.engine_name

    @property
    def version(self) -> str:
        if not self.available():
            return "unavailable"
        cache_key = self.binary
        cached = self._version_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            _code, stdout, stderr = run_external_solver(
                [self.binary, *self.version_args],
                limits=SolverResourceLimits(
                    timeout_seconds=5, max_memory_mb=64, max_output_bytes=4096
                ),
            )
            version = (stdout or stderr or "unknown").strip().splitlines()[0]
        except Exception as exc:  # pragma: no cover - availability already probed
            version = f"unavailable ({type(exc).__name__})"
        self._version_cache[cache_key] = version
        return version

    def available(self) -> bool:
        cache_key = self.binary
        cached = self._availability_cache.get(cache_key)
        if cached is not None:
            return cached
        if shutil.which(self.binary) is None:
            self._availability_cache[cache_key] = False
            return False
        try:
            run_external_solver(
                [self.binary, *self.version_args],
                limits=SolverResourceLimits(
                    timeout_seconds=5, max_memory_mb=64, max_output_bytes=4096
                ),
            )
            available = True
        except Exception:
            available = False
        self._availability_cache[cache_key] = available
        return available

    def last_tptp_program(self) -> str | None:
        return self._last_tptp_program

    def solve(
        self,
        request: SolverRequest,
        *,
        timeout_seconds: float = 30.0,
    ) -> SolverResponse:
        if not self.available():
            return SolverResponse(
                result="unknown",
                message=f"{self.name} binary is not installed.",
                error_info={"reason": "engine_unavailable", "binary": self.binary},
            )
        try:
            return self._solve_impl(request, timeout_seconds=timeout_seconds)
        except Exception as exc:  # noqa: BLE001
            return SolverResponse(
                result="error",
                message=f"{self.name} raised {type(exc).__name__}: {exc}",
                error_info={
                    "reason": "exception",
                    "exception": type(exc).__name__,
                    "detail": str(exc),
                },
            )

    def _solve_impl(self, request: SolverRequest, *, timeout_seconds: float) -> SolverResponse:
        program = build_tptp_program(request.snapshot, request)
        self._last_tptp_program = program
        limits = SolverResourceLimits(
            timeout_seconds=timeout_seconds,
            max_memory_mb=512,
            max_output_bytes=65536,
        )

        with tempfile.TemporaryDirectory(prefix=f"lkb-{self.name}-") as tmpdir:
            program_path = Path(tmpdir) / "problem.p"
            program_path.write_text(program, encoding="utf-8")
            try:
                returncode, stdout, stderr = run_external_solver(
                    [self.binary, *self.default_args, str(program_path)],
                    limits=limits,
                )
            except SolverLimitError as exc:
                if exc.reason == "timeout":
                    return SolverResponse(
                        result="timeout",
                        message=f"{self.name} exceeded the {timeout_seconds}s timeout.",
                        error_info={"reason": "timeout", "timeout_seconds": timeout_seconds},
                    )
                return SolverResponse(
                    result="unknown",
                    message=f"{self.name} resource limit hit: {exc.reason}.",
                    error_info={"reason": exc.reason},
                )

        result = parse_szs_status(stdout)
        if result == "pass":
            proof_lines = _extract_proof(stdout)
            return SolverResponse(
                result="pass",
                derived_facts=tuple(sorted(set(request.snapshot.facts))),
                proof_trace=(
                    {
                        "rule": "ATP-THEOREM",
                        "premises": list(proof_lines) or ["SZS status Theorem"],
                        "conclusion": f"{self.name} proved the proposal conjecture.",
                        "solverVersion": self.version,
                        "solverSyntax": "tptp-fof",
                    },
                ),
                message=f"{self.name} returned SZS Theorem.",
            )
        if result == "fail":
            violated, message, premises = AtpTptpSolverAdapter._classify_unsat(request)
            counterexample = self._counterexample(stdout, stderr, violated)
            return SolverResponse(
                result="fail",
                violated_rule=violated,
                message=message,
                proof_trace=(
                    {
                        "rule": violated,
                        "premises": list(premises),
                        "conclusion": f"{self.name} returned a countermodel status.",
                        "solverVersion": self.version,
                        "solverSyntax": "tptp-fof",
                    },
                ),
                counterexample=counterexample,
            )
        if result == "timeout":
            return SolverResponse(
                result="timeout",
                message=f"{self.name} reported SZS timeout/resource exhaustion.",
                error_info={"reason": "szs_timeout"},
            )
        if returncode != 0:
            return SolverResponse(
                result="error",
                message=f"{self.name} exited with code {returncode}.",
                error_info={"reason": "nonzero_exit", "stderr": stderr[:2048]},
            )
        return SolverResponse(
            result=result,
            message=f"{self.name} returned an inconclusive SZS status.",
            error_info={"reason": "szs_inconclusive", "stdout": stdout[:2048]},
        )

    def _counterexample(self, stdout: str, stderr: str, violated_rule: str) -> dict[str, Any]:
        return {
            "kind": "szs-countermodel",
            "violatedRule": violated_rule,
            "stdout": stdout[:8192],
            "stderr": stderr[:2048],
        }
