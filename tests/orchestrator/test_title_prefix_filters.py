"""Title-prefix filtering across tracker adapters and hot workflow reload."""

from __future__ import annotations

import tempfile
import textwrap
import unittest
import os
from pathlib import Path
from types import SimpleNamespace

import httpx

from extensions.orchestrator.config.schema import WorkflowConfig
from extensions.orchestrator.linear.client import LinearGraphQLClient
from extensions.orchestrator.local_tracker.adapter import LocalTrackerAdapter
from extensions.orchestrator.orchestrator import Orchestrator
from extensions.orchestrator.repo_tracker.adapter import RepositoryTrackerAdapter


def _repo_issue(number: int, title: str) -> dict[str, object]:
    return {"number": number, "title": title, "state": "open", "labels": []}


class TestTitlePrefixFilters(unittest.IsolatedAsyncioTestCase):
    async def test_repository_any_and_all_semantics(self) -> None:
        payload = [_repo_issue(1, "feat: api"), _repo_issue(2, "fix: api")]

        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = RepositoryTrackerAdapter(
                platform="github", owner="a", repo="b", api_key="token", http_client=client,
                title_prefixes=["feat:", "fix:"], title_prefix_match="any",
            )
            self.assertEqual([issue.id for issue in await adapter.fetch_candidate_issues()], ["1", "2"])
            adapter.configure_title_prefix_filter(["feat:", "feat: api"], "all")
            self.assertEqual([issue.id for issue in await adapter.fetch_candidate_issues()], ["1"])

    async def test_local_and_linear_apply_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "issue.md"
            path.write_text("---\nid: one\ntitle: '[auto] local'\nstate: open\n---\n", encoding="utf-8")
            adapter = LocalTrackerAdapter(tmp, title_prefixes=["[auto]"], title_prefix_match="any")
            self.assertEqual([i.id for i in await adapter.fetch_candidate_issues()], ["one"])
            adapter.configure_title_prefix_filter(["[manual]"], "any")
            self.assertEqual(await adapter.fetch_candidate_issues(), [])

        client = LinearGraphQLClient("token", title_prefixes=["[auto]"], title_prefix_match="any")
        page = {
            "data": {"issues": {"nodes": [
                {"id": "one", "identifier": "T-1", "title": "[auto] linear", "labels": {"nodes": []}},
                {"id": "two", "identifier": "T-2", "title": "manual", "labels": {"nodes": []}},
            ], "pageInfo": {"hasNextPage": False, "endCursor": None}}}
        }

        async def graphql(*_: object, **__: object) -> dict[str, object]:
            return page

        client.graphql = graphql  # type: ignore[method-assign]
        issues = await client.fetch_candidate_issues("project", ["Todo"])
        self.assertEqual([issue.id for issue in issues], ["one"])


class TestDynamicTitlePrefixReload(unittest.TestCase):
    def test_modified_workflow_updates_existing_tracker(self) -> None:
        class FakeTracker:
            received: tuple[list[str], str] | None = None

            def configure_title_prefix_filter(self, prefixes: list[str], match: str) -> None:
                self.received = (prefixes, match)

        with tempfile.TemporaryDirectory() as tmp:
            workflow_path = Path(tmp) / "workflow.md"
            workflow_path.write_text(textwrap.dedent("""\
                ---
                tracker:
                  kind: local
                  title_prefixes: ["[old]"]
                ---
            """), encoding="utf-8")
            initial_mtime = workflow_path.stat().st_mtime_ns
            workflow_path.write_text(textwrap.dedent("""\
                ---
                tracker:
                  kind: local
                  title_prefixes: ["[new]", "[urgent]"]
                  title_prefix_match: all
                ---
            """), encoding="utf-8")
            # Some filesystems use a coarse timestamp. Make the save visible
            # to the mtime-based hot-reload check in every test environment.
            os.utime(workflow_path, ns=(initial_mtime + 1, initial_mtime + 1))
            workflow = WorkflowConfig.from_dict({"tracker": {"kind": "local"}})
            tracker = FakeTracker()
            orchestrator = object.__new__(Orchestrator)
            orchestrator.workflow = workflow
            orchestrator.tracker = tracker
            orchestrator._workflow_path = str(workflow_path)
            orchestrator._dynamic_tracker_config_mtime_ns = initial_mtime
            orchestrator._refresh_dynamic_title_prefix_filter()
            self.assertEqual(tracker.received, (["[new]", "[urgent]"], "all"))
            self.assertEqual(workflow.tracker.title_prefixes, ["[new]", "[urgent]"])
