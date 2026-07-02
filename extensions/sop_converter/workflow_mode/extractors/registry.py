"""Extractor registry (F-50.11.2)."""

from __future__ import annotations

import logging
from pathlib import Path

from ..discriminator import _detect_adapter_name
from ..scan_context import SourceScanContext
from .adapters.arc import ArcExtractor
from .adapters.generic import GenericPipelineExtractor
from .base import WorkflowExtractorBase

logger = logging.getLogger(__name__)

_PROJECT_ADAPTERS: dict[str, type[WorkflowExtractorBase]] = {
    "arc": ArcExtractor,
}


class ExtractorRegistry:
    @staticmethod
    def get_extractor(
        source_dir: Path,
        *,
        name: str | None = None,
        scan: SourceScanContext | None = None,
        mode: str = "fwa",
        allow_coarse: bool = False,
    ) -> WorkflowExtractorBase:
        resolved = name or _detect_adapter_name(source_dir)
        cls = _PROJECT_ADAPTERS.get(resolved, GenericPipelineExtractor)
        return cls(scan=scan, mode=mode, allow_coarse=allow_coarse)

    @staticmethod
    def register_adapter(project_name: str, extractor_cls: type[WorkflowExtractorBase]) -> None:
        _PROJECT_ADAPTERS[project_name] = extractor_cls

    @staticmethod
    def available_adapters() -> list[str]:
        return list(_PROJECT_ADAPTERS.keys())
