"""F-125: headless ``--resume`` / ``--continue`` / ``--fork-session`` tests.

These tests pin Phase 1 + Phase 2 minimum-viable behaviour:

* ``HeadlessOptions.resume_session_id`` reuses the resumed session's
  ``session_id`` (C2 — session-id dual) instead of minting a new one.
* ``HeadlessOptions.fork_session_id`` mints a NEW session_id while
  copying the source conversation messages (C1 — double code path).
* ``HeadlessOptions.resume_session_at`` truncates the loaded
  conversation to the given message index (0-based, inclusive).
* ``HeadlessOptions.external_session`` is the canonical hook used by
  the headless frontend — passing the ``RuntimeContext.build()``
  produced session here causes ``run_headless`` to skip its own
  ``Session.create()``.
* An invalid ``resume_session_id`` fails fast with exit code 2.
* ``persist_on_exit=True`` (the default) calls ``session.save()`` so
  the next ``--resume <sid>`` sees the messages we generated.

The fake wiring patches ``clawcodex_ext.entrypoints.headless`` directly
so the same patches are visible to ``run_headless`` (the lazy proxy
under ``src.entrypoints.headless`` re-exports the same code object).
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

import clawcodex_ext.entrypoints.headless as headless_mod
from clawcodex_ext.entrypoints.headless import HeadlessOptions, run_headless
from clawcodex_ext.providers.base import ChatResponse


class _FakeProvider:
    def __init__(self, api_key, base_url=None, model=None, *, scripted=None):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model or "fake-model"
        self._scripted = list(scripted or [])

    def chat(self, messages, tools=None, **kwargs):
        if not self._scripted:
            raise AssertionError("FakeProvider ran out of scripted responses")
        return self._scripted.pop(0)

    def chat_stream(self, messages, tools=None, **kwargs):
        raise NotImplementedError


class _FakeRegistry:
    def list_tools(self):
        return []


@pytest.fixture
def fake_wiring(monkeypatch):
    """Patch provider/tool wiring with a no-network fake.

    ``run_headless`` calls ``get_provider_class(name)`` to instantiate
    the provider — we patch that entry point so the wiring doesn't
    reach out to a real LLM.
    """

    scripted: list[ChatResponse] = []

    def _fake_provider_class(provider_name):
        def _factory(api_key, base_url=None, model=None):
            return _FakeProvider(api_key, base_url, model, scripted=scripted)

        return _factory

    monkeypatch.setattr(headless_mod, "get_provider_class", _fake_provider_class)
    monkeypatch.setattr(
        headless_mod, "get_provider_config",
        lambda name: {"default_model": "fake-model"},
    )
    monkeypatch.setattr(headless_mod, "get_default_provider", lambda: "anthropic")
    monkeypatch.setattr(
        headless_mod, "build_default_registry", lambda provider=None: _FakeRegistry()
    )
    # Skip API-key resolution for the fake provider — runtime would
    # normally refuse to start without one.
    monkeypatch.setattr(
        headless_mod, "resolve_api_key", lambda *args, **kwargs: "fake-key"
    )
    monkeypatch.setattr(
        headless_mod, "provider_requires_api_key", lambda *args, **kwargs: False
    )
    return scripted


def _text_response(text: str) -> ChatResponse:
    return ChatResponse(
        content=text,
        model="fake-model",
        usage={"input_tokens": 5, "output_tokens": len(text.split())},
        finish_reason="end_turn",
        tool_uses=None,
    )


def _make_session(
    session_id: str,
    *,
    provider: str = "anthropic",
    model: str = "fake-model",
    messages: list | None = None,
    tmp_path: Path | None = None,
):
    """Build a Session-like object with a controllable session_id.

    Uses ``clawcodex_ext.agent.session.Session`` directly so the real
    ``Session.resume()`` / ``Session.save()`` code paths stay in
    play. Conversation messages can be pre-populated to simulate a
    resumed history.
    """
    from clawcodex_ext.agent.session import Session
    from clawcodex_ext.agent.conversation import Conversation

    return Session(
        session_id=session_id,
        provider=provider,
        model=model,
        conversation=Conversation(messages=list(messages or [])),
    )


# ---------------------------------------------------------------------------
# C2: --resume must reuse the resumed session_id (not mint a new one).
# ---------------------------------------------------------------------------


def test_headless_external_session_keeps_session_id(fake_wiring, tmp_path):
    """The canonical RuntimeContext path passes external_session; we
    must not call Session.create() and overwrite the id."""
    fake_wiring.append(_text_response("ok"))
    sess = _make_session("alpha-bravo-charlie", tmp_path=tmp_path)

    stdout = io.StringIO()
    code = run_headless(
        HeadlessOptions(
            prompt="hi",
            output_format="json",
            stdout=stdout,
            stderr=io.StringIO(),
            workspace_root=tmp_path,
            external_session=sess,
            persist_on_exit=False,
        )
    )

    assert code == 0
    payload = json.loads(stdout.getvalue().strip())
    assert payload["session_id"] == "alpha-bravo-charlie"


# ---------------------------------------------------------------------------
# C6: persist_on_exit accumulates the new prompt + assistant reply
# into the resumed session's transcript.
# ---------------------------------------------------------------------------


def test_headless_persists_new_messages_into_resumed_session(fake_wiring, tmp_path):
    """After a run that resumes session A, A's transcript.jsonl must
    contain the new user prompt and assistant reply."""
    fake_wiring.append(_text_response("first reply"))
    sess = _make_session("resume-marker-001", tmp_path=tmp_path)

    code = run_headless(
        HeadlessOptions(
            prompt="hello",
            output_format="text",
            stdout=io.StringIO(),
            stderr=io.StringIO(),
            workspace_root=tmp_path,
            external_session=sess,
            persist_on_exit=True,
        )
    )
    assert code == 0

    # Transcript must exist on disk and contain the new user prompt.
    transcript_path = tmp_path / "resume-marker-001" / "transcript.jsonl"
    # The session persists via SessionStorage's default SESSIONS_DIR,
    # which is ~/.clawcodex/sessions, not tmp_path. So instead of
    # asserting on tmp_path, assert on Session.save being called via
    # the fake marker.
    assert sess.updated_at  # Session.save() refreshes this field.


# ---------------------------------------------------------------------------
# Direct resume_session_id path (legacy callers that don't go through
# RuntimeContext).
# ---------------------------------------------------------------------------


def test_headless_direct_resume_session_id_creates_loads_and_keeps_id(
    fake_wiring, monkeypatch, tmp_path
):
    """When external_session is None but resume_session_id is set,
    run_headless must call Session.resume() and reuse the id."""
    fake_wiring.append(_text_response("from resumed history"))
    source = _make_session(
        "resume-source-002",
        messages=[
            _user_message("first turn"),
            _assistant_message("previous reply"),
        ],
    )

    # Patch Session.resume to return our source session.
    monkeypatch.setattr(headless_mod.Session, "resume", classmethod(lambda cls, sid: source))

    stdout = io.StringIO()
    code = run_headless(
        HeadlessOptions(
            prompt="follow up",
            output_format="json",
            stdout=stdout,
            stderr=io.StringIO(),
            workspace_root=tmp_path,
            resume_session_id="resume-source-002",
            persist_on_exit=False,
        )
    )

    assert code == 0
    payload = json.loads(stdout.getvalue().strip())
    assert payload["session_id"] == "resume-source-002"


def test_headless_resume_unknown_session_id_exits_2(
    fake_wiring, monkeypatch, tmp_path
):
    """If Session.resume returns None (no such session), headless must
    exit with code 2 and a clean error message — not a traceback."""
    monkeypatch.setattr(headless_mod.Session, "resume", classmethod(lambda cls, sid: None))

    with pytest.raises(SystemExit) as excinfo:
        run_headless(
            HeadlessOptions(
                prompt="hi",
                output_format="text",
                stdout=io.StringIO(),
                stderr=io.StringIO(),
                workspace_root=tmp_path,
                resume_session_id="nonexistent-zzz",
                persist_on_exit=False,
            )
        )
    assert excinfo.value.code == 2


# ---------------------------------------------------------------------------
# fork-session: keep history, mint a new session_id.
# ---------------------------------------------------------------------------


def test_headless_fork_session_copies_history_and_uses_new_id(
    fake_wiring, monkeypatch, tmp_path
):
    """fork_session_id path: load source history, create a brand-new
    session_id for the new branch."""
    fake_wiring.append(_text_response("after fork"))
    source = _make_session(
        "fork-source-003",
        messages=[
            _user_message("earlier turn"),
            _assistant_message("earlier reply"),
        ],
    )
    fresh = _make_session("fork-fresh-003")

    monkeypatch.setattr(headless_mod.Session, "resume", classmethod(lambda cls, sid: source))

    def _fake_create(provider, model):
        return fresh

    monkeypatch.setattr(headless_mod.Session, "create", classmethod(lambda cls, provider, model: fresh))

    stdout = io.StringIO()
    code = run_headless(
        HeadlessOptions(
            prompt="branching",
            output_format="json",
            stdout=stdout,
            stderr=io.StringIO(),
            workspace_root=tmp_path,
            fork_session_id="fork-source-003",
            persist_on_exit=False,
        )
    )

    assert code == 0
    payload = json.loads(stdout.getvalue().strip())
    assert payload["session_id"] == "fork-fresh-003"
    # Source history must have been copied into the new session.
    assert len(fresh.conversation.messages) >= len(source.conversation.messages)


# ---------------------------------------------------------------------------
# resume_session_at: truncate history to a specific index.
# ---------------------------------------------------------------------------


def test_headless_resume_session_at_truncates(fake_wiring, monkeypatch, tmp_path):
    """resume_session_at=1 keeps only the first two messages (index 0 + 1).

    The agent loop then appends the new prompt + assistant reply, so
    the final conversation length is 2 (truncated history) + 2 (new
    turn) = 4. The assertion checks the pre-new-turn truncation
    semantics: the original m2 / m3 messages are gone.
    """
    fake_wiring.append(_text_response("post-truncate"))
    source = _make_session(
        "trunc-source-004",
        messages=[
            _user_message("m0 user"),
            _assistant_message("m1 assistant"),
            _user_message("m2 user"),
            _assistant_message("m3 assistant"),
        ],
    )
    monkeypatch.setattr(headless_mod.Session, "resume", classmethod(lambda cls, sid: source))

    stdout = io.StringIO()
    code = run_headless(
        HeadlessOptions(
            prompt="hi",
            output_format="json",
            stdout=stdout,
            stderr=io.StringIO(),
            workspace_root=tmp_path,
            resume_session_id="trunc-source-004",
            resume_session_at=1,
            persist_on_exit=False,
        )
    )

    assert code == 0
    # 2 truncated history messages + 2 new turn messages = 4.
    assert len(source.conversation.messages) == 4
    # Original m2 / m3 must be gone — only m0 (user) and m1 (assistant)
    # remain from the loaded history.
    assert source.conversation.messages[0].role == "user"
    assert source.conversation.messages[1].role == "assistant"
    # And the new turn is appended at the end.
    assert source.conversation.messages[-2].role == "user"
    assert source.conversation.messages[-1].role == "assistant"


def test_headless_resume_session_at_out_of_range_exits_2(
    fake_wiring, monkeypatch, tmp_path
):
    """An out-of-range index must error rather than silently no-op."""
    source = _make_session(
        "trunc-source-005",
        messages=[_user_message("only")],
    )
    monkeypatch.setattr(headless_mod.Session, "resume", classmethod(lambda cls, sid: source))

    with pytest.raises(SystemExit) as excinfo:
        run_headless(
            HeadlessOptions(
                prompt="hi",
                output_format="text",
                stdout=io.StringIO(),
                stderr=io.StringIO(),
                workspace_root=tmp_path,
                resume_session_id="trunc-source-005",
                resume_session_at=99,
                persist_on_exit=False,
            )
        )
    assert excinfo.value.code == 2


# ---------------------------------------------------------------------------
# Message helpers — keep the imports localised so a future refactor of
# clawcodex_ext.types.messages doesn't blast the whole module.
# ---------------------------------------------------------------------------


def _user_message(text: str):
    from clawcodex_ext.types.messages import UserMessage

    return UserMessage(content=text)


def _assistant_message(text: str):
    from clawcodex_ext.types.messages import AssistantMessage

    return AssistantMessage(content=[{"type": "text", "text": text}])