"""Unit tests for ``PromptBuilder`` ``python_executable`` injection.

Verifies the MVP that replaces the previously hardcoded
``/root/Conda/bin/python3`` path in continuation guidance with a
workflow-configurable ``agent.python_executable`` value.

Acceptance points:

* ``AgentConfig.python_executable`` defaults to ``""`` (opt-in).
* ``PromptBuilder.render()`` with ``python_executable=None`` or
  ``""`` does NOT inject a "约束提醒" block into the turn-0 prompt
  and does NOT mention the hardcoded path.
* ``PromptBuilder.render()`` with a non-empty
  ``python_executable`` DOES inject the constraint and uses the
  supplied path verbatim.
* ``PromptBuilder.build_continuation_prompt()`` no longer contains
  the hardcoded ``/root/Conda/bin/python3`` string anywhere when
  the new argument is empty, and DOES contain the supplied path
  when the argument is non-empty.

MVP-2 additions (workspace-level cascade resolver):

* ``WorkspaceConfig`` exposes ``python_executable``,
  ``python_auto_detect``, ``python_detect_files`` with safe defaults.
* ``_detect_python_in_workspace`` returns the right absolute path
  for ``.python-version`` (pyenv), ``pyvenv.cfg`` (venv), and
  ``environment.yml`` (conda); returns ``""`` on miss.
* ``resolve_python_executable`` cascade: workspace explicit > detect
  > agent default > empty; respects ``python_auto_detect = False``.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from extensions.orchestrator.config.schema import AgentConfig, WorkspaceConfig
from extensions.orchestrator.issue import Issue
from extensions.orchestrator.local_tracker.parser import parse_markdown_issue
from extensions.orchestrator.prompt_builder import (
    PromptBuilder,
    _detect_python_in_workspace,
    _parse_conda_env_name,
    _parse_pyvenv_home,
    resolve_python_executable,
)


# Hardcoded path that lived in prompt_builder.py:284 prior to the fix.
# Tests assert that this string does NOT appear in rendered output
# when ``python_executable`` is not supplied.
_LEGACY_HARDCODED_PATH = "/root/Conda/bin/python3"


@dataclass
class _FakeIssue:
    """Minimal Issue stand-in for PromptBuilder.render().

    PromptBuilder calls ``issue.to_dict()`` when present; otherwise
    the object is used directly. We provide to_dict() so the
    template receives a plain dict.
    """

    identifier: str = "TEST-1"
    title: str = "Test issue"
    description: str = "Test description"
    priority: int | None = None
    state: str = "open"
    labels: list[str] | None = None
    branch_name: str = "test/branch"
    base_branch: str | None = "main"

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "state": self.state,
            "labels": self.labels or [],
            "branch_name": self.branch_name,
            "base_branch": self.base_branch,
        }


class TestAgentConfigPythonExecutable(unittest.TestCase):
    """``AgentConfig.python_executable`` defaults to empty string."""

    def test_default_is_empty_string(self) -> None:
        cfg = AgentConfig()
        self.assertEqual(cfg.python_executable, "")

    def test_explicit_override_persists(self) -> None:
        cfg = AgentConfig(python_executable="/opt/project/.venv/bin/python")
        self.assertEqual(cfg.python_executable, "/opt/project/.venv/bin/python")


class TestRenderPythonExecutable(unittest.TestCase):
    """Turn-0 prompt (``render()``) honors ``python_executable``."""

    def setUp(self) -> None:
        self.issue = _FakeIssue()

    def test_none_does_not_inject_constraint(self) -> None:
        rendered = PromptBuilder.render(
            self.issue,
            session=None,
            python_executable=None,
        )
        self.assertNotIn("约束提醒", rendered)
        self.assertNotIn(_LEGACY_HARDCODED_PATH, rendered)

    def test_empty_string_does_not_inject_constraint(self) -> None:
        rendered = PromptBuilder.render(
            self.issue,
            session=None,
            python_executable="",
        )
        self.assertNotIn("约束提醒", rendered)
        self.assertNotIn(_LEGACY_HARDCODED_PATH, rendered)

    def test_non_empty_path_is_injected(self) -> None:
        path = "/opt/projectX/.venv/bin/python"
        rendered = PromptBuilder.render(
            self.issue,
            session=None,
            python_executable=path,
        )
        self.assertIn("约束提醒", rendered)
        self.assertIn(path, rendered)
        # Regression: legacy hardcoded path must NOT leak through.
        self.assertNotIn(_LEGACY_HARDCODED_PATH, rendered)


class TestBuildContinuationPromptPythonExecutable(unittest.TestCase):
    """Turn-N prompt (``build_continuation_prompt()``) honors ``python_executable``."""

    def test_default_does_not_contain_legacy_hardcoded_path(self) -> None:
        """The default call must no longer mention ``/root/Conda/bin/python3``.

        This is the core regression test for the hardcoded-path bug.
        """
        rendered = PromptBuilder.build_continuation_prompt(
            turn_number=2,
            max_turns=20,
            issue_context=None,
            session=None,
        )
        self.assertNotIn(_LEGACY_HARDCODED_PATH, rendered)

    def test_none_does_not_inject_constraint(self) -> None:
        rendered = PromptBuilder.build_continuation_prompt(
            turn_number=2,
            max_turns=20,
            issue_context=None,
            session=None,
            python_executable=None,
        )
        self.assertNotIn("约束提醒", rendered)
        self.assertNotIn(_LEGACY_HARDCODED_PATH, rendered)

    def test_empty_string_does_not_inject_constraint(self) -> None:
        rendered = PromptBuilder.build_continuation_prompt(
            turn_number=2,
            max_turns=20,
            issue_context=None,
            session=None,
            python_executable="",
        )
        self.assertNotIn("约束提醒", rendered)
        self.assertNotIn(_LEGACY_HARDCODED_PATH, rendered)

    def test_non_empty_path_is_injected(self) -> None:
        path = "/usr/bin/python3"
        rendered = PromptBuilder.build_continuation_prompt(
            turn_number=2,
            max_turns=20,
            issue_context=None,
            session=None,
            python_executable=path,
        )
        self.assertIn("约束提醒", rendered)
        self.assertIn(path, rendered)
        # Regression: legacy hardcoded path must NOT leak through.
        self.assertNotIn(_LEGACY_HARDCODED_PATH, rendered)

    def test_other_constraints_still_present(self) -> None:
        """Sanity: changing the python path must not break the
        unrelated pytest-pipe / clawcodex-dev CLI constraints that
        live in the same continuation prompt."""
        rendered = PromptBuilder.build_continuation_prompt(
            turn_number=2,
            max_turns=20,
            issue_context=None,
            session=None,
        )
        self.assertIn("pytest", rendered)
        self.assertIn("clawcodex-dev", rendered)


class TestWorkspaceConfigPythonFields(unittest.TestCase):
    """``WorkspaceConfig.python_*`` defaults are safe + opt-in."""

    def test_defaults(self) -> None:
        cfg = WorkspaceConfig()
        self.assertEqual(cfg.python_executable, "")
        self.assertTrue(cfg.python_auto_detect)
        self.assertIn(".python-version", cfg.python_detect_files)
        self.assertIn("pyvenv.cfg", cfg.python_detect_files)
        self.assertIn("environment.yml", cfg.python_detect_files)

    def test_explicit_override(self) -> None:
        cfg = WorkspaceConfig(
            python_executable="/opt/x/.venv/bin/python",
            python_auto_detect=False,
            python_detect_files=["only-this-one"],
        )
        self.assertEqual(cfg.python_executable, "/opt/x/.venv/bin/python")
        self.assertFalse(cfg.python_auto_detect)
        self.assertEqual(cfg.python_detect_files, ["only-this-one"])


class TestParsePyvenvHome(unittest.TestCase):
    def test_parses_home_line(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "pyvenv.cfg"
            p.write_text(
                "home = /usr/local/bin\ninclude-system-site-packages = false\nversion = 3.11.7\n",
                encoding="utf-8",
            )
            self.assertEqual(_parse_pyvenv_home(p), "/usr/local/bin")

    def test_handles_quoted_value(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "pyvenv.cfg"
            p.write_text('home = "/opt/venv with spaces/bin"\n', encoding="utf-8")
            self.assertEqual(_parse_pyvenv_home(p), "/opt/venv with spaces/bin")

    def test_missing_file_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(_parse_pyvenv_home(Path(d) / "nope.cfg"), "")


class TestParseCondaEnvName(unittest.TestCase):
    def test_parses_name_field(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "environment.yml"
            p.write_text(
                "name: myenv\nchannels:\n  - defaults\ndependencies:\n  - python=3.11\n",
                encoding="utf-8",
            )
            self.assertEqual(_parse_conda_env_name(p), "myenv")

    def test_missing_name_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "environment.yml"
            p.write_text("channels:\n  - defaults\n", encoding="utf-8")
            self.assertEqual(_parse_conda_env_name(p), "")


class TestDetectPythonInWorkspace(unittest.TestCase):
    """``_detect_python_in_workspace`` probe logic."""

    def test_nonexistent_workspace_returns_empty(self) -> None:
        self.assertEqual(
            _detect_python_in_workspace(Path("/no/such/path"), [".python-version"]), ""
        )

    def test_none_workspace_returns_empty(self) -> None:
        self.assertEqual(_detect_python_in_workspace(None, [".python-version"]), "")

    def test_pyvenv_cfg_wins_over_python_version(self) -> None:
        """Both signals present: pyvenv.cfg has higher effective priority
        because it's listed first in the default candidates and yields
        a direct interpreter path."""
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            venv_home = ws / "venv"
            (venv_home / "bin").mkdir(parents=True)
            py = venv_home / "bin" / "python3"
            py.write_text("#!/bin/sh\n", encoding="utf-8")
            (ws / "pyvenv.cfg").write_text(f"home = {venv_home}\n", encoding="utf-8")
            (ws / ".python-version").write_text("3.11.7\n", encoding="utf-8")
            result = _detect_python_in_workspace(ws, [".python-version", "pyvenv.cfg"])
            self.assertEqual(result, str(py))

    def test_pyenv_python_version_resolves(self) -> None:
        """``.python-version`` resolves under a fake ``PYENV_ROOT``."""
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            fake_pyenv = ws / "fake_pyenv"
            version_dir = fake_pyenv / "versions" / "3.11.7" / "bin"
            version_dir.mkdir(parents=True)
            py = version_dir / "python3"
            py.write_text("#!/bin/sh\n", encoding="utf-8")
            (ws / ".python-version").write_text("3.11.7\n", encoding="utf-8")
            old = os.environ.get("PYENV_ROOT")
            os.environ["PYENV_ROOT"] = str(fake_pyenv)
            try:
                result = _detect_python_in_workspace(ws, [".python-version"])
                self.assertEqual(result, str(py))
            finally:
                if old is None:
                    os.environ.pop("PYENV_ROOT", None)
                else:
                    os.environ["PYENV_ROOT"] = old

    def test_pyenv_version_missing_falls_through(self) -> None:
        """``.python-version`` points at a version that isn't installed."""
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            (ws / ".python-version").write_text("99.99.99\n", encoding="utf-8")
            old = os.environ.get("PYENV_ROOT")
            os.environ["PYENV_ROOT"] = str(ws / "fake_pyenv")
            try:
                result = _detect_python_in_workspace(ws, [".python-version"])
                self.assertEqual(result, "")
            finally:
                if old is None:
                    os.environ.pop("PYENV_ROOT", None)
                else:
                    os.environ["PYENV_ROOT"] = old

    def test_environment_yml_uses_conda_prefix_env(self) -> None:
        """``environment.yml`` with ``CONDA_PREFIX`` env var resolves."""
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            (ws / "environment.yml").write_text("name: projX\n", encoding="utf-8")
            conda_root = ws / "conda"
            py = conda_root / "envs" / "projX" / "bin" / "python3"
            py.parent.mkdir(parents=True)
            py.write_text("#!/bin/sh\n", encoding="utf-8")
            old = os.environ.get("CONDA_PREFIX")
            os.environ["CONDA_PREFIX"] = str(conda_root)
            try:
                result = _detect_python_in_workspace(ws, ["environment.yml"])
                self.assertEqual(result, str(py))
            finally:
                if old is None:
                    os.environ.pop("CONDA_PREFIX", None)
                else:
                    os.environ["CONDA_PREFIX"] = old

    def test_pipfile_is_recognised_but_skipped(self) -> None:
        """Pipfile is in the default candidate list but produces no
        interpreter path (it has no direct ``bin/python3`` link)."""
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            (ws / "Pipfile").write_text('[packages]\nrequests = "*"\n', encoding="utf-8")
            self.assertEqual(_detect_python_in_workspace(ws, ["Pipfile"]), "")

    def test_no_signals_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            self.assertEqual(_detect_python_in_workspace(ws, [".python-version", "pyvenv.cfg"]), "")

    def test_workspace_with_no_candidates_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(_detect_python_in_workspace(Path(d), []), "")


