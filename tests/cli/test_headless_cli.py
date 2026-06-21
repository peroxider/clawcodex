"""Integration tests for the headless (``--print``) CLI path.

These tests bypass the real provider and tool registry by monkey-patching the
wiring inside ``src.entrypoints.headless`` so we can exercise the stdout
contract without any network IO.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from src.entrypoints import HeadlessOptions, run_headless
from src.entrypoints import headless as headless_mod
from clawcodex_ext.providers.base import ChatResponse

from clawcodex_ext.utils.resume_hint import reset_resume_hint_for_test_only


class _FakeProvider:
    """Minimal stand-in for an LLM provider.

    ``responses`` is a list of ``ChatResponse`` to return in order. If tool
    calls are requested, they must match the shape
    ``{"id": str, "name": str, "input": dict}``.
    """

    def __init__(self, api_key: str, base_url=None, model=None, *, responses=None):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model or "fake-model"
        self._responses = list(responses or [])

    def chat(self, messages, tools=None, **kwargs):
        if not self._responses:
            raise AssertionError("FakeProvider ran out of scripted responses")
        return self._responses.pop(0)

    def chat_stream(self, messages, tools=None, **kwargs):
        raise NotImplementedError


class _FakeRegistry:
    def list_tools(self):
        return []


@pytest.fixture
def fake_wiring(monkeypatch):
    """Patch provider/tool wiring with fakes that require no API key."""

    scripted_responses: list[ChatResponse] = []

    def _fake_build_provider_from_config(provider_name, model=None):
        return _FakeProvider("test-key", model=model, responses=list(scripted_responses))

    monkeypatch.setattr(
        headless_mod, "build_provider_from_config", _fake_build_provider_from_config
    )
    monkeypatch.setattr(headless_mod, "get_default_provider", lambda: "anthropic")
    monkeypatch.setattr(
        headless_mod, "build_default_registry", lambda provider=None: _FakeRegistry()
    )

    return scripted_responses


def _text_response(text: str) -> ChatResponse:
    return ChatResponse(
        content=text,
        model="fake-model",
        usage={"input_tokens": 5, "output_tokens": len(text.split())},
        finish_reason="end_turn",
        tool_uses=None,
    )


# ---------------------------------------------------------------------------
# text output


def test_headless_text_output_prints_assistant_reply(fake_wiring, tmp_path):
    fake_wiring.append(_text_response("Hello, human!"))

    stdout = io.StringIO()
    stderr = io.StringIO()
    code = run_headless(
        HeadlessOptions(
            prompt="hi",
            output_format="text",
            stdout=stdout,
            stderr=stderr,
            workspace_root=tmp_path,
        )
    )

    assert code == 0
    assert stdout.getvalue().strip() == "Hello, human!"


def test_headless_text_reads_prompt_from_stdin_when_dash(fake_wiring, tmp_path):
    fake_wiring.append(_text_response("from-stdin"))

    code = run_headless(
        HeadlessOptions(
            prompt="-",
            output_format="text",
            stdin=io.StringIO("piped prompt"),
            stdout=(out := io.StringIO()),
            stderr=io.StringIO(),
            workspace_root=tmp_path,
        )
    )

    assert code == 0
    assert "from-stdin" in out.getvalue()


# ---------------------------------------------------------------------------
# json output


def test_headless_json_output_emits_single_object(fake_wiring, tmp_path):
    fake_wiring.append(_text_response("json reply"))

    stdout = io.StringIO()
    code = run_headless(
        HeadlessOptions(
            prompt="hi",
            output_format="json",
            stdout=stdout,
            stderr=io.StringIO(),
            workspace_root=tmp_path,
        )
    )

    assert code == 0
    payload = json.loads(stdout.getvalue().strip())
    assert payload["type"] == "result"
    assert payload["subtype"] == "success"
    assert payload["result"] == "json reply"
    assert payload["provider"] == "anthropic"
    assert payload["num_turns"] == 1
    assert payload["usage"]["input_tokens"] == 5


# ---------------------------------------------------------------------------
# stream-json output


def test_headless_stream_json_emits_system_assistant_result(fake_wiring, tmp_path):
    fake_wiring.append(_text_response("stream reply"))

    stdout = io.StringIO()
    code = run_headless(
        HeadlessOptions(
            prompt="hi",
            output_format="stream-json",
            stdout=stdout,
            stderr=io.StringIO(),
            workspace_root=tmp_path,
        )
    )

    assert code == 0
    lines = [l for l in stdout.getvalue().splitlines() if l.strip()]
    parsed = [json.loads(l) for l in lines]
    types = [ev["type"] for ev in parsed]
    assert types[0] == "system"
    assert "assistant" in types
    assert types[-1] == "result"
    assistant = next(ev for ev in parsed if ev["type"] == "assistant")
    assert assistant["text"] == "stream reply"
    result = parsed[-1]
    assert result["result"] == "stream reply"
    assert result["num_turns"] == 1
    assert result["subtype"] == "success"


def test_headless_stream_json_input_requires_matching_output(fake_wiring, tmp_path):
    stderr = io.StringIO()
    with pytest.raises(SystemExit) as excinfo:
        run_headless(
            HeadlessOptions(
                prompt="hi",
                input_format="stream-json",
                output_format="text",
                stdout=io.StringIO(),
                stderr=stderr,
                workspace_root=tmp_path,
            )
        )
    assert excinfo.value.code == 2


def test_headless_stream_json_multi_turn_from_stdin(fake_wiring, tmp_path):
    fake_wiring.append(_text_response("A"))
    fake_wiring.append(_text_response("B"))

    stdin = io.StringIO(
        "\n".join(
            [
                json.dumps({"type": "user", "message": {"content": "one"}}),
                json.dumps({"type": "user", "message": {"content": "two"}}),
            ]
        )
        + "\n"
    )
    stdout = io.StringIO()
    code = run_headless(
        HeadlessOptions(
            output_format="stream-json",
            input_format="stream-json",
            stdin=stdin,
            stdout=stdout,
            stderr=io.StringIO(),
            workspace_root=tmp_path,
        )
    )

    assert code == 0
    parsed = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]
    assistants = [ev for ev in parsed if ev["type"] == "assistant"]
    assert [ev["text"] for ev in assistants] == ["A", "B"]
    result = parsed[-1]
    assert result["num_turns"] == 2
    assert "A" in result["result"] and "B" in result["result"]


# ---------------------------------------------------------------------------
# permission handling in headless mode


def test_headless_without_skip_permissions_installs_auto_deny_handler(fake_wiring, tmp_path):
    fake_wiring.append(_text_response("ok"))

    captured: dict = {}
    original = headless_mod.run_query_as_agent_loop

    async def _capture(*args, **kwargs):
        captured["tool_context"] = kwargs["tool_context"]
        return await original(*args, **kwargs)

    import src.entrypoints.headless as mod

    mod.run_query_as_agent_loop = _capture  # type: ignore[assignment]
    try:
        code = run_headless(
            HeadlessOptions(
                prompt="hi",
                output_format="text",
                stdout=io.StringIO(),
                stderr=io.StringIO(),
                workspace_root=tmp_path,
            )
        )
    finally:
        mod.run_query_as_agent_loop = original  # type: ignore[assignment]

    assert code == 0
    ctx = captured["tool_context"]
    assert ctx.options.is_non_interactive_session is True
    # Non-interactive mode installs an auto-deny handler that returns (False, False).
    allowed, _ = ctx.permission_handler("Bash", "needs approval", None)
    assert allowed is False


def test_headless_with_skip_permissions_clears_handler(fake_wiring, tmp_path):
    fake_wiring.append(_text_response("ok"))

    captured: dict = {}
    original = headless_mod.run_query_as_agent_loop

    async def _capture(*args, **kwargs):
        captured["tool_context"] = kwargs["tool_context"]
        return await original(*args, **kwargs)

    import src.entrypoints.headless as mod

    mod.run_query_as_agent_loop = _capture  # type: ignore[assignment]
    try:
        run_headless(
            HeadlessOptions(
                prompt="hi",
                output_format="text",
                skip_permissions=True,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
                workspace_root=tmp_path,
            )
        )
    finally:
        mod.run_query_as_agent_loop = original  # type: ignore[assignment]

    ctx = captured["tool_context"]
    assert ctx.permission_handler is None
    assert ctx.allow_docs is True
    assert ctx.options.is_non_interactive_session is True


# ---------------------------------------------------------------------------
# flag validation


def test_headless_invalid_output_format_exits_2(fake_wiring, tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        run_headless(
            HeadlessOptions(
                prompt="hi",
                output_format="bogus",
                stdout=io.StringIO(),
                stderr=io.StringIO(),
                workspace_root=tmp_path,
            )
        )
    assert excinfo.value.code == 2


def test_headless_empty_prompt_exits_2(fake_wiring, tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        run_headless(
            HeadlessOptions(
                prompt="",
                output_format="text",
                stdin=io.StringIO(""),
                stdout=io.StringIO(),
                stderr=io.StringIO(),
                workspace_root=tmp_path,
            )
        )
    assert excinfo.value.code == 2


# ---------------------------------------------------------------------------
# S-R1: resume hint on text / json / stream-json output
#
# The headless entrypoint should print the standard
# ``Resume this session with: clawcodex --resume <sid>`` line to a TTY in
# text mode. JSON and stream-json consumers already receive the session id
# in their structured payload, so the hint must not pollute those streams.


class _FakeTTYStdout:
    """Minimal stdout that pretends to be a TTY.

    The resume-hint helper gates on ``stream.isatty()``; this stand-in
    lets the text-mode test exercise the gate being open.
    """

    def __init__(self) -> None:
        self._buf = io.StringIO()

    def isatty(self) -> bool:
        return True

    def write(self, s: str) -> int:
        return self._buf.write(s)

    def flush(self) -> None:
        self._buf.flush()

    def getvalue(self) -> str:
        return self._buf.getvalue()


def _wire_tty_wiring(monkeypatch, scripted_responses):
    """Self-contained fixture for the S-R1 headless tests.

    Patches the *real* ext module (not the src.entrypoints proxy) so
    ``run_headless`` can run with no API key, no real provider, and no
    real tool registry.
    """
    import clawcodex_ext.entrypoints.headless as ext_headless

    def _fake_get_provider_class(_name):
        def _factory(api_key, base_url=None, model=None, **_kwargs):
            return _FakeProvider(api_key, model=model, responses=list(scripted_responses))
        return _factory

    def _fake_get_provider_config(_name):
        return {
            "api_key": "test-key",
            "base_url": None,
            "default_model": "fake-model",
        }

    monkeypatch.setattr(
        ext_headless, "get_provider_class", _fake_get_provider_class, raising=False
    )
    monkeypatch.setattr(
        ext_headless, "get_provider_config", _fake_get_provider_config, raising=False
    )
    monkeypatch.setattr(
        ext_headless, "get_default_provider", lambda: "anthropic", raising=False
    )
    monkeypatch.setattr(
        ext_headless, "build_default_registry", lambda provider=None: _FakeRegistry(),
        raising=False,
    )


@pytest.fixture
def tty_fake_wiring(monkeypatch):
    """Per-test scripted responses + TTY-friendly provider wiring."""
    reset_resume_hint_for_test_only()
    scripted: list[ChatResponse] = []
    _wire_tty_wiring(monkeypatch, scripted)
    return scripted


def test_headless_text_output_prints_resume_hint_on_tty(tty_fake_wiring, tmp_path):
    """S-R1: text mode on a TTY must append the resume hint after the reply."""
    tty_fake_wiring.append(_text_response("Hello, human!"))

    stdout = _FakeTTYStdout()
    stderr = io.StringIO()
    code = run_headless(
        HeadlessOptions(
            prompt="hi",
            output_format="text",
            stdout=stdout,  # type: ignore[arg-type]
            stderr=stderr,
            workspace_root=tmp_path,
        )
    )

    assert code == 0
    rendered = stdout.getvalue()
    # The reply is still emitted first.
    assert "Hello, human!" in rendered
    # The hint follows, matching the CCB ``printResumeHint()`` format.
    assert "Resume this session with: clawcodex --resume " in rendered
    # Pull the session id from the hint and confirm it is at least 16 chars.
    after = rendered.split("Resume this session with: clawcodex --resume ", 1)[1]
    sid = after.strip().splitlines()[0].strip()
    assert len(sid) >= 16, f"session id looks too short: {sid!r}"


def test_headless_json_output_omits_resume_hint(tty_fake_wiring, tmp_path):
    """S-R1: JSON mode must not append the hint — the structured
    ``session_id`` field is the canonical channel for machine consumers.
    """
    tty_fake_wiring.append(_text_response("json reply"))

    stdout = io.StringIO()
    code = run_headless(
        HeadlessOptions(
            prompt="hi",
            output_format="json",
            stdout=stdout,
            stderr=io.StringIO(),
            workspace_root=tmp_path,
        )
    )

    assert code == 0
    rendered = stdout.getvalue()
    # No human-readable hint text on the JSON stream.
    assert "Resume this session with:" not in rendered
    assert "clawcodex --resume" not in rendered
    # But the structured payload still carries the session id.
    payload = json.loads(rendered.strip())
    assert payload["session_id"]
    assert len(payload["session_id"]) >= 16


def test_headless_stream_json_output_omits_resume_hint(tty_fake_wiring, tmp_path):
    """S-R1: stream-json mode must not append the hint either —
    the session id is already in the SystemEvent and ResultEvent frames.
    """
    tty_fake_wiring.append(_text_response("stream reply"))

    stdout = io.StringIO()
    code = run_headless(
        HeadlessOptions(
            prompt="hi",
            output_format="stream-json",
            stdout=stdout,
            stderr=io.StringIO(),
            workspace_root=tmp_path,
        )
    )

    assert code == 0
    rendered = stdout.getvalue()
    # The structured frames contain the session id; the plain-text hint
    # must not appear anywhere on the stream.
    assert "Resume this session with:" not in rendered
    assert "clawcodex --resume" not in rendered
    # Verify the session id is still in the structured frames.
    frames = [json.loads(l) for l in rendered.splitlines() if l.strip()]
    assert any("session_id" in f and f["session_id"] for f in frames)
