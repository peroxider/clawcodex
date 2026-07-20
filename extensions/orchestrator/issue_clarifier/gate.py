"""Orchestrator dispatch gate that connects F-124 to the existing resolver."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from .models import ClarifyResult
from .service import IssueClarifierService, format_clarification_request

if TYPE_CHECKING:
    from ..clarification import ClarificationResolver
    from ..issue import Issue
    from ..issue_registry import IssueRegistry

logger = logging.getLogger(__name__)


class IssueClarificationGate:
    """Return whether an issue may be dispatched in the current poll."""

    def __init__(
        self,
        *,
        service: IssueClarifierService,
        resolver: "ClarificationResolver",
        registry: "IssueRegistry",
        config: Any,
    ) -> None:
        self.service = service
        self.resolver = resolver
        self.registry = registry
        self.config = config
        self._analyses_this_poll = 0

    def begin_poll(self) -> None:
        """Reset the bounded first-analysis budget for a poll cycle."""
        self._analyses_this_poll = 0

    async def should_dispatch(self, issue: "Issue") -> bool:
        issue_id = str(issue.id or "")
        if not issue_id or not self.config.enabled:
            return True
        record = self.registry.get(issue_id)
        if record is None:
            return True

        replies = list(record.clarification_replies)
        current_fingerprint = self.service.fingerprint(issue, prior_replies=replies)
        status = str(record.clarification_status or "")

        if status == "manual_resolved":
            return True

        if status == "awaiting_author":
            resolved = self.resolver.get_answer(issue_id)
            if resolved is None:
                if record.clarifier_fingerprint == current_fingerprint:
                    return False
                # The issue text changed while waiting. Retire the stale
                # question and analyze the new text immediately.
                self.resolver.clear(issue_id)
                record.clarification_round = 0
                record.open_questions = []
                record.touch()
                self.registry._save()
            else:
                resolved_item = self.resolver.get_item(issue_id)
                comment_cursor = (
                    getattr(resolved_item, "last_checked_comment_id", None)
                    if resolved_item is not None
                    else None
                )
                answer = str(resolved.answer or "").strip()
                if answer and answer not in replies:
                    replies.append(answer)
                current_fingerprint = self.service.fingerprint(issue, prior_replies=replies)
                self.resolver.clear(issue_id)
                if comment_cursor:
                    self.registry.update_clarification(
                        issue_id,
                        clarifier_comment_cursor=comment_cursor,
                    )

        if record.clarifier_fingerprint == current_fingerprint and status in {
            "clear",
            "resolved",
            "observation",
        }:
            return True
        if record.clarifier_fingerprint == current_fingerprint and status == "manual_required":
            return False

        max_analyses = max(1, int(getattr(self.config, "max_analyses_per_poll", 4)))
        if self._analyses_this_poll >= max_analyses:
            logger.info(
                "Deferring F-124 analysis for issue %s: per-poll budget %d exhausted",
                issue_id,
                max_analyses,
            )
            return False
        self._analyses_this_poll += 1
        result = await asyncio.to_thread(
            self.service.analyze,
            issue,
            prior_replies=replies,
        )
        return await self._apply_result(issue, result, replies)

    async def _apply_result(
        self,
        issue: "Issue",
        result: ClarifyResult,
        replies: list[str],
    ) -> bool:
        issue_id = str(issue.id or "")
        record = self.registry.get(issue_id)
        if record is None:
            return True

        if result.is_clear:
            status = "resolved" if replies else "clear"
            self.registry.mark_clarification_resolved(
                issue_id,
                fingerprint=result.fingerprint,
                answer=(replies[-1] if replies else None),
                source=("author" if replies else None),
                status=status,
                replies=replies,
            )
            return True

        questions = result.questions
        if not questions:
            self.registry.mark_clarification_manual_required(
                issue_id,
                questions=["The clarity analyzer could not produce an actionable question."],
                fingerprint=result.fingerprint,
            )
            return False
        if not self.config.block_on_unclear:
            self.registry.update_clarification(
                issue_id,
                clarification_status="observation",
                open_questions=questions,
                clarifier_fingerprint=result.fingerprint,
                clarification_replies=replies,
            )
            return True

        if record.clarification_round >= self.config.max_rounds:
            self.registry.mark_clarification_manual_required(
                issue_id,
                questions=questions,
                fingerprint=result.fingerprint,
            )
            logger.warning(
                "Issue %s still unclear after %d rounds; manual input required",
                issue_id,
                record.clarification_round,
            )
            return False

        if self.config.author_first and not issue.author_login:
            self.registry.mark_clarification_manual_required(
                issue_id,
                questions=questions,
                fingerprint=result.fingerprint,
            )
            logger.warning(
                "Issue %s requires clarification but its author identity is unavailable",
                issue_id,
            )
            return False

        prior_item = self.resolver.get_item(issue_id)
        since_comment_id = getattr(record, "clarifier_comment_cursor", None)
        if prior_item is not None and getattr(prior_item, "last_checked_comment_id", None):
            since_comment_id = prior_item.last_checked_comment_id
        self.resolver.clear(issue_id)
        question, options = format_clarification_request(result)
        await self.resolver.request_clarification(
            issue_id=issue_id,
            issue_identifier=str(issue.identifier or issue_id),
            question=question,
            context=str(issue.description or "")[:2000],
            options=options,
            start_with_author=bool(self.config.author_first),
            since_comment_id=since_comment_id,
            author_login=issue.author_login,
        )
        self.registry.update_clarification(
            issue_id,
            clarification_status="awaiting_author",
            author_login=issue.author_login,
            clarification_replies=replies,
        )
        self.registry.mark_clarification_blocked(
            issue_id,
            questions=questions,
            fingerprint=result.fingerprint,
            round_number=record.clarification_round + 1,
        )
        return False


__all__ = ["IssueClarificationGate"]
