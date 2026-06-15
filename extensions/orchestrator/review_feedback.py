"""Pull request review feedback follow-up planning."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from .issue import Issue
from .issue_registry import IssueRecord, IssueRegistry
from .tracker import PullRequestFeedback, PullRequestRef, TrackerAdapter

logger = logging.getLogger(__name__)

REPLY_MARKER = "Handled in the latest ClawCodex follow-up commit."
CLAWCODEX_SYSTEM_MARKERS = (
    "## ClawCodex Run Summary",
    "## ClawCodex Automated Change",
    "## ClawCodex Follow-up",
    "## ClawCodex PR Review Follow-up Summary",
    "<!-- metadata: report_path=",
)


@dataclass(frozen=True)
class ReviewFollowup:
    issue: Issue
    record: IssueRecord
    pull_request: PullRequestRef
    feedback: list[PullRequestFeedback]
    prompt: str


class ReviewFeedbackService:
    """Find PR feedback that should trigger a follow-up agent run."""

    def __init__(
        self,
        *,
        tracker: TrackerAdapter,
        registry: IssueRegistry,
        config: object,
    ) -> None:
        self.tracker = tracker
        self.registry = registry
        self.config = config
        self._bot_login: str | None = None
        self._bot_login_resolved = False

    async def collect_followups(self, available_slots: int) -> list[ReviewFollowup]:
        if available_slots <= 0 or not getattr(self.config, "enabled", False):
            return []

        if not self._bot_login_resolved:
            explicit = getattr(self.config, "bot_login", None)
            if explicit:
                self._bot_login = explicit
            else:
                try:
                    self._bot_login = await self.tracker.get_authenticated_user()
                except Exception:
                    pass
            self._bot_login_resolved = True
            if self._bot_login:
                logger.debug("Bot login resolved: %s", self._bot_login)

        followups: list[ReviewFollowup] = []
        for record in self.registry.iter_records_with_pr():
            if len(followups) >= available_slots:
                break
            if not self.registry.can_follow_up(
                record.issue_id,
                getattr(self.config, "max_followup_attempts_per_pr", 5),
            ):
                continue

            pull_request = PullRequestRef(
                number=record.pr_number,
                url=record.pr_url,
            )
            feedback = await self.tracker.fetch_pull_request_feedback(
                pull_request=pull_request,
                issue_id=record.issue_id,
                include_ci_failures=getattr(self.config, "include_ci_failures", True),
                max_log_chars_per_check=getattr(self.config, "max_log_chars_per_check", 12_000),
            )
            pending = self._filter_pending(record, feedback, bot_login=self._bot_login)
            if not pending:
                self.registry.mark_feedback_checked(record.issue_id)
                continue

            limit = getattr(self.config, "max_feedback_items_per_run", 20)
            selected = pending[:limit]
            self.registry.mark_feedback_pending(
                record.issue_id,
                [item.id for item in selected],
                cursor=selected[-1].updated_at or selected[-1].created_at or selected[-1].id,
            )
            issue = Issue(
                id=record.issue_id,
                identifier=record.issue_identifier,
                title=record.issue_identifier,
                branch_name=record.branch_name,
            )
            followups.append(
                ReviewFollowup(
                    issue=issue,
                    record=record,
                    pull_request=pull_request,
                    feedback=selected,
                    prompt="",
                )
            )
        return followups

    def _filter_pending(
        self,
        record: IssueRecord,
        feedback: list[PullRequestFeedback],
        *,
        bot_login: str | None = None,
    ) -> list[PullRequestFeedback]:
        ignored_authors = {
            author.strip().lower()
            for author in getattr(self.config, "ignore_authors", [])
            if author.strip()
        }
        if bot_login:
            ignored_authors.add(bot_login.strip().lower())
        processed = set(record.processed_feedback_ids)
        already_pending = set(record.pending_feedback_ids)
        pending: list[PullRequestFeedback] = []
        for item in feedback:
            if item.id in processed or item.id in already_pending:
                continue
            if item.status in {"resolved", "outdated"}:
                continue
            if item.author_login and item.author_login.strip().lower() in ignored_authors:
                continue
            if _is_clawcodex_system_comment(item.body):
                continue
            pending.append(item)
        return pending


def _is_clawcodex_system_comment(body: str | None) -> bool:
    if not body:
        return False
    return any(marker in body for marker in (REPLY_MARKER, *CLAWCODEX_SYSTEM_MARKERS))
