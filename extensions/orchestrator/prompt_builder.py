"""Build agent prompts from Linear issue data.

Port of Symphony's PromptBuilder (Solid template → Jinja2).
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined, TemplateError

from .tracker import PullRequestFeedback, PullRequestRef
from .workflow_store import get_workflow_store

logger = logging.getLogger(__name__)

# Jinja2 environment with strict undefined handling (mirrors Solid's strict_variables)
_jinja_env = Environment(undefined=StrictUndefined)

_DEFAULT_PROMPT = """You are an autonomous software engineering agent.

Issue: {{ issue.identifier }} - {{ issue.title }}
{% if issue.description %}
Description:
{{ issue.description }}
{% endif %}
{% if issue.priority %}
Priority: {{ issue.priority }}
{% endif %}
{% if issue.state %}
State: {{ issue.state }}
{% endif %}

Please analyze the issue, implement the necessary changes, and ensure all tests pass.

## CLI Usage Guidelines
When you need to suggest terminal commands for the user:
- Always use the `clawcodex-dev` CLI entrypoint, NOT `python3 -c` or `PYTHONPATH=`.
- For orchestrator status: `clawcodex-dev orchestrator server status`
- For issue list: `clawcodex-dev orchestrator issue list`
- For issue tail: `clawcodex-dev orchestrator issue tail --id <id>`
- For other commands: use `clawcodex-dev orchestrator --help` or `clawcodex-dev --help`
{% if clarification %}
{{ clarification }}
{% endif %}
"""


# Jinja2 template for clarification guidance injected into the prompt.
# Rendered when an issue is in the clarification flow.
_CLARIFICATION_TEMPLATE = """
---
## Clarification Context

This issue is currently awaiting clarification. When the answer is available,
it will be provided below. If you are unsure about any aspect of the issue,
use the `AskIssueAuthor` tool to request clarification from the issue author
or local operator.

When requesting clarification:
- Be specific: ask exactly what is ambiguous (e.g., "Should this function be sync or async?")
- Provide context: include relevant code snippets or error messages
- Limit to one question at a time to avoid overwhelming responders
{% if pending_question %}
- Current pending question: "{{ pending_question }}"
{% if options %}
- Available options: {{ options|join(', ') }}
{% endif %}
{% endif %}
---"""

_REVIEW_FEEDBACK_TEMPLATE = """You are an autonomous software engineering agent fixing pull request feedback.

Issue: {{ issue.identifier }} - {{ issue.title }}
Pull request: {% if pull_request.number %}#{{ pull_request.number }}{% else %}unknown{% endif %}{% if pull_request.url %} ({{ pull_request.url }}){% endif %}
Branch: {{ branch_name }}

Current task:
- Fix only the PR review feedback and CI failures listed below.
- Do not expand scope or reimplement unrelated issue requirements.
- Work on the current branch only; do not create a new branch or pull request.
- Prefer the smallest correct change that addresses the feedback.
- If feedback is conflicting or unclear, leave code unchanged for that item and explain what clarification is needed.
- Run relevant tests or record why they cannot be run.
- CLI Usage: when suggesting terminal commands, use `clawcodex-dev` not `python3 -c` or `PYTHONPATH=`.

