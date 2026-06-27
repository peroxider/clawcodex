"""F-89 unit tests for ``clawcodex_ext.agent_mention``.

Covers:
* Unquoted + quoted mention shapes.
* Case-insensitive normalisation.
* Kebab / snake / camel aliases all collapse to one type.
* Dedupe semantics (first occurrence wins).
* Known-types allow-list filtering.
* Strict mode (raise_on_unknown).
* Helper predicates (is_agent_mention, extract_agent_type).
* ``expand_mentions`` produces the same attachment shape as the legacy
  ``expand_agent_mentions`` from input_processing.
"""

from __future__ import annotations

from typing import Any

import pytest

from clawcodex_ext.agent_mention import (
    AgentMention,
    UnknownAgentMentionError,
    extract_agent_type,
    expand_mentions,
    is_agent_mention,
    parse_mentions,
)
from clawcodex_ext.command_system.input_processing import expand_agent_mentions


# ---------------------------------------------------------------------------
# parse_mentions — unquoted
# ---------------------------------------------------------------------------


def test_parse_simple_unquoted_mention() -> None:
    result = parse_mentions("hello @agent-explore world")
    assert len(result) == 1
    assert result[0].agent_type == "explore"
    assert result[0].kind == "unquoted"


def test_parse_mention_at_start_of_text() -> None:
    result = parse_mentions("@agent-critic hi")
    assert len(result) == 1
    assert result[0].agent_type == "critic"


def test_parse_mention_without_leading_whitespace_in_middle() -> None:
    result = parse_mentions("prefix @agent-foo suffix")
    assert len(result) == 1
    assert result[0].agent_type == "foo"


def test_parse_mention_does_not_match_email() -> None:
    """``user@example.com`` must not be parsed as a mention."""
    result = parse_mentions("contact user@example.com")
    assert result == []


def test_parse_mention_does_not_match_inline_at_word() -> None:
    """``hello@agent-foo`` must not be parsed."""
    result = parse_mentions("hello@agent-foo bar")
    assert result == []


# ---------------------------------------------------------------------------
# parse_mentions — quoted
# ---------------------------------------------------------------------------


def test_parse_quoted_mention() -> None:
    result = parse_mentions('ping @"reviewer (agent)" please')
    assert len(result) == 1
    assert result[0].agent_type == "reviewer"
    assert result[0].kind == "quoted"


def test_parse_unquoted_and_quoted_together() -> None:
    text = '@agent-explore and @"critic (agent)" — both please'
    result = parse_mentions(text)
    types = [m.agent_type for m in result]
    assert types == ["explore", "critic"]


# ---------------------------------------------------------------------------
# Case + alias normalisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("@agent-explore", "explore"),
        ("@Agent-Explore", "explore"),
        ("@AGENT-EXPLORE", "explore"),
        ("@agent-Explore", "explore"),
    ],
)
def test_case_insensitive(raw: str, expected: str) -> None:
    result = parse_mentions(raw)
    assert len(result) == 1
    assert result[0].agent_type == expected


def test_dash_dot_colon_at_alias_characters() -> None:
    """The regex accepts a few extras to round-trip file/agent-like names."""
    for raw in ("@agent-test.critic", "@agent-test_critic", "@agent-test:critic"):
        result = parse_mentions(raw)
        assert len(result) == 1, raw
        assert result[0].agent_type == raw[len("@agent-") :].lower()


# ---------------------------------------------------------------------------
# Dedupe
# ---------------------------------------------------------------------------


def test_duplicate_mention_is_deduped() -> None:
    text = "@agent-explore then @agent-explore again"
    result = parse_mentions(text)
    assert len(result) == 1
    assert result[0].agent_type == "explore"


def test_dedupe_across_unquoted_and_quoted() -> None:
    text = '@agent-explore vs @"explore (agent)"'
    result = parse_mentions(text)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# known_types allow-list
# ---------------------------------------------------------------------------


def test_unknown_mention_silently_dropped() -> None:
    result = parse_mentions("@agent-nope", known_types={"explore", "critic"})
    assert result == []


def test_known_mention_kept_with_allow_list() -> None:
    result = parse_mentions("@agent-explore", known_types={"explore", "critic"})
    assert len(result) == 1
    assert result[0].agent_type == "explore"


def test_raise_on_unknown_raises() -> None:
    with pytest.raises(UnknownAgentMentionError) as ei:
        parse_mentions(
            "@agent-mystery", known_types={"explore"}, raise_on_unknown=True
        )
    assert ei.value.agent_type == "mystery"