class TestResolvePythonExecutable(unittest.TestCase):
    """Cascade priority: workspace explicit > detect > agent default > empty."""

    def test_workspace_explicit_wins_over_detect_and_agent(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            venv = ws / "venv"
            (venv / "bin").mkdir(parents=True)
            (venv / "bin" / "python3").write_text("#!/bin/sh\n", encoding="utf-8")
            (ws / "pyvenv.cfg").write_text(f"home = {venv}\n", encoding="utf-8")
            ws_cfg = WorkspaceConfig(python_executable="/explicit/override")
            agent_cfg = AgentConfig(python_executable="/agent/default")
            self.assertEqual(
                resolve_python_executable(
                    workspace_path=ws,
                    agent_cfg=agent_cfg,
                    workspace_cfg=ws_cfg,
                ),
                "/explicit/override",
            )

    def test_detected_wins_over_agent_default(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            venv = ws / "venv"
            (venv / "bin").mkdir(parents=True)
            detected_py = venv / "bin" / "python3"
            detected_py.write_text("#!/bin/sh\n", encoding="utf-8")
            (ws / "pyvenv.cfg").write_text(f"home = {venv}\n", encoding="utf-8")
            ws_cfg = WorkspaceConfig()  # no explicit override
            agent_cfg = AgentConfig(python_executable="/agent/default")
            self.assertEqual(
                resolve_python_executable(
                    workspace_path=ws,
                    agent_cfg=agent_cfg,
                    workspace_cfg=ws_cfg,
                ),
                str(detected_py),
            )

    def test_agent_default_used_when_no_workspace_signal(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ws_cfg = WorkspaceConfig()
            agent_cfg = AgentConfig(python_executable="/agent/default")
            self.assertEqual(
                resolve_python_executable(
                    workspace_path=Path(d),
                    agent_cfg=agent_cfg,
                    workspace_cfg=ws_cfg,
                ),
                "/agent/default",
            )

    def test_empty_when_nothing_configured(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(
                resolve_python_executable(
                    workspace_path=Path(d),
                    agent_cfg=AgentConfig(),
                    workspace_cfg=WorkspaceConfig(),
                ),
                "",
            )

    def test_auto_detect_false_skips_probing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            venv = ws / "venv"
            (venv / "bin").mkdir(parents=True)
            (venv / "bin" / "python3").write_text("#!/bin/sh\n", encoding="utf-8")
            (ws / "pyvenv.cfg").write_text(f"home = {venv}\n", encoding="utf-8")
            ws_cfg = WorkspaceConfig(python_auto_detect=False)
            agent_cfg = AgentConfig(python_executable="/agent/default")
            # detect disabled, so detection is skipped entirely; agent
            # default still applies.
            self.assertEqual(
                resolve_python_executable(
                    workspace_path=ws,
                    agent_cfg=agent_cfg,
                    workspace_cfg=ws_cfg,
                ),
                "/agent/default",
            )

    def test_workspace_path_none_falls_through(self) -> None:
        """When no workspace path is available (e.g. unit tests), the
        resolver must skip detection and fall back to agent default."""
        agent_cfg = AgentConfig(python_executable="/agent/default")
        self.assertEqual(
            resolve_python_executable(
                workspace_path=None,
                agent_cfg=agent_cfg,
                workspace_cfg=WorkspaceConfig(),
            ),
            "/agent/default",
        )

    def test_empty_workspace_cfg_falls_through_to_agent(self) -> None:
        """A workspace_cfg with ``python_auto_detect=False`` and
        ``python_executable=""`` must not block the agent default."""
        agent_cfg = AgentConfig(python_executable="/agent/default")
        self.assertEqual(
            resolve_python_executable(
                workspace_path=None,
                agent_cfg=agent_cfg,
                workspace_cfg=WorkspaceConfig(
                    python_auto_detect=False,
                    python_detect_files=[],
                ),
            ),
            "/agent/default",
        )


class TestPromptBuilderIntegrationWithResolver(unittest.TestCase):
    """End-to-end: the resolver's output is what the builder sees."""

    def test_render_uses_resolved_path(self) -> None:
        issue = _FakeIssue()
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            venv = ws / "venv"
            (venv / "bin").mkdir(parents=True)
            (venv / "bin" / "python3").write_text("#!/bin/sh\n", encoding="utf-8")
            (ws / "pyvenv.cfg").write_text(f"home = {venv}\n", encoding="utf-8")
            ws_cfg = WorkspaceConfig()
            agent_cfg = AgentConfig()
            resolved = resolve_python_executable(
                workspace_path=ws,
                agent_cfg=agent_cfg,
                workspace_cfg=ws_cfg,
            )
            self.assertNotEqual(resolved, "")  # sanity
            rendered = PromptBuilder.render(
                issue,
                session=None,
                python_executable=resolved,
            )
            self.assertIn(resolved, rendered)
            self.assertIn("约束提醒", rendered)
            self.assertNotIn("/root/Conda/bin/python3", rendered)

    def test_continuation_uses_resolved_path(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            venv = ws / "venv"
            (venv / "bin").mkdir(parents=True)
            (venv / "bin" / "python3").write_text("#!/bin/sh\n", encoding="utf-8")
            (ws / "pyvenv.cfg").write_text(f"home = {venv}\n", encoding="utf-8")
            ws_cfg = WorkspaceConfig()
            agent_cfg = AgentConfig()
            resolved = resolve_python_executable(
                workspace_path=ws,
                agent_cfg=agent_cfg,
                workspace_cfg=ws_cfg,
            )
            rendered = PromptBuilder.build_continuation_prompt(
                turn_number=2,
                max_turns=20,
                issue_context=None,
                session=None,
                python_executable=resolved,
            )
            self.assertIn(resolved, rendered)
            self.assertIn("约束提醒", rendered)
            self.assertNotIn("/root/Conda/bin/python3", rendered)


class TestIssuePythonExecutable(unittest.TestCase):
    """``Issue.python_executable`` field defaults to empty string."""

    def test_default_is_empty_string(self) -> None:
        issue = Issue()
        self.assertEqual(issue.python_executable, "")

    def test_explicit_override_persists(self) -> None:
        issue = Issue(python_executable="/opt/proj/.venv/bin/python")
        self.assertEqual(issue.python_executable, "/opt/proj/.venv/bin/python")


class TestLocalTrackerFrontmatterParse(unittest.TestCase):
    """``parse_markdown_issue`` extracts ``python_executable`` from frontmatter."""

    def test_frontmatter_python_executable_extracted(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "issue-42.md"
            p.write_text(
                "---\n"
                "id: 42\n"
                "identifier: PROJ-42\n"
                "title: Fix pyenv issue\n"
                "state: open\n"
                "python_executable: /opt/projX/.venv/bin/python\n"
                "---\n"
                "Body of the issue.\n",
                encoding="utf-8",
            )
            doc = parse_markdown_issue(p)
            self.assertEqual(doc.issue.python_executable, "/opt/projX/.venv/bin/python")

    def test_missing_frontmatter_field_yields_empty_string(self) -> None:
        """Backward compat: issues without the new field keep working."""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "issue-7.md"
            p.write_text(
                "---\nid: 7\nidentifier: PROJ-7\ntitle: Plain issue\nstate: open\n---\nBody.\n",
                encoding="utf-8",
            )
            doc = parse_markdown_issue(p)
            self.assertEqual(doc.issue.python_executable, "")

    def test_empty_string_frontmatter_yields_empty_string(self) -> None:
        """``python_executable: ""`` is treated the same as missing."""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "issue-9.md"
            p.write_text(
                "---\n"
                "id: 9\n"
                "identifier: PROJ-9\n"
                "title: Empty override\n"
                'python_executable: ""\n'
                "---\n"
                "Body.\n",
                encoding="utf-8",
            )
            doc = parse_markdown_issue(p)
            self.assertEqual(doc.issue.python_executable, "")


class TestResolveCascadeWithIssueOverride(unittest.TestCase):
    """Per-issue override is the highest-priority cascade level."""

    def test_issue_wins_over_workspace_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            ws_cfg = WorkspaceConfig(python_executable="/workspace/override")
            agent_cfg = AgentConfig(python_executable="/agent/default")
            self.assertEqual(
                resolve_python_executable(
                    workspace_path=ws,
                    agent_cfg=agent_cfg,
                    workspace_cfg=ws_cfg,
                    issue_executable="/issue/override",
                ),
                "/issue/override",
            )

    def test_issue_wins_over_detect(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            venv = ws / "venv"
            (venv / "bin").mkdir(parents=True)
            (venv / "bin" / "python3").write_text("#!/bin/sh\n", encoding="utf-8")
            (ws / "pyvenv.cfg").write_text(f"home = {venv}\n", encoding="utf-8")
            ws_cfg = WorkspaceConfig()  # auto_detect=True, no explicit
            agent_cfg = AgentConfig()
            self.assertEqual(
                resolve_python_executable(
                    workspace_path=ws,
                    agent_cfg=agent_cfg,
                    workspace_cfg=ws_cfg,
                    issue_executable="/issue/override",
                ),
                "/issue/override",
            )

    def test_issue_wins_over_agent_default(self) -> None:
        agent_cfg = AgentConfig(python_executable="/agent/default")
        self.assertEqual(
            resolve_python_executable(
                workspace_path=None,
                agent_cfg=agent_cfg,
                workspace_cfg=WorkspaceConfig(),
                issue_executable="/issue/override",
            ),
            "/issue/override",
        )

    def test_issue_strips_whitespace(self) -> None:
        """Leading/trailing whitespace in the override is trimmed so
        hand-authored frontmatter like ``python_executable: '  /x  '``
        doesn't accidentally fall through to lower-priority levels."""
        self.assertEqual(
            resolve_python_executable(
                workspace_path=None,
                agent_cfg=AgentConfig(python_executable="/agent/default"),
                workspace_cfg=WorkspaceConfig(python_executable="/ws/override"),
                issue_executable="   /issue/override   ",
            ),
            "/issue/override",
        )

    def test_issue_empty_string_falls_through(self) -> None:
        """Backward compat: when ``issue_executable`` is ``""`` (the
        default), the resolver behaves exactly as MVP-2: workspace
        explicit > detect > agent default > empty."""
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            ws_cfg = WorkspaceConfig(python_executable="/workspace/override")
            self.assertEqual(
                resolve_python_executable(
                    workspace_path=ws,
                    agent_cfg=AgentConfig(),
                    workspace_cfg=ws_cfg,
                    issue_executable="",
                ),
                "/workspace/override",
            )

    def test_issue_whitespace_only_falls_through(self) -> None:
        """``issue_executable='   '`` is treated as empty so the
        cascade can still resolve to a lower-priority value."""
        self.assertEqual(
            resolve_python_executable(
                workspace_path=None,
                agent_cfg=AgentConfig(python_executable="/agent/default"),
                workspace_cfg=WorkspaceConfig(),
                issue_executable="   ",
            ),
            "/agent/default",
        )

    def test_cascade_order_issue_ws_detect_agent_empty(self) -> None:
        """Full cascade smoke test: every level set, issue wins.

        Each level takes a turn "winning" — set up a workspace where
        the issue override is the only non-empty source, and verify
        the resolver returns it. Then remove the issue override and
        verify the workspace explicit wins; remove that and verify
        the detected path wins; remove the signal and verify the
        agent default wins; remove that and verify empty.
        """
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            venv = ws / "venv"
            (venv / "bin").mkdir(parents=True)
            detected_py = venv / "bin" / "python3"
            detected_py.write_text("#!/bin/sh\n", encoding="utf-8")
            (ws / "pyvenv.cfg").write_text(f"home = {venv}\n", encoding="utf-8")
            ws_cfg = WorkspaceConfig(python_executable="/ws/override")
            agent_cfg = AgentConfig(python_executable="/agent/default")

            # All four set: issue wins
            self.assertEqual(
                resolve_python_executable(
                    workspace_path=ws,
                    agent_cfg=agent_cfg,
                    workspace_cfg=ws_cfg,
                    issue_executable="/issue/override",
                ),
                "/issue/override",
            )

            # Issue removed: workspace explicit wins
            self.assertEqual(
                resolve_python_executable(
                    workspace_path=ws,
                    agent_cfg=agent_cfg,
                    workspace_cfg=ws_cfg,
                    issue_executable="",
                ),
                "/ws/override",
            )

            # Workspace explicit removed: detect wins
            self.assertEqual(
                resolve_python_executable(
                    workspace_path=ws,
                    agent_cfg=agent_cfg,
                    workspace_cfg=WorkspaceConfig(),
                    issue_executable="",
                ),
                str(detected_py),
            )

            # Detection disabled + no workspace signal: agent default wins
            self.assertEqual(
                resolve_python_executable(
                    workspace_path=ws,
                    agent_cfg=agent_cfg,
                    workspace_cfg=WorkspaceConfig(python_auto_detect=False),
                    issue_executable="",
                ),
                "/agent/default",
            )

            # Everything empty: empty string
            self.assertEqual(
                resolve_python_executable(
                    workspace_path=ws,
                    agent_cfg=AgentConfig(),
                    workspace_cfg=WorkspaceConfig(python_auto_detect=False),
                    issue_executable="",
                ),
                "",
            )


class TestPromptBuilderIntegrationWithIssueOverride(unittest.TestCase):
    """End-to-end: frontmatter override flows into the rendered prompt."""

    def test_render_uses_issue_override(self) -> None:
        issue = _FakeIssue()
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            resolved = resolve_python_executable(
                workspace_path=ws,
                agent_cfg=AgentConfig(),
                workspace_cfg=WorkspaceConfig(),
                issue_executable="/opt/projX/.venv/bin/python",
            )
            rendered = PromptBuilder.render(
                issue,
                session=None,
                python_executable=resolved,
            )
            self.assertIn("/opt/projX/.venv/bin/python", rendered)
            self.assertIn("约束提醒", rendered)

    def test_continuation_uses_issue_override(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            resolved = resolve_python_executable(
                workspace_path=ws,
                agent_cfg=AgentConfig(),
                workspace_cfg=WorkspaceConfig(),
                issue_executable="/opt/projY/conda/bin/python",
            )
            rendered = PromptBuilder.build_continuation_prompt(
                turn_number=3,
                max_turns=10,
                issue_context=None,
                session=None,
                python_executable=resolved,
            )
            self.assertIn("/opt/projY/conda/bin/python", rendered)
            self.assertIn("约束提醒", rendered)


@dataclass
class _FakeWorkspace:
    """Minimal workspace stand-in for operator-hints tests."""

    path: Path


@dataclass
class _FakeSession:
    """Minimal session stand-in that exposes a workspace."""

    workspace: _FakeWorkspace | None = None


class TestOperatorHintsInjection(unittest.TestCase):
    """.operator_hints.md is injected into render() and continuation prompts."""

    def test_render_injects_hints_when_file_present(self) -> None:
        issue = _FakeIssue()
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            hints = "Focus on implementation only."
            (ws / ".operator_hints.md").write_text(hints, encoding="utf-8")
            rendered = PromptBuilder.render(
                issue,
                session=_FakeSession(workspace=_FakeWorkspace(path=ws)),
            )
            self.assertIn("## Operator Hints", rendered)
            self.assertIn(hints, rendered)

    def test_render_skips_hints_when_file_missing(self) -> None:
        issue = _FakeIssue()
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            rendered = PromptBuilder.render(
                issue,
                session=_FakeSession(workspace=_FakeWorkspace(path=ws)),
            )
            self.assertNotIn("## Operator Hints", rendered)

    def test_render_skips_hints_when_session_has_no_workspace(self) -> None:
        issue = _FakeIssue()
        rendered = PromptBuilder.render(issue, session=_FakeSession(workspace=None))
        self.assertNotIn("## Operator Hints", rendered)

    def test_continuation_injects_hints_when_file_present(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            hints = "Do not re-read files."
            (ws / ".operator_hints.md").write_text(hints, encoding="utf-8")
            rendered = PromptBuilder.build_continuation_prompt(
                turn_number=2,
                max_turns=10,
                issue_context=None,
                session=_FakeSession(workspace=_FakeWorkspace(path=ws)),
            )
            self.assertIn("## Operator Hints", rendered)
            self.assertIn(hints, rendered)

    def test_continuation_skips_hints_when_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            rendered = PromptBuilder.build_continuation_prompt(
                turn_number=2,
                max_turns=10,
                issue_context=None,
                session=_FakeSession(workspace=_FakeWorkspace(path=ws)),
            )
            self.assertNotIn("## Operator Hints", rendered)


if __name__ == "__main__":
    unittest.main()
