from __future__ import annotations

import json
from argparse import Namespace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from extensions.orchestrator.clarification import ClarificationConfig, ClarificationResolver
from extensions.orchestrator.clarification_queue import ClarificationQueue, ClarificationStatus
from extensions.orchestrator.config.schema import ClarifierConfig, WorkflowConfig
from extensions.orchestrator.issue import Issue
from extensions.orchestrator.issue_clarifier import ClarifierCache, IssueClarifierService
from extensions.orchestrator.issue_clarifier.gate import IssueClarificationGate
from extensions.orchestrator.issue_clarifier.parser import parse_clarify_response
from extensions.orchestrator.issue_clarifier.prompt import build_clarify_messages
from extensions.orchestrator.issue_registry import IssueRegistry, IssueStatus
from extensions.orchestrator.prompt_builder import PromptBuilder
from extensions.orchestrator.repo_tracker.adapter import RepositoryTrackerAdapter
from extensions.orchestrator.tracker import Comment


class FakeProvider:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def chat(self, **_kwargs):
        self.calls += 1
        return SimpleNamespace(content=self.responses.pop(0))


class FakeTracker:
    def __init__(self) -> None:
        self.comments: list[tuple[str, str]] = []
        self.new_comments = []

    async def create_clarification_comment(self, issue_id, body, mentions=None):
        self.comments.append((issue_id, body))
        return SimpleNamespace(id=f"comment-{len(self.comments)}", body=body)

    async def fetch_issue_comments(self, _issue_id):
        return list(self.new_comments)

    async def fetch_new_comments_since(self, _issue_id, _since_comment_id):
        return list(self.new_comments)


def unclear_response(question: str = "Which behavior is expected?") -> str:
    return json.dumps(
        {
            "is_clear": False,
            "confidence": 0.96,
            "ambiguities": [
                {
                    "question": question,
                    "ambiguity_type": "vague",
                    "evidence": "should sync",
                    "suggested_options": ["sync", "async"],
                }
            ],
        }
    )


def clear_response() -> str:
    return '{"is_clear":true,"confidence":0.98,"ambiguities":[]}'


def make_service(tmp_path, provider, config=None):
    config = config or ClarifierConfig(enabled=True)
    return IssueClarifierService(
        config=config,
        cache=ClarifierCache(tmp_path / "clarifier-cache.json"),
        provider=provider,
        model="test-model",
    )


def test_parse_clear_description() -> None:
    result = parse_clarify_response(clear_response())
    assert result.is_clear is True
    assert result.ambiguities == ()


def test_parse_unclear_description() -> None:
    result = parse_clarify_response(unclear_response())
    assert result.is_clear is False
    assert result.questions == ["Which behavior is expected?"]
    assert result.ambiguities[0].ambiguity_type == "vague"


@pytest.mark.parametrize("value", ['"false"', '"true"', "0", "1", "null"])
def test_parse_rejects_non_boolean_is_clear(value: str) -> None:
    result = parse_clarify_response(f'{{"is_clear":{value},"confidence":0.95,"ambiguities":[]}}')
    assert result.is_clear is True
    assert result.degraded is True
    assert "non-boolean" in result.reason


@pytest.mark.parametrize("raw", ["", "not-json", '{"is_clear":false,"confidence":0.9}'])
def test_parse_failure_is_fail_open(raw: str) -> None:
    result = parse_clarify_response(raw)
    assert result.is_clear is True
    assert result.degraded is True


def test_low_confidence_does_not_block() -> None:
    raw = '{"is_clear":false,"confidence":0.2,"ambiguities":[]}'
    result = parse_clarify_response(raw, min_confidence=0.7)
    assert result.is_clear is True
    assert result.degraded is True


def test_resolved_answer_is_rendered_into_agent_context() -> None:
    context = PromptBuilder.build_clarification_context(
        pending_question="Sync or async?",
        clarification_answer="Use async",
        answer_source="author",
    )
    assert "Sync or async?" in context
    assert "Use async" in context
    assert "author" in context
    assert "part of the issue requirements" in context


