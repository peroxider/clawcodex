"""CLI `orchestrator issue feedback --list` shows comment URLs.

Covers the feedback-URL persistence surface: ``--list`` prints the
canonical comment/check URL (persisted from the tracker ``html_url``)
instead of the internal source-prefixed id, falling back to the id when
no URL is stored (records written before URL persistence, or items
without a URL such as some CI check runs).
"""

from __future__ import annotations

import argparse
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from extensions.orchestrator.cli.issue import _run_feedback
from extensions.orchestrator.issue_registry import IssueRegistry


def _make_args(issue_id: str = "7", **overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "id": issue_id,
        "list_feedback": True,
        "approve": False,
        "dismiss": False,
        "feedback_id": None,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


class TestFeedbackListUrls(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.reg_path = Path(self.tmp.name) / "registry.json"
        self.registry = IssueRegistry(self.reg_path)
        self.registry.register("7", "owner/repo#7")

    def test_list_shows_id_and_url_when_available(self) -> None:
        self.registry.mark_feedback_pending(
            "7",
            ["conversation:179122966", "inline_review:202"],
            feedback_urls={
                "conversation:179122966": "https://gitcode.com/owner/repo/issues/7#tid-179122966",
                "inline_review:202": "https://gitcode.com/owner/repo/pulls/7#discussion-202",
            },
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = _run_feedback(self.reg_path, _make_args())
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        # Both the internal id (for --feedback-id) and the URL (to read
        # the comment) must appear on the same line.
        self.assertIn("conversation:179122966", out)
        self.assertIn("https://gitcode.com/owner/repo/issues/7#tid-179122966", out)
        self.assertIn("inline_review:202", out)
        self.assertIn("https://gitcode.com/owner/repo/pulls/7#discussion-202", out)
        # Hint that ids feed --feedback-id.
        self.assertIn("--feedback-id", out)

    def test_list_falls_back_to_id_when_no_url(self) -> None:
        # No pr_url on the record and no stored url -> show the raw id alone.
        self.registry.mark_feedback_pending("7", ["conversation:123"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = _run_feedback(self.reg_path, _make_args())
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("conversation:123", out)
        # No URL could be reconstructed, so no arrow separator / http link.
        self.assertNotIn("->", out)

    def test_list_reconstructs_url_from_pr_url_when_no_stored_url(self) -> None:
        # GitCode issue-comments API omits html_url, and records written
        # before URL persistence have no pending_feedback_urls entry.
        # --list must reconstruct the comment permalink from pr_url +
        # the issue number + the raw comment id, shown alongside the id.
        # The issue number comes from issue_id (GitCode stores the bare
        # issue number there); the client fetches comments under
        # /issues/{issue_id}/comments, so the anchor lives there too.
        self.registry.register("4", "owner/repo#4")
        self.registry.mark_feedback_pending("4", ["conversation:179164353"])
        record = self.registry.get("4")
        assert record is not None
        record.pr_number = "3"
        record.pr_url = "https://gitcode.com/Gideon_Zhao/perf-reference-ascend/merge_requests/3"
        self.registry._save()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = _run_feedback(self.reg_path, _make_args(issue_id="4"))
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        # Both id and reconstructed URL appear (comment lives under issue
        # 4, anchored by #tid-).
        self.assertIn("conversation:179164353", out)
        self.assertIn(
            "https://gitcode.com/Gideon_Zhao/perf-reference-ascend/issues/4#tid-179164353",
            out,
        )

    def test_list_falls_back_to_id_for_review_summary(self) -> None:
        # review_summary / ci sources have no comment anchor -> show id
        # alone (no arrow / URL).
        self.registry.mark_feedback_pending("7", ["review_summary:5"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = _run_feedback(self.reg_path, _make_args())
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("review_summary:5", out)
        self.assertNotIn("->", out)

    def test_list_no_pending(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = _run_feedback(self.reg_path, _make_args())
        self.assertEqual(rc, 0)
        self.assertIn("No pending feedback", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
