"""Stage 6 — 性能守卫（budget 详见各测试 docstring）。

验证关键操作的响应时间在可接受范围内。
防止因意外引入重型 import 或阻塞操作导致的 CLI / Agent / REPL 启动缓慢。

CI 阈值放宽
-----------
本文件硬编码的本地基线阈值在 CI runner 上会假阳性（GitHub Actions
ubuntu-latest 2 核通常比开发者本地慢 2-3 倍）。通过环境变量
``CLAWCODEX_CI_THRESHOLD_MULT`` 可以在 CI 上按倍率放宽：

* 本地开发：默认 1（使用原始基线）
* CI PR job：设为 ``2``（保留 ~50% 余量）
* CI nightly job：不设（严格使用原始阈值，作为 perf 回归把关）

参见 ``.github/workflows/ci.yml`` 和 ``stage6-perf-nightly.yml``。
"""

from __future__ import annotations

import os
import time


# CI 上放宽阈值的倍率。读取环境变量是为了让 PR/nightly 用同一份代码。
# 本地默认 1.0；CI 在 workflow 里 export 为 2.0。
_THRESHOLD_MULT = float(os.environ.get("CLAWCODEX_CI_THRESHOLD_MULT", "1"))


class TestStage6Perf:
    """性能回归检测 — 冷启动 / 导入 / 管线响应预算。"""

    # ── CLI budgets ──────────────────────────────────────────────

    def test_cli_help_import_time(self):
        """--help 快速路径不应导入重型模块（budget: < 3s，CI x N）。"""
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
        budget = 3.0 * _THRESHOLD_MULT
        assert elapsed < budget, (
            f"CLI --help import took {elapsed:.2f}s, expected < {budget:.2f}s "
            f"(threshold multiplier={_THRESHOLD_MULT})"
        )

    def test_cli_subprocess_startup_time(self):
        """python -m src.cli --help 子进程启动时间（budget: < 5s，CI x N）。"""
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
        budget = 5.0 * _THRESHOLD_MULT
        assert elapsed < budget, (
            f"CLI --help subprocess took {elapsed:.2f}s, expected < {budget:.2f}s "
            f"(threshold multiplier={_THRESHOLD_MULT})"
        )

    # ── Conversation budget ──────────────────────────────────────

    def test_conversation_import_time(self):
        """Conversation 模块导入不应拉入重型依赖（budget: < 2s，CI x N）。"""
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
        budget = 2.0 * _THRESHOLD_MULT
        assert elapsed < budget, (
            f"Conversation import took {elapsed:.2f}s, expected < {budget:.2f}s "
            f"(threshold multiplier={_THRESHOLD_MULT})"
        )

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
        budget = 3.0 * _THRESHOLD_MULT
        assert elapsed < budget, (
            f"Agent loop warm-start took {elapsed:.2f}s, expected < {budget:.2f}s "
            f"(threshold multiplier={_THRESHOLD_MULT})"
        )

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
        budget = 2.0 * _THRESHOLD_MULT
        assert elapsed < budget, (
            f"Tool execution path took {elapsed:.2f}s, expected < {budget:.2f}s "
            f"(threshold multiplier={_THRESHOLD_MULT})"
        )

    # ── REPL / Headless budget ───────────────────────────────────

    def test_repl_input_pipeline_cold_start(self):
        """REPL 类导入（不实例化）不应超过 5s，CI x N。

        测量从零冷启动 ``from src.repl import ClawcodexREPL`` 的时间。
        重型依赖（Session、providers、tools）在首次实例化时通过
        ``_load_heavy_runtime()`` 加载，因此本测试只覆盖类导入成本。
        本地 budget 设在 prompt_toolkit + rich + completer 基线 ~4.5s 之上
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
        budget = 5.0 * _THRESHOLD_MULT
        assert elapsed < budget, (
            f"REPL cold start took {elapsed:.2f}s, expected < {budget:.2f}s "
            f"(threshold multiplier={_THRESHOLD_MULT})"
        )
