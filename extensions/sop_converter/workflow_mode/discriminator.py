"""F-50-A workflow mode discriminator."""

from __future__ import annotations

import logging
from pathlib import Path

from .heuristics import ALL_RULES
from .models import DiscriminationResult, HeuristicMatch, THRESHOLD_FWA, THRESHOLD_SDK
from .scan_context import SourceScanContext

logger = logging.getLogger(__name__)


def _detect_adapter_name(source_dir: Path) -> str:
    name_lower = source_dir.name.lower()
    if "autoresearch" in name_lower or "arc" in name_lower:
        return "arc"
    if (source_dir / ".arc-workflow").is_file():
        return "arc"
    pyproject = source_dir / "pyproject.toml"
    if pyproject.is_file():
        try:
            text = pyproject.read_text(encoding="utf-8").lower()
            if "autoresearch" in text:
                return "arc"
        except OSError:
            pass
    return "generic"


def _fwa_qualified(matches: list[HeuristicMatch]) -> bool:
    matched = {m.name for m in matches if m.matched}
    if "stage_enum" in matched and "state_transition" in matched:
        return True
    if "stage_enum" in matched and "gate_definition" in matched:
        return True
    return False


class WorkflowDiscriminator:
    def __init__(self, source_dir: str | Path, *, scan: SourceScanContext | None = None) -> None:
        self._source_dir = Path(source_dir)
        self._scan = scan
        self._result: DiscriminationResult | None = None

    def discriminate(self, *, force_mode: str | None = None) -> DiscriminationResult:
        if self._result is not None and force_mode is None:
            return self._result

        if force_mode and force_mode not in ("auto", ""):
            mode = force_mode if force_mode in ("sdk", "hybrid", "fwa") else "sdk"
            self._result = DiscriminationResult(
                source_dir=str(self._source_dir),
                total_score=0.0,
                matches=[],
                mode=mode,
                forced=True,
                recommended_extractor=_detect_adapter_name(self._source_dir),
            )
            return self._result

        scan = self._scan or SourceScanContext.build(self._source_dir)
        matches: list[HeuristicMatch] = []
        enum_names: set[str] = set()

        for rule in ALL_RULES:
            if rule.name == "state_transition":
                m = rule.check(scan, enum_names=enum_names or scan.enum_member_names)
            else:
                m = rule.check(scan)
            if rule.name == "stage_enum" and m.matched:
                enum_names = scan.enum_member_names
            matches.append(m)

        total = sum(m.score for m in matches)
        matched_count = sum(1 for m in matches if m.matched)
        confidence = matched_count / len(matches) if matches else 0.0
        qualified = _fwa_qualified(matches)

        if total >= THRESHOLD_FWA and qualified:
            mode = "fwa"
        elif total >= THRESHOLD_SDK:
            mode = "hybrid"
        else:
            mode = "sdk"

        self._result = DiscriminationResult(
            source_dir=str(self._source_dir),
            total_score=total,
            matches=matches,
            mode=mode,
            forced=False,
            confidence=confidence,
            recommended_extractor=_detect_adapter_name(self._source_dir),
            scan=scan,
            fwa_qualified=qualified,
        )
        return self._result