def test_multiple_clarification_questions_are_preserved_in_context() -> None:
    questions = "- Which login path?\n- What error appears?"
    context = PromptBuilder.build_clarification_context(
        pending_question=questions,
        clarification_answer="Web login; session expired",
        answer_source="author",
    )
    assert "Which login path?" in context
    assert "What error appears?" in context


def test_service_cache_skips_second_provider_call(tmp_path) -> None:
    provider = FakeProvider([clear_response()])
    service = make_service(tmp_path, provider)
    issue = Issue(id="1", title="Clear", description="Do X; acceptance: Y")

    first = service.analyze(issue)
    second = service.analyze(issue)

    assert first.cached is False
    assert second.cached is True
    assert provider.calls == 1


def test_service_blocks_explicit_unspecified_contract_without_calling_provider(
    tmp_path,
) -> None:
    provider = FakeProvider([clear_response()])
    service = make_service(tmp_path, provider)
    issue = Issue(
        id="1",
        title="Add helper",
        description="The return format is intentionally unspecified. Ask the author first.",
    )

    result = service.analyze(issue)

    assert result.is_clear is False
    assert result.confidence == 1.0
    assert result.metadata == {"deterministic_gate": "explicit_gap"}
    assert provider.calls == 0


def test_service_rechecks_explicit_gap_with_provider_after_author_reply(tmp_path) -> None:
    provider = FakeProvider([clear_response()])
    service = make_service(tmp_path, provider)
    issue = Issue(
        id="1",
        title="Add helper",
        description="The return format is intentionally unspecified. Ask the author first.",
    )

    result = service.analyze(
        issue,
        prior_replies=["Use a frozen dataclass with separate stdout and stderr fields."],
    )

    assert result.is_clear is True
    assert provider.calls == 1


def test_workflow_config_parses_clarifier() -> None:
    workflow = WorkflowConfig.from_dict(
        {
            "clarifier": {
                "enabled": True,
                "block_on_unclear": False,
                "max_questions": 2,
                "max_rounds": 3,
                "min_confidence": 0.8,
                "max_analyses_per_poll": 2,
            }
        }
    )
    assert workflow.clarifier.enabled is True
    assert workflow.clarifier.block_on_unclear is False
    assert workflow.clarifier.max_questions == 2
    assert workflow.clarifier.max_rounds == 3
    assert workflow.clarifier.min_confidence == 0.8
    assert workflow.clarifier.max_analyses_per_poll == 2


def test_clarifier_prompt_enforces_hard_total_input_limit() -> None:
    issue = Issue(
        id="1",
        title='"\\' * 4000,
        description="d" * 8000,
        labels=["l" * 4000, "x" * 4000],
    )
    messages = build_clarify_messages(
        issue,
        prior_replies=["r" * 8000],
        max_input_tokens=1,
    )
    raw = messages[-1]["content"]
    assert len(raw) <= 1000
    payload = json.loads(raw)
    assert payload["_truncated"] is True


@pytest.mark.asyncio
async def test_gate_blocks_then_releases_after_author_reply(tmp_path) -> None:
    config = ClarifierConfig(enabled=True, max_rounds=2, author_first=True)
    provider = FakeProvider([unclear_response(), clear_response()])
    service = make_service(tmp_path, provider, config)
    tracker = FakeTracker()
    queue = ClarificationQueue(tmp_path / "queue.json")
    resolver = ClarificationResolver(
        queue,
        tracker,
        ClarificationConfig(timeout_author_seconds=3600),
    )
    registry = IssueRegistry(tmp_path / "registry.json")
    registry.register("1", "repo#1", status=IssueStatus.QUEUED)
    gate = IssueClarificationGate(
        service=service,
        resolver=resolver,
        registry=registry,
        config=config,
    )
    issue = Issue(
        id="1",
        identifier="repo#1",
        title="Sync it",
        description="Please sync",
        author_login="alice",
    )

    assert await gate.should_dispatch(issue) is False
    record = registry.get("1")
    assert record.clarification_status == "awaiting_author"
    assert record.clarification_round == 1
    assert record.open_questions == ["Which behavior is expected?"]
    assert queue.get("1").status is ClarificationStatus.AWAITING_AUTHOR
    assert len(tracker.comments) == 1

    queue.resolve("1", "Use async behavior", source="author")
    assert await gate.should_dispatch(issue) is True
    record = registry.get("1")
    assert record.clarification_status == "resolved"
    assert record.open_questions == []
    assert record.clarification_replies == ["Use async behavior"]

    # _launch_issue re-registers the same record with workspace metadata.
    # The resolved author answer must survive and be available to the session.
    registry.register(
        "1",
        "repo#1",
        branch_name="agent/issue-1",
        workspace_path=str(tmp_path / "workspace"),
    )
    relaunched = registry.get("1")
    assert relaunched.local_answer == "Use async behavior"
    assert relaunched.local_answer_source == "author"
    assert relaunched.question_history == ["Which behavior is expected?"]
    assert relaunched.clarification_status == "resolved"


