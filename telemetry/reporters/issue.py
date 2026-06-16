"""IssueReporter — opt-in GitHub/Gitee/GitCode telemetry summaries."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
from dataclasses import dataclass
from typing import Any

from ..config import ReportingConfig
from ..redaction import Redactor
from ..storage import LocalJsonlStorage, utc_now
from .dry_run import _render_markdown

logger = logging.getLogger(__name__)

_BEGIN = "<!-- clawcodex-telemetry:{date}:begin -->"
_END = "<!-- clawcodex-telemetry:{date}:end -->"


@dataclass(frozen=True)
class IssueReporterHttp:
    client: Any


class IssueReporter:
    """Create or update remote telemetry issues without affecting callers."""

    def __init__(
        self,
        *,
        storage: LocalJsonlStorage,
        redactor: Redactor,
        config: ReportingConfig,
        client: Any | None = None,
    ) -> None:
        self._storage = storage
        self._redactor = redactor
        self._config = config
        self._client = client

    def render(self, summary: dict[str, Any], date: str) -> str:
        return _render_markdown(summary, date)

    def emit(self, rendered: str, *, date: str) -> bool:
        try:
            return self._emit(rendered, date=date)
        except Exception as exc:  # noqa: BLE001
            logger.warning("telemetry: issue reporter failed: %s", exc)
            self._record_error(
                date=date,
                reason="unexpected_error",
                rendered=rendered,
                error=str(exc),
            )
            return False

    def _emit(self, rendered: str, *, date: str) -> bool:
        if not self._valid_config():
            self._record_error(date=date, reason="missing_config", rendered=rendered)
            return False

        hits = self._redactor.scan_secrets(rendered)
        if hits:
            self._record_error(
                date=date,
                reason="secret_scan",
                rendered=rendered,
                patterns=hits,
            )
            return False

        content_hash = _content_hash(rendered)
        cursor = self._storage.read_reporter_cursor("issue")
        if (
            cursor.get("date") == date
            and cursor.get("content_hash") == content_hash
            and cursor.get("mode") == self._config.mode
            and cursor.get("platform") == self._config.platform
            and cursor.get("owner") == self._config.owner
            and cursor.get("repo") == self._config.repo
        ):
            return True

        try:
            issue = _run_coro_sync(self._upsert(rendered, date=date))
        except Exception as exc:  # noqa: BLE001
            self._record_error(
                date=date,
                reason="request_failed",
                rendered=rendered,
                error=str(exc),
            )
            return False

        issue_id = _issue_id(issue)
        self._storage.write_reporter_cursor(
            "issue",
            {
                "reporter": "issue",
                "date": date,
                "content_hash": content_hash,
                "issue_id": issue_id,
                "mode": self._config.mode,
                "platform": self._config.platform,
                "owner": self._config.owner,
                "repo": self._config.repo,
                "updated_at": utc_now(),
            },
        )
        return True

    async def _upsert(self, rendered: str, *, date: str) -> dict[str, Any] | None:
        client = self._get_client()
        mode = self._config.mode
        if mode == "create_daily":
            return await self._upsert_daily_issue(rendered, date=date)
        if mode == "update_or_create":
            return await self._upsert_inbox_issue(rendered, date=date)
        self._record_error(date=date, reason="unsupported_mode", rendered=rendered)
        return None

    async def _upsert_daily_issue(self, rendered: str, *, date: str) -> dict[str, Any] | None:
        client = self._get_client()
        title = f"{self._config.issue_title} — {date}"
        body = _wrap_date_block(rendered, date)
        existing = await client.find_issue_by_title(title, state=client.platform.open_state)
        if existing:
            issue_id = _issue_id(existing)
            if issue_id:
                return await client.update_issue_body(issue_id, title=title, body=body)
        return await client.create_issue(title=title, body=body)

    async def _upsert_inbox_issue(self, rendered: str, *, date: str) -> dict[str, Any] | None:
        client = self._get_client()
        title = self._config.issue_title
        block = _wrap_date_block(rendered, date)
        existing = await client.find_issue_by_title(title, state=client.platform.open_state)
        if not existing:
            return await client.create_issue(title=title, body=block)
        issue_id = _issue_id(existing)
        if not issue_id:
            return None
        current_body = str(existing.get("body") or existing.get("description") or "")
        updated_body = _replace_or_append_date_block(current_body, block, date)
        return await client.update_issue_body(issue_id, title=title, body=updated_body)

    def _valid_config(self) -> bool:
        return bool(
            self._config.kind == "issue"
            and self._config.platform
            and self._config.owner
            and self._config.repo
            and self._config.api_key
            and self._config.mode in {"update_or_create", "create_daily"}
        )

    def _get_client(self) -> Any:
        if self._client is None:
            from extensions.orchestrator.repo_tracker.client import RepositoryIssueClient

            self._client = RepositoryIssueClient(
                platform=self._config.platform,
                owner=self._config.owner,
                repo=self._config.repo,
                api_key=self._config.api_key,
                endpoint=self._config.endpoint,
            )
        return self._client

    def _record_error(
        self,
        *,
        date: str,
        reason: str,
        rendered: str,
        **fields: Any,
    ) -> None:
        payload: dict[str, Any] = {
            "timestamp": utc_now(),
            "date": date,
            "kind": "issue",
            "reason": reason,
            "platform": self._config.platform,
            "mode": self._config.mode,
            "owner": self._config.owner,
            "repo": self._config.repo,
            "content_hash": _content_hash(rendered),
            "length": len(rendered),
        }
        payload.update(fields)
        self._storage.append("reporter_errors", payload, date=date)


def _content_hash(rendered: str) -> str:
    return hashlib.sha256(rendered.encode("utf-8", errors="replace")).hexdigest()


def _wrap_date_block(rendered: str, date: str) -> str:
    return f"{_BEGIN.format(date=date)}\n{rendered.rstrip()}\n{_END.format(date=date)}\n"


def _replace_or_append_date_block(body: str, block: str, date: str) -> str:
    begin = _BEGIN.format(date=date)
    end = _END.format(date=date)
    start = body.find(begin)
    if start == -1:
        prefix = body.rstrip()
        return f"{prefix}\n\n{block}" if prefix else block
    stop = body.find(end, start)
    if stop == -1:
        prefix = body.rstrip()
        return f"{prefix}\n\n{block}" if prefix else block
    stop += len(end)
    return f"{body[:start]}{block.rstrip()}{body[stop:]}".rstrip() + "\n"


def _issue_id(issue: dict[str, Any] | None) -> str:
    if not isinstance(issue, dict):
        return ""
    value = issue.get("number") or issue.get("iid") or issue.get("id")
    return str(value) if value is not None else ""


def _run_coro_sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}
    error: list[BaseException] = []

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001
            error.append(exc)

    thread = threading.Thread(target=_runner, name="telemetry-issue-reporter", daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result.get("value")


__all__ = [
    "IssueReporter",
    "_replace_or_append_date_block",
    "_wrap_date_block",
]
