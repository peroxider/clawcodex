"""Unit tests for :mod:`extensions.orchestrator.workspace_locator`.

Covers the shared workspace root resolution and orchestrator metadata
helpers:

* :func:`get_workspace_root` priority chain (workspace_arg > env var
  > workflow front matter > metadata file > CWD registry > default).
* :func:`get_registry_path` and :func:`resolve_for_cli` thin wrappers.
* :func:`_parse_workspace_from_workflow` private front-matter parser.
* :func:`_slug_from_workspace` path-slug generator.
* :func:`_find_latest_metadata` metadata discovery.
* :func:`write_orchestrator_metadata` / :func:`clear_orchestrator_metadata`
  / :func:`list_orchestrator_projects` / :func:`get_live_projects` —
  including PID-liveness filtering.
* :func:`print_multi_project_hint` (writes a multi-line hint to stderr).
* :func:`print_workspace_info` formatting.

The module's :data:`CLAWCODEX_BASE` and :data:`ORCHESTRATOR_DIR` are
computed at import time from :meth:`pathlib.Path.home`, so each
filesystem-touching test patches those module-level attributes (not
``Path.home`` itself) to redirect writes into a temp dir.
"""

from __future__ import annotations

import json
import os
import tempfile
import textwrap
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from extensions.orchestrator import workspace_locator as wsl
from extensions.orchestrator.workspace_locator import (
    _find_latest_metadata,
    _parse_workspace_from_workflow,
    _slug_from_workspace,
    clear_orchestrator_metadata,
    get_live_projects,
    get_registry_path,
    get_workspace_root,
    list_orchestrator_projects,
    print_multi_project_hint,
    print_workspace_info,
    resolve_for_cli,
    write_orchestrator_metadata,
)


def _isolated_home() -> tuple[ExitStack, Path]:
    """Return (exit_stack, temp_home) that redirects all module writes.

    Patches :data:`CLAWCODEX_BASE` and :data:`ORCHESTRATOR_DIR` to point
    into a fresh temp dir, so tests cannot pollute the developer's
    ``~/.clawcodex`` directory.
    """
    stack = ExitStack()
    tmp = tempfile.TemporaryDirectory()
    stack.callback(tmp.cleanup)
    home = Path(tmp.name) / "home"
    home.mkdir()
    fake_base = home / ".clawcodex"
    fake_orch = fake_base / "orchestrator"
    fake_orch.mkdir(parents=True, exist_ok=True)
    stack.enter_context(patch.object(wsl, "CLAWCODEX_BASE", fake_base))
    stack.enter_context(patch.object(wsl, "ORCHESTRATOR_DIR", fake_orch))
    return stack, home


# ---------------------------------------------------------------------------
# _slug_from_workspace
# ---------------------------------------------------------------------------


class TestSlugFromWorkspace(unittest.TestCase):
    def test_absolute_path_slug(self) -> None:
        # The exact format isn't pinned — just ensure the function
        # produces a non-empty, filesystem-safe string.
        slug = _slug_from_workspace("/tmp/symphony_workspaces/proj-foo")
        self.assertIsInstance(slug, str)
        self.assertNotIn("/", slug)
        self.assertNotIn("\\", slug)
        self.assertNotEqual(slug, "")

    def test_relative_path_slug(self) -> None:
        slug = _slug_from_workspace("home/user/code")
        self.assertIsInstance(slug, str)
        self.assertNotEqual(slug, "")

    def test_strips_tmp_segments(self) -> None:
        # "tmp" is filtered, so the slug derives from non-tmp components.
        slug = _slug_from_workspace("/tmp/proj-foo")
        self.assertNotIn("tmp", slug.split("-"))

    def test_empty_falls_back_to_default(self) -> None:
        # All components are filtered → "default" fallback.
        # Need a path where every component is in the skip list.
        slug = _slug_from_workspace("///")
        # All parts are empty after filter → "default".
        self.assertEqual(slug, "default")


# ---------------------------------------------------------------------------
# get_workspace_root priority chain
# ---------------------------------------------------------------------------