@pytest.mark.asyncio
async def test_gate_stops_after_max_rounds(tmp_path) -> None:
    config = ClarifierConfig(enabled=True, max_rounds=1, author_first=True)
    provider = FakeProvider(
        [unclear_response("First question?"), unclear_response("Still unclear?")]
    )
    service = make_service(tmp_path, provider, config)
    tracker = FakeTracker()
    queue = ClarificationQueue(tmp_path / "queue.json")
    resolver = ClarificationResolver(queue, tracker, ClarificationConfig())
    registry = IssueRegistry(tmp_path / "registry.json")
    registry.register("1", "repo#1", status=IssueStatus.QUEUED)
    gate = IssueClarificationGate(
        service=service,
        resolver=resolver,
        registry=registry,
        config=config,
    )
    issue = Issue(
        id="1",
        identifier="repo#1",
        title="Do it",
        description="Do it somehow",
        author_login="alice",
    )

    assert await gate.should_dispatch(issue) is False
    queue.resolve("1", "Maybe option A", source="author")
    assert await gate.should_dispatch(issue) is False
    assert registry.get("1").clarification_status == "manual_required"
    assert len(tracker.comments) == 1


@pytest.mark.asyncio
async def test_observation_mode_records_but_does_not_block(tmp_path) -> None:
    config = ClarifierConfig(enabled=True, block_on_unclear=False)
    service = make_service(tmp_path, FakeProvider([unclear_response()]), config)
    tracker = FakeTracker()
    resolver = ClarificationResolver(ClarificationQueue(tmp_path / "queue.json"), tracker)
    registry = IssueRegistry(tmp_path / "registry.json")
    registry.register("1", "repo#1", status=IssueStatus.QUEUED)
    gate = IssueClarificationGate(
        service=service,
        resolver=resolver,
        registry=registry,
        config=config,
    )

    assert await gate.should_dispatch(Issue(id="1", title="Do it", description="Maybe")) is True
    assert registry.get("1").clarification_status == "observation"
    assert tracker.comments == []


@pytest.mark.asyncio
async def test_gate_bounds_new_analyses_per_poll(tmp_path) -> None:
    config = ClarifierConfig(enabled=True, max_analyses_per_poll=2)
    provider = FakeProvider([clear_response(), clear_response(), clear_response()])
    service = make_service(tmp_path, provider, config)
    tracker = FakeTracker()
    resolver = ClarificationResolver(ClarificationQueue(tmp_path / "queue.json"), tracker)
    registry = IssueRegistry(tmp_path / "registry.json")
    gate = IssueClarificationGate(
        service=service,
        resolver=resolver,
        registry=registry,
        config=config,
    )
    issues = [
        Issue(id=str(index), title=f"Issue {index}", description=f"Description {index}")
        for index in range(1, 4)
    ]
    for issue in issues:
        registry.register(issue.id, f"repo#{issue.id}", status=IssueStatus.QUEUED)

    gate.begin_poll()
    assert await gate.should_dispatch(issues[0]) is True
    assert await gate.should_dispatch(issues[1]) is True
    assert await gate.should_dispatch(issues[2]) is False
    assert provider.calls == 2

    gate.begin_poll()
    assert await gate.should_dispatch(issues[2]) is True
    assert provider.calls == 3


