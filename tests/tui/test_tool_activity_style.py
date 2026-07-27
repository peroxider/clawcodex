"""Visual contracts for flat tool-result trails."""

from __future__ import annotations

from io import StringIO

from rich.console import Console, Group
from rich.text import Text

from clawcodex_ext.tui.widgets.tool_activity.base import _with_trail_connector


def _render(renderable) -> str:
    stream = StringIO()
    Console(file=stream, force_terminal=False, width=80).print(renderable)
    return stream.getvalue()


def test_text_tool_result_indents_every_continuation_line() -> None:
    rendered = _render(_with_trail_connector(Text("line one\nline two")))
    lines = rendered.splitlines()

    assert lines[0].startswith("  ⎿  line one")
    assert lines[1].startswith("     line two")


def test_compound_tool_result_indents_the_entire_body() -> None:
    rendered = _render(_with_trail_connector(Group(Text("summary"), Text("diff"))))
    lines = rendered.splitlines()

    assert lines[0].startswith("  ⎿")
    assert lines[1].startswith("     summary")
    assert lines[2].startswith("     diff")
