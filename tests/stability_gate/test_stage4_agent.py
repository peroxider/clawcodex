"""Stage 4 — Agent / Conversation 测试（< 3 秒）。

验证：
- Conversation 序列化/反序列化
- Message types 类型构建和 API payload 转换
- Session 创建/保存/加载
- 子 agent transcript 在主 agent session 目录的 subagents/ 下
  （F-49 / S-R4-A：与主 session 共享 ~/.clawcodex/sessions/ 父路径，
   依赖 src.init.init() 注册 nested resolver；resolver 缺失时
   兜底写到 ~/.clawcodex/transcripts/）
- ToolUseBlock / TextBlock 构建
"""

from __future__ import annotations

import sys


class TestStage4Conversation:
    """Conversation 序列化和反序列化测试。"""

    def test_conversation_round_trip(self):
        from src.agent.conversation import Conversation
        from src.types.messages import UserMessage, AssistantMessage

        conv = Conversation()
        conv.add_user_message("Hello")
        conv.add_assistant_message("Hi there!")

        data = conv.to_dict()
        reloaded = Conversation.from_dict(data)

        msgs = reloaded.get_messages()
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"

    def test_conversation_empty(self):
        from src.agent.conversation import Conversation

        conv = Conversation()
        data = conv.to_dict()
        reloaded = Conversation.from_dict(data)
        assert len(reloaded.get_messages()) == 0

    def test_conversation_multi_turn(self):
        from src.agent.conversation import Conversation
        from src.types.messages import UserMessage, AssistantMessage

        conv = Conversation()
        for i in range(3):
            conv.add_user_message(f"User message {i}")
            conv.add_assistant_message(f"Assistant response {i}")

        msgs = conv.get_messages()
        assert len(msgs) == 6
        assistant_content = msgs[-1]["content"]
        if isinstance(assistant_content, list):
            assert any(
                isinstance(b, dict) and b.get("text") == "Assistant response 2"
                for b in assistant_content
            ), f"Expected text block, got {assistant_content}"
        else:
            assert msgs[-1]["content"] == "Assistant response 2"


class TestStage4MessageTypes:
    """消息类型和 API payload 转换测试。"""

    def test_message_types_in_api_payload(self):
        from src.types.messages import (
            UserMessage,
            AssistantMessage,
            normalize_messages_for_api,
        )
        from src.types.content_blocks import TextBlock, ToolUseBlock

        msgs = [
            UserMessage(content="ping"),
            AssistantMessage(
                content=[
                    TextBlock(text="pong"),
                    ToolUseBlock(
                        id="t1", name="Read", input={"file_path": "/foo"}
                    ),
                ]
            ),
        ]
        payload = normalize_messages_for_api(msgs)
        assert payload[0] == {"role": "user", "content": "ping"}
        assert payload[1]["role"] == "assistant"
        blocks = payload[1]["content"]
        assert blocks[0] == {"type": "text", "text": "pong"}
        assert blocks[1]["type"] == "tool_use"
        assert blocks[1]["name"] == "Read"

    def test_user_message_creation(self):
        from src.types.messages import UserMessage

        msg = UserMessage(content="test message")
        assert msg.content == "test message"
        assert msg.role == "user"


class TestStage4Session:
    """Session 创建 / 保存 / 加载测试。"""

    def test_session_create(self):
        from src.agent.session import Session

        session = Session.create(provider="anthropic", model="claude-sonnet-4-20250514")
        assert session.provider == "anthropic"
        assert session.model == "claude-sonnet-4-20250514"
        assert session.session_id is not None

    def test_session_conversation_integration(self):
        from src.agent.session import Session

        session = Session.create(provider="anthropic", model="claude-sonnet-4-20250514")
        session.conversation.add_user_message("Hello")
        session.conversation.add_assistant_message("World")
        assert len(session.conversation.get_messages()) == 2