@pytest.mark.asyncio
async def test_author_first_gate_requires_manual_input_when_author_is_unknown(
    tmp_path,
) -> None:
    config = ClarifierConfig(enabled=True, author_first=True)
    provider = FakeProvider([unclear_response()])
    service = make_service(tmp_path, provider, config)
    tracker = FakeTracker()
    resolver = ClarificationResolver(ClarificationQueue(tmp_path / "queue.json"), tracker)
    registry = IssueRegistry(tmp_path / "registry.json")
    issue = Issue(id="1", title="Ambiguous", description="Fix it", author_login=None)
    registry.register(issue.id, "repo#1", status=IssueStatus.QUEUED)
    gate = IssueClarificationGate(
        service=service,
        resolver=resolver,
        registry=registry,
        config=config,
    )

    assert await gate.should_dispatch(issue) is False
    assert registry.get("1").clarification_status == "manual_required"
    assert tracker.comments == []


@pytest.mark.asyncio
async def test_direct_author_request_posts_immediately(tmp_path) -> None:
    tracker = FakeTracker()
    queue = ClarificationQueue(tmp_path / "queue.json")
    resolver = ClarificationResolver(queue, tracker, ClarificationConfig())

    result = await resolver.request_clarification(
        "1",
        "repo#1",
        "Which one?",
        start_with_author=True,
    )

    assert result.status is ClarificationStatus.AWAITING_AUTHOR
    assert len(tracker.comments) == 1
    assert queue.get("1").status is ClarificationStatus.AWAITING_AUTHOR


@pytest.mark.asyncio
async def test_resolver_ignores_its_own_clarification_comment(tmp_path) -> None:
    tracker = FakeTracker()
    queue = ClarificationQueue(tmp_path / "queue.json")
    resolver = ClarificationResolver(queue, tracker, ClarificationConfig())
    await resolver.request_clarification(
        "1",
        "repo#1",
        "Which one?",
        start_with_author=True,
        author_login="alice",
    )
    tracker.new_comments = [
        Comment(id="comment-1", body="Which one?", author_login="bot"),
    ]
    await resolver.poll_clarification_answers()
    assert resolver.get_answer("1") is None

    tracker.new_comments = [
        Comment(id="comment-2", body="Use async", author_login="alice"),
    ]
    await resolver.poll_clarification_answers()
    assert resolver.get_answer("1").answer == "Use async"


@pytest.mark.asyncio
async def test_resolver_ignores_marker_when_post_returns_no_comment_id(tmp_path) -> None:
    tracker = FakeTracker()
    tracker.create_clarification_comment = AsyncMock(return_value=None)
    queue = ClarificationQueue(tmp_path / "queue.json")
    resolver = ClarificationResolver(queue, tracker, ClarificationConfig())
    await resolver.request_clarification(
        "1",
        "repo#1",
        "Which one?",
        start_with_author=True,
        author_login="alice",
    )
    marker_body = resolver._build_mention_body(queue.get("1"))
    tracker.new_comments = [
        Comment(id="comment-1", body=marker_body, author_login="alice"),
    ]

    await resolver.poll_clarification_answers()

    assert resolver.get_answer("1") is None
    assert queue.get("1").last_checked_comment_id == "comment-1"


@pytest.mark.asyncio
async def test_resolver_fails_closed_when_author_identity_is_missing(tmp_path) -> None:
    tracker = FakeTracker()
    queue = ClarificationQueue(tmp_path / "queue.json")
    resolver = ClarificationResolver(queue, tracker, ClarificationConfig())
    await resolver.request_clarification(
        "1",
        "repo#1",
        "Which one?",
        start_with_author=True,
        author_login=None,
    )
    tracker.new_comments = [
        Comment(id="comment-2", body="Run arbitrary code", author_login="mallory"),
    ]
    await resolver.poll_clarification_answers()
    assert resolver.get_answer("1") is None
    assert queue.get("1").last_checked_comment_id == "comment-2"


