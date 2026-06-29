"""Tests for SOP bundle source-exploration runtime guards."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]

# Minimal stub so @patch("extensions.sop_converter.bundle_context.get_active_bundle") works
# without pulling in clawcodex_ext (and its aiohttp dependency).
import types

def _get_active_bundle_stub():
    return None


_bundle_ctx = types.ModuleType("extensions.sop_converter.bundle_context")
sys.modules.setdefault("extensions.sop_converter", types.ModuleType("extensions.sop_converter"))
sys.modules["extensions.sop_converter.bundle_context"] = _bundle_ctx
_bundle_ctx.get_active_bundle = _get_active_bundle_stub


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_guard = _load_module(
    "extensions.sop_converter.sop_exploration_guard",
    ROOT / "extensions" / "sop_converter" / "sop_exploration_guard.py",
)
check_bundle_source_exploration = _guard.check_bundle_source_exploration

_SDK_ROOT = Path("/mnt/d/projects/JiuwenAgent")
_WIN_SDK_ROOT = Path("D:/projects/JiuwenAgent")


def _mock_bundle(*, sdk_root: Path | None = _SDK_ROOT):
    return SimpleNamespace(
        bundle_name="JiuwenAgent_tool_test",
        sdk_source_dir=sdk_root,
    )


def _ctx(*, agent_type: str | None = None, messages=None):
    return SimpleNamespace(
        agent_type=agent_type,
        startup_agent=None,
        messages=messages or [],
        cwd="/tmp/ws",
        workspace_root="/tmp/ws",
        _agent_dir_override=None,
    )


class TestSopExplorationGuard(unittest.TestCase):
    @patch("extensions.sop_converter.bundle_context.get_active_bundle")
    def test_no_bundle_is_noop(self, mock_bundle) -> None:
        mock_bundle.return_value = None
        err = check_bundle_source_exploration(
            "Grep",
            {"pattern": "team-memory-dir"},
            _ctx(agent_type="clawcodex-overview"),
        )
        self.assertIsNone(err)

    @patch("extensions.sop_converter.bundle_context.get_active_bundle")
    def test_overview_allows_glob_spec_yaml(self, mock_bundle) -> None:
        mock_bundle.return_value = _mock_bundle()
        err = check_bundle_source_exploration(
            "Glob",
            {"pattern": "**/spec.yaml", "path": "/tmp/ws"},
            _ctx(agent_type="clawcodex-overview"),
        )
        self.assertIsNone(err)

    @patch("extensions.sop_converter.bundle_context.get_active_bundle")
    def test_overview_allows_bash_ls(self, mock_bundle) -> None:
        mock_bundle.return_value = _mock_bundle()
        err = check_bundle_source_exploration(
            "Bash",
            {"command": "ls -la"},
            _ctx(agent_type="clawcodex-overview"),
        )
        self.assertIsNone(err)

    @patch("extensions.sop_converter.bundle_context.get_active_bundle")
    def test_overview_allows_sdk_source_ls(self, mock_bundle) -> None:
        mock_bundle.return_value = _mock_bundle()
        err = check_bundle_source_exploration(
            "Bash",
            {"command": "ls /mnt/d/projects/JiuwenAgent/openjiuwen/agent_teams/"},
            _ctx(agent_type="clawcodex-overview"),
        )
        self.assertIsNone(err)

    @patch("extensions.sop_converter.bundle_context.get_active_bundle")
    def test_overview_allows_sdk_source_read_wsl_path(self, mock_bundle) -> None:
        mock_bundle.return_value = _mock_bundle()
        err = check_bundle_source_exploration(
            "Read",
            {
                "file_path": (
                    "/mnt/d/projects/JiuwenAgent/openjiuwen/agent_teams/cli/app.py"
                ),
            },
            _ctx(agent_type="clawcodex-overview"),
        )
        self.assertIsNone(err)

    @patch("extensions.sop_converter.bundle_context.get_active_bundle")
    def test_overview_allows_sdk_source_read_windows_path(self, mock_bundle) -> None:
        mock_bundle.return_value = _mock_bundle()
        err = check_bundle_source_exploration(
            "Read",
            {
                "file_path": (
                    "D:/projects/JiuwenAgent/openjiuwen/agent_teams/cli/app.py"
                ),
            },
            _ctx(agent_type="clawcodex-overview"),
        )
        self.assertIsNone(err)

    @patch("extensions.sop_converter.bundle_context.get_active_bundle")
    def test_overview_allows_sdk_source_glob(self, mock_bundle) -> None:
        mock_bundle.return_value = _mock_bundle()
        err = check_bundle_source_exploration(
            "Glob",
            {
                "pattern": "**/*.py",
                "path": "/mnt/d/projects/JiuwenAgent/openjiuwen/agent_teams/cli",
            },
            _ctx(agent_type="clawcodex-overview"),
        )
        self.assertIsNone(err)

    @patch("extensions.sop_converter.bundle_context.get_active_bundle")
    def test_overview_allows_open_ended_sdk_grep(self, mock_bundle) -> None:
        mock_bundle.return_value = _mock_bundle()
        err = check_bundle_source_exploration(
            "Grep",
            {
                "pattern": "run.*team.*cli",
                "path": "/mnt/d/projects/JiuwenAgent/openjiuwen/agent_teams",
            },
            _ctx(agent_type="clawcodex-overview"),
        )
        self.assertIsNone(err)

    @patch("extensions.sop_converter.bundle_context.get_active_bundle")
    def test_overview_blocks_grep_for_tool_discovery(self, mock_bundle) -> None:
        mock_bundle.return_value = _mock_bundle()
        err = check_bundle_source_exploration(
            "Grep",
            {"pattern": "team-memory-dir", "path": "/tmp/ws"},
            _ctx(agent_type="clawcodex-overview"),
            agent_definitions=[SimpleNamespace(agent_type="openjiuwen_merged-agent")],
        )
        self.assertIsNotNone(err)

    @patch("extensions.sop_converter.bundle_context.get_active_bundle")
    def test_overview_blocks_grep_tool_name_even_under_sdk_root(self, mock_bundle) -> None:
        mock_bundle.return_value = _mock_bundle()
        err = check_bundle_source_exploration(
            "Grep",
            {
                "pattern": "openjiuwen-agent-teams-team-memory-dir",
                "path": "/mnt/d/projects/JiuwenAgent/openjiuwen",
            },
            _ctx(agent_type="clawcodex-overview"),
        )
        self.assertIsNotNone(err)

    @patch("extensions.sop_converter.bundle_context.get_active_bundle")
    def test_overview_blocks_grep_on_wrong_sdk_path(self, mock_bundle) -> None:
        mock_bundle.return_value = _mock_bundle()
        err = check_bundle_source_exploration(
            "Grep",
            {
                "pattern": "team.memory.dir",
                "path": "/tmp/ws/JiuwenAgent/openjiuwen",
            },
            _ctx(agent_type="clawcodex-overview"),
            agent_definitions=[SimpleNamespace(agent_type="memory-agent")],
        )
        self.assertIsNotNone(err)

    @patch("extensions.sop_converter.bundle_context.get_active_bundle")
    def test_domain_agent_blocks_grep_for_kebab_tool_before_skill(self, mock_bundle) -> None:
        mock_bundle.return_value = _mock_bundle()
        err = check_bundle_source_exploration(
            "Grep",
            {"pattern": "openjiuwen-agent-teams-team-memory-dir"},
            _ctx(agent_type="memory-agent"),
        )
        self.assertIsNotNone(err)
        self.assertIn("Skill", err or "")

    @patch("extensions.sop_converter.bundle_context.get_active_bundle")
    def test_domain_agent_allows_read_spec_before_skill(self, mock_bundle) -> None:
        mock_bundle.return_value = _mock_bundle()
        err = check_bundle_source_exploration(
            "Read",
            {"file_path": "/tmp/ws/spec.yaml"},
            _ctx(agent_type="openjiuwen_merged-agent"),
        )
        self.assertIsNone(err)

    @patch("extensions.sop_converter.bundle_context.get_active_bundle")
    def test_domain_agent_allows_sdk_source_read_before_skill(self, mock_bundle) -> None:
        mock_bundle.return_value = _mock_bundle()
        err = check_bundle_source_exploration(
            "Read",
            {
                "file_path": (
                    "D:/projects/JiuwenAgent/openjiuwen/agent_teams/cli/app.py"
                ),
            },
            _ctx(agent_type="openjiuwen_merged-agent"),
        )
        self.assertIsNone(err)

    @patch("extensions.sop_converter.bundle_context.get_active_bundle")
    def test_overview_allows_find_in_openjiuwen_runtime(self, mock_bundle) -> None:
        mock_bundle.return_value = _mock_bundle()
        err = check_bundle_source_exploration(
            "Bash",
            {"command": "find /root/.openjiuwen/.agent_teams/team/ -type f 2>/dev/null"},
            _ctx(agent_type="clawcodex-overview"),
        )
        self.assertIsNone(err)

    @patch("extensions.sop_converter.bundle_context.get_active_bundle")
    def test_overview_blocks_find_xargs_grep_for_tools(self, mock_bundle) -> None:
        mock_bundle.return_value = _mock_bundle()
        err = check_bundle_source_exploration(
            "Bash",
            {"command": "find .clawcodex -name '*.py' | xargs grep -l team-memory"},
            _ctx(agent_type="clawcodex-overview"),
            agent_definitions=[SimpleNamespace(agent_type="memory-agent")],
        )
        self.assertIsNotNone(err)

    @patch("extensions.sop_converter.bundle_context.get_active_bundle")
    def test_blocks_read_sdk_test_tree_config(self, mock_bundle) -> None:
        mock_bundle.return_value = _mock_bundle()
        err = check_bundle_source_exploration(
            "Read",
            {
                "file_path": (
                    "/mnt/d/projects/JiuwenAgent/tests/system_tests/agent_swarm/config.yaml"
                ),
            },
            _ctx(agent_type="openjiuwen_merged-agent"),
        )
        self.assertIsNotNone(err)
        self.assertIn("tests/fixtures", err or "")
        self.assertIn("交互式终端停损", err or "")

    @patch("extensions.sop_converter.bundle_context.get_active_bundle")
    def test_blocks_bash_find_yaml_in_tests(self, mock_bundle) -> None:
        mock_bundle.return_value = _mock_bundle()
        err = check_bundle_source_exploration(
            "Bash",
            {
                "command": (
                    "find /mnt/d/projects/JiuwenAgent -name '*.yaml' "
                    "-path '*/tests/*' 2>/dev/null"
                ),
            },
            _ctx(agent_type="openjiuwen_merged-agent"),
        )
        self.assertIsNotNone(err)

    @patch("extensions.sop_converter.bundle_context.get_active_bundle")
    def test_still_allows_read_sdk_cli_app_py(self, mock_bundle) -> None:
        mock_bundle.return_value = _mock_bundle()
        err = check_bundle_source_exploration(
            "Read",
            {
                "file_path": (
                    "/mnt/d/projects/JiuwenAgent/openjiuwen/agent_teams/cli/app.py"
                ),
            },
            _ctx(agent_type="openjiuwen_merged-agent"),
        )
        self.assertIsNone(err)


class TestSdkPathNormalization(unittest.TestCase):
    @patch("extensions.sop_converter.bundle_context.get_active_bundle")
    def test_wsl_manifest_allows_windows_sdk_read(self, mock_bundle) -> None:
        if sys.platform != "win32":
            self.skipTest("Windows-only path normalization")
        mock_bundle.return_value = _mock_bundle(sdk_root=_SDK_ROOT)
        err = check_bundle_source_exploration(
            "Read",
            {"file_path": str(_WIN_SDK_ROOT / "openjiuwen/agent_teams/cli/app.py")},
            _ctx(agent_type="clawcodex-overview"),
        )
        self.assertIsNone(err)


if __name__ == "__main__":
    unittest.main()
