"""Daily aggregation over the local JSONL store.

The aggregator is the only place that turns raw per-event JSONL into the
``summaries/YYYY-MM-DD.json`` shape consumed by reporters. It must:

* be cheap to call (recorder invokes it after each append, gated by
  a per-day cache);
* never raise out of its public method (caller is a hot path);
* be deterministic given the same input files (so the same data set
  produces the same summary).
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from typing import Any, Final

from .events import SCHEMA_VERSION, EventType
from .migration import SCHEMA_VERSION_V2, _fingerprint_dict_to_hash, normalize_event
from .storage import LocalJsonlStorage, utc_date, utc_now
from .version import __version__

logger = logging.getLogger(__name__)

# How many error fingerprints to surface in the summary. 10 keeps the
# daily file small but enough to spot regressions. The same constant
# governs the crash summary table.
_TOP_N_FINGERPRINTS: Final[int] = 10
_TOP_N_COMMANDS: Final[int] = 10


class DailyAggregator:
    """Compute ``summaries/YYYY-MM-DD.json`` from raw event files."""

    def __init__(self, storage: LocalJsonlStorage) -> None:
        self._storage = storage
        self._last_aggregated_date: str | None = None

    @property
    def last_aggregated_date(self) -> str | None:
        return self._last_aggregated_date

    def reset_cache(self) -> None:
        """Forget the per-day cache; primarily for tests."""
        self._last_aggregated_date = None

    # -- public ----------------------------------------------------------

    def aggregate(self, date: str) -> dict[str, Any]:
        """Recompute and persist the summary for *date*.

        Returns the summary dict on success and ``{}`` on any failure.
        Never raises; aggregation errors are logged at WARNING.
        """
        try:
            summary = self._build_summary(date)
        except Exception as exc:  # noqa: BLE001
            logger.warning("telemetry: aggregation failed for %s: %s", date, exc)
            return {}
        if not summary:
            return {}
        ok = self._storage.write_summary(date, summary)
        if ok:
            self._last_aggregated_date = date
        return summary if ok else {}

    def aggregate_today_if_stale(self) -> dict[str, Any]:
        """Convenience: aggregate today once per process unless already done.

        The recorder calls this after each append so a single command
        run still produces a daily summary, but a busy session doesn't
        rebuild it for every event.
        """
        today = utc_date(utc_now())
        if self._last_aggregated_date == today:
            return self._storage.read_latest_summary(today) or {}
        return self.aggregate(today)

    # -- internals -------------------------------------------------------

    def _build_summary(self, date: str) -> dict[str, Any]:
        events = self._storage.read_day("events", date)
        crashes = self._storage.read_day("crashes", date)

        sessions_seen: set[str] = set()
        commands_total = 0
        command_counts: Counter[str] = Counter()
        command_success: Counter[str] = Counter()
        command_failure: Counter[str] = Counter()
        exit_status_counts: Counter[str] = Counter()
        provider_counts: Counter[str] = Counter()
        model_counts: Counter[str] = Counter()
        platform_counts: Counter[str] = Counter()
        tool_counts: Counter[str] = Counter()
        tool_success: Counter[str] = Counter()
        tool_failure: Counter[str] = Counter()
        duration_total = 0.0
        duration_count = 0

        for raw in events:
            # Normalize to v2 so the rest of the loop can rely
            # on a single shape (especially the structured fingerprint
            # dict). The upgrade is idempotent for already-v2 events.
            raw = normalize_event(raw)
            etype = raw.get("type")
            fields = raw.get("fields", {}) or {}
            sid = raw.get("session_id", "")
            if etype == EventType.SESSION_START.value:
                if sid:
                    sessions_seen.add(sid)
                platform = fields.get("platform") or "unknown"
                platform_counts[platform] += 1
                provider = fields.get("provider") or "unknown"
                if provider != "unknown":
                    provider_counts[provider] += 1
                model = fields.get("model") or "unknown"
                if model != "unknown":
                    model_counts[model] += 1
            elif etype == EventType.COMMAND_RUN.value:
                commands_total += 1
                name = fields.get("command_name") or "other"
                command_counts[name] += 1
                success = fields.get("success")
                if success is True:
                    command_success[name] += 1
                elif success is False:
                    command_failure[name] += 1
                duration = fields.get("duration_s")
                if isinstance(duration, (int, float)):
                    duration_total += float(duration)
                    duration_count += 1
                exit_status = fields.get("exit_status")
                if exit_status is not None:
                    exit_status_counts[str(exit_status)] += 1
            elif etype == EventType.SESSION_END.value:
                exit_status = fields.get("exit_status")
                if exit_status is not None:
                    exit_status_counts[str(exit_status)] += 1
                duration = fields.get("duration_s")
                if isinstance(duration, (int, float)):
                    duration_total += float(duration)
                    duration_count += 1
            elif etype == EventType.TOOL_SUMMARY.value:
                tool = fields.get("tool_name") or "unknown"
                tool_counts[tool] += 1
                success = fields.get("success")
                if success is True:
                    tool_success[tool] += 1
                elif success is False:
                    tool_failure[tool] += 1
            elif etype == EventType.ERROR.value:
                exit_status_counts["error"] += 1

        crash_summary = self._build_crash_summary(crashes)

        return {
            "schema_version": SCHEMA_VERSION_V2,
            "date": date,
            "version": __version__,
            "generated_at": utc_now(),
            "sessions": len(sessions_seen),
            "commands": commands_total,
            "duration_s": {
                "total": round(duration_total, 3),
                "samples": duration_count,
            },
            "exit_status_counts": dict(exit_status_counts),
            "platforms": dict(platform_counts),
            "providers": dict(provider_counts),
            "models": dict(model_counts),
            "top_commands": [
                {"name": name, "count": count}
                for name, count in command_counts.most_common(_TOP_N_COMMANDS)
            ],
            "command_success": dict(command_success),
            "command_failure": dict(command_failure),
            "tools": {
                "top": [
                    {"name": name, "count": count}
                    for name, count in tool_counts.most_common(_TOP_N_COMMANDS)
                ],
                "success": dict(tool_success),
                "failure": dict(tool_failure),
            },
            "crashes": crash_summary,
        }

    @staticmethod
    def _build_crash_summary(crashes: list[dict[str, Any]]) -> dict[str, Any]:
        if not crashes:
            return {"total": 0, "top": []}

        buckets: dict[str, dict[str, Any]] = {}
        for raw in crashes:
            # v2 events carry fingerprint as a structured dict;
            # v1 events carry it as a string. ``normalize_event`` already
            # ran in ``_build_summary`` but the crash sub-loop may also
            # be called directly, so re-normalize for safety.
            raw = normalize_event(raw)
            fields = raw.get("fields", {}) or {}
            fp = _fingerprint_dict_to_hash(fields.get("fingerprint")) or "unknown"
            bucket = buckets.setdefault(
                fp,
                {
                    "fingerprint": fp,
                    "count": 0,
                    "error_class": fields.get("error_class") or "unknown",
                    "first_seen": None,
                    "last_seen": None,
                    "stacktrace": [],
                },
            )
            bucket["count"] += 1
            ts = raw.get("timestamp")
            if isinstance(ts, (int, float)):
                if bucket["first_seen"] is None or ts < bucket["first_seen"]:
                    bucket["first_seen"] = ts
                if bucket["last_seen"] is None or ts > bucket["last_seen"]:
                    bucket["last_seen"] = ts
                    # Capture the stacktrace from the most recent occurrence,
                    # which typically has the most complete frame chain.
                    st = fields.get("stacktrace")
                    if st and len(st) > len(bucket["stacktrace"]):
                        bucket["stacktrace"] = list(st)
                # Also update if current stacktrace is longer than stored.
                st = fields.get("stacktrace")
                if st and len(st) > len(bucket["stacktrace"]):
                    bucket["stacktrace"] = list(st)

        top = sorted(
            buckets.values(),
            key=lambda b: (-b["count"], b["first_seen"] or 0.0),
        )[:_TOP_N_FINGERPRINTS]
        for entry in top:
            if entry["first_seen"] is not None:
                entry["first_seen_iso"] = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(entry["first_seen"])
                )
            if entry["last_seen"] is not None:
                entry["last_seen_iso"] = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(entry["last_seen"])
                )
        return {"total": sum(b["count"] for b in buckets.values()), "top": top}
