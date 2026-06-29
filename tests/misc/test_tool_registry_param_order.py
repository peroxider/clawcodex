"""Lightweight tests for wrapper param ordering (no clawcodex_ext import)."""

from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_bridge():
    pos = ROOT / "extensions" / "sop_converter"
    sp_name = "extensions.sop_converter.source_parser"
    if sp_name not in sys.modules:
        pkg = type(sys)("extensions.sop_converter")
        sys.modules["extensions"] = type(sys)("extensions")
        sys.modules["extensions.sop_converter"] = pkg
        sp = _load(sp_name, pos / "source_parser.py")
    else:
        sp = sys.modules[sp_name]

    # Stub heavy imports used at module level in tool_registry_bridge.
    for mod_name in (
        "clawcodex_ext.agent.tool_authoring.persistence",
        "clawcodex_ext.agent.tool_authoring.spec",
        "clawcodex_ext.agent.tool_authoring.validators",
        "extensions.sop_converter.search_tags",
    ):
        if mod_name not in sys.modules:
            stub = type(sys)(mod_name)
            if mod_name.endswith("persistence"):
                stub.TOOL_DIR = Path("/tmp/agent-tools")
                stub.SCRIPTS_DIR = Path("/tmp/agent-tools/scripts")
                stub.bundle_tool_dir = lambda _p: Path("/tmp/agent-tools")
                stub.save_spec = lambda *a, **k: None
                stub.scripts_dir_for = lambda _p: Path("/tmp/agent-tools/scripts")
            if mod_name.endswith("spec"):
                stub.AgentToolSpec = type("AgentToolSpec", (), {})
            if mod_name.endswith("validators"):
                stub.validate_spec = lambda _s: None
            if mod_name.endswith("search_tags"):
                stub.generate_search_tags = lambda *a, **k: ()
            sys.modules[mod_name] = stub

    trb_name = "extensions.sop_converter.tool_registry_bridge"
    return _load(trb_name, pos / "tool_registry_bridge.py")


class TestWrapperParamOrder(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.trb = _load_bridge()
        cls.ParamSpec = cls.trb.ParamSpec
        cls.SourceOperation = cls.trb.SourceOperation

    def test_required_before_optional_after_merge(self) -> None:
        ParamSpec = self.ParamSpec
        init = [
            ParamSpec(name="team_memory_dir", type_hint="str", required=True),
            ParamSpec(name="sys_operation", type_hint="str", required=False, default="None"),
        ]
        merged = self.trb._merge_init_and_method_params(init, [])
        self.assertEqual([p.name for p in merged], ["team_memory_dir", "sys_operation"])

    def test_shared_memory_manager_stub_parses(self) -> None:
        ParamSpec = self.ParamSpec
        SourceOperation = self.SourceOperation
        init = [
            ParamSpec(name="team_memory_dir", type_hint="str", required=True),
            ParamSpec(name="sys_operation", type_hint="str", required=False, default="None"),
        ]
        op = SourceOperation(
            name="ensure_dir",
            description="Ensure.",
            class_name="SharedMemoryManager",
        )
        stub = self.trb._generate_method_stub(
            op,
            is_class_method=True,
            module_name="demo.memory",
            init_params=init,
        )
        ast.parse(stub)
        self.assertIn("def ensure_dir(team_memory_dir, sys_operation=None)", stub)

    def test_full_wrapper_script_runs(self) -> None:
        ParamSpec = self.ParamSpec
        SourceOperation = self.SourceOperation
        source = '''
class SharedMemoryManager:
    def __init__(self, team_memory_dir: str, sys_operation=None) -> None:
        self.team_memory_dir = team_memory_dir

    def ensure_dir(self) -> str:
        import os
        os.makedirs(self.team_memory_dir, exist_ok=True)
        return self.team_memory_dir
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            pkg = tmp / "demo_pkg"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("")
            (pkg / "memory.py").write_text(source)
            init = [
                ParamSpec(name="team_memory_dir", type_hint="str", required=True),
                ParamSpec(name="sys_operation", type_hint="str", required=False, default="None"),
            ]
            op = SourceOperation(
                name="ensure_dir",
                description="Ensure.",
                class_name="SharedMemoryManager",
                file_stem="memory",
            )
            script = self.trb._generate_wrapper_script(
                [op],
                class_name="SharedMemoryManager",
                module_name="demo_pkg.memory",
                file_stem="memory",
                source_dir=str(tmp),
                init_params=init,
            )
            ast.parse(script.read_text(encoding="utf-8"))
            args = json.dumps({"team_memory_dir": str(tmp / "team-memory")})
            result = subprocess.run(
                [sys.executable, str(script), "ensure_dir", args],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((tmp / "team-memory").is_dir())


if __name__ == "__main__":
    unittest.main()