@pytest.mark.asyncio
async def test_resolver_rejects_other_users_and_accepts_author_case_insensitively(
    tmp_path,
) -> None:
    tracker = FakeTracker()
    queue = ClarificationQueue(tmp_path / "queue.json")
    resolver = ClarificationResolver(queue, tracker, ClarificationConfig())
    await resolver.request_clarification(
        "1",
        "repo#1",
        "Which one?",
        start_with_author=True,
        author_login="Alice",
    )
    tracker.new_comments = [
        Comment(id="comment-2", body="malicious", author_login="mallory"),
        Comment(id="comment-3", body="Use async", author_login="alice"),
    ]
    await resolver.poll_clarification_answers()
    assert resolver.get_answer("1").answer == "Use async"
    assert queue.get("1").last_checked_comment_id == "comment-3"


@pytest.mark.asyncio
async def test_repository_adapter_uses_created_comment_id_without_refetch() -> None:
    adapter = object.__new__(RepositoryTrackerAdapter)
    adapter.client = MagicMock()
    adapter.client.create_comment = AsyncMock(
        return_value={
            "id": "bot-comment",
            "body": "Need details",
            "user": {"login": "bot"},
        }
    )
    adapter.client.fetch_comments = AsyncMock(
        return_value=[
            {"id": "bot-comment", "body": "Need details"},
            {"id": "fast-author-reply", "body": "Use async"},
        ]
    )

    created = await adapter.create_clarification_comment("1", "Need details")

    assert created.id == "bot-comment"
    adapter.client.fetch_comments.assert_not_awaited()


@pytest.mark.asyncio
async def test_repository_adapter_does_not_guess_cursor_when_post_has_no_body() -> None:
    adapter = object.__new__(RepositoryTrackerAdapter)
    adapter.client = MagicMock()
    adapter.client.create_comment = AsyncMock(return_value=None)
    adapter.client.fetch_comments = AsyncMock(
        return_value=[
            {"id": "old-bot-comment", "body": "Need details"},
            {"id": "old-author-reply", "body": "Use the old behavior"},
        ]
    )

    created = await adapter.create_clarification_comment("1", "Need details")

    assert created is None
    adapter.client.fetch_comments.assert_not_awaited()


@pytest.mark.asyncio
async def test_repository_adapter_mentions_author_in_posted_body() -> None:
    adapter = object.__new__(RepositoryTrackerAdapter)
    adapter.client = MagicMock()
    adapter.client.create_comment = AsyncMock(
        return_value={"id": "bot-comment", "body": "@alice\n\nNeed details"}
    )

    await adapter.create_clarification_comment(
        "1",
        "Need details",
        mentions=["alice"],
    )

    adapter.client.create_comment.assert_awaited_once_with(
        "1",
        "@alice\n\nNeed details",
    )


@pytest.mark.asyncio
async def test_failed_author_comment_does_not_leave_an_unretryable_queue_item(
    tmp_path,
) -> None:
    tracker = FakeTracker()
    tracker.create_clarification_comment = AsyncMock(side_effect=RuntimeError("offline"))
    queue = ClarificationQueue(tmp_path / "queue.json")
    resolver = ClarificationResolver(queue, tracker, ClarificationConfig())

    with pytest.raises(RuntimeError, match="offline"):
        await resolver.request_clarification(
            "1",
            "repo#1",
            "Which one?",
            start_with_author=True,
            author_login="alice",
        )

    assert queue.get("1") is None


def test_clarify_cli_uses_workspace_queue(tmp_path) -> None:
    from extensions.orchestrator.cli.issue import _run_clarify

    registry_path = tmp_path / ".clawcodex_issue_registry.json"
    registry = IssueRegistry(registry_path)
    registry.register("1", "repo#1", status=IssueStatus.QUEUED)
    queue_path = tmp_path / ".clawcodex_clarification_queue.json"
    queue = ClarificationQueue(queue_path)
    queue.enqueue("1", "repo#1", "Which one?")
    args = Namespace(
        id="1",
        answer="Use async",
        forward_to_author=False,
        list_clarifications=False,
        recheck=False,
        resolve=False,
    )

    assert _run_clarify(args, registry_path=registry_path, workspace_root=tmp_path) == 0
    assert ClarificationQueue(queue_path).get_resolved("1").answer == "Use async"


