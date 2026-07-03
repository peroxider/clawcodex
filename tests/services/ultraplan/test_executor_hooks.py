from __future__ import annotations

from clawcodex_ext.services.ultraplan import Plan, PlanExecutor, Step, StepStatus, SubPlan


def test_executor_transition_hook_receives_plan_id_and_transition() -> None:
    plan = Plan(
        id="p1",
        title="Hooked",
        goal="Hooked",
        sub_plans=[
            SubPlan(
                id="sp1",
                title="Work",
                description="Work",
                steps=[Step(id="s1", title="Step", description="Step")],
            )
        ],
    )
    seen = []
    executor = PlanExecutor(plan, transition_hooks=[lambda plan_id, tr: seen.append((plan_id, tr))])

    executor.mark_in_progress("s1")

    assert seen[0][0] == "p1"
    assert seen[0][1].step_id == "s1"
    assert seen[0][1].new_status is StepStatus.IN_PROGRESS