class TestStage4SubagentInParentSession:
    """子 agent transcript 必须落在主 agent session 目录的 subagents/ 子目录下。

    设计要求（g1 session 治理基本保证，F-49/S-R4-A 演进）：

    - 子 agent 与主 agent 共享父路径 ``~/.clawcodex/sessions/``，方便
      ``list_sessions`` / ``cleanup_sessions`` 一起扫描、一起清理。
    - 子 agent transcript 落在
      ``<parent_session_id>/subagents/agent-<agent_id>.jsonl``，与
      主 session 的 ``<parent_session_id>/transcript.jsonl`` 同根不同枝。
    - 该路径在 ``src.init.init()`` 之后由
      ``clawcodex_ext.transcript.nested_path.nested_session_path_resolver``
      提供；若 init 被旁路，则落到 flat
      ``~/.clawcodex/transcripts/<agent_id>.jsonl``，不污染主 session。

    5 个测试覆盖 wiring、路径结构、命名约定、HOME 隔离、兜底可写。
    不依赖外部 API，全部使用 stdlib + 代码内构造。
    """

    def _isolated_setup(self, monkeypatch, tmp_path):
        """Wire up isolated HOME + clear resolver state for one test.

        Returns the (transcript_module, init_callable, reset_callable,
        original_resolver, original_warned, original_nested_flag) tuple.
        Caller is responsible for restoring state in a try/finally block.

        The clawcodex_ext module-level flag
        ``_nested_transcript_initialized`` is sticky across the test
        process (it exists to dedupe registration in production). We
        must reset it explicitly; otherwise the first test's
        registration sticks, and subsequent tests that clear the
        resolver find init() a no-op and fail.
        """
        monkeypatch.setenv("HOME", str(tmp_path))
        # Windows: Path.home() uses USERPROFILE, not HOME
        if sys.platform == "win32":
            monkeypatch.setenv("USERPROFILE", str(tmp_path))
            # Also clear HOMEDRIVE/HOMEPATH so they don't bypass USERPROFILE
            monkeypatch.delenv("HOMEDRIVE", raising=False)
            monkeypatch.delenv("HOMEPATH", raising=False)
        import src.agent.transcript as transcript
        from src.init import init as init_callable
        from src.init import reset_init_for_test_only
        import clawcodex_ext

        original_resolver = transcript._transcript_path_resolver
        original_warned = transcript._flat_fallback_warned
        original_nested_flag = clawcodex_ext._nested_transcript_initialized
        # 清空 init memoize 缓存 + 之前的 resolver 注册 + 嵌套注册 flag，
        # 确保从干净状态起步
        reset_init_for_test_only()
        transcript._transcript_path_resolver = None
        transcript._flat_fallback_warned = False
        clawcodex_ext._nested_transcript_initialized = False
        return (
            transcript,
            init_callable,
            reset_init_for_test_only,
            original_resolver,
            original_warned,
            original_nested_flag,
        )

    def test_init_registers_nested_resolver(self, monkeypatch, tmp_path):
        """``init()`` 调用后 ``_transcript_path_resolver`` 不再为 ``None``。

        防止以后入口绕开 init()、resolver 永远为 None、子 agent 全部
        落 flat 的回归。
        """
        transcript, init_callable, reset, original_resolver, original_warned, original_nested_flag = self._isolated_setup(
            monkeypatch, tmp_path
        )
        try:
            assert transcript._transcript_path_resolver is None, (
                "precondition: resolver must start cleared for this test"
            )
            init_callable()
            assert transcript._transcript_path_resolver is not None, (
                "init() must register the nested-session transcript "
                "path resolver so sub-agent JSONL files land under "
                "<parent_session_id>/subagents/. See "
                "src/init.py:init() substep 6 and "
                "clawcodex_ext/transcript/nested_path.py"
            )
        finally:
            transcript._transcript_path_resolver = None
            transcript._flat_fallback_warned = original_warned
            import clawcodex_ext
            clawcodex_ext._nested_transcript_initialized = original_nested_flag
            reset()

    def test_subagent_path_lands_in_subagents_dir(self, monkeypatch, tmp_path):
        """``get_agent_transcript_path(agent_id, parent_session_id=sid)``
        返回 ``<HOME>/.clawcodex/sessions/<sid>/subagents/agent-<id>.jsonl``。
        """
        transcript, init_callable, reset, original_resolver, original_warned, original_nested_flag = self._isolated_setup(
            monkeypatch, tmp_path
        )
        try:
            init_callable()
            path = transcript.get_agent_transcript_path(
                "a1b2c3d4z", parent_session_id="ses-stability-gate"
            )
            from pathlib import Path

            p = Path(path)
            # 文件名格式
            assert p.name == "agent-a1b2c3d4z.jsonl", (
                f"unexpected filename; got {p.name!r}, "
                f"want 'agent-a1b2c3d4z.jsonl'"
            )
            # 倒一目录: subagents
            assert p.parent.name == "subagents", (
                f"parent dir must be 'subagents'; got {p.parent.name!r}"
            )
            # 倒二目录: parent_session_id
            assert p.parent.parent.name == "ses-stability-gate", (
                f"grandparent must be the parent session id; "
                f"got {p.parent.parent.name!r}"
            )
            # HOME 隔离断言: 路径必须在 tmp_path 之下
            try:
                p.relative_to(tmp_path)
            except ValueError as exc:
                raise AssertionError(
                    f"path {p} escapes isolated tmp_path {tmp_path}: {exc}"
                )
        finally:
            transcript._transcript_path_resolver = None
            transcript._flat_fallback_warned = original_warned
            import clawcodex_ext
            clawcodex_ext._nested_transcript_initialized = original_nested_flag
            reset()

    def test_subagent_path_shares_sessions_parent_with_main_session(
        self, monkeypatch, tmp_path
    ):
        """子 agent path 与主 session 目录共享父路径
        ``~/.clawcodex/sessions/``，方便统一治理。
        """
        transcript, init_callable, reset, original_resolver, original_warned, original_nested_flag = self._isolated_setup(
            monkeypatch, tmp_path
        )
        try:
            init_callable()
            subagent_path = transcript.get_agent_transcript_path(
                "a-share-parent", parent_session_id="ses-share-parent"
            )
            from pathlib import Path

            p = Path(subagent_path)
            # 子 agent: agent-X.jsonl / subagents / <sid> / sessions
            sessions_root = p.parent.parent.parent
            expected_root = Path(tmp_path) / ".clawcodex" / "sessions"
            assert sessions_root == expected_root, (
                f"subagent sessions_root mismatch: "
                f"got {sessions_root}, expected {expected_root} "
                f"(full path: {p})"
            )
            # 共享父路径, 但子 agent 在 sessions/ 之下再深一层
            # (sessions/<sid>/subagents/), 不能直接等于 sessions/
            assert sessions_root != p.parent, (
                "subagent path must be nested under the per-session "
                "directory, not flattened to the sessions/ root"
            )
        finally:
            transcript._transcript_path_resolver = None
            transcript._flat_fallback_warned = original_warned
            import clawcodex_ext
            clawcodex_ext._nested_transcript_initialized = original_nested_flag
            reset()

    def test_subagent_filename_is_agent_dash_id_jsonl(
        self, monkeypatch, tmp_path
    ):
        """子 agent 文件名遵循 ``agent-<agent_id>.jsonl`` 格式。

        与 ``clawcodex_ext/transcript/nested_path.py:35`` 中的字面量
        ``f"agent-{agent_id}.jsonl"`` 同步——任何变更需要两边一起改。
        """
        transcript, init_callable, reset, original_resolver, original_warned, original_nested_flag = self._isolated_setup(
            monkeypatch, tmp_path
        )
        try:
            init_callable()
            for agent_id in ("a1", "agent-xyz", "a-b-c-9z"):
                path = transcript.get_agent_transcript_path(
                    agent_id, parent_session_id="ses-name-test"
                )
                from pathlib import Path
                assert Path(path).name == f"agent-{agent_id}.jsonl", (
                    f"agent_id={agent_id!r}: expected "
                    f"agent-{agent_id}.jsonl suffix, got {path}"
                )
        finally:
            transcript._transcript_path_resolver = None
            transcript._flat_fallback_warned = original_warned
            import clawcodex_ext
            clawcodex_ext._nested_transcript_initialized = original_nested_flag
            reset()

    def test_flat_fallback_remains_writable_when_resolver_missing(
        self, monkeypatch, tmp_path
    ):
        """兜底 flat 路径在 resolver 缺失时仍可写, 不污染主 session 目录。

        模拟某个未来入口漏走 init() 的回归场景——
        ``_transcript_path_resolver`` 保持 ``None``, 调用
        ``get_agent_transcript_path`` 不应抛错、路径应落在
        ``<HOME>/.clawcodex/transcripts/`` 而不是 ``<HOME>/.clawcodex/sessions/``。
        """
        transcript, _, reset, original_resolver, original_warned, original_nested_flag = (
            self._isolated_setup(monkeypatch, tmp_path)
        )
        try:
            # 显式保持 resolver 为 None, 不调 init, 模拟回归
            assert transcript._transcript_path_resolver is None
            path = transcript.get_agent_transcript_path(
                "a-fallback-test", parent_session_id="ses-fallback"
            )
            from pathlib import Path

            p = Path(path)
            transcripts_root = Path(tmp_path) / ".clawcodex" / "transcripts"
            assert p.parent == transcripts_root, (
                f"flat fallback parent must be the transcripts/ "
                f"directory; got {p.parent}, expected {transcripts_root}"
            )
            # flat fallback 不应污染 sessions/ 目录
            sessions_root = Path(tmp_path) / ".clawcodex" / "sessions"
            assert not str(p).startswith(str(sessions_root)), (
                f"flat fallback leaked into sessions/: {p}"
            )
            # 文件名应只是 <id>.jsonl (无 agent- 前缀), 与嵌套路径区分
            assert p.name == "a-fallback-test.jsonl", (
                f"flat fallback filename should be <id>.jsonl without "
                f"the 'agent-' prefix used in nested mode; got {p.name}"
            )
        finally:
            transcript._transcript_path_resolver = original_resolver
            transcript._flat_fallback_warned = original_warned
            import clawcodex_ext
            clawcodex_ext._nested_transcript_initialized = original_nested_flag
            reset()


