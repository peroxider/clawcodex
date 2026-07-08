"""Built-in composite tool specs.

Composite tools are macro-level operations that orchestrate multiple atomic
tools into a workflow.  They are registered alongside regular per-component
tools and can emit ``workflow.yaml`` sidecars for the orchestrator engine.

Available builtins
------------------
* ``agent_teams`` — Delegate a task to a sub-agent team.
* ``pipeline_execute`` — Execute a multi-stage pipeline.
* ``code_review`` — Run code review and auto-fix on a PR branch.
"""

from __future__ import annotations

from pathlib import Path

from .models import CompositeStage, CompositeToolSpec


_INVOKE_EXISTING_AGENT_WRAPPER = Path(__file__).with_name("scripts").joinpath(
    "invoke_existing_agent_wrapper.py"
)


def builtin_composite_tools(*, bundle_dir: Path | None = None) -> list[CompositeToolSpec]:
    """Return all built-in composite tool specifications.

    These are the macro-level tools that stage agents and overview agents
    reference for cross-cutting orchestration patterns.
    """
    return [
        _agent_teams(),
        _pipeline_execute(),
        _code_review(),
        _invoke_existing_agent(bundle_dir=bundle_dir),
    ]


# ---------------------------------------------------------------------------
# Individual specs
# ---------------------------------------------------------------------------


def _agent_teams() -> CompositeToolSpec:
    """Delegate a task to a sub-agent team with automatic routing."""
    return CompositeToolSpec(
        name="agent_teams",
        description=(
            "Delegate a sub-task to an agent team.  The orchestrator routes "
            "the request to the most capable sub-agent based on the task "
            "description and available skill set."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Detailed task description for the sub-agent team.",
                },
                "target_skill": {
                    "type": "string",
                    "description": "Optional skill name to route the task to a specific agent.",
                },
                "delegation_mode": {
                    "type": "string",
                    "enum": ["auto", "explicit", "broadcast"],
                    "description": "How to delegate: auto=route by skill, explicit=use target_skill, broadcast=all agents.",
                },
            },
            "required": ["task"],
        },
        stages=[
            CompositeStage(
                name="task-analysis",
                description="Analyze the incoming task and determine the best sub-agent route.",
                agent_ref="agent_teams-analyze",
                expected_duration_s=15,
            ),
            CompositeStage(
                name="delegation",
                description="Delegate the task to the selected sub-agent.",
                agent_ref="agent_teams-delegate",
                expected_duration_s=60,
            ),
            CompositeStage(
                name="result-collection",
                description="Collect and consolidate results from sub-agents.",
                agent_ref="agent_teams-collect",
                expected_duration_s=30,
            ),
        ],
        tags=("composite", "macro", "teams", "delegation"),
        aliases=("agent-teams", "subagent-delegate"),
    )


def _pipeline_execute() -> CompositeToolSpec:
    """Execute a multi-stage pipeline with dependency ordering."""
    return CompositeToolSpec(
        name="pipeline_execute",
        description=(
            "Execute a multi-stage pipeline where each stage depends on one "
            "or more previous stages.  Stages are run in dependency order "
            "with automatic gate checks between transitions."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "pipeline_name": {
                    "type": "string",
                    "description": "Name of the pipeline definition to execute.",
                },
                "run_dir": {
                    "type": "string",
                    "description": "Absolute path to the pipeline run directory.",
                },
                "params": {
                    "type": "object",
                    "description": "Optional parameter overrides passed to each stage.",
                },
            },
            "required": ["pipeline_name", "run_dir"],
        },
        stages=[
            CompositeStage(
                name="pipeline-init",
                description="Initialize the pipeline run directory and validate configuration.",
                agent_ref="pipeline-init",
                expected_duration_s=10,
            ),
            CompositeStage(
                name="stage-execution",
                description="Execute pipeline stages sequentially, respecting dependency order.",
                agent_ref="pipeline-execute-stage",
                expected_duration_s=300,
            ),
            CompositeStage(
                name="post-processing",
                description="Collect artifacts, generate reports, and clean up.",
                agent_ref="pipeline-postprocess",
                expected_duration_s=30,
            ),
        ],
        tags=("composite", "macro", "pipeline"),
        aliases=("pipeline", "run-pipeline"),
    )


