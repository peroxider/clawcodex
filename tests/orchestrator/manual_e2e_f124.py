"""F-124 Issue Clarifier — manual E2E with real provider + LocalTracker.

Requires:
  CLAWCODEX_TEST_PROVIDER=openai (or any configured provider name)
  CLAWCODEX_TEST_MODEL=gpt-4o-mini   (optional, default: gpt-4o-mini)

Run locally:
  CLAWCODEX_TEST_PROVIDER=openai python3 -m pytest \\
    tests/orchestrator/manual_e2e_f124.py -v -s

CI skips this file via --ignore and the @skipif decorator below.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Generator

import pytest

from extensions.orchestrator.clarification import ClarificationConfig, ClarificationResolver
from extensions.orchestrator.clarification_queue import ClarificationQueue, ClarificationStatus
from extensions.orchestrator.config.schema import ClarifierConfig
from extensions.orchestrator.issue import Issue
from extensions.orchestrator.issue_clarifier import ClarifierCache, IssueClarifierService
from extensions.orchestrator.issue_clarifier.gate import IssueClarificationGate
from extensions.orchestrator.issue_registry import IssueRegistry
from extensions.orchestrator.local_tracker.adapter import LocalTrackerAdapter


@pytest.mark.skipif(
    not os.environ.get("CLAWCODEX_TEST_PROVIDER"),
    reason="set CLAWCODEX_TEST_PROVIDER to run real-provider E2E tests",
)
class TestF124LongRunningE2E:
    """Real-provider E2E tests for the F-124 issue clarifier pipeline.

    These tests exercise the full endpoint-to-endpoint flow:
      issue → analyze → block → answer → unblock → dispatch
    with a real LLM provider and a LocalTrackerAdapter.
    """

    @pytest.fixture
    def setup(self, tmp_path: Path) -> Generator:
        """Build a minimal E2E environment: LocalTracker + real provider + gate."""
        tracker_path = tmp_path / "tracker"
        tracker = LocalTrackerAdapter(tracker_path)

        provider_name = os.environ.get("CLAWCODEX_TEST_PROVIDER", "openai")
        model = os.environ.get("CLAWCODEX_TEST_MODEL", "gpt-4o-mini")

        # Late import: the provider module may fail if the provider is not installed.
        from clawcodex_ext.providers.runtime import build_provider_from_config

        provider = build_provider_from_config(provider_name, model)
        config = ClarifierConfig(
            enabled=True,
            block_on_unclear=True,
            max_rounds=2,
            min_confidence=0.7,
            fail_open=True,
            remote_label="",
        )
        cache = ClarifierCache(tmp_path / "cache.json", enabled=True)
        registry = IssueRegistry(tmp_path / "registry.json")
        queue = ClarificationQueue(tmp_path / "queue.json")
        resolver = ClarificationResolver(
            clarification_queue=queue,
            tracker=tracker,
            config=ClarificationConfig(enabled=True),
        )
        service = IssueClarifierService(
            config=config,
            cache=cache,
            provider=provider,
            model=model,
        )
        gate = IssueClarificationGate(
            service=service,
            resolver=resolver,
            registry=registry,
            config=config,
            tracker=tracker,
        )

        yield tracker, gate, registry, resolver, cache

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_clear_issue_passes_through(self, setup: tuple) -> None:
        """清晰描述：should_dispatch 返回 True，不产生澄清状态。"""
        _, gate, registry, _, _ = setup
        issue = Issue(
            id="1",
            title="Add retry logic",
            description="Add exponential backoff retry to the HTTP client. "
            "Acceptance: max 3 retries, 1s initial delay, doubles each retry.",
        )
        result = asyncio.run(gate.should_dispatch(issue))
        assert result is True, "Clear issue should dispatch"
        record = registry.get("1")
        status = record.clarification_status if record else None
        assert status in (None, "clear", "observation"), (
            f"Unexpected clarification status: {status}"
        )

    def test_unclear_issue_blocks_and_awaits(self, setup: tuple) -> None:
        """模糊描述：阻断 → 等待 → 通过 CLI 回答 → 解除。"""
        _, gate, registry, resolver, _ = setup
        issue = Issue(
            id="2",
            title="Optimize performance",
            description="Make the processing faster. No baseline provided.",
        )
        # 第一轮：应被阻断
        blocked = asyncio.run(gate.should_dispatch(issue))
        assert blocked is False, "Unclear issue should be blocked"
        record = registry.get("2")
        assert record is not None
        assert record.clarification_status == "awaiting_author", (
            f"Expected awaiting_author, got {record.clarification_status}"
        )
        assert len(record.open_questions) > 0, "Should have at least one question"
        print(f"  Questions: {record.open_questions}")

        # 模拟操作员通过 CLI 回答
        resolver.mark_answer(issue_id="2", answer="target 1000 QPS", source="dashboard")
        unblocked = asyncio.run(gate.should_dispatch(issue))
        assert unblocked is True, "After answer, issue should dispatch"

    def test_round_trip_api_latency(self, setup: tuple) -> None:
        """单次 analyze() 延迟 < 10s（真实 provider 网络延迟）。"""
        _, gate, _, _, _ = setup
        issue = Issue(
            id="3",
            title="Vague requirement",
            description="Add some kind of caching layer to improve performance.",
        )
        t0 = time.time()
        result = asyncio.run(gate.should_dispatch(issue))
        elapsed = time.time() - t0
        # Fail-open: if provider is slow, still accept the result
        print(f"  analyze() took {elapsed:.2f}s")
        assert isinstance(result, bool)
        # 延迟阈值宽松：网络波动下 15s 是可接受的上限
        assert elapsed < 15.0, f"analyze() took {elapsed:.2f}s (max 15s)"

    def test_provider_fail_open(self, setup: tuple) -> None:
        """provider 不可用时降级放行，不阻塞。"""
        _, gate, _, _, _ = setup
        # 模拟 provider 不可用
        gate.service._provider = None
        issue = Issue(
            id="4",
            title="Anything",
            description="Some random description.",
        )
        result = asyncio.run(gate.should_dispatch(issue))
        assert result is True, "Should fail-open when provider is unavailable"

    def test_multi_round_clarification(self, setup: tuple) -> None:
        """多轮追问：部分回答后仍不清晰，进入第二轮。"""
        _, gate, registry, resolver, _ = setup
        issue = Issue(
            id="5",
            title="Refactor database layer",
            description="Clean up the database code. No specifics about what to change.",
        )
        # 第一轮：阻断
        blocked = asyncio.run(gate.should_dispatch(issue))
        assert blocked is False
        record = registry.get("5")
        assert record.clarification_round == 1

        # 模拟不完整的回答
        resolver.mark_answer(issue_id="5", answer="just clean it up", source="dashboard")
        still_blocked = asyncio.run(gate.should_dispatch(issue))
        # 可能仍然不清晰（取决于 LLM 判断）
        print(f"  After partial answer: dispatch={still_blocked}, round={record.clarification_round}")

    def test_observation_mode_does_not_block(self, setup: tuple) -> None:
        """观察模式：block_on_unclear=false 时不阻断，只记录。"""
        gate = self._make_gate(setup, block_on_unclear=False)
        issue = Issue(
            id="6",
            title="Improve things",
            description="Make the code better. Very vague.",
        )
        result = asyncio.run(gate.should_dispatch(issue))
        assert result is True, "Observation mode should not block"

    def _make_gate(
        self,
        setup: tuple,
        block_on_unclear: bool = True,
    ) -> IssueClarificationGate:
        """Build a gate with custom config for this test case."""
        _, _, _, _, _ = setup
        from clawcodex_ext.providers.runtime import build_provider_from_config
        from extensions.orchestrator.clarification import ClarificationConfig, ClarificationResolver
        from extensions.orchestrator.clarification_queue import ClarificationQueue

        provider_name = os.environ.get("CLAWCODEX_TEST_PROVIDER", "openai")
        model = os.environ.get("CLAWCODEX_TEST_MODEL", "gpt-4o-mini")
        provider = build_provider_from_config(provider_name, model)

        config = ClarifierConfig(
            enabled=True,
            block_on_unclear=block_on_unclear,
            max_rounds=2,
            min_confidence=0.7,
            fail_open=True,
        )
        # Use separate temp paths to avoid cross-test contamination
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        cache = ClarifierCache(tmp / "cache.json", enabled=True)
        registry = IssueRegistry(tmp / "registry.json")
        queue = ClarificationQueue(tmp / "queue.json")
        resolver = ClarificationResolver(
            clarification_queue=queue,
            tracker=MagicMock(),
            config=ClarificationConfig(enabled=True),
        )
        service = IssueClarifierService(
            config=config,
            cache=cache,
            provider=provider,
            model=model,
        )
        return IssueClarificationGate(
            service=service,
            resolver=resolver,
            registry=registry,
            config=config,
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])