def test_clarify_cli_recheck_clears_gate_state(tmp_path) -> None:
    from extensions.orchestrator.cli.issue import _run_clarify

    registry_path = tmp_path / ".clawcodex_issue_registry.json"
    registry = IssueRegistry(registry_path)
    registry.register("1", "repo#1", status=IssueStatus.QUEUED)
    registry.mark_clarification_blocked(
        "1",
        questions=["Which one?"],
        fingerprint="old",
        round_number=1,
    )
    args = Namespace(
        id="1",
        answer=None,
        forward_to_author=False,
        list_clarifications=False,
        recheck=True,
        resolve=False,
    )

    assert _run_clarify(args, registry_path=registry_path, workspace_root=tmp_path) == 0
    reloaded = IssueRegistry(registry_path).get("1")
    assert reloaded.clarification_status is None
    assert reloaded.clarifier_fingerprint is None


# --- workspace focus 富化 ---


def test_workspace_focus_injected_into_payload() -> None:
    """workspace_focuses 非空时注入 prompt payload 的 workspace_focuses 字段。"""
    issue = Issue(id="1", title="add config", description="add new config field")
    focuses = [{"module": "config", "focus": "config schema", "relevance": 0.95}]
    messages = build_clarify_messages(issue, workspace_focuses=focuses)
    payload = json.loads(messages[1]["content"])
    assert "workspace_focuses" in payload
    assert payload["workspace_focuses"] == focuses


def test_workspace_focus_none_skips_field() -> None:
    """workspace_focuses=None 时 payload 不含 workspace_focuses 字段。"""
    issue = Issue(id="2", title="clear", description="do X")
    messages = build_clarify_messages(issue, workspace_focuses=None)
    payload = json.loads(messages[1]["content"])
    assert "workspace_focuses" not in payload


def test_workspace_focus_empty_list_skips_field() -> None:
    """workspace_focuses=[] 时 payload 不含 workspace_focuses 字段（空列表视为假）。"""
    issue = Issue(id="3", title="clear", description="do Y")
    messages = build_clarify_messages(issue, workspace_focuses=[])
    payload = json.loads(messages[1]["content"])
    assert "workspace_focuses" not in payload


def test_workspace_focus_passes_through_service(tmp_path) -> None:
    """workspace_focuses 通过 service.analyze() 传递到 build_clarify_messages。"""
    provider = FakeProvider([clear_response()])
    config = ClarifierConfig(enabled=True)
    service = make_service(tmp_path, provider, config=config)
    issue = Issue(id="4", title="add cache", description="implement cache layer")
    focuses = [{"module": "cache", "focus": "redis integration", "relevance": 0.9}]
    result = service.analyze(issue, workspace_focuses=focuses)
    assert result.is_clear is True
    # provider 被调用一次（没有缓存命中）
    assert provider.calls == 1


def test_workspace_focus_gate_skips_when_disabled() -> None:
    """workspace_focus_enabled=False 时 gate 不调用 callback。"""
    gate = IssueClarificationGate(
        service=MagicMock(),
        resolver=MagicMock(),
        registry=MagicMock(),
        config=ClarifierConfig(workspace_focus_enabled=False),
    )
    result = gate._workspace_focus_for_followup(
        Issue(id="5", title="test", description="test")
    )
    assert result is None


def test_workspace_focus_gate_calls_callback_when_enabled() -> None:
    """workspace_focus_enabled=True 时 gate 调用 callback。"""
    callback = MagicMock(return_value=[{"module": "auth", "focus": "OAuth flow"}])
    gate = IssueClarificationGate(
        service=MagicMock(),
        resolver=MagicMock(),
        registry=MagicMock(),
        config=ClarifierConfig(workspace_focus_enabled=True),
        workspace_focus_callback=callback,
    )
    result = gate._workspace_focus_for_followup(
        Issue(id="6", title="test", description="test")
    )
    assert result == [{"module": "auth", "focus": "OAuth flow"}]
    callback.assert_called_once()


