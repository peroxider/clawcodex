"""End-to-end pipeline orchestrator for SR-5.1.

Glues :class:`SourceRegistry`, :class:`Fetcher`, :class:`FeatureExtractor`,
:class:`FeatureClassifier`, :class:`FeatureDeduplicator`,
:class:`FeatureScorer`, and :class:`CommunityReporter` into a single
``run_scan()`` call. CLI / Cron call this — they never touch the
individual modules directly.

Pipeline stages:

    registry → fetcher → extractor → classifier → dedup → scorer →
    reporter → dual-write

Every stage is failure-isolated: an exception in one source does not
abort the scan. Errors are captured in :attr:`CommunityDigest.errors`
so the digest always renders (with a "抓取错误" section).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .classifier import FeatureClassifier
from .config import RadarConfig
from .cron_integration import ensure_cron_installed
from .deduplicator import FeatureDeduplicator
from .extractor import FeatureExtractor
from .fetcher import Fetcher
from .models import (
    CommunityDigest,
    FeatureRecord,
    ScoredFeature,
    WatchSource,
)
from .notifier import DigestNotifier
from .registry import SourceRegistry
from .reporter import CommunityReporter, DigestWriteResult, copy_to_persistent
from .scorer import FeatureScorer

_log = logging.getLogger(__name__)


@dataclass
class ScanResult:
    digest: CommunityDigest
    write_result: DigestWriteResult | None
    records: list[FeatureRecord]
    notifications: dict[str, bool] | None = None
    cron_status: dict[str, Any] | None = None


class CommunityRadarPipeline:
    """High-level entrypoint used by the CLI and the Cron trigger."""

    def __init__(
        self,
        *,
        config: RadarConfig | None = None,
        registry: SourceRegistry | None = None,
        fetcher: Fetcher | None = None,
        extractor: FeatureExtractor | None = None,
        classifier: FeatureClassifier | None = None,
        deduplicator: FeatureDeduplicator | None = None,
        scorer: FeatureScorer | None = None,
        reporter: CommunityReporter | None = None,
        notifier: DigestNotifier | None = None,
        ensure_cron: bool = True,
    ) -> None:
        self.config = config or RadarConfig()
        self.registry = registry
        self.extractor = extractor or FeatureExtractor()

        # Build source_name → domain map from the registry so the
        # classifier can reject cross-domain keyword matches.
        _domain_map: dict[str, str] = {}
        if self.registry is not None:
            for source in self.registry.list():
                if source.domain:
                    _domain_map[source.name] = source.domain
        if classifier is not None:
            self.classifier = classifier
        else:
            self.classifier = FeatureClassifier(
                roadmap_keywords=self.config.roadmap_keywords,
                source_domain_map=_domain_map,
            )
        self.deduplicator = deduplicator or FeatureDeduplicator()
        self.scorer = scorer or FeatureScorer(self.config)
        self.reporter = reporter or CommunityReporter(self.config)
        self.notifier = notifier or DigestNotifier(self.config)
        self._ensure_cron = ensure_cron
        self._owns_fetcher = fetcher is None
        self.fetcher = fetcher

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_scan(
        self,
        *,
        sources: Iterable[WatchSource] | None = None,
        period: str = "weekly",
        write: bool = True,
        output_dir: Path | str | None = None,
        persistent_copy: bool = True,
        notify: bool | None = None,
        auto_install_cron: bool | None = None,
        compare: bool = False,
        incremental: bool = False,
    ) -> ScanResult:
        """Run the full pipeline and (optionally) persist a digest.

        ``sources`` overrides the registry when supplied; callers that
        already pre-loaded their own list of :class:`WatchSource`
        records can skip the registry entirely.

        ``notify`` and ``auto_install_cron`` override the corresponding
        ``RadarConfig`` flags for this call only. ``None`` means
        "inherit from config".
        """
        sources = list(sources) if sources is not None else self._load_sources()
        if not sources:
            _log.warning("community radar scan: no sources configured")

        # Auto-detect domains for sources still marked "general" so the
        # classifier's domain-blocking logic can work correctly.
        if self.registry is not None:
            import os as _os

            token = _os.environ.get("GITHUB_TOKEN")
            detected = self.registry.auto_detect_domains(self.config.cache_dir, github_token=token)
            if detected:
                _log.info("auto-detected domain for %d source(s)", detected)
                sources = self._load_sources()

        cron_status: dict[str, Any] | None = None
        if auto_install_cron is None:
            auto_install_cron = self._ensure_cron
        if auto_install_cron:
            try:
                summary = ensure_cron_installed()
                cron_status = {
                    "task_id": summary.task_id,
                    "installed": summary.installed,
                    "schedule": summary.schedule,
                    "message": summary.message,
                }
            except Exception as exc:  # noqa: BLE001
                _log.warning("ensure_cron_installed failed: %s", exc)
                cron_status = {"error": str(exc)}

        notify_flag = self.config.notify if notify is None else bool(notify)
        notifications: dict[str, bool] | None = None

        try:
            fetch_results = self._fetch_all(sources, incremental=incremental)
            records = self._extract(fetch_results)
            records = self.classifier.classify_many(records)
            records = self.deduplicator.deduplicate(records)
            scored = [
                ScoredFeature(record=record, score=self.scorer.score(record)) for record in records
            ]
            versions_total = sum(len(fr.releases) for fr in fetch_results)
            errors: list[str] = []
            for fr in fetch_results:
                errors.extend(f"[{fr.source}] {msg}" for msg in fr.errors)

            digest = self.reporter.build_digest(
                period=period,
                features=records,
                scored=scored,
                sources_used=[s.name for s in sources],
                errors=errors,
                versions_total=versions_total,
            )

            write_result: DigestWriteResult | None = None
            if write:
                target_dir = Path(output_dir or self.config.output_dir)
                write_result = self.reporter.write(digest, target_dir, compare=compare)
                if persistent_copy:
                    copy_to_persistent(write_result.markdown_path)
                    copy_to_persistent(write_result.json_path)
                    if write_result.proposals_path is not None:
                        copy_to_persistent(write_result.proposals_path)

            if notify_flag and write_result is not None:
                try:
                    notifications = self.notifier.broadcast(digest, write_result)
                except Exception as exc:  # noqa: BLE001
                    _log.warning("notification broadcast failed: %s", exc)
                    notifications = {"error": str(exc)}  # type: ignore[assignment]
        finally:
            # Always close an owned fetcher so HTTP clients don't leak
            # even when the pipeline short-circuits on empty input.
            if self._owns_fetcher and self.fetcher is not None:
                self.fetcher.close()

        return ScanResult(
            digest=digest,
            write_result=write_result,
            records=records,
            notifications=notifications,
            cron_status=cron_status,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _load_sources(self) -> list[WatchSource]:
        if self.registry is None:
            _log.debug("no registry configured; returning empty source list")
            return []
        if not self.registry._sources:  # type: ignore[attr-defined]
            try:
                self.registry.load()
            except Exception as exc:  # noqa: BLE001
                _log.warning("registry load failed: %s", exc)
        return self.registry.list()

    def _fetch_all(self, sources: list[WatchSource], *, incremental: bool = False) -> list:
        if not sources:
            return []
        if self.fetcher is None:
            self.fetcher = Fetcher(cache_dir=self.config.cache_dir)
        return self.fetcher.fetch_all(sources, incremental=incremental)

    def _extract(self, fetch_results: list) -> list[FeatureRecord]:
        records: list[FeatureRecord] = []
        for fetch_result in fetch_results:
            records.extend(self.extractor.extract_many(fetch_result.releases, fetch_result.source))
        return records


# ---------------------------------------------------------------------------
# Convenience: one-call entry used by the Cron task and the CLI.
# ---------------------------------------------------------------------------


def run_community_scan(
    *,
    config: RadarConfig | None = None,
    registry: SourceRegistry | None = None,
    output_dir: Path | str | None = None,
    period: str = "weekly",
    sources: Iterable[WatchSource] | None = None,
    incremental: bool = False,
) -> ScanResult:
    """Run a single scan and return the result.

    Both ``clawcodex-dev community-radar scan`` and the F-22 Cron
    durable task (``run_community_scan``) call this. It is intentionally
    side-effect-free aside from the dual-write performed by the
    pipeline, so tests can call it against a temp directory.
    """
    pipeline = CommunityRadarPipeline(
        config=config,
        registry=registry,
    )
    return pipeline.run_scan(
        sources=sources,
        period=period,
        write=True,
        output_dir=output_dir,
        persistent_copy=True,
        incremental=incremental,
    )
