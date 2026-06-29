"""F-120 Step 3: MergeableStatus + tracker adapter delegate.

Covers:
  - MergeableStatus dataclass 字段默认值 + has_conflicts derived
  - _normalize_mergeable_status 处理 GitHub / Gitee / GitCode shapes
  - RepositoryTrackerAdapter.fetch_pull_request_mergeable 委托给 client
  - GitCode 字段缺失 fallback（返回 has_conflicts=False）
"""

from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from extensions.orchestrator.repo_tracker.client import (
    _normalize_mergeable_status,
)
from extensions.orchestrator.tracker import MergeableStatus, PullRequestRef


class TestMergeableStatusDataclass(unittest.TestCase):
    def test_default_values(self) -> None:
        s = MergeableStatus()
        self.assertIsNone(s.mergeable)
        self.assertIsNone(s.mergeable_state)
        self.assertIsNone(s.behind_by)
        self.assertIsNone(s.ahead_by)
        self.assertFalse(s.has_conflicts)
        self.assertEqual(s.raw, {})

    def test_has_conflicts_false_when_mergeable_true(self) -> None:
        # Constructor: has_conflicts is set explicitly by the caller;
        # the dataclass does not derive it.
        s = MergeableStatus(mergeable=True, mergeable_state="clean")
        self.assertFalse(s.has_conflicts)

    def test_has_conflicts_explicitly_true(self) -> None:
        # When the normalizer sees mergeable=False or state="dirty"
        # it sets has_conflicts=True explicitly.
        s = MergeableStatus(
            mergeable=False,
            mergeable_state="dirty",
            has_conflicts=True,
        )
        self.assertTrue(s.has_conflicts)

    def test_has_conflicts_false_when_state_behind(self) -> None:
        # "behind" just means ahead/behind, not a conflict.
        s = MergeableStatus(mergeable=None, mergeable_state="behind", behind_by=2)
        self.assertFalse(s.has_conflicts)


class TestNormalizeMergeableStatus(unittest.TestCase):
    """Tests against the GitHub/Gitee/GitCode response shapes."""

    def test_github_clean(self) -> None:
        # GitHub returns `mergeable: true, mergeable_state: "clean"`.
        raw = {"mergeable": True, "mergeable_state": "clean", "behind_by": 0}
        s = _normalize_mergeable_status(raw, platform="github")
        self.assertIs(s.mergeable, True)
        self.assertEqual(s.mergeable_state, "clean")
        self.assertFalse(s.has_conflicts)
        self.assertEqual(s.raw["platform"], "github")
        self.assertEqual(s.raw["payload"], raw)

    def test_github_dirty(self) -> None:
        raw = {"mergeable": False, "mergeable_state": "dirty"}
        s = _normalize_mergeable_status(raw, platform="github")
        self.assertIs(s.mergeable, False)
        self.assertTrue(s.has_conflicts)

    def test_gitee_dirty_state(self) -> None:
        # Gitee uses mergeable_state in {"clean", "dirty", "blocked", ...}.
        raw = {"mergeable": False, "mergeable_state": "dirty"}
        s = _normalize_mergeable_status(raw, platform="gitee")
        self.assertEqual(s.mergeable_state, "dirty")
        self.assertTrue(s.has_conflicts)

    def test_gitee_mergeable(self) -> None:
        # Gitee "mergeable" = True when no conflict.
        raw = {"mergeable": True, "mergeable_state": "clean"}
        s = _normalize_mergeable_status(raw, platform="gitee")
        self.assertFalse(s.has_conflicts)

    def test_gitcode_missing_mergeable(self) -> None:
        # GitCode does not always include the `mergeable` field; the
        # normalizer should fall back to has_conflicts=False so the
        # daemon PR scan is a no-op (operator must use CLI / label /
        # comment to trigger rebase).
        raw = {"mergeable_state": "clean"}
        s = _normalize_mergeable_status(raw, platform="gitcode")
        self.assertIsNone(s.mergeable)
        self.assertFalse(s.has_conflicts)

    def test_gitcode_state_only_dirty(self) -> None:
        raw = {"mergeable_state": "dirty"}
        s = _normalize_mergeable_status(raw, platform="gitcode")
        self.assertEqual(s.mergeable_state, "dirty")
        self.assertTrue(s.has_conflicts)

    def test_gitcode_nested_conflict_passed(self) -> None:
        # GitCode can return a nested mergeable_state dict with
        # conflict_passed flag.
        raw = {
            "mergeable": None,
            "mergeable_state": {
                "state": "open",
                "conflict_passed": False,
            },
        }
        s = _normalize_mergeable_status(raw, platform="gitcode")
        self.assertTrue(s.has_conflicts)

    def test_gitcode_nested_conflict_passed_true(self) -> None:
        raw = {
            "mergeable": None,
            "mergeable_state": {
                "state": "open",
                "conflict_passed": True,
            },
        }
        s = _normalize_mergeable_status(raw, platform="gitcode")
        self.assertFalse(s.has_conflicts)

    def test_ahead_behind_populated(self) -> None:
        raw = {"ahead_by": 3, "behind_by": 5, "mergeable": True}
        s = _normalize_mergeable_status(raw, platform="github")
        self.assertEqual(s.ahead_by, 3)
        self.assertEqual(s.behind_by, 5)

    def test_string_mergeable_normalized(self) -> None:
        # Some APIs return "true"/"false" as strings.
        raw = {"mergeable": "true", "mergeable_state": "clean"}
        s = _normalize_mergeable_status(raw, platform="github")
        self.assertIs(s.mergeable, True)
        raw2 = {"mergeable": "false", "mergeable_state": "dirty"}
        s2 = _normalize_mergeable_status(raw2, platform="github")
        self.assertIs(s2.mergeable, False)
        self.assertTrue(s2.has_conflicts)


class TestRepositoryTrackerAdapterDelegate(unittest.TestCase):
    """Verifies that the adapter delegates to the client and returns
    the same MergeableStatus (does not transform)."""

    def _make(self, client: Any) -> Any:
        # Use real adapter without spinning up the real client.
        from extensions.orchestrator.repo_tracker.adapter import (
            RepositoryTrackerAdapter,
        )

        adapter = RepositoryTrackerAdapter.__new__(RepositoryTrackerAdapter)
        adapter.client = client
        return adapter

    def test_adapter_returns_client_status(self) -> None:
        expected = MergeableStatus(mergeable=False, mergeable_state="dirty")
        client = MagicMock()
        client.fetch_pull_request_mergeable = AsyncMock(return_value=expected)
        adapter = self._make(client)
        pr = PullRequestRef(number=42, url="https://example/pr/42")
        # Run the async method synchronously.
        import asyncio

        result = asyncio.run(adapter.fetch_pull_request_mergeable(pull_request=pr))
        self.assertIs(result, expected)
        client.fetch_pull_request_mergeable.assert_awaited_once_with(
            pull_request=pr,
        )


if __name__ == "__main__":
    unittest.main()