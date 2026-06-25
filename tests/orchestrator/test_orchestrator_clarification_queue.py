"""Unit tests for :class:`extensions.orchestrator.clarification_queue`.

Covers the file-backed clarification queue state machine:

* :class:`ClarificationItem` lifecycle helpers (``touch``, ``is_expired``,
  ``mark_answered``).
* :class:`ClarificationQueue` enqueue / mark-awaiting-local / awaiting-author
  / resolve / mark-duplicate / mark-stale / mark-expired / mark-exhausted /
  mark-issue-failed transitions.
* Persistence round-trip via :func:`_load` / :func:`_save`.
* Failure modes: missing file, malformed JSON, write errors.
* :meth:`ClarificationQueue.inject_feedback` for review-rejection feedback.
"""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from extensions.orchestrator.clarification_queue import (
    ClarificationItem,
    ClarificationQueue,
    ClarificationStatus,
    DEFAULT_QUEUE_PATH,
)


# ---------------------------------------------------------------------------
# ClarificationItem
# ---------------------------------------------------------------------------


class TestClarificationItem(unittest.TestCase):
    def test_defaults(self) -> None:
        item = ClarificationItem(issue_id="i1", issue_identifier="owner/repo#1", question="why?")
        self.assertEqual(item.issue_id, "i1")
        self.assertEqual(item.options, [])
        self.assertEqual(item.context_summary, "")
        self.assertEqual(item.status, ClarificationStatus.PENDING)
        self.assertIsNone(item.answer)
        self.assertIsNone(item.answer_source)
        self.assertIsNone(item.answered_at)
        self.assertFalse(item.escalation_notified)
        self.assertEqual(item.stale_answers, [])

    def test_touch_updates_updated_at(self) -> None:
        item = ClarificationItem(issue_id="i1", issue_identifier="x", question="?")
        original = item.updated_at
        time.sleep(0.005)
        item.touch()
        self.assertGreater(item.updated_at, original)

    def test_is_expired_when_no_deadline(self) -> None:
        item = ClarificationItem(issue_id="i1", issue_identifier="x", question="?")
        # No expires_at set → never expired.
        self.assertFalse(item.is_expired())

    def test_is_expired_before_deadline(self) -> None:
        item = ClarificationItem(
            issue_id="i1", issue_identifier="x", question="?",
            expires_at=time.time() + 100,
        )
        self.assertFalse(item.is_expired())

    def test_is_expired_after_deadline(self) -> None:
        item = ClarificationItem(
            issue_id="i1", issue_identifier="x", question="?",
            expires_at=time.time() - 5,
        )
        self.assertTrue(item.is_expired())

    def test_is_expired_with_explicit_now(self) -> None:
        item = ClarificationItem(
            issue_id="i1", issue_identifier="x", question="?",
            expires_at=100.0,
        )
        self.assertTrue(item.is_expired(now=200.0))
        self.assertFalse(item.is_expired(now=50.0))

    def test_mark_answered_records_source_and_time(self) -> None:
        item = ClarificationItem(issue_id="i1", issue_identifier="x", question="?")
        item.mark_answered("yes", "dashboard", answered_at=123.0)
        self.assertEqual(item.answer, "yes")
        self.assertEqual(item.answer_source, "dashboard")
        self.assertEqual(item.answered_at, 123.0)

    def test_mark_answered_defaults_to_current_time(self) -> None:
        item = ClarificationItem(issue_id="i1", issue_identifier="x", question="?")
        before = time.time()
        item.mark_answered("yes", "author")
        after = time.time()
        self.assertIsNotNone(item.answered_at)
        self.assertGreaterEqual(item.answered_at, before)
        self.assertLessEqual(item.answered_at, after)


# ---------------------------------------------------------------------------
# ClarificationQueue — construction / persistence
# ---------------------------------------------------------------------------


