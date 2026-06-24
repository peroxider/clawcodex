"""Stage 6 — 性能守卫（budget 详见各测试 docstring）。

验证关键操作的响应时间在可接受范围内。
防止因意外引入重型 import 或阻塞操作导致的 CLI / Agent / REPL 启动缓慢。
"""

from __future__ import annotations

import time


class TestStage6Perf:
    """性能回归检测 — 冷启动 / 导入 / 管线响应预算。"""

    # ── CLI budgets ──────────────────────────────────────────────

    def test_cli_help_import_time(self):
        """--help 快速路径不应导入重型模块（budget: < 3s）。"""
        import subprocess
        import sys

        start = time.monotonic()
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.argv = ['clawcodex', '--help']; "
                "from src.cli import _build_parser; p = _build_parser(); "
                "p.parse_args(['--help'])",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        elapsed = time.monotonic() - start
        assert proc.returncode == 0, f"stderr={proc.stderr!r}"
        assert elapsed < 3.0, f"CLI --help import took {elapsed:.2f}s, expected < 3s"

    def test_cli_subprocess_startup_time(self):
        """python -m src.cli --help 子进程启动时间（budget: < 5s）。"""
        import subprocess
        import sys

        start = time.monotonic()
        proc = subprocess.run(
            [sys.executable, "-m", "src.cli", "--help"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        elapsed = time.monotonic() - start
        assert proc.returncode == 0
        assert elapsed < 5.0, f"CLI --help subprocess took {elapsed:.2f}s, expected < 5s"

    # ── Conversation budget ──────────────────────────────────────

    def test_conversation_import_time(self):
        """Conversation 模块导入不应拉入重型依赖（budget: < 2s）。"""
        import subprocess
        import sys

        start = time.monotonic()
        proc = subprocess.run(
            [sys.executable, "-c", "from src.agent.conversation import Conversation"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        elapsed = time.monotonic() - start
        assert proc.returncode == 0, f"stderr={proc.stderr!r}"
        assert elapsed < 2.0, f"Conversation import took {elapsed:.2f}s, expected < 2s"

    # ── Agent loop budget ────────────────────────────────────────

    def test_agent_loop_warm_start(self):
        """Agent loop 全套模块导入（query + engine + transitions）不应超过 3s。

        测量从零冷启动导入完整 agent loop 路径的时间。
        这是用户第一条消息进入 LLM 调用前必须等待的模块解析成本。
        """
        import subprocess
        import sys

        start = time.monotonic()
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "from src.query import query, QueryParams, "
                "QueryEngine, QueryEngineConfig, StreamEvent",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        elapsed = time.monotonic() - start
        assert proc.returncode == 0, f"stderr={proc.stderr!r}"
        assert elapsed < 3.0, f"Agent loop warm-start took {elapsed:.2f}s, expected < 3s"

    # ── Tool execution budget ────────────────────────────────────

    def test_tool_execution_path_latency(self):
        """工具执行路径导入（registry + build_tool + dispatch）不应超过 2s。

        测量从零冷启动导入工具注册表、工具构建器和查找函数的
        时间。这是工具执行管线的最小冷启动成本。
        """
        import subprocess
        import sys

        start = time.monotonic()
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "from src.tool_system.registry import ToolRegistry, get_all_base_tools; "
                "from src.tool_system.build_tool import find_tool_by_name, Tool",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        elapsed = time.monotonic() - start
        assert proc.returncode == 0, f"stderr={proc.stderr!r}"
        assert elapsed < 2.0, f"Tool execution path took {elapsed:.2f}s, expected < 2s"

    # ── REPL / Headless budget ───────────────────────────────────

    def test_repl_input_pipeline_cold_start(self):
        """REPL 类导入（不实例化）不应超过 5s。

        测量从零冷启动 ``from src.repl import ClawcodexREPL`` 的时间。
        重型依赖（Session、providers、tools）在首次实例化时通过
        ``_load_heavy_runtime()`` 加载，因此本测试只覆盖类导入成本。
        budget 设在 prompt_toolkit + rich + completer 基线 ~4.5s 之上
        留 0.5s 余量。
        """
        import subprocess
        import sys

        start = time.monotonic()
        proc = subprocess.run(
            [sys.executable, "-c", "from src.repl import ClawcodexREPL"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        elapsed = time.monotonic() - start
        assert proc.returncode == 0, f"stderr={proc.stderr!r}"
        assert elapsed < 5.0, f"REPL cold start took {elapsed:.2f}s, expected < 5s"