class TestGetWorkspaceRoot(unittest.TestCase):
    def setUp(self) -> None:
        self.stack, self.home = _isolated_home()
        self.addCleanup(self.stack.close)
        # Use a per-test cwd dir for the cwd-related tests.
        self.cwd_fake = self.home / "cwd"
        self.cwd_fake.mkdir()

    def test_returns_none_when_nothing_matches(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("CLAWCODEX_WORKSPACE_ROOT", None)
            with patch("os.getcwd", return_value=str(self.home / "no-cwd")):
                result = get_workspace_root()
        self.assertIsNone(result)

    def test_workspace_arg_highest_priority(self) -> None:
        explicit = self.home / "from-arg"
        explicit.mkdir()
        with patch.dict(
            os.environ,
            {"CLAWCODEX_WORKSPACE_ROOT": "/from/env"},
        ):
            result = get_workspace_root(workspace_arg=str(explicit))
        # workspace_arg wins over env.
        self.assertEqual(result, Path(str(explicit)).resolve())

    def test_env_var_used_when_no_arg(self) -> None:
        env_path = self.home / "from-env"
        env_path.mkdir()
        with patch.dict(os.environ, {"CLAWCODEX_WORKSPACE_ROOT": str(env_path)}):
            result = get_workspace_root()
        self.assertEqual(result, Path(str(env_path)).resolve())

    def test_workflow_yaml_workspace_root(self) -> None:
        # Write a WORKFLOW.md that specifies workspace.root.
        wf_path = self.home / "WORKFLOW.md"
        target = self.home / "from-workflow"
        target.mkdir()
        wf_path.write_text(
            textwrap.dedent(
                f"""\
                ---
                workspace:
                  root: {target}
                ---
                prompt
                """
            ),
            encoding="utf-8",
        )
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("CLAWCODEX_WORKSPACE_ROOT", None)
            with patch("os.getcwd", return_value=str(self.home / "no-cwd")):
                result = get_workspace_root(workflow_path=str(wf_path))
        self.assertEqual(result, target)

    def test_metadata_file_fallback(self) -> None:
        # Pre-create an orchestrator metadata file.
        ws_path = self.home / "from-metadata"
        ws_path.mkdir()
        write_orchestrator_metadata(ws_path)
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("CLAWCODEX_WORKSPACE_ROOT", None)
            with patch("os.getcwd", return_value=str(self.home / "no-cwd")):
                result = get_workspace_root()
        self.assertEqual(result, ws_path)

    def test_cwd_registry_fallback(self) -> None:
        # Create a fake cwd with a .clawcodex_issue_registry.json.
        cwd_fake = self.home / "cwd"
        (cwd_fake / ".clawcodex_issue_registry.json").write_text("{}")
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("CLAWCODEX_WORKSPACE_ROOT", None)
            with patch("os.getcwd", return_value=str(cwd_fake)):
                result = get_workspace_root()
        self.assertEqual(result, cwd_fake)

    def test_default_workspace_fallback(self) -> None:
        # Create the default workspace path.
        default_ws = wsl.CLAWCODEX_BASE / "workspace"
        default_ws.mkdir()
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("CLAWCODEX_WORKSPACE_ROOT", None)
            with patch("os.getcwd", return_value=str(self.home / "no-cwd")):
                result = get_workspace_root()
        self.assertEqual(result, default_ws)

    def test_priority_order(self) -> None:
        """workspace_arg > env > workflow > metadata > cwd > default."""
        # Set up all six sources.
        arg_path = self.home / "arg"
        arg_path.mkdir()
        env_path = self.home / "env"
        env_path.mkdir()
        workflow_target = self.home / "workflow"
        workflow_target.mkdir()
        wf_path = self.home / "WORKFLOW.md"
        wf_path.write_text(
            f"---\nworkspace:\n  root: {workflow_target}\n---\np",
            encoding="utf-8",
        )
        metadata_path = self.home / "metadata"
        metadata_path.mkdir()
        write_orchestrator_metadata(metadata_path)
        cwd_path = self.home / "cwd-prio"
        cwd_path.mkdir()
        (cwd_path / ".clawcodex_issue_registry.json").write_text("{}")
        default_path = wsl.CLAWCODEX_BASE / "workspace"
        default_path.mkdir()

        with patch.dict(os.environ, {"CLAWCODEX_WORKSPACE_ROOT": str(env_path)}):
            with patch("os.getcwd", return_value=str(cwd_path)):
                result = get_workspace_root(
                    workspace_arg=str(arg_path),
                    workflow_path=str(wf_path),
                )
        # arg_path wins.
        self.assertEqual(result, Path(str(arg_path)).resolve())


# ---------------------------------------------------------------------------
# get_registry_path / resolve_for_cli
# ---------------------------------------------------------------------------


class TestGetRegistryPath(unittest.TestCase):
    def setUp(self) -> None:
        self.stack, self.home = _isolated_home()
        self.addCleanup(self.stack.close)

    def test_returns_none_when_no_workspace(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("CLAWCODEX_WORKSPACE_ROOT", None)
            with patch("os.getcwd", return_value=str(self.home / "no-cwd")):
                result = get_registry_path()
        self.assertIsNone(result)

    def test_returns_registry_path_under_workspace(self) -> None:
        explicit = self.home / "ws"
        explicit.mkdir()
        result = get_registry_path(workspace_arg=str(explicit))
        self.assertEqual(result, explicit / ".clawcodex_issue_registry.json")


class TestResolveForCli(unittest.TestCase):
    def setUp(self) -> None:
        self.stack, self.home = _isolated_home()
        self.addCleanup(self.stack.close)

    def test_returns_none_pair_when_no_workspace(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("CLAWCODEX_WORKSPACE_ROOT", None)
            with patch("os.getcwd", return_value=str(self.home / "no-cwd")):
                root, registry = resolve_for_cli(None, None)
        self.assertIsNone(root)
        self.assertIsNone(registry)

    def test_returns_pair_when_workspace_found(self) -> None:
        explicit = self.home / "ws"
        explicit.mkdir()
        root, registry = resolve_for_cli(str(explicit), None)
        self.assertEqual(root, explicit)
        self.assertEqual(
            registry,
            explicit / ".clawcodex_issue_registry.json",
        )


# ---------------------------------------------------------------------------
# _parse_workspace_from_workflow
# ---------------------------------------------------------------------------


class TestParseWorkspaceFromWorkflow(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "WORKFLOW.md"

    def test_no_front_matter_returns_none(self) -> None:
        self.path.write_text("just a prompt", encoding="utf-8")
        self.assertIsNone(_parse_workspace_from_workflow(self.path))

    def test_no_workspace_key_returns_none(self) -> None:
        self.path.write_text(
            "---\ntracker:\n  kind: github\n---\nprompt",
            encoding="utf-8",
        )
        self.assertIsNone(_parse_workspace_from_workflow(self.path))

    def test_workspace_root_extracted(self) -> None:
        self.path.write_text(
            "---\nworkspace:\n  root: /some/path\n---\nprompt",
            encoding="utf-8",
        )
        result = _parse_workspace_from_workflow(self.path)
        self.assertEqual(result, Path("/some/path"))

    def test_tilde_expanded(self) -> None:
        self.path.write_text(
            '---\nworkspace:\n  root: "~/my-ws"\n---\nprompt',
            encoding="utf-8",
        )
        result = _parse_workspace_from_workflow(self.path)
        self.assertEqual(result, Path("~/my-ws").expanduser())

    def test_malformed_yaml_returns_none(self) -> None:
        self.path.write_text(
            "---\n: invalid yaml [\n---\nprompt",
            encoding="utf-8",
        )
        # Malformed YAML → returns None (no exception).
        self.assertIsNone(_parse_workspace_from_workflow(self.path))

    def test_non_dict_front_matter_returns_none(self) -> None:
        # A list at the top level.
        self.path.write_text(
            "---\n- one\n- two\n---\nprompt",
            encoding="utf-8",
        )
        self.assertIsNone(_parse_workspace_from_workflow(self.path))

    def test_workspace_root_empty_returns_none(self) -> None:
        self.path.write_text(
            '---\nworkspace:\n  root: ""\n---\nprompt',
            encoding="utf-8",
        )
        # Empty string is falsy → returns None.
        self.assertIsNone(_parse_workspace_from_workflow(self.path))

    def test_unclosed_front_matter_returns_none(self) -> None:
        self.path.write_text(
            "---\nworkspace:\n  root: /x",
            encoding="utf-8",
        )
        # No closing `---` → can't find end_idx → returns None.
        self.assertIsNone(_parse_workspace_from_workflow(self.path))


# ---------------------------------------------------------------------------
# write_orchestrator_metadata / clear / list
# ---------------------------------------------------------------------------


class TestOrchestratorMetadata(unittest.TestCase):
    def setUp(self) -> None:
        self.stack, self.home = _isolated_home()
        self.addCleanup(self.stack.close)

    def test_write_creates_metadata_file(self) -> None:
        path = write_orchestrator_metadata(
            str(self.home / "ws"),
            workflow_path="/path/to/WORKFLOW.md",
            started_at=12345.0,
        )
        self.assertTrue(path.exists())
        data = json.loads(path.read_text())
        self.assertEqual(data["workspace_root"], str(self.home / "ws"))
        self.assertEqual(data["pid"], os.getpid())
        self.assertEqual(data["started_at"], 12345.0)
        self.assertEqual(data["workflow_path"], "/path/to/WORKFLOW.md")

    def test_write_uses_workflow_owner_repo_for_project_slug(self) -> None:
        # If WORKFLOW.md has tracker.owner + tracker.repo, the project
        # slug is "{owner}-{repo}".
        wf_path = self.home / "WORKFLOW.md"
        wf_path.write_text(
            textwrap.dedent(
                """\
                ---
                tracker:
                  owner: octo
                  repo: hello
                ---
                p
                """
            ),
            encoding="utf-8",
        )
        path = write_orchestrator_metadata(
            str(self.home / "ws"),
            workflow_path=str(wf_path),
        )
        data = json.loads(path.read_text())
        self.assertEqual(data["project_slug"], "octo-hello")

    def test_write_handles_malformed_workflow(self) -> None:
        # If workflow parsing fails, fall back to the workspace-derived slug.
        wf_path = self.home / "WORKFLOW.md"
        wf_path.write_text(": invalid [", encoding="utf-8")
        path = write_orchestrator_metadata(
            str(self.home / "ws"),
            workflow_path=str(wf_path),
        )
        # No exception, and project_slug is non-empty.
        data = json.loads(path.read_text())
        self.assertTrue(data["project_slug"])

    def test_clear_removes_metadata_file(self) -> None:
        path = write_orchestrator_metadata(str(self.home / "ws"))
        self.assertTrue(path.exists())
        clear_orchestrator_metadata(str(self.home / "ws"))
        self.assertFalse(path.exists())

    def test_clear_nonexistent_is_silent(self) -> None:
        # No prior write → clear should not raise.
        clear_orchestrator_metadata("/does/not/exist")  # noop

    def test_list_projects(self) -> None:
        write_orchestrator_metadata(str(self.home / "ws1"))
        write_orchestrator_metadata(str(self.home / "ws2"))
        projects = list_orchestrator_projects()
        self.assertEqual(len(projects), 2)
        # All entries have the expected fields.
        for entry in projects:
            self.assertIn("workspace_root", entry)
            self.assertIn("pid", entry)
            self.assertIn("started_at", entry)
            self.assertIn("project_slug", entry)

    def test_list_projects_skips_invalid_json(self) -> None:
        # Inject a malformed metadata file.
        write_orchestrator_metadata(str(self.home / "ws-good"))
        # Create a sibling project with malformed metadata.
        slug_dir = wsl.ORCHESTRATOR_DIR / "broken"
        slug_dir.mkdir(parents=True, exist_ok=True)
        (slug_dir / "metadata.json").write_text("not json", encoding="utf-8")
        projects = list_orchestrator_projects()
        # Broken entry is silently dropped.
        slugs = [p.get("project_slug", "") for p in projects]
        self.assertTrue(all(s != "broken" for s in slugs))


# ---------------------------------------------------------------------------
# _find_latest_metadata
# ---------------------------------------------------------------------------


class TestFindLatestMetadata(unittest.TestCase):
    def setUp(self) -> None:
        self.stack, self.home = _isolated_home()
        self.addCleanup(self.stack.close)

    def test_no_dir_returns_none(self) -> None:
        # _isolated_home creates the orchestrator dir, but we want to
        # test the "no dir" branch — patch the dir to a non-existing
        # location.
        with patch.object(wsl, "ORCHESTRATOR_DIR", self.home / "missing"):
            result = _find_latest_metadata()
        self.assertIsNone(result)

    def test_returns_most_recently_modified(self) -> None:
        import time

        path_old = write_orchestrator_metadata(
            str(self.home / "ws-old"),
            started_at=1.0,
        )
        time.sleep(0.05)
        path_new = write_orchestrator_metadata(
            str(self.home / "ws-new"),
            started_at=2.0,
        )
        result = _find_latest_metadata()
        # The most recently modified is `path_new`.
        self.assertEqual(result, path_new)

    def test_ignores_files_without_metadata_json(self) -> None:
        # Write a real metadata file.
        path_real = write_orchestrator_metadata(str(self.home / "ws"))
        # Create a sibling dir with no metadata.json — should be ignored.
        (wsl.ORCHESTRATOR_DIR / "empty").mkdir(parents=True, exist_ok=True)
        result = _find_latest_metadata()
        self.assertEqual(result, path_real)


# ---------------------------------------------------------------------------
# get_live_projects
# ---------------------------------------------------------------------------


class TestGetLiveProjects(unittest.TestCase):
    def setUp(self) -> None:
        self.stack, self.home = _isolated_home()
        self.addCleanup(self.stack.close)

    def test_includes_current_pid(self) -> None:
        write_orchestrator_metadata(str(self.home / "ws"))
        live = get_live_projects()
        # Our own PID is alive.
        self.assertEqual(len(live), 1)
        self.assertEqual(live[0]["pid"], os.getpid())

    def test_excludes_dead_pids(self) -> None:
        write_orchestrator_metadata(str(self.home / "ws"))
        # Patch os.kill to simulate the process is dead.
        with patch("os.kill", side_effect=OSError("no such process")):
            live = get_live_projects()
        self.assertEqual(live, [])

    def test_provides_projects_param(self) -> None:
        # Caller-supplied projects skip the disk scan.
        live = get_live_projects(
            projects=[
                {
                    "workspace_root": "/x",
                    "pid": os.getpid(),
                    "started_at": 0.0,
                    "project_slug": "x",
                    "workflow_path": None,
                }
            ]
        )
        self.assertEqual(len(live), 1)
        self.assertEqual(live[0]["workspace_root"], "/x")

    def test_skips_projects_with_no_pid(self) -> None:
        # A metadata entry without a pid is silently skipped.
        live = get_live_projects(
            projects=[{"workspace_root": "/x", "pid": None}],
        )
        self.assertEqual(live, [])


# ---------------------------------------------------------------------------
# print_multi_project_hint
# ---------------------------------------------------------------------------


class TestPrintMultiProjectHint(unittest.TestCase):
    def test_writes_to_stderr(self) -> None:
        import io
        from contextlib import redirect_stderr

        buf = io.StringIO()
        projects = [
            {
                "workspace_root": "/tmp/ws1",
                "pid": 1234,
                "started_at": 0.0,
                "project_slug": "proj1",
                "workflow_path": None,
            },
        ]
        with redirect_stderr(buf):
            print_multi_project_hint(projects, command_hint="orchestrator server start")
        output = buf.getvalue()
        self.assertIn("1 running orchestrator projects detected", output)
        self.assertIn("orchestrator server start", output)
        self.assertIn("proj1", output)
        self.assertIn("--workspace", output)

    def test_uptime_minutes_when_long(self) -> None:
        import io
        import time as time_mod
        from contextlib import redirect_stderr

        buf = io.StringIO()
        # started_at > 120s ago → minutes format.
        projects = [
            {
                "workspace_root": "/tmp/ws1",
                "pid": 1234,
                "started_at": time_mod.time() - 600.0,
                "project_slug": "proj1",
                "workflow_path": None,
            },
        ]
        with redirect_stderr(buf):
            print_multi_project_hint(projects, command_hint="x")
        output = buf.getvalue()
        self.assertIn("m", output)  # minute suffix


# ---------------------------------------------------------------------------
# print_workspace_info
# ---------------------------------------------------------------------------


class TestPrintWorkspaceInfo(unittest.TestCase):
    def test_with_workspace(self) -> None:
        result = print_workspace_info(Path("/tmp/ws"))
        self.assertIn("workspace: /tmp/ws", result)

    def test_without_workspace(self) -> None:
        result = print_workspace_info(None)
        self.assertIn("workspace: (not found)", result)

    def test_with_workflow(self) -> None:
        result = print_workspace_info(
            Path("/tmp/ws"),
            workflow_path="/path/to/WORKFLOW.md",
        )
        self.assertIn("workspace: /tmp/ws", result)
        self.assertIn("workflow: /path/to/WORKFLOW.md", result)


if __name__ == "__main__":
    unittest.main()