class TestClarificationQueuePersistence(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "queue.json"

    def test_empty_file_loads_empty(self) -> None:
        # File doesn't exist → empty records.
        queue = ClarificationQueue(queue_path=self.path)
        self.assertEqual(queue.poll_pending(), [])
        self.assertIsNone(queue.get("any"))

    def test_round_trip_persists_records(self) -> None:
        queue = ClarificationQueue(queue_path=self.path)
        queue.enqueue(
            issue_id="i1",
            issue_identifier="owner/repo#1",
            question="which?",
            options=["a", "b"],
            context_summary="ctx",
            timeout_seconds=120,
        )
        # File should be written.
        self.assertTrue(self.path.exists())
        # Reload from disk.
        reloaded = ClarificationQueue(queue_path=self.path)
        item = reloaded.get("i1")
        self.assertIsNotNone(item)
        self.assertEqual(item.question, "which?")
        self.assertEqual(item.options, ["a", "b"])
        self.assertEqual(item.context_summary, "ctx")
        self.assertIsNotNone(item.expires_at)

    def test_malformed_json_loads_empty(self) -> None:
        self.path.write_text("not-valid-json", encoding="utf-8")
        with self.assertLogs("extensions.orchestrator.clarification_queue", level="WARNING"):
            queue = ClarificationQueue(queue_path=self.path)
        self.assertEqual(queue.poll_pending(), [])

    def test_default_path_uses_home(self) -> None:
        # DEFAULT_QUEUE_PATH is a module-level constant under ~/.clawcodex.
        # It must always resolve under the user's home.
        self.assertTrue(str(DEFAULT_QUEUE_PATH).startswith(str(Path.home())))


# ---------------------------------------------------------------------------
# ClarificationQueue — enqueue / mark / resolve lifecycle
# ---------------------------------------------------------------------------


class TestClarificationQueueLifecycle(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "queue.json"
        self.queue = ClarificationQueue(queue_path=self.path)

    def test_enqueue_creates_pending_item(self) -> None:
        item = self.queue.enqueue(
            issue_id="i1", issue_identifier="x", question="?",
            options=["a", "b"], timeout_seconds=60,
        )
        self.assertEqual(item.status, ClarificationStatus.PENDING)
        self.assertIsNotNone(item.expires_at)
        # Without a mark_awaiting_*, the item is still pending.
        self.assertEqual(len(self.queue.poll_pending()), 1)

    def test_enqueue_without_options(self) -> None:
        self.queue.enqueue(issue_id="i1", issue_identifier="x", question="?")
        item = self.queue.get("i1")
        self.assertEqual(item.options, [])

    def test_enqueue_without_timeout_has_no_expiry(self) -> None:
        self.queue.enqueue(issue_id="i1", issue_identifier="x", question="?")
        item = self.queue.get("i1")
        self.assertIsNone(item.expires_at)

    def test_mark_awaiting_local(self) -> None:
        self.queue.enqueue(issue_id="i1", issue_identifier="x", question="?")
        result = self.queue.mark_awaiting_local("i1")
        self.assertIsNotNone(result)
        self.assertEqual(result.status, ClarificationStatus.AWAITING_LOCAL)

    def test_mark_awaiting_local_missing_returns_none(self) -> None:
        self.assertIsNone(self.queue.mark_awaiting_local("missing"))

    def test_mark_awaiting_author(self) -> None:
        self.queue.enqueue(issue_id="i1", issue_identifier="x", question="?")
        result = self.queue.mark_awaiting_author("i1")
        self.assertEqual(result.status, ClarificationStatus.AWAITING_AUTHOR)

    def test_resolve_local_channel_from_local(self) -> None:
        self.queue.enqueue(issue_id="i1", issue_identifier="x", question="?")
        self.queue.mark_awaiting_local("i1")
        self.queue.resolve("i1", "yes", "clarification_queue")
        item = self.queue.get("i1")
        self.assertEqual(item.status, ClarificationStatus.RESOLVED_LOCAL)
        self.assertEqual(item.answer, "yes")
        self.assertEqual(item.first_response_source, "clarification_queue")

    def test_resolve_author_from_local(self) -> None:
        # Status AWAITING_LOCAL + source "author" → RESOLVED_AUTHOR.
        self.queue.enqueue(issue_id="i1", issue_identifier="x", question="?")
        self.queue.mark_awaiting_local("i1")
        self.queue.resolve("i1", "answer from author", "author")
        self.assertEqual(
            self.queue.get("i1").status, ClarificationStatus.RESOLVED_AUTHOR
        )

    def test_resolve_from_author_channel(self) -> None:
        self.queue.enqueue(issue_id="i1", issue_identifier="x", question="?")
        self.queue.mark_awaiting_author("i1")
        self.queue.resolve("i1", "answer", "author")
        self.assertEqual(
            self.queue.get("i1").status, ClarificationStatus.RESOLVED_AUTHOR
        )

    def test_resolve_missing_returns_none(self) -> None:
        self.assertIsNone(self.queue.resolve("missing", "x", "dashboard"))

    def test_resolve_from_unexpected_status_warns(self) -> None:
        # Resolve from EXHAUSTED → still records answer but keeps status.
        self.queue.enqueue(issue_id="i1", issue_identifier="x", question="?")
        self.queue.mark_exhausted("i1")
        with self.assertLogs("extensions.orchestrator.clarification_queue", level="WARNING"):
            self.queue.resolve("i1", "late", "dashboard")
        item = self.queue.get("i1")
        self.assertEqual(item.answer, "late")
        self.assertEqual(item.status, ClarificationStatus.EXHAUSTED)

    def test_get_resolved_only_for_resolved_statuses(self) -> None:
        self.queue.enqueue(issue_id="i1", issue_identifier="x", question="?")
        self.assertIsNone(self.queue.get_resolved("i1"))  # still PENDING
        self.queue.mark_awaiting_local("i1")
        self.queue.resolve("i1", "x", "dashboard")
        self.assertIsNotNone(self.queue.get_resolved("i1"))

    def test_get_resolved_missing_returns_none(self) -> None:
        self.assertIsNone(self.queue.get_resolved("nope"))

    def test_poll_pending_excludes_expired(self) -> None:
        self.queue.enqueue(
            issue_id="i1", issue_identifier="x", question="?",
            timeout_seconds=0,
        )
        # Force expiration: the expires_at was set to time.time() + 0 → effectively now.
        time.sleep(0.01)
        pending = self.queue.poll_pending()
        self.assertEqual(pending, [])


# ---------------------------------------------------------------------------
# ClarificationQueue — conflict + escalation
# ---------------------------------------------------------------------------


class TestClarificationQueueConflict(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "queue.json"
        self.queue = ClarificationQueue(queue_path=self.path)

    def test_mark_duplicate(self) -> None:
        self.queue.enqueue(issue_id="i1", issue_identifier="x", question="?")
        result = self.queue.mark_duplicate("i1", "dup-answer", 12345.0)
        self.assertEqual(result.status, ClarificationStatus.DUPLICATE_REJECTED)
        self.assertEqual(result.duplicate_of, "12345.0")
        self.assertIn("dup-answer", result.stale_answers)
        self.assertEqual(self.queue.get_stale("i1"), ["dup-answer"])

    def test_mark_duplicate_missing(self) -> None:
        self.assertIsNone(self.queue.mark_duplicate("missing", "x", 0.0))

    def test_mark_stale(self) -> None:
        self.queue.enqueue(issue_id="i1", issue_identifier="x", question="?")
        result = self.queue.mark_stale("i1", "stale", reason="escalated_to_author")
        self.assertEqual(result.status, ClarificationStatus.STALE_REJECTED)
        self.assertIn("stale", result.stale_answers)

    def test_mark_stale_missing(self) -> None:
        self.assertIsNone(self.queue.mark_stale("missing", "x"))

    def test_mark_escalation_notified(self) -> None:
        self.queue.enqueue(issue_id="i1", issue_identifier="x", question="?")
        result = self.queue.mark_escalation_notified("i1")
        self.assertTrue(result.escalation_notified)

    def test_mark_escalation_notified_missing(self) -> None:
        self.assertIsNone(self.queue.mark_escalation_notified("missing"))

    def test_mark_expired_transitions_by_status(self) -> None:
        # AWAITING_LOCAL → TIMED_OUT_LOCAL
        self.queue.enqueue(issue_id="i1", issue_identifier="x", question="?")
        self.queue.mark_awaiting_local("i1")
        result = self.queue.mark_expired("i1")
        self.assertEqual(result.status, ClarificationStatus.TIMED_OUT_LOCAL)

        # AWAITING_AUTHOR → TIMED_OUT_AUTHOR
        self.queue.enqueue(issue_id="i2", issue_identifier="x", question="?")
        self.queue.mark_awaiting_author("i2")
        result = self.queue.mark_expired("i2")
        self.assertEqual(result.status, ClarificationStatus.TIMED_OUT_AUTHOR)

        # Other status → EXHAUSTED
        self.queue.enqueue(issue_id="i3", issue_identifier="x", question="?")
        result = self.queue.mark_expired("i3")
        self.assertEqual(result.status, ClarificationStatus.EXHAUSTED)

    def test_mark_expired_missing(self) -> None:
        self.assertIsNone(self.queue.mark_expired("missing"))

    def test_mark_exhausted(self) -> None:
        self.queue.enqueue(issue_id="i1", issue_identifier="x", question="?")
        result = self.queue.mark_exhausted("i1")
        self.assertEqual(result.status, ClarificationStatus.EXHAUSTED)

    def test_mark_issue_failed_writes_sentinel(self) -> None:
        self.queue.enqueue(issue_id="i1", issue_identifier="x", question="?")
        self.queue.mark_issue_failed("i1")
        sentinel = self.path.parent / ".escalated_issues.json"
        self.assertTrue(sentinel.exists())
        data = json.loads(sentinel.read_text())
        self.assertIn("i1", data)
        self.assertIn("failed_at", data["i1"])

    def test_mark_issue_failed_appends_existing_sentinel(self) -> None:
        self.queue.mark_issue_failed("i1")
        self.queue.mark_issue_failed("i2")
        sentinel = self.path.parent / ".escalated_issues.json"
        data = json.loads(sentinel.read_text())
        self.assertIn("i1", data)
        self.assertIn("i2", data)

    def test_remove(self) -> None:
        self.queue.enqueue(issue_id="i1", issue_identifier="x", question="?")
        self.assertIsNotNone(self.queue.get("i1"))
        self.queue.remove("i1")
        self.assertIsNone(self.queue.get("i1"))

    def test_remove_missing_is_silent(self) -> None:
        self.queue.remove("missing")  # should not raise


# ---------------------------------------------------------------------------
# inject_feedback (for review-rejection feedback)
# ---------------------------------------------------------------------------


class TestInjectFeedback(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "queue.json"
        self.queue = ClarificationQueue(queue_path=self.path)

    def test_inject_creates_new_item_when_missing(self) -> None:
        result = self.queue.inject_feedback("i1", "please fix the lint")
        self.assertEqual(result.issue_id, "i1")
        self.assertEqual(result.question, "please fix the lint")
        self.assertEqual(result.status, ClarificationStatus.PENDING)
        self.assertEqual(result.context_summary, "Human review rejection feedback")

    def test_inject_resets_existing_item(self) -> None:
        # First, create an item with a question.
        self.queue.enqueue(issue_id="i1", issue_identifier="x", question="old?")
        self.queue.mark_awaiting_local("i1")
        self.queue.resolve("i1", "old-answer", "dashboard")
        # Now inject feedback — should reset state.
        result = self.queue.inject_feedback("i1", "new feedback")
        self.assertEqual(result.question, "new feedback")
        self.assertEqual(result.options, [])
        self.assertEqual(result.status, ClarificationStatus.PENDING)
        self.assertIsNone(result.answer)
        self.assertIsNone(result.answer_source)


# ---------------------------------------------------------------------------
# save error path
# ---------------------------------------------------------------------------


class TestSaveFailure(unittest.TestCase):
    def test_save_error_does_not_propagate(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "queue.json"
        queue = ClarificationQueue(queue_path=path)
        queue.enqueue(issue_id="i1", issue_identifier="x", question="?")
        # Force _save to fail by patching the Path.write_text to raise.
        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            with self.assertLogs(
                "extensions.orchestrator.clarification_queue", level="WARNING"
            ):
                # Should not raise — write errors are logged.
                queue.enqueue(issue_id="i2", issue_identifier="x", question="?")
        # In-memory state still updated.
        self.assertIsNotNone(queue.get("i2"))


if __name__ == "__main__":
    unittest.main()
