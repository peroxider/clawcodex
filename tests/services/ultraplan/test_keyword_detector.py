from __future__ import annotations

from clawcodex_ext.services.ultraplan.keyword_detector import (
    find_ultraplan_trigger_positions,
    is_ultraplan_command,
    replace_ultraplan_keyword,
)


def test_detects_command_at_line_start_after_spaces() -> None:
    hits = find_ultraplan_trigger_positions("  /ultraplan refactor executor.py")
    assert hits[0].start == 2
    assert hits[0].keyword == "/ultraplan"
    assert is_ultraplan_command("  /ultraplan refactor executor.py")


def test_does_not_treat_middle_text_as_submit_command() -> None:
    assert find_ultraplan_trigger_positions("echo /ultraplan") != []
    assert not is_ultraplan_command("echo /ultraplan")


def test_skips_escaped_and_quoted_triggers() -> None:
    assert find_ultraplan_trigger_positions("\\/ultraplan foo") == []
    assert find_ultraplan_trigger_positions('"/ultraplan"') == []
    assert find_ultraplan_trigger_positions("`/ultraplan`") == []


def test_skips_when_inside_code_fence() -> None:
    assert find_ultraplan_trigger_positions("/ultraplan foo", inside_code_fence=True) == []


def test_replace_only_detected_keywords() -> None:
    text = "/up foo and '/up bar'"
    assert replace_ultraplan_keyword(text, "/up", "/ultraplan") == "/ultraplan foo and '/up bar'"