class TestStage4Resilience:
    """Conversation / Session 恢复性测试 — P0#5 空/downstream保护, P1#10 损坏恢复, P2#15 并发写安全。"""

    def test_conversation_empty_messages_downstream(self):
        """空的 Conversation.get_messages() 返回 []，下游不炸。"""
        from src.agent.conversation import Conversation

        conv = Conversation()
        msgs = conv.get_messages()
        assert msgs == []

    def test_conversation_to_dict_from_dict_round_trip_empty(self):
        """空 Conversation to_dict → from_dict 不抛异常，messages 为空。"""
        from src.agent.conversation import Conversation

        conv = Conversation()
        data = conv.to_dict()
        restored = Conversation.from_dict(data)
        assert restored.get_messages() == []

    def test_conversation_from_dict_missing_messages_key(self):
        """from_dict 入参缺失 messages key 时不抛异常。"""
        from src.agent.conversation import Conversation

        conv = Conversation.from_dict({"max_history": 500})
        assert conv.get_messages() == []

    def test_conversation_from_dict_none_messages(self):
        """from_dict 入参 messages 为 None 时不抛异常。"""
        from src.agent.conversation import Conversation

        conv = Conversation.from_dict({"messages": None})
        assert conv.get_messages() == []

    def test_conversation_max_history_cap(self):
        """超过 max_history 时旧消息被截断，不爆炸。"""
        from src.agent.conversation import Conversation

        conv = Conversation(max_history=3)
        for i in range(5):
            conv.add_user_message(f"msg-{i}")
            conv.add_assistant_message(f"resp-{i}")
        msgs = conv.get_messages()
        assert len(msgs) <= 6  # 3 pairs max
        assert msgs[0]["content"] != "msg-0"  # 旧消息被弹出

    def test_session_load_nonexistent(self):
        """Session.load 不存在的 session_id 返回 None 而非抛异常。"""
        from src.agent.session import Session

        s = Session.load("__nonexistent_session_id_for_test__")
        assert s is None

    def test_session_save_and_load_round_trip(self, tmp_path):
        """Session.save 后 Session.load 能恢复。"""
        from pathlib import Path
        from unittest.mock import patch
        from src.agent.session import Session
        from src.agent.conversation import Conversation

        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        with patch("pathlib.Path.home", return_value=fake_home):
            conv = Conversation()
            conv.add_user_message("hello")
            conv.add_assistant_message("world")
            session = Session(session_id="test-save-load", provider="test", model="test", conversation=conv)
            session.save()
            loaded = Session.load("test-save-load")
            assert loaded is not None
            assert loaded.session_id == "test-save-load"
            msgs = loaded.conversation.get_messages()
            assert len(msgs) == 2

    def test_add_message_large_content(self):
        """给 Conversation 添加超长字符串不崩溃。"""
        from src.agent.conversation import Conversation

        conv = Conversation()
        large = "x" * 100_000
        conv.add_user_message(large)
        msgs = conv.get_messages()
        assert len(msgs) == 1
        assert len(msgs[0]["content"]) == 100_000
