from __future__ import annotations

import pytest

pytest.importorskip("textual")

from clawcodex_ext.tui.widgets.prompt_input import PromptInput


def _prompt() -> PromptInput:
    return PromptInput(words_provider=lambda: [])


def test_prompt_input_shows_ultraplan_trigger_preview() -> None:
    prompt = _prompt()
    prompt._refresh_ultraplan_trigger_preview("/ultraplan refactor")  # type: ignore[attr-defined]
    assert not prompt._ultraplan_trigger_preview.has_class("-hidden")  # type: ignore[attr-defined]
    assert prompt._ultraplan_trigger_preview.renderable.plain == "ultraplan: /ultraplan refactor"  # type: ignore[attr-defined]


def test_prompt_input_hides_preview_for_middle_trigger() -> None:
    prompt = _prompt()
    prompt._refresh_ultraplan_trigger_preview("echo /ultraplan")  # type: ignore[attr-defined]
    assert prompt._ultraplan_trigger_preview.has_class("-hidden")  # type: ignore[attr-defined]