def test_raise_on_unknown_passes_for_known() -> None:
    result = parse_mentions(
        "@agent-explore", known_types={"explore"}, raise_on_unknown=True
    )
    assert len(result) == 1


def test_unknown_types_filter_does_not_raise_by_default() -> None:
    """Default mode = silent drop, matching TS UX."""
    result = parse_mentions("@agent-nope", known_types={"explore"})
    assert result == []


# ---------------------------------------------------------------------------
# Predicates & helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("hello world", False),
        ("", False),
        ("@agent-foo", True),
        ("ping @agent-bar please", True),
        ('@"reviewer (agent)"', True),
        ("user@example.com", False),
        ("@agent-foo @agent-bar", True),
    ],
)
def test_is_agent_mention(text: str, expected: bool) -> None:
    assert is_agent_mention(text) is expected


@pytest.mark.parametrize(
    "token, expected",
    [
        ("@agent-explore", "explore"),
        ("@agent-Explore", "explore"),
        ('@"reviewer (agent)"', "reviewer"),
        ('@"Critic (agent)"', "critic"),
        ("plain text", None),
        ("@agent-", None),  # empty type
        ("", None),
    ],
)
def test_extract_agent_type(token: str, expected: str | None) -> None:
    assert extract_agent_type(token) == expected


# ---------------------------------------------------------------------------
# expand_mentions — attachment shape parity with legacy
# ---------------------------------------------------------------------------


class _FakeAgent:
    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type


@pytest.fixture
def agents() -> list[_FakeAgent]:
    return [
        _FakeAgent("explore"),
        _FakeAgent("critic"),
        _FakeAgent("reviewer"),
    ]


def test_expand_mentions_returns_attachment_dicts(agents: list[_FakeAgent]) -> None:
    result = expand_mentions("@agent-explore please", agents)
    assert result == [{"kind": "agent_mention", "agent_type": "explore"}]


def test_expand_mentions_dedupes(agents: list[_FakeAgent]) -> None:
    result = expand_mentions("@agent-explore @agent-explore", agents)
    assert len(result) == 1


def test_expand_mentions_drops_unknown(agents: list[_FakeAgent]) -> None:
    result = expand_mentions("@agent-explore @agent-mystery", agents)
    assert result == [{"kind": "agent_mention", "agent_type": "explore"}]


def test_expand_mentions_accepts_dict_agents() -> None:
    agents = [{"agent_type": "explore"}, {"agent_type": "reviewer"}]
    result = expand_mentions("@agent-explore", agents)
    assert result == [{"kind": "agent_mention", "agent_type": "explore"}]


def test_expand_mentions_empty_inputs() -> None:
    assert expand_mentions("", [_FakeAgent("x")]) == []
    assert expand_mentions("@agent-x", None) == []
    assert expand_mentions("@agent-x", []) == []


def test_expand_mentions_strict_mode_raises_on_unknown() -> None:
    with pytest.raises(UnknownAgentMentionError):
        expand_mentions(
            "@agent-mystery", [_FakeAgent("explore")], raise_on_unknown=True
        )


# ---------------------------------------------------------------------------
# Parity with the legacy expand_agent_mentions (input_processing)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "@agent-explore check this",
        '@agent-explore vs @"critic (agent)"',
        "@Agent-EXPLORE another",
        "no mentions here",
        "@agent-unknown @agent-explore",
        "@agent-explore @agent-explore dup",
    ],
)
def test_new_expand_matches_legacy(text: str) -> None:
    """The new module must produce identical output to the legacy shim."""
    agents = [
        _FakeAgent("explore"),
        _FakeAgent("critic"),
        {"agent_type": "explore"},  # mixed shape
    ]
    legacy = expand_agent_mentions(text, agents)
    fresh = expand_mentions(text, agents)
    assert fresh == legacy


# ---------------------------------------------------------------------------
# Dataclass contract
# ---------------------------------------------------------------------------


def test_agent_mention_is_frozen() -> None:
    m = AgentMention(agent_type="explore", kind="unquoted", span=(0, 13))
    with pytest.raises(Exception):
        m.agent_type = "critic"  # type: ignore[misc]


def test_agent_mention_span_captures_source_range() -> None:
    text = "prefix @agent-explore suffix"
    result = parse_mentions(text)
    assert len(result) == 1
    start, end = result[0].span
    assert text[start:end] == "@agent-explore"