def _code_review() -> CompositeToolSpec:
    """Run a code review workflow with auto-fix and verification."""
    return CompositeToolSpec(
        name="code_review",
        description=(
            "Run an automated code review on the current branch, apply "
            "auto-fixable changes, run verification tests, and generate "
            "a review report.  Designed for PR review automation (F-37)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "branch": {
                    "type": "string",
                    "description": "Git branch to review.",
                },
                "auto_fix": {
                    "type": "boolean",
                    "description": "Apply auto-fixable changes (lint, format).",
                },
                "run_tests": {
                    "type": "boolean",
                    "description": "Run verification tests after auto-fix.",
                },
            },
            "required": ["branch"],
        },
        stages=[
            CompositeStage(
                name="diff-analysis",
                description="Analyze the diff and categorize changes.",
                agent_ref="code-review-diff",
                expected_duration_s=15,
            ),
            CompositeStage(
                name="auto-fix",
                description="Apply auto-fixable changes (lint, format, import sorting).",
                agent_ref="code-review-autofix",
                expected_duration_s=30,
            ),
            CompositeStage(
                name="verification",
                description="Run tests to verify the auto-fix didn't break anything.",
                agent_ref="code-review-verify",
                expected_duration_s=120,
            ),
            CompositeStage(
                name="report",
                description="Generate and post the review report.",
                agent_ref="code-review-report",
                expected_duration_s=10,
            ),
        ],
        tags=("composite", "macro", "review", "pr"),
        aliases=("code-review", "review-pr"),
    )


def _shell_quote(s: str) -> str:
    """POSIX single-quote escape: ' -> '\'' ."""
    return "'" + s.replace("'", "'\\''") + "'"


def _invoke_existing_agent(*, bundle_dir: Path | None = None) -> CompositeToolSpec:
    """Invoke a previously-created SOP agent by ``agent_id``.

    The tool looks up the agent in the bundle-local (or home-fallback)
    AgentCatalog, materializes the SDK class, and calls its ``invoke`` /
    ``run`` / ``__call__`` method.  This is the F-55 L1 recovery path
    for the create-then-invoke workflow break.
    """
    escaped_bundle = _shell_quote(str(bundle_dir)) if bundle_dir else ""
    wrapper = _INVOKE_EXISTING_AGENT_WRAPPER
    if bundle_dir is not None:
        call_impl = (
            f"python3 {wrapper} invoke_existing_agent '{{json_args}}' "
            f"--bundle-path {escaped_bundle}"
        )
    else:
        call_impl = f"python3 {wrapper} invoke_existing_agent '{{json_args}}'"
    return CompositeToolSpec(
        name="invoke_existing_agent",
        description=(
            "Invoke a previously-created agent by stable agent_id.  The tool "
            "loads the agent catalog, materializes the saved SDK class, and "
            "calls it with the provided query / inputs."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Stable agent_id returned by a prior build/create tool.",
                },
                "query": {
                    "type": "string",
                    "description": "Primary query / instruction passed to the agent.",
                },
                "inputs": {
                    "type": "object",
                    "description": "Optional additional inputs merged into the agent call.",
                },
            },
            "required": ["agent_id"],
        },
        stages=[
            CompositeStage(
                name="resolve-catalog",
                description="Load the bundle-local agent catalog by agent_id.",
            ),
            CompositeStage(
                name="materialize",
                description="Import the SDK module and instantiate the saved class.",
            ),
            CompositeStage(
                name="invoke",
                description="Call the agent's invoke/run method with the query.",
            ),
        ],
        tags=("composite", "macro", "agent-lifecycle", "f-55"),
        aliases=("invoke-existing-agent", "agent-invoke", "run-existing-agent"),
        call_type="bash",
        call_impl=call_impl,
        query_arg="query",
    )
