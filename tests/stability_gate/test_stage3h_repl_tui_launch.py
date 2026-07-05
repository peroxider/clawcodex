"""Stage 3h — REPL & TUI 启动与可使用性烟雾测试（< 10 秒）。

验证：
- REPL / TUI 模块可正常导入，不会因重构或注册链断裂导致 ImportError
- Frontend 注册表正确注册了 ``repl`` / ``tui`` 插件
- ``TUIOptions`` / ``should_use_tui`` 等关键类型可正常构造与调用
- 子进程 ``--tui`` 标志解析正常，不导致 segfault / traceback 崩溃
- TUI App 类可导入（如果 textual 已安装）
- ``run_tui`` / ``ClawCodexExtREPL`` 等核心入口函数可调用

背景：F-48 解耦重构中，``src/entrypoints/tui.py`` 和 ``src/repl/core.py``
已改为 lazy-proxy facade，通过 ``__getattr__`` 代理到 ``clawcodex_ext``。
若代理链或 import 路径断裂，用户运行 ``clawcodex --tui`` 或 ``clawcodex``
（默认 REPL）时将直接报错。此门禁锁住该行为。
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest


# =========================================================================
# Section 1 — 模块导入（Module import）
# =========================================================================


class TestStage3hModuleImport:
    """REPL / TUI 模块导入测试 — 确保入口模块可正常加载。"""

    def test_src_entrypoints_tui_facade_importable(self):
        """``src.entrypoints.tui`` 门面模块可导入且有正确 symbol。"""
        import src.entrypoints.tui as tui_proxy

        assert hasattr(tui_proxy, "TUIOptions"), "missing TUIOptions"
        assert hasattr(tui_proxy, "run_tui"), "missing run_tui"
        assert hasattr(tui_proxy, "should_use_tui"), "missing should_use_tui"

    def test_ext_entrypoints_tui_importable(self):
        """``clawcodex_ext.entrypoints.tui`` 可导入且有正确 symbol。"""
        import clawcodex_ext.entrypoints.tui as ext_tui

        assert hasattr(ext_tui, "TUIOptions")
        assert hasattr(ext_tui, "run_tui")
        assert hasattr(ext_tui, "should_use_tui")
        assert callable(ext_tui.run_tui)

    def test_ext_tui_entrypoint_run_tui_importable(self):
        """``clawcodex_ext.tui.entrypoint.run_tui`` 可直接导入。"""
        from clawcodex_ext.tui.entrypoint import run_tui

        assert callable(run_tui)

    def test_ext_repl_core_importable(self):
        """``clawcodex_ext.repl.core`` 可导入。
        
        这是 ``ClawcodexREPL`` 的 canonical 位置，``src.repl.core`` 的
        lazy-proxy 通过 ``__getattr__`` 指向此处。若此处断裂则 REPL 完全不可用。
        """
        import clawcodex_ext.repl.core as ext_repl

        assert ext_repl is not None
        assert hasattr(ext_repl, "ClawcodexREPL")

    def test_src_repl_core_facade_importable(self):
        """``src.repl.core`` 门面可导入 — lazy-proxy 链完整。"""
        import src.repl.core as repl_facade

        assert hasattr(repl_facade, "ClawcodexREPL")
        # 验证 lazy proxy 可实际解析到 canonical 类
        cls = repl_facade.ClawcodexREPL
        assert cls is not None

    def test_ext_repl_app_importable(self):
        """``clawcodex_ext.repl.app.ClawCodexExtREPL`` 可导入。"""
        from clawcodex_ext.repl.app import ClawCodexExtREPL

        assert ClawCodexExtREPL is not None

    def test_repl_frontend_registered(self):
        """``REPLFrontend`` 已在 frontend 注册表中注册。"""
        from clawcodex_ext.frontend.registry import get_frontend

        repl = get_frontend("repl")
        assert repl is not None, "REPLFrontend should be registered"
        assert repl.name == "repl"
        assert callable(repl.run)

    def test_tui_frontend_registered(self):
        """``TUIFrontend`` 已在 frontend 注册表中注册。"""
        from clawcodex_ext.frontend.registry import get_frontend

        tui = get_frontend("tui")
        assert tui is not None, "TUIFrontend should be registered"
        assert tui.name == "tui"
        assert callable(tui.run)

    def test_cli_dispatch_can_import_tui_should_use(self):
        """CLI dispatch 路径上的 ``should_use_tui`` 可正常导入。
        
        回归防护：```dispatch.py:635`` 执行 ``from src.entrypoints.tui import should_use_tui``
        不应因 lazy-proxy 链断裂而炸。
        """
        from src.entrypoints.tui import should_use_tui

        assert callable(should_use_tui)

    def test_frontend_plugins_module_imports_cleanly(self):
        """``clawcodex_ext.frontend`` 包导入不抛异常。
        
        该 __init__.py 触发所有 ``@register_frontend`` 装饰器，若任一插件
        注册时产生 import 失败，整个 frontend 系统不可用。
        """
        # 无副作用：仅仅导入包
        import clawcodex_ext.frontend as f

        assert hasattr(f, "get_frontend")
        assert hasattr(f, "register_frontend")
        assert hasattr(f, "list_frontends")


# =========================================================================
# Section 2 — TUIOptions / should_use_tui
# =========================================================================


class TestStage3hTuiOptions:
    """``TUIOptions`` 构造和 ``should_use_tui`` 行为。"""

    def test_TUIOptions_dataclass(self):
        """``TUIOptions`` 可用关键参数构造且默认值合理。"""
        from src.entrypoints.tui import TUIOptions

        opts = TUIOptions(
            provider_name="anthropic",
            max_turns=10,
            stream=True,
        )
        assert opts.provider_name == "anthropic"
        assert opts.max_turns == 10
        assert opts.stream is True
        assert opts.permission_mode == "default"
        assert opts.workspace_root is None

    def test_TUIOptions_defaults(self):
        """不传参时所有字段有合理默认值。"""
        from src.entrypoints.tui import TUIOptions

        opts = TUIOptions()
        assert opts.max_turns == 20  # default from dataclass
        assert opts.stream is True
        assert opts.permission_mode == "default"
        assert opts.is_bypass_permissions_mode_available is False

    def test_should_use_tui_explicit_false(self):
        """``explicit=False`` 永远返回 False。"""
        from src.entrypoints.tui import should_use_tui

        assert should_use_tui(False) is False

    def test_should_use_tui_explicit_none_no_env(self):
        """不设 ``CLAWCODEX_TUI`` 时默认返回 False。"""
        old = os.environ.pop("CLAWCODEX_TUI", None)
        try:
            from src.entrypoints.tui import should_use_tui

            result = should_use_tui(None)
            # 非 TTY 环境就是 False
            assert result is False
        finally:
            if old is not None:
                os.environ["CLAWCODEX_TUI"] = old

    def test_should_use_tui_handles_env_var(self):
        """``CLAWCODEX_TUI=1`` 环境变量被正确读取（即使最终因 isatty 返回 False）。"""
        old = os.environ.get("CLAWCODEX_TUI")
        os.environ["CLAWCODEX_TUI"] = "1"
        try:
            from src.entrypoints.tui import should_use_tui

            # subprocess / CI 非 TTY 中 isatty() 返回 False，所以最终是 False
            # 但不抛异常就是好的 — 真实环境 isatty 为 True 时才会走 TUI
            result = should_use_tui(None)
            assert result is False  # non-TTY
        finally:
            if old is not None:
                os.environ["CLAWCODEX_TUI"] = old
            else:
                os.environ.pop("CLAWCODEX_TUI", None)

    def test_should_use_tui_handles_legacy_repl(self):
        """``CLAWCODEX_LEGACY_REPL=1`` 强制返回 False。"""
        old = os.environ.get("CLAWCODEX_LEGACY_REPL")
        os.environ["CLAWCODEX_LEGACY_REPL"] = "1"
        try:
            from src.entrypoints.tui import should_use_tui

            # explicit=True 但 LEGACY_REPL 接管
            assert should_use_tui(True) is False
        finally:
            if old is not None:
                os.environ["CLAWCODEX_LEGACY_REPL"] = old
            else:
                os.environ.pop("CLAWCODEX_LEGACY_REPL", None)

    def test_should_use_tui_handles_tui_0(self):
        """``CLAWCODEX_TUI=0`` 强制返回 False。"""
        old = os.environ.get("CLAWCODEX_TUI")
        os.environ["CLAWCODEX_TUI"] = "0"
        try:
            from src.entrypoints.tui import should_use_tui

            assert should_use_tui(None) is False
        finally:
            if old is not None:
                os.environ["CLAWCODEX_TUI"] = old
            else:
                os.environ.pop("CLAWCODEX_TUI", None)


# =========================================================================
# Section 3 — TUI App 导入（需要 textual）
# =========================================================================


class TestStage3hTuiAppImport:
    """Textual TUI App 类的导入 — 仅在 textual 已安装时测试。"""

    def test_tui_app_importable_when_textual_available(self):
        """``ClawCodexTUI`` (src) 和 ``ClawCodexExtTUI`` (ext) 可导入。
        
        ``clawcodex_ext.tui.app.ClawCodexExtTUI`` 是 TUI frontend 使用的
        actual app 类，``src.tui.app.ClawCodexTUI`` 是上游基类。
        """
        try:
            import textual  # noqa: F401
        except ImportError:
            pytest.skip("textual not installed — cannot test TUI App import")

        from src.tui.app import ClawCodexTUI
        from clawcodex_ext.tui.app import ClawCodexExtTUI

        assert ClawCodexTUI is not None
        assert ClawCodexExtTUI is not None

    def test_tui_ext_entrypoint_importable_when_textual_available(self):
        """``clawcodex_ext.tui.entrypoint`` 全模块可导入。
        
        这包括 ``ClawCodexExtTUI``、``TUIOptions`` 及各种 tool context 的导入。
        """
        try:
            import textual  # noqa: F401
        except ImportError:
            pytest.skip("textual not installed — cannot test TUI entrypoint")

        import clawcodex_ext.tui.entrypoint as tui_ep

        assert hasattr(tui_ep, "run_tui")
        assert callable(tui_ep.run_tui)
        # 确保不因 import 副作用抛异常
        assert tui_ep.__name__ == "clawcodex_ext.tui.entrypoint"

    def test_tui_app_inheritance_chain(self):
        """``ClawCodexExtTUI`` 继承自 ``ClawCodexTUI`` 且关键方法存在。"""
        try:
            import textual  # noqa: F401
        except ImportError:
            pytest.skip("textual not installed")

        from clawcodex_ext.tui.app import ClawCodexExtTUI
        from src.tui.app import ClawCodexTUI

        assert issubclass(ClawCodexExtTUI, ClawCodexTUI)
        # 确保 app 有 compose / on_mount 等基础方法
        assert hasattr(ClawCodexExtTUI, "compose")
        assert hasattr(ClawCodexExtTUI, "on_mount")


# =========================================================================
# Section 4 — 子进程 CLI 烟雾测试（Subprocess smoke）
# =========================================================================


class TestStage3hCliSubprocess:
    """子进程 CLI ``--tui`` / ``--no-tui`` 标志解析测试。

    在非 TTY 环境中，``should_use_tui`` 会返回 False，最终 fallback 到 REPL
    路径。REPL 会阻塞等待 stdin，但启动阶段不应产生 traceback / segfault。

    测试方法：用 ``Popen`` 启动、等待 3 秒让 import + 初始化完成、然后终止，
    检查已捕获的 stderr 输出中无 traceback。
    """

    def _check_no_crash_startup(self, *args: str) -> None:
        """启动子进程，3 秒后终止，验证启动阶段无 traceback/crash。"""
        import time

        proc = subprocess.Popen(
            [sys.executable, "-m", "src.cli", *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
        )
        time.sleep(3)
        # 如果进程已自行退出，直接检查退出码和输出
        returncode = proc.poll()
        if returncode is not None:
            out, err = proc.communicate()
            assert returncode != -6, f"SIGABRT, stderr={err!r}"
            assert returncode != -11, f"SIGSEGV, stderr={err!r}"
            assert "Traceback" not in err, f"Traceback in stderr: {err}"
            assert "ImportError" not in err, f"ImportError in stderr: {err}"
            assert "AttributeError" not in err, f"AttributeError in stderr: {err}"
            return

        # 进程仍在运行（阻塞在 REPL prompt），终止并检查现有输出
        proc.terminate()
        try:
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate(timeout=3)

        # 核心检查：启动阶段不应有 traceback / ImportError
        assert "Traceback" not in err, f"Traceback in stderr: {err}"
        assert "ImportError" not in err, f"ImportError in stderr: {err}"
        assert "AttributeError" not in err, f"AttributeError in stderr: {err}"
        # 不应 SIGABRT / SIGSEGV（terminate 可能回 0/±15 是正常的）
        if err:
            # 只有当我们捕获到网络错误才检查 — terminate 通常给 143
            pass

    def test_cli_tui_help_works(self):
        """``--tui --help`` 正常输出 usage，exit 0。"""
        proc = subprocess.run(
            [sys.executable, "-m", "src.cli", "--tui", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, f"stderr={proc.stderr!r}"
        output = (proc.stdout + proc.stderr).lower()
        assert "usage:" in output, "expected usage in --tui --help output"

    def test_cli_no_tui_help_works(self):
        """``--no-tui --help`` 正常输出。"""
        proc = subprocess.run(
            [sys.executable, "-m", "src.cli", "--no-tui", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, f"stderr={proc.stderr!r}"
        output = (proc.stdout + proc.stderr).lower()
        assert "usage:" in output

    def test_cli_tui_version_works(self):
        """``--tui --version`` 正常返回版本信息。"""
        proc = subprocess.run(
            [sys.executable, "-m", "src.cli", "--tui", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, f"stderr={proc.stderr!r}"
        assert len(proc.stdout.strip()) > 0

    def test_cli_tui_flag_no_traceback(self):
        """``--tui`` 单独传入不应产生 traceback / segfault / ImportError。

        非 TTY 环境：``should_use_tui`` 返回 False → fallback 到 REPL。
        REPL 会阻塞在 prompt — 我们用 3 秒窗口检查启动阶段无 crash。
        """
        self._check_no_crash_startup("--tui")

    def test_cli_no_tui_flag_no_traceback(self):
        """``--no-tui`` 单独传入不应产生 traceback / segfault。"""
        self._check_no_crash_startup("--no-tui")

    def test_cli_legacy_repl_flag_no_traceback(self):
        """``--legacy-repl`` 标志也应能正常解析不 crash。"""
        proc = subprocess.run(
            [sys.executable, "-m", "src.cli", "--legacy-repl", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, f"stderr={proc.stderr!r}"

    def test_cli_tui_resume_no_traceback(self):
        """``--tui --resume browse`` 不 crash（即使最终因非 TTY fallback）。"""
        self._check_no_crash_startup("--tui", "--resume", "browse")

    def test_cli_tui_remembers_slash_commands_importable(self):
        """``clawcodex_ext.repl.core`` 内部 slash 命令系统不因导入而炸。
        
        回归防护：CLI ``--tui`` 路径上会触发 ``src.entrypoints.tui`` 的导入，
        进而触发 ``clawcodex_ext`` 包初始化。若命令系统注册链断裂，
        import 阶段即 crash。
        """
        # 验证 ``register_builtin_commands`` 可导入调用
        from clawcodex_ext.command_system.builtins import register_builtin_commands

        assert callable(register_builtin_commands)


# =========================================================================
# Section 5 — Import 链韧性（Import chain resilience）
# =========================================================================


class TestStage3hImportChain:
    """模拟 CLI dispatch 路径上的关键 import 点，确保链不断裂。"""

    def test_cli_dispatch_imports_work_individually(self):
        """CLI dispatch 中 TUI 分支的 import 语句可独立执行。"""
        # dispatch.py:635 — from src.entrypoints.tui import should_use_tui
        from src.entrypoints.tui import should_use_tui, TUIOptions, run_tui

        assert callable(should_use_tui)
        assert callable(run_tui)
        assert TUIOptions is not None

    def test_frontend_tui_plugin_imports_cleanly(self):
        """``clawcodex_ext.frontend.tui`` 模块导入不抛异常。
        
        该模块被 ``clawcodex_ext.frontend.__init__`` 在 ``import clawcodex_ext.frontend``
        时自动触发。若内部 import 链断裂（如 ``run_tui`` 引用了不存在的 symbol），
        整个 frontend 系统不可用。
        """
        import clawcodex_ext.frontend.tui as f_tui

        # 验证 @register_frontend 装饰器已触发
        from clawcodex_ext.frontend.registry import get_frontend

        tui = get_frontend("tui")
        assert tui is not None
        # TUIFrontend.run 方法应可调用（不用实际执行）
        assert callable(tui.run)

    def test_frontend_repl_plugin_imports_cleanly(self):
        """``clawcodex_ext.frontend.repl`` 模块导入不抛异常。"""
        import clawcodex_ext.frontend.repl as f_repl

        assert f_repl is not None
        from clawcodex_ext.frontend.registry import get_frontend

        repl = get_frontend("repl")
        assert repl is not None
        assert callable(repl.run)

    def test_ext_repl_app_initialization_without_provider(self):
        """``ClawCodexExtREPL`` 可不传 provider 参数构造（缺 api key 降级模式）。
        
        这模拟了用户运行 ``clawcodex --no-tui`` 但未配置 provider 的场景：
        REPL 应进入降级模式（``_api_key_missing = True``），而非 crash。
        
        注意：如果测试环境已有 provider 配置，``_api_key_missing`` 可能为
        False，但这不影响测试通过 — 核心是构造过程不抛异常。
        """
        try:
            from clawcodex_ext.repl.app import ClawCodexExtREPL
        except ImportError:
            pytest.skip("ClawCodexExtREPL import failed (is prompt_toolkit installed?)")

        from pathlib import Path

        try:
            repl = ClawCodexExtREPL(
                provider_name="anthropic",
                stream=False,
                permission_mode="default",
            )
            # 无论 _api_key_missing 是 True 还是 False，构造都不应抛异常
            assert isinstance(repl._api_key_missing, bool), (
                f"_api_key_missing should be bool, got {type(repl._api_key_missing)}"
            )
        except Exception as exc:
            pytest.fail(f"ClawCodexExtREPL() raised unexpected exception: {exc}")

    def test_repl_inheritance_chain(self):
        """``ClawCodexExtREPL`` 继承自 ``ClawcodexREPL`` 且关键方法存在。"""
        from clawcodex_ext.repl.app import ClawCodexExtREPL
        import clawcodex_ext.repl.core as ext_repl

        assert issubclass(ClawCodexExtREPL, ext_repl.ClawcodexREPL)
        # 确保 run / chat / handle_command 等核心方法存在
        assert hasattr(ClawCodexExtREPL, "run")
        assert hasattr(ClawCodexExtREPL, "chat")
        assert hasattr(ClawCodexExtREPL, "handle_command")


# =========================================================================
# Section 6 — TUI _textual_available 探测逻辑
# =========================================================================


class TestStage3hTextualAvailability:
    """``_textual_available()`` 在不抛出异常的前提下正确报告 textual 状态。"""

    def test_textual_available(self):
        """``_textual_available()`` 可正常调用，不抛异常。"""
        from src.entrypoints.tui import _textual_available

        result = _textual_available()
        # 只需可调用且返回 bool 即可
        assert isinstance(result, bool)