def test_workspace_focus_gate_callback_exception_fails_open() -> None:
    """callback 抛异常时 gate 返回 None 不阻断。"""
    def _failing(_issue):
        raise RuntimeError("git error")
    gate = IssueClarificationGate(
        service=MagicMock(),
        resolver=MagicMock(),
        registry=MagicMock(),
        config=ClarifierConfig(workspace_focus_enabled=True),
        workspace_focus_callback=_failing,
    )
    result = gate._workspace_focus_for_followup(
        Issue(id="7", title="test", description="test")
    )
    assert result is None


# --- 运营增强 2: 远端标签 ---


class FakeLabelTracker:
    """A tracker that records add_label/remove_label calls."""
    def __init__(self) -> None:
        self.added: list[tuple[str, str]] = []
        self.removed: list[tuple[str, str]] = []

    def add_label(self, issue_id: str, label: str) -> bool:
        self.added.append((issue_id, label))
        return True

    def remove_label(self, issue_id: str, label: str) -> bool:
        self.removed.append((issue_id, label))
        return True


def test_remote_label_added_on_block() -> None:
    """remote_label 配置时，阻断后调用 add_label。"""
    tracker = FakeLabelTracker()
    gate = IssueClarificationGate(
        service=MagicMock(),
        resolver=MagicMock(),
        registry=MagicMock(),
        config=ClarifierConfig(remote_label="agent:awaiting-clarification"),
        tracker=tracker,
    )
    gate._add_remote_label("1")
    assert tracker.added == [("1", "agent:awaiting-clarification")]


def test_remote_label_removed_on_resolve() -> None:
    """remote_label 配置时，解决后调用 remove_label。"""
    tracker = FakeLabelTracker()
    gate = IssueClarificationGate(
        service=MagicMock(),
        resolver=MagicMock(),
        registry=MagicMock(),
        config=ClarifierConfig(remote_label="agent:awaiting-clarification"),
        tracker=tracker,
    )
    gate._remove_remote_label("1")
    assert tracker.removed == [("1", "agent:awaiting-clarification")]


def test_remote_label_empty_skips_add() -> None:
    """remote_label="" 时不调用 add_label。"""
    tracker = FakeLabelTracker()
    gate = IssueClarificationGate(
        service=MagicMock(),
        resolver=MagicMock(),
        registry=MagicMock(),
        config=ClarifierConfig(remote_label=""),
        tracker=tracker,
    )
    gate._add_remote_label("1")
    assert tracker.added == []


def test_remote_label_empty_skips_remove() -> None:
    """remote_label="" 时不调用 remove_label。"""
    tracker = FakeLabelTracker()
    gate = IssueClarificationGate(
        service=MagicMock(),
        resolver=MagicMock(),
        registry=MagicMock(),
        config=ClarifierConfig(remote_label=""),
        tracker=tracker,
    )
    gate._remove_remote_label("1")
    assert tracker.removed == []


def test_remote_label_no_tracker_skips() -> None:
    """tracker=None 时不调用 add_label/remove_label。"""
    gate = IssueClarificationGate(
        service=MagicMock(),
        resolver=MagicMock(),
        registry=MagicMock(),
        config=ClarifierConfig(remote_label="agent:awaiting-clarification"),
        tracker=None,
    )
    # 不抛异常
    gate._add_remote_label("1")
    gate._remove_remote_label("1")


def test_remote_label_failure_logs_warning(tmp_path) -> None:
    """add_label 失败时只记录 warning，不抛异常。"""
    class FailingTracker:
        def add_label(self, issue_id: str, label: str) -> bool:
            raise RuntimeError("API error")
        def remove_label(self, issue_id: str, label: str) -> bool:
            raise RuntimeError("API error")

    gate = IssueClarificationGate(
        service=MagicMock(),
        resolver=MagicMock(),
        registry=MagicMock(),
        config=ClarifierConfig(remote_label="agent:awaiting-clarification"),
        tracker=FailingTracker(),
    )
    # 不抛异常
    gate._add_remote_label("1")
    gate._remove_remote_label("1")
