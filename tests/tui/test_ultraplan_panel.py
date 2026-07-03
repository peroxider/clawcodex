from __future__ import annotations

from rich.console import Console

from clawcodex_ext.services.ultraplan import Plan, Step, StepStatus, SubPlan
from clawcodex_ext.tui.screens.ultraplan_panel import render_ultraplan_panel


def test_render_ultraplan_panel_contains_progress_and_steps() -> None:
    plan = Plan(
        id="p1",
        title="Panel",
        goal="Panel",
        sub_plans=[
            SubPlan(
                id="sp1",
                title="Work",
                description="Work",
                steps=[
                    Step(id="s1", title="Done", description="Done", status=StepStatus.COMPLETED),
                    Step(id="s2", title="Todo", description="Todo"),
                ],
            )
        ],
    )
    console = Console(record=True, width=100)
    console.print(render_ultraplan_panel(plan))
    exported = console.export_text()
    assert "p1 - Panel" in exported
    assert "progress: 1/2" in exported
    assert "s1: Done" in exported