Feedback:
{% for item in feedback %}
{{ loop.index }}. [{{ item.source }}] {{ item.id }}{% if item.severity %} severity={{ item.severity }}{% endif %}{% if item.status %} status={{ item.status }}{% endif %}
{% if item.file_path %}   File: {{ item.file_path }}{% if item.line %}:{{ item.line }}{% endif %}
{% endif %}{% if item.commit_sha %}   Commit: {{ item.commit_sha }}
{% endif %}{% if item.url %}   URL: {{ item.url }}
{% endif %}{% if item.diff_hunk %}   Diff hunk:
```diff
{{ item.diff_hunk }}
```
{% endif %}   Body:
{{ item.body | indent(3) }}
{% endfor %}
"""


class PromptBuilder:
    """Render agent prompts from issue data + workflow config."""

    @staticmethod
    def render(
        issue: Any,
        attempt: int | None = None,
        clarification_context: str | None = None,
        pending_question: str | None = None,
        options: list[str] | None = None,
        session: Any | None = None,
        python_executable: str | None = None,
    ) -> str:
        """Build prompt using workflow's WORKFLOW.md body template + issue data.

        Args:
            issue: Issue object with to_dict() method or dict-like
            attempt: Current attempt number (for retry tracking)
            clarification_context: Pre-rendered clarification guidance block
            pending_question: If issue is in clarification flow, the pending question
            options: If in clarification flow, the available options for the question
        """
        store = get_workflow_store()
        current = store.current()

        if current:
            template_str = current[1]
        else:
            template_str = _DEFAULT_PROMPT

        if not template_str or not template_str.strip():
            template_str = _DEFAULT_PROMPT

        try:
            template = _jinja_env.from_string(template_str)
        except TemplateError as exc:
            logger.error("Template parse error: %s", exc)
            template = _jinja_env.from_string(_DEFAULT_PROMPT)

        issue_dict = issue.to_dict() if hasattr(issue, "to_dict") else issue
        context = {
            "attempt": attempt,
            "issue": _to_jinja_value(issue_dict),
            "clarification": clarification_context,
            "pending_question": pending_question,
            "options": options,
        }

        try:
            rendered = template.render(context).strip()
        except TemplateError as exc:
            logger.error("Template render error: %s", exc)
            # Fallback to default prompt
            fallback = _jinja_env.from_string(_DEFAULT_PROMPT)
            rendered = fallback.render(context).strip()
        if session is not None and getattr(session, "workspace_strategy", None) == "sequential":
            rendered = f"{rendered}\n\n{_build_sequential_workspace_context(session)}"

        # F-40 root-cause fix: inject workspace diff context so the
        # agent sees exactly which files are already modified and can
        # skip re-exploration when code already exists on disk.
        # Only injected when there are uncommitted changes (first turn).
        ws_path = _resolve_workspace_path(session)
        ws_diff = _get_workspace_diff(ws_path) if ws_path else None
        if ws_diff:
            rendered = (
                "---\n"
                "## Current Workspace Changes\n"
                "\n"
                "The following files have already been modified or created in the\n"
                "workspace but are not yet committed. If these changes match the\n"
                "current issue's requirements, **do not re-implement them**.\n"
                "Skip directly to `git add` + `git commit`.\n"
                "\n"
                f"{ws_diff}\n"
                "---\n"
                "\n"
                f"{rendered}"
            )

        if python_executable:
            rendered = (
                f"⛔ **约束提醒**：始终用 `{python_executable}` 绝对路径运行 Python，"
                f"不要调试环境差异。\n\n{rendered}"
            )

        return rendered

    @staticmethod
    def render_review_feedback(
        *,
        issue: Any,
        pull_request: PullRequestRef,
        branch_name: str,
        feedback: list[PullRequestFeedback],
    ) -> str:
        issue_dict = issue.to_dict() if hasattr(issue, "to_dict") else issue
        context = {
            "issue": _to_jinja_value(issue_dict),
            "pull_request": pull_request,
            "branch_name": branch_name,
            "feedback": feedback,
        }
        try:
            return _jinja_env.from_string(_REVIEW_FEEDBACK_TEMPLATE).render(context).strip()
        except TemplateError as exc:
            logger.error("Review feedback template render error: %s", exc)
            return _DEFAULT_PROMPT

    @staticmethod
    def render_feedback_summary(
        *,
        attempt: int,
        processed: list[PullRequestFeedback],
        skipped: list[dict],
    ) -> str:
        """Render a post-followup summary for the PR.

        Args:
            attempt: Follow-up attempt number.
            processed: Feedback items that were auto-handled.
            skipped: Dicts with keys ``feedback`` (PullRequestFeedback)
                and ``reason`` (str) for items needing human attention.
        """
        lines = [
            "## ClawCodex PR Review Follow-up Summary",
            "",
            f"**Follow-up attempt**: #{attempt}",
            f"**Processed**: {len(processed)} item(s)",
        ]
        if processed:
            lines += ["", "### Auto-handled"]
            for item in processed:
                loc = ""
                if item.file_path:
                    loc = f" (`{item.file_path}"
                    if item.line:
                        loc += f":{item.line}"
                    loc += "`)"
                body_preview = (item.body or "")[:80]
                if len(item.body or "") > 80:
                    body_preview += "..."
                lines.append(f"- [{item.source}] {item.id}{loc}: {body_preview}")
        if skipped:
            lines += ["", "### Needs human attention"]
            for entry in skipped:
                fb = entry["feedback"]
                reason = entry["reason"]
                loc = ""
                if fb.file_path:
                    loc = f" (`{fb.file_path}"
                    if fb.line:
                        loc += f":{fb.line}"
                    loc += "`)"
                lines.append(f"- [{fb.source}] {fb.id}{loc}: {reason}")
        return "\n".join(lines)

    @staticmethod
    def build_continuation_prompt(
        turn_number: int,
        max_turns: int,
        issue_context: str | None = None,
        session: Any | None = None,
        python_executable: str | None = None,
    ) -> str:
        """Build continuation prompt for subsequent turns.

        F-54 root-cause fix: inject a summary of recent git commits
        so the LLM can see what has already been done in previous
        turns and avoid re-exploring from scratch.
        """
        context_block = f"\n\nCurrent issue context:\n{issue_context}\n" if issue_context else ""
        urgency = (
            f"\n- ⚠️  You have only {max_turns - turn_number + 1} turn(s) remaining. "
            f"Prioritize code implementation over reading more files. "
            f"Use Write/Edit to make concrete changes NOW."
            if turn_number >= max_turns // 2
            else ""
        )

        # F-54 root-cause fix: inject recent git log so the LLM knows
        # what was already done in previous turns.
        git_log_summary = _get_git_log_summary(session)

        python_constraint = (
            f"⛔ **约束提醒**：始终用 `{python_executable}` 绝对路径，不要调试环境差异。\n"
            if python_executable
            else ""
        )

        return (
            f"Continuation guidance:\n\n"
            f"{python_constraint}"
            f"⛔ `pytest` 禁止使用管道 `| tail -40`/`| head -50`，用 `--tb=short -q` 替代。\n"
            f"⛔ 建议终端命令时用 `clawcodex-dev` CLI，不要用 `python3 -c` 或 `PYTHONPATH=`。\n"
            f"- This is continuation turn #{turn_number} of {max_turns}.{context_block}{urgency}\n"
            f"- Resume from the current workspace state and continue implementing.\n"
            f"- Use available tools (Bash, Write, Edit, Grep, Glob, etc.) to make changes.\n"
            f"- Focus on completing the issue requirements. Do NOT re-read files you have already explored.\n"
            f"- Your FIRST action should be a Write or Edit to implement the feature.\n"
            f"{git_log_summary}"
        )

    @staticmethod
    def build_clarification_context(
        pending_question: str | None = None,
        options: list[str] | None = None,
    ) -> str:
        """Build a clarification guidance block for the system prompt.

        This text is injected into the agent's prompt when an issue is in
        the clarification flow, guiding the agent to use AskIssueAuthor
        correctly and informing it about any pending question.

        Args:
            pending_question: The pending clarification question, if any
            options: Available options (for multiple-choice questions)

        Returns:
            A formatted clarification guidance block, or empty string if
            clarification is not active
        """
        if not pending_question:
            return ""

        template_str = _CLARIFICATION_TEMPLATE.strip()
        try:
            template = _jinja_env.from_string(template_str)
        except TemplateError as exc:
            logger.error("Clarification template parse error: %s", exc)
            return ""

        context = {
            "pending_question": pending_question,
            "options": options or [],
        }
        try:
            return template.render(context).strip()
        except TemplateError as exc:
            logger.error("Clarification template render error: %s", exc)
            return ""


def _build_sequential_workspace_context(session: Any) -> str:
    return "\n".join(
        [
            "---",
            "## Sequential Workspace Context",
            "",
            "This issue is running in a sequential shared workspace.",
            f"- Workspace strategy: `{getattr(session, 'workspace_strategy', 'sequential')}`",
            f"- Integration branch: `{getattr(session, 'integration_branch', None) or 'current branch'}`",
            f"- Start commit: `{getattr(session, 'start_commit_sha', None) or 'unknown'}`",
            f"- Base commit: `{getattr(session, 'base_commit_sha', None) or 'unknown'}`",
            f"- Previous issue: `{getattr(session, 'previous_issue_id', None) or 'none'}`",
            f"- Sequence index: `{getattr(session, 'sequence_index', None) or 'unknown'}`",
            "",
            "Build on the existing commit chain in this workspace. Do not redo earlier issues.",
            "If the expected prior commit chain appears to be missing, stop and report it.",
            "---",
        ]
    )


def _to_jinja_value(value: Any) -> Any:
    """Coerce a value into Jinja2-friendly shapes."""
    if isinstance(value, dict):
        return {str(k): _to_jinja_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_jinja_value(v) for v in value]
    return value


def _resolve_workspace_path(session: Any) -> Path | None:
    """Extract the workspace root path from a session object.
    
    Returns None when there is no session or no workspace, which means
    the workspace-diff context is silently skipped.
    """
    if session is None:
        return None
    ws = getattr(session, "workspace", None)
    if ws is None:
        return None
    path = getattr(ws, "path", None)
    if path is None:
        return None
    return Path(path)


def _get_workspace_diff(ws_path: Path) -> str | None:
    """Run ``git diff --stat`` and ``git status --short`` in the
    workspace to produce a compact summary of uncommitted changes.
    
    Returns ``None`` when the workspace is clean (no changes), so the
    caller can skip injecting the diff context block entirely.
    """
    try:
        proc = subprocess.run(
            ["git", "diff", "--stat", "HEAD"],
            cwd=str(ws_path),
            capture_output=True,
            text=True,
            timeout=10,
        )
        diff_stat = proc.stdout.strip()
        proc2 = subprocess.run(
            ["git", "status", "--short"],
            cwd=str(ws_path),
            capture_output=True,
            text=True,
            timeout=10,
        )
        status_short = proc2.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None

    if not diff_stat and not status_short:
        return None  # clean workspace — nothing to inject
    parts = []
    if diff_stat:
        parts.append(f"```\n{diff_stat}\n```")
    if status_short:
        parts.append(f"Uncommitted files:\n```\n{status_short}\n```")
    return "\n".join(parts)


def _get_git_log_summary(session: Any) -> str:
    """Run ``git log --oneline -3`` in the workspace and return a
    compact summary of recent commits, or an empty string when there
    is no session / workspace / git history.

    F-54 root-cause fix: injected into continuation prompts so the
    LLM can see what has already been committed in previous turns
    and avoid re-exploring from scratch.
    """
    if session is None:
        return ""
    ws = getattr(session, "workspace", None)
    if ws is None:
        return ""
    ws_path = getattr(ws, "path", None)
    if ws_path is None:
        return ""
    try:
        proc = subprocess.run(
            ["git", "log", "--oneline", "-3"],
            cwd=str(ws_path),
            capture_output=True,
            text=True,
            timeout=10,
        )
        log_out = proc.stdout.strip()
        if not log_out:
            return ""
        return f"\nRecent commits in workspace:\n```\n{log_out}\n```\n"
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


# ─── Python interpreter detection + cascade resolver ────────────────
# F-?? workspace-level python_executable: detect the interpreter
# inside the target repo via project-level signals, then expose a
# cascade so the prompt builder can pick the most specific value.


def _parse_pyvenv_home(cfg_path: Path) -> str:
    """Extract ``home = <path>`` from a pyvenv.cfg file.

    Returns the home directory string or ``""`` on parse failure /
    missing file. Soft-fails by design: malformed pyvenv.cfg must
    not block prompt rendering.
    """
    try:
        text = cfg_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.lower().startswith("home"):
            _, _, value = stripped.partition("=")
            return value.strip().strip('"').strip("'")
    return ""


def _parse_conda_env_name(yml_path: Path) -> str:
    """Extract the conda env ``name:`` from an environment.yml.

    Returns the env name or ``""`` if no ``name:`` key is set.
    """
    try:
        text = yml_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.lower().startswith("name"):
            _, _, value = stripped.partition(":")
            return value.strip().strip('"').strip("'")
    return ""


# Ordered conda root locations probed when an ``environment.yml`` is
# present. ``CONDA_PREFIX`` is consulted first when set (covers any
# non-standard install location), then the common defaults.
_CONDA_ROOT_CANDIDATES: tuple[str, ...] = (
    "/opt/conda",
    "/root/anaconda3",
    "/root/miniconda3",
    "/usr/local/anaconda3",
    "/usr/local/miniconda3",
    "/opt/anaconda3",
)


def _detect_python_in_workspace(
    workspace_path: Path | None,
    candidates: list[str],
) -> str:
    """Walk a list of project-level signals and return the absolute
    path of the first Python interpreter that can be derived from
    them. Returns ``""`` when nothing matches.

    Soft-fails: missing files, malformed contents, or non-existent
    interpreter binaries are silently skipped — the function is
    best-effort and never raises.

    Recognised probe kinds (matched by relative path):

    * ``.python-version`` — pyenv version spec; resolved against
      ``$PYENV_ROOT`` or ``~/.pyenv/versions/<v>/bin/python3``.
    * ``pyvenv.cfg`` and ``.venv/pyvenv.cfg`` — venv / uv / poetry
      venv markers; the ``home = ...`` line gives the venv root.
    * ``environment.yml`` — conda env file; ``name:`` is matched
      against ``$CONDA_PREFIX`` and a set of well-known conda
      install prefixes.
    * ``Pipfile`` and ``pyproject.toml`` — recognised but skipped
      because they describe dependencies rather than interpreter
      paths. Listed in the default candidates so operators can
      disable them via ``python_detect_files`` if desired.
    """
    if workspace_path is None:
        return ""
    workspace_path = Path(workspace_path)
    if not workspace_path.exists():
        return ""

    for rel in candidates:
        f = workspace_path / rel
        if not f.exists() or not f.is_file():
            continue
        try:
            if rel == ".python-version":
                version = f.read_text(encoding="utf-8", errors="replace").strip()
                if version:
                    pyenv_root = Path(
                        os.environ.get("PYENV_ROOT", str(Path.home() / ".pyenv"))
                    )
                    py = pyenv_root / "versions" / version / "bin" / "python3"
                    if py.exists():
                        return str(py)
            elif rel.endswith("pyvenv.cfg"):
                home = _parse_pyvenv_home(f)
                if home:
                    py = Path(home) / "bin" / "python3"
                    if py.exists():
                        return str(py)
            elif rel == "environment.yml":
                env_name = _parse_conda_env_name(f)
                if env_name:
                    conda_prefix = os.environ.get("CONDA_PREFIX", "").strip()
                    roots: list[str] = [conda_prefix] if conda_prefix else []
                    roots += list(_CONDA_ROOT_CANDIDATES)
                    for root in roots:
                        if not root:
                            continue
                        py = Path(root) / "envs" / env_name / "bin" / "python3"
                        if py.exists():
                            return str(py)
            elif rel in ("Pipfile", "pyproject.toml"):
                continue
        except OSError:
            continue
    return ""


def resolve_python_executable(
    *,
    workspace_path: Path | None,
    agent_cfg: Any,
    workspace_cfg: Any,
    issue_executable: str = "",
) -> str:
    """Cascade resolver: pick the most specific Python interpreter
    path available.

    Resolution order (first non-empty wins):

    1. ``issue_executable`` — per-issue override (e.g. from
       ``LocalTracker`` frontmatter ``python_executable: ...``).
       Highest priority because a single issue may legitimately
       need a different interpreter than its sibling issues in the
       same workspace.
    2. ``workspace_cfg.python_executable`` — explicit per-workspace
       override (handles "different repo needs different python").
    3. Auto-detected path via
       :func:`_detect_python_in_workspace` when
       ``workspace_cfg.python_auto_detect`` is True.
    4. ``agent_cfg.python_executable`` — workflow-wide default
       (the MVP-1 knob).
    5. Empty string — caller should treat as "no constraint"; the
       agent will rely on PATH ``python3``.

    Args:
        workspace_path: Absolute path to the workspace directory
            (``Workspace.path``), or ``None`` when there is no
            workspace yet (e.g. unit tests).
        agent_cfg: An ``AgentConfig``-like object exposing
            ``python_executable``.
        workspace_cfg: A ``WorkspaceConfig``-like object exposing
            ``python_executable``, ``python_auto_detect`` and
            ``python_detect_files``.
        issue_executable: Per-issue override string. ``""`` (the
            default) skips this level entirely. Provided by the
            caller from ``Issue.python_executable`` (populated by
            ``LocalTrackerAdapter`` from the issue markdown
            frontmatter).

    Returns:
        Absolute path string, or ``""`` when no constraint applies.
    """
    issue_override = (issue_executable or "").strip()
    if issue_override:
        return issue_override

    ws_explicit = getattr(workspace_cfg, "python_executable", "") or ""
    if ws_explicit:
        return ws_explicit

    auto_detect = getattr(workspace_cfg, "python_auto_detect", True)
    if auto_detect:
        detect_files = list(
            getattr(workspace_cfg, "python_detect_files", None)
            or [
                ".python-version",
                "pyvenv.cfg",
                ".venv/pyvenv.cfg",
                "Pipfile",
                "environment.yml",
            ]
        )
        detected = _detect_python_in_workspace(workspace_path, detect_files)
        if detected:
            return detected

    agent_default = getattr(agent_cfg, "python_executable", "") or ""
    if agent_default:
        return agent_default

    return ""
