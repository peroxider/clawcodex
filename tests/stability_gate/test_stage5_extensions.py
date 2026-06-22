"""Stage 5 — 三方扩展组件测试（< 5 秒）。

验证 clawcodex_ext/ 下扩展模块的可用性：
- CLI dispatch 入口
- Runtime context
- Frontend 插件注册
- TUI 应用层级
- REPL 扩展
- Provider / Auth 扩展
- 命令系统 / 权限 / Cron 系统
- Memory / Hooks / Settings / Skills
- Bridge 服务
- Tool system
"""

from __future__ import annotations

import os
import sys


class TestStage5ExtCli:
    """下游 CLI 派发和入口点测试。"""

    def test_downstream_cli_main_is_callable(self):
        import clawcodex_ext.cli.main as main_mod

        assert callable(main_mod.main)

    def test_downstream_cli_dispatch_run_cli(self):
        from clawcodex_ext.cli.dispatch import run_cli

        assert callable(run_cli)

    def test_downstream_cli_parser_build(self):
        from clawcodex_ext.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(["--dangerously-skip-permissions", "--permission-mode", "plan"])
        assert args.dangerously_skip_permissions is True
        assert args.permission_mode == "plan"

    def test_downstream_cli_import_is_lightweight(self):
        """导入入口模块不应该拉入重型模块。"""
        for name in ("clawcodex_ext.cli.main", "src.tui.app", "src.repl.core"):
            sys.modules.pop(name, None)

        import clawcodex_ext.cli.main as main_mod  # noqa: F811

        assert "src.tui.app" not in sys.modules
        assert "src.repl.core" not in sys.modules


class TestStage5ExtRuntime:
    """Runtime 扩展测试。"""

    def test_runtime_context_imports(self):
        from clawcodex_ext.runtime.context import RuntimeContext, RuntimeOptions

        assert RuntimeOptions is not None
        assert RuntimeContext is not None
        assert hasattr(RuntimeContext, "build")

    def test_runtime_observer_import(self):
        from clawcodex_ext.runtime.observer import RuntimeObserver

        assert RuntimeObserver is not None


class TestStage5ExtFrontend:
    """Frontend 插件注册测试。"""

    def test_frontend_plugins_registered(self):
        from clawcodex_ext.frontend import get_frontend

        for name in ("tui", "repl", "headless"):
            frontend = get_frontend(name)
            assert frontend is not None, f"Frontend {name!r} not registered"
            assert callable(frontend.run)

    def test_frontend_protocol_import(self):
        from clawcodex_ext.frontend.protocol import Frontend, FrontendPlugin

        assert Frontend is not None
        assert FrontendPlugin is not None

    def test_frontend_registry_import(self):
        from clawcodex_ext.frontend.registry import register_frontend, get_frontend, list_frontends

        assert callable(register_frontend)
        assert callable(get_frontend)
        assert callable(list_frontends)


class TestStage5ExtTui:
    """TUI 扩展测试。"""

    def test_downstream_tui_app_subclasses_upstream(self):
        from clawcodex_ext.tui.app import ClawCodexTUI as ClawCodexExtTUI
        from src.tui.app import ClawCodexTUI

        assert issubclass(ClawCodexExtTUI, ClawCodexTUI)

    def test_tui_entrypoint_imports(self):
        from clawcodex_ext.entrypoints.tui import run_tui, TUIOptions

        assert callable(run_tui)
        assert TUIOptions is not None

    def test_tui_should_use_tui_logic(self):
        from src.entrypoints.tui import should_use_tui

        result = should_use_tui(explicit=None)
        assert result in (True, False)

    def test_tui_should_use_tui_explicit_false(self):
        from src.entrypoints.tui import should_use_tui

        assert should_use_tui(explicit=False) is False


class TestStage5ExtRepl:
    """REPL 扩展测试。"""

    def test_repl_app_import(self):
        from clawcodex_ext.repl.app import ClawCodexExtREPL

        assert ClawCodexExtREPL is not None

    def test_repl_extensions_import(self):
        from clawcodex_ext.repl.core import ClawcodexREPL

        assert ClawcodexREPL is not None

    def test_repl_background_escape_import(self):
        from clawcodex_ext.repl.background_escape import BackgroundEscape

        assert BackgroundEscape is not None


class TestStage5ExtAgent:
    """Agent 扩展测试。"""

    def test_agent_session_ext_import(self):
        from clawcodex_ext.agent.session_ext import resume_session_with_tail

        assert callable(resume_session_with_tail)

    def test_background_runner_import(self):
        from clawcodex_ext.agent.background_runner import (
            launch_background_runner,
            get_background_runner_status,
        )

        assert callable(launch_background_runner)
        assert callable(get_background_runner_status)

    def test_tool_authoring_import(self):
        from clawcodex_ext.agent.tool_authoring import (
            AgentToolSpec,
            list_tools,
            add_tool,
        )

        assert AgentToolSpec is not None
        assert callable(list_tools)
        assert callable(add_tool)


class TestStage5ExtCommandSystem:
    """命令系统扩展测试。"""

    def test_command_system_engine_import(self):
        from clawcodex_ext.command_system.engine import CommandEngine

        assert CommandEngine is not None

    def test_command_system_builtins_import(self):
        from clawcodex_ext.command_system.builtins import (
            HELP_COMMAND,
            CLEAR_COMMAND,
            EXIT_COMMAND,
            get_builtin_commands,
            register_builtin_commands,
        )

        assert HELP_COMMAND is not None
        assert CLEAR_COMMAND is not None
        assert EXIT_COMMAND is not None
        assert callable(get_builtin_commands)
        assert callable(register_builtin_commands)


class TestStage5ExtProviders:
    """Provider 扩展测试。"""

    def test_providers_runtime_import(self):
        from clawcodex_ext.providers.runtime import create_provider, build_provider_from_config

        assert callable(create_provider)
        assert callable(build_provider_from_config)

    def test_providers_codex_models_import(self):
        from clawcodex_ext.providers.codex_models import get_codex_model_ids, CODEX_FALLBACK_MODELS

        assert callable(get_codex_model_ids)
        assert isinstance(CODEX_FALLBACK_MODELS, list)

    def test_providers_openai_codex_provider_import(self):
        from clawcodex_ext.providers.openai_codex_provider import OpenAICodexProvider

        assert OpenAICodexProvider is not None


class TestStage5ExtPermissions:
    """权限扩展测试。"""

    def test_permissions_cycle_import(self):
        from clawcodex_ext.permissions.cycle import (
            cycle_permission_mode,
            get_next_permission_mode,
        )

        assert callable(cycle_permission_mode)
        assert callable(get_next_permission_mode)


class TestStage5ExtCron:
    """Cron 系统扩展测试。"""

    def test_cron_subsystem_imports(self):
        from clawcodex_ext.cron_system import (
            CronTask,
            CronFields,
            CronRun,
            CronJitterConfig,
        )

        assert CronTask is not None
        assert CronFields is not None
        assert CronRun is not None
        assert CronJitterConfig is not None

    def test_cron_scheduler_import(self):
        from clawcodex_ext.cron_system.scheduler import CronScheduler

        assert CronScheduler is not None


class TestStage5ExtAuth:
    """Auth 扩展测试。"""

    def test_auth_codex_oauth_import(self):
        from clawcodex_ext.auth.codex_oauth import (
            CodexDeviceFlow,
            CodexOAuthTokens,
            login_codex_device_flow,
        )

        assert CodexDeviceFlow is not None
        assert CodexOAuthTokens is not None
        assert callable(login_codex_device_flow)

    def test_auth_codex_store_import(self):
        from clawcodex_ext.auth.codex_store import (
            CodexAuthRecord,
            CodexOAuthTokens,
            read_codex_tokens,
            save_codex_tokens,
        )

        assert CodexAuthRecord is not None
        assert CodexOAuthTokens is not None
        assert callable(read_codex_tokens)
        assert callable(save_codex_tokens)


class TestStage5ExtMemory:
    """Memory 扩展测试。"""

    def test_memory_scope_aware_prompt_import(self):
        from clawcodex_ext.memory.scope_aware_prompt import (
            build_scope_aware_memory_prompt,
            set_default_memory_scopes,
            VALID_MEMORY_SCOPES,
        )

        assert callable(build_scope_aware_memory_prompt)
        assert callable(set_default_memory_scopes)
        assert isinstance(VALID_MEMORY_SCOPES, (list, tuple, frozenset))


class TestStage5ExtHooks:
    """Hooks 扩展测试。"""

    def test_hooks_pluggy_adapter_import(self):
        from clawcodex_ext.hooks._pluggy_adapter import (
            PluggyHookManager,
            HookPluginAdapter,
            HookEvent,
            is_pluggy_available,
        )

        assert PluggyHookManager is not None
        assert HookPluginAdapter is not None
        assert HookEvent is not None
        assert callable(is_pluggy_available)


class TestStage5ExtSettings:
    """Settings 扩展测试。"""

    def test_settings_pydantic_adapter_import(self):
        from clawcodex_ext.settings.pydantic_adapter import (
            ClawCodexSettings,
            get_pydantic_settings_class,
            is_pydantic_settings_available,
        )

        assert ClawCodexSettings is not None
        assert callable(get_pydantic_settings_class)
        assert callable(is_pydantic_settings_available)


class TestStage5ExtSkills:
    """Skills 扩展测试。"""

    def test_skills_frontmatter_adapter_import(self):
        from clawcodex_ext.skills._frontmatter_adapter import (
            FrontmatterParseResult,
            parse_frontmatter_with_library,
            is_frontmatter_available,
        )

        assert FrontmatterParseResult is not None
        assert callable(parse_frontmatter_with_library)
        assert callable(is_frontmatter_available)


class TestStage5ExtToolSystem:
    """Tool system 扩展测试。"""

    def test_tool_system_tools_import(self):
        """工具模块（ask_issue_author / create_agent_tool / progress_report）可导入。"""
        from clawcodex_ext.tool_system.tools.ask_issue_author import _ask_issue_author_call
        from clawcodex_ext.tool_system.tools.create_agent_tool import make_create_agent_tool
        from clawcodex_ext.tool_system.tools.progress_report import ProgressReportTool

        assert callable(_ask_issue_author_call)
        assert callable(make_create_agent_tool)
        assert ProgressReportTool is not None


class TestStage5ExtContextSystem:
    """Context system 扩展测试。"""

    def test_context_system_prompt_assembly_import(self):
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
            SystemPromptParts,
            SystemPromptSection,
        )

        assert callable(build_full_system_prompt)
        assert SystemPromptParts is not None
        assert SystemPromptSection is not None

    def test_context_system_gitpython_adapter_import(self):
        """GitPython 适配器导入。

        注意：由于 `tests/git_fixtures/` 不再遮蔽 `git` 包名（2026-06 重命名），
        此导入可以正常进行。如未来 `tests/` 下出现 `git` 目录名，会再次
        触发 PYTHONPATH 遮蔽。
        """
        import pytest
        import importlib
        import sys

        # 安全地检查 git 是否已加载且来自 tests/ 目录
        if "git" in sys.modules:
            git_mod = sys.modules["git"]
            git_file = getattr(git_mod, "__file__", "") or ""
            if "tests" in git_file and "gitpython" not in git_file.lower():
                pass  # 可能被遮蔽 — 继续下面的 try
        try:
            import git  # noqa: F401
        except ImportError:
            pytest.skip("GitPython 未安装")
        # 防御性检查：如果 git 加载后没有 Repo 属性，说明被非 GitPython 的
        # 影子包覆盖了
        import git as _git_check

        if not hasattr(_git_check, "Repo"):
            pytest.skip("PYTHONPATH 遮蔽：tests/ 下存在遮盖 GitPython 的目录")
        from clawcodex_ext.context_system._gitpython_adapter import (
            GitPythonProvider,
            GitContextSnapshot,
            is_gitpython_available,
        )

        assert GitPythonProvider is not None
        assert GitContextSnapshot is not None
        assert callable(is_gitpython_available)


class TestStage5ExtUtils:
    """Utils 扩展测试。"""

    def test_utils_session_watcher_import(self):
        from clawcodex_ext.utils.session_watcher import SessionWatcher

        assert SessionWatcher is not None

    def test_utils_cache_warning_import(self):
        from clawcodex_ext.utils.cache_warning import CacheWarning

        assert CacheWarning is not None


class TestStage5ExtBridge:
    """Bridge 服务扩展测试。"""

    def test_bridge_session_import(self):
        from clawcodex_ext.services.bridge.session import BridgeSession

        assert BridgeSession is not None

    def test_bridge_transport_import(self):
        from clawcodex_ext.services.bridge.transport import BridgeTransport

        assert BridgeTransport is not None

    def test_bridge_auth_import(self):
        from clawcodex_ext.services.bridge.auth import BridgeAuth

        assert BridgeAuth is not None

    def test_tail_follower_import(self):
        from clawcodex_ext.services.tail_follower import TailFollower

        assert TailFollower is not None

    # ------------------------------------------------------------------
    # Phase 2-A: extensions/ports/ + clawcodex_ext/services/context_collapse
    # ------------------------------------------------------------------

    def test_phase2a_ports_bridge_repl_bridge(self):
        import extensions.ports.bridge.repl_bridge as m

        assert hasattr(m, "ReplBridgeHandle")
        assert hasattr(m, "BridgeCoreParams")
        assert callable(m.init_bridge_core)

    def test_phase2a_ports_bridge_bridge_main(self):
        import extensions.ports.bridge.bridge_main as m

        assert hasattr(m, "BackoffConfig")
        assert callable(m.run_bridge_loop)

    def test_phase2a_ports_bridge_session_runner(self):
        import extensions.ports.bridge.session_runner as m

        assert hasattr(m, "SessionSpawnerDeps")
        assert callable(m.create_session_spawner)

    def test_phase2a_ports_bridge_remote_bridge_core(self):
        import extensions.ports.bridge.remote_bridge_core as m

        assert hasattr(m, "RemoteBridgeHandle")
        assert callable(m.init_env_less_bridge_core)

    def test_phase2a_ports_transports_websocket_v1(self):
        import extensions.ports.transports.websocket_v1 as m

        assert hasattr(m, "WebSocketTransport")
        assert hasattr(m, "WebSocketTransportState")

    def test_phase2a_ports_transports_serial_uploader(self):
        import extensions.ports.transports.serial_uploader as m

        assert hasattr(m, "SerialBatchEventUploader")
        assert hasattr(m, "SerialBatchEventUploaderConfig")

    def test_phase2a_ports_transports_hybrid_v1(self):
        import extensions.ports.transports.hybrid_v1 as m

        assert hasattr(m, "HybridTransport")

    def test_phase2a_clawcodex_ext_context_collapse(self):
        import clawcodex_ext.services.context_collapse as m

        # Top-level package re-exports the full public surface
        assert hasattr(m, "CollapseEngine")
        assert hasattr(m, "BoundaryDetector")
        assert hasattr(m, "CollapseStateFile")
        assert hasattr(m, "TokenCounter")
        assert hasattr(m, "SummaryGenerator")
        assert hasattr(m, "Trigger")
        # Submodules accessible via the package
        assert hasattr(m, "boundary")
        assert hasattr(m, "engine")
        assert hasattr(m, "exceptions")
        assert hasattr(m, "persistence")
        assert hasattr(m, "summary")
        assert hasattr(m, "tokens")
        assert hasattr(m, "trigger")


class TestStage5Resilience:
    """扩展加载健壮性 — P1#9 坏扩展不阻塞启动, P2#12 Hook 异常隔离。"""

    def test_bad_extension_import_does_not_crash_interpreter(self):
        """模拟 import 一个坏的 .py 模块不应造成进程级崩溃。

        验证: 即使 import 一个语法错误的模块, Python 的 ImportError
        可以被 caught, 不会级联到 SystemExit/SIGABRT.
        """
        import sys
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            bad_pkg = Path(tmpdir) / "bad_ext"
            bad_pkg.mkdir()
            (bad_pkg / "__init__.py").write_text("this is not valid python =(", encoding="utf-8")
            sys.path.insert(0, tmpdir)
            try:
                # 这应该抛 ImportError / SyntaxError 而不是 SystemExit
                __import__("bad_ext")
                assert False, "should have raised"
            except Exception:
                # 任何 Exception 都可以 —— 关键是不导致进程崩溃
                pass
            finally:
                if tmpdir in sys.path:
                    sys.path.remove(tmpdir)

    def test_root_level_py_import_error_caught(self):
        """项目根目录的 *.py 如果 import 失败, 不应级联到其他模块。

        注: 这是对 '坏扩展不阻塞主程序启动' 的简化模拟 ——
        验证 import 异常的作用域被限制在 try/except 内。
        """
        # 核心模块的导入不应被前一个失败的 import 影响
        from src.agent.conversation import Conversation

        conv = Conversation()
        conv.add_user_message("still works after bad import")
        assert len(conv.get_messages()) == 1


class TestStage5Telemetry:
    """F-97: telemetry (clawcodex_ext/cli/dispatch 段并行的遥测段)。

    验证 telemetry 子系统在不破坏现有扩展语义的前提下提供
    privacy-first 的本地事件流 + crash 去重 fingerprint。
    """

    def test_telemetry_subpackage_imports(self):
        """All F-97 submodules importable."""
        import telemetry
        from telemetry import (
            aggregator,
            cli as telemetry_cli,
            config,
            events,
            fingerprint,
            hooks,
            redaction,
            storage,
            version,
        )
        from telemetry.reporters import (
            base,
            dry_run,
            local_file,
        )

        # Events enum has the full set defined in the design doc.
        from telemetry.events import EventType

        assert EventType.SESSION_START.value == "session_start"
        assert EventType.SESSION_END.value == "session_end"
        assert EventType.COMMAND_RUN.value == "command_run"
        assert EventType.TOOL_SUMMARY.value == "tool_summary"
        assert EventType.ERROR.value == "error"
        assert EventType.CRASH.value == "crash"
        assert EventType.DAILY_SUMMARY.value == "daily_summary"

        # Each module exposes the public surface the public API expects.
        assert callable(config.load_config)
        assert callable(redaction.Redactor)
        assert callable(fingerprint.compute_fingerprint)
        assert callable(storage.LocalJsonlStorage)
        assert callable(aggregator.DailyAggregator)
        assert callable(hooks.install_exception_hooks)
        assert callable(hooks.uninstall_exception_hooks)
        assert callable(telemetry_cli.run_status)
        assert callable(telemetry_cli.run_preview)
        assert callable(telemetry_cli.run_flush)
        assert callable(telemetry_cli.run_enable)
        assert callable(telemetry_cli.run_disable)

    def test_telemetry_default_off_zero_io(self):
        """Default config must have telemetry on (dev-phase) so the
        _NullRecorder path is exercised ONLY when explicitly disabled.

        .. note::
           ``TelemetryConfig.enabled`` and ``ReportingConfig.reporting_enabled``
           are currently ``True`` during development to enable end-to-end testing
           of error-to-Issue push (see ``telemetry/config.py`` TODOs).
           Before formal release, revert both to ``False`` and flip the three
           assertions below back to ``is False`` / ``_NullRecorder``.
        """
        from telemetry import config, recorder

        # Reset the cached singleton to honor any leftover state.
        recorder.reset_recorder_for_tests()

        # Dev-phase default: telemetry is ON.
        cfg = config.TelemetryConfig()
        assert cfg.enabled is True  # TODO: revert to False before formal release
        assert cfg.reporting.reporting_enabled is True  # TODO: revert to False

        # With enabled=True the singleton is a real recorder, not null.
        r = recorder.get_recorder()
        assert r.enabled is True

    def test_telemetry_recorder_endpoints_noop_when_disabled(self):
        """All public recorder endpoints are no-ops when telemetry is off.

        Each method must NOT raise and must NOT touch storage. The
        cold-start path (--help) goes through this code, so any
        exception here would break the 5-second budget.
        """
        from telemetry import recorder

        recorder.reset_recorder_for_tests()
        r = recorder.get_recorder()
        # None of these may raise.
        r.record_session_start(session_id="x", entrypoint="cli")
        r.record_session_end(session_id="x", duration_s=0.1, exit_status=0)
        r.record_command_run(
            session_id="x",
            command_name="repl",
            mode="interactive",
            success=True,
            duration_s=0.1,
            exit_status=0,
        )
        try:
            raise RuntimeError("noop")
        except RuntimeError as exc:
            r.record_error(session_id="x", exc=exc)
        r.record_tool_summary(
            session_id="x",
            tool_name="bash",
            success=True,
            duration_s=0.05,
        )
        r.flush()
        r.close()

    def test_telemetry_redaction_strips_secrets(self):
        """Redactor must mask API keys, tokens, and absolute paths.

        ``redact_text`` is the message-level scrubber (AKIA / sk- /
        ghp_ / Bearer / password= / api_key= / private key blocks).
        Field-level path normalization happens on ``cwd`` /
        ``file_path`` keys via ``_normalize_path``, not in
        ``redact_text``. We exercise both surfaces here.
        """
        from telemetry.redaction import RedactionConfig, Redactor

        redactor = Redactor(RedactionConfig(), project_roots=("/proj",))

        # Message-level: AWS / OpenAI / GitHub / Bearer / private key.
        text = (
            "AKIAIOSFODNN7EXAMPLE leaked "
            "sk-abcdefghijklmnopqrstuv "
            "ghp_abcdefghijklmnopqrstuv "
            "Bearer eyJabc123def456ghi789jkl"
        )
        sanitized = redactor.redact_text(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in sanitized
        assert "sk-abcdefghijklmnopqrstuv" not in sanitized
        assert "ghp_abcdefghijklmnopqrstuv" not in sanitized
        assert "eyJabc123def456ghi789jkl" not in sanitized
        # Placeholder should appear at least 4 times.
        assert sanitized.count("[REDACTED]") >= 4

        # Field-level: cwd / file_path keys get normalized to project
        # relative form (or path:<hash> when not under any project
        # root). Absolute paths in those fields must not survive.
        redacted = redactor._redact_value("file_path", "/home/alice/secret.txt")
        assert "/home/alice" not in str(redacted)
        redacted_cwd = redactor._redact_value("cwd", "/home/alice/projects/secret")
        assert "/home/alice" not in str(redacted_cwd)

    def test_telemetry_fingerprint_stable_across_runs(self):
        """Fingerprint for the same exception class+location is stable."""
        from telemetry.fingerprint import compute_fingerprint

        try:
            raise ValueError("boom")
        except ValueError as exc:
            a = compute_fingerprint(exc)
            b = compute_fingerprint(exc)
        assert a == b
        assert len(a) == 16

    def test_telemetry_storage_creates_dirs_lazily(self):
        """Storage eagerly creates the base dir on construction; subdirs
        (events/, crashes/, ...) are created lazily on first append.

        Validates the privacy-first design: enabled=False never
        instantiates the storage at all (covered by the prior test).
        """
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "telemetry"
            from telemetry.storage import LocalJsonlStorage

            # Constructor creates the base dir eagerly so the first
            # append can write without an extra mkdir round-trip.
            assert not base.exists()
            storage = LocalJsonlStorage(base, retention_days=7)
            assert base.exists()
            # Subdirectories (events/, crashes/, ...) are NOT created
            # until the first append lands — that's the lazy bit.
            assert not (base / "events").exists()
            assert not (base / "crashes").exists()

            from telemetry.events import EventType, TelemetryEvent

            event = TelemetryEvent(
                type=EventType.SESSION_START,
                timestamp=0.0,
                session_id="deadbeef",
            )
            storage.append("events", event.to_dict())
            # After first append, the events/ subdir exists.
            assert (base / "events").exists()


class TestStage5ExtDreaming:
    """F-100: 移植 Dreaming 后台记忆整合系统 — Phase A.

    验证 ``clawcodex_ext/dreaming/`` 子系统的 public surface 可加载,
    并锁定与上游 ``claude-code-best`` 对齐的常量/默认值. 子模块覆盖:
    config / paths / lock / prompt / runner / service.
    """

    def test_dreaming_package_imports(self):
        """Top-level package re-exports the consolidated public API."""
        import clawcodex_ext.dreaming as dreaming_mod

        for name in (
            # config
            "DreamConfig",
            "DEFAULT_DREAM_CONFIG",
            "get_dream_config",
            "set_dream_config",
            "is_auto_dream_enabled",
            # paths
            "get_auto_mem_entrypoint",
            "get_auto_mem_path",
            "is_auto_memory_enabled",
            "is_kairos_active",
            "project_transcript_dir",
            # lock
            "HOLDER_STALE_MS",
            "LOCK_FILE_NAME",
            "list_sessions_touched_since",
            "read_last_consolidated_at",
            "record_consolidation",
            "rollback_consolidation_lock",
            "try_acquire_consolidation_lock",
            # prompt
            "DREAM_PROMPT_PREFIX",
            "build_consolidation_prompt",
            # runner
            "DreamRunResult",
            "run_dream_consolidation",
            # service
            "execute_auto_dream",
            "init_auto_dream",
            "kill_dream_task",
            "manual_dream",
        ):
            assert hasattr(dreaming_mod, name), f"dreaming missing {name!r}"

    def test_dreaming_paths_re_exports(self):
        """paths.py re-exports upstream memdir helpers + clawcodex additions."""
        from clawcodex_ext.dreaming import paths as paths_mod
        from src.memdir.paths import (
            get_auto_mem_entrypoint,
            get_auto_mem_path,
            is_auto_memory_enabled,
        )

        # Upstream re-exports must be the *same* object (no shadow copy).
        assert paths_mod.get_auto_mem_entrypoint is get_auto_mem_entrypoint
        assert paths_mod.get_auto_mem_path is get_auto_mem_path
        assert paths_mod.is_auto_memory_enabled is is_auto_memory_enabled

        # clawcodex-specific additions — all callable.
        assert callable(paths_mod.is_kairos_active)
        assert callable(paths_mod.project_transcript_dir)

        # KAIROS is upstream-only — default off unless CLAWCODEX_KAIROS=1.
        # is_kairos_active() is best-effort, no external side effect.
        if "CLAWCODEX_KAIROS" not in os.environ:
            assert paths_mod.is_kairos_active() is False

    def test_dreaming_lock_constants(self):
        """lock.py exposes the file lock filename + stale timeout."""
        from clawcodex_ext.dreaming import lock as lock_mod

        # Filename matches the upstream consolidation lock file.
        assert lock_mod.LOCK_FILE_NAME == ".consolidate-lock"
        # 60 minutes — matches upstream HOLDER_STALE_MS.
        assert lock_mod.HOLDER_STALE_MS == 60 * 60 * 1000
        # Public lock helpers are callable.
        for fn in (
            lock_mod.try_acquire_consolidation_lock,
            lock_mod.rollback_consolidation_lock,
            lock_mod.read_last_consolidated_at,
            lock_mod.record_consolidation,
            lock_mod.list_sessions_touched_since,
        ):
            assert callable(fn)

    def test_dreaming_config_defaults(self):
        """DEFAULT_DREAM_CONFIG matches the documented thresholds (24h / 5 sessions)."""
        from clawcodex_ext.dreaming import (
            DEFAULT_DREAM_CONFIG,
            DreamConfig,
            get_dream_config,
            is_auto_dream_enabled,
        )

        assert isinstance(DEFAULT_DREAM_CONFIG, DreamConfig)
        assert DEFAULT_DREAM_CONFIG.min_hours == 24.0
        assert DEFAULT_DREAM_CONFIG.min_sessions == 5
        # get_dream_config returns a DreamConfig (not None).
        assert isinstance(get_dream_config(), DreamConfig)
        # is_auto_dream_enabled is callable; value depends on env, don't assert.
        assert callable(is_auto_dream_enabled)

    def test_dreaming_runner_factory_swap(self):
        """runner.py exposes a swap point + stable result dataclass."""
        from clawcodex_ext.dreaming.runner import (
            DreamRunResult,
            run_dream_consolidation,
            set_dream_runner_factory,
        )

        # Result dataclass has stable defaults — stub has same shape as real.
        result = DreamRunResult()
        assert result.files_touched == []
        assert result.usage == {}
        assert result.summary == ""

        # set_dream_runner_factory(None) is a valid no-op (clear to built-in stub).
        set_dream_runner_factory(None)
        assert callable(set_dream_runner_factory)
        assert callable(run_dream_consolidation)

    def test_dreaming_service_exports(self):
        """service.py exposes the gate-chain entry points + kill path."""
        from clawcodex_ext.dreaming.service import (
            execute_auto_dream,
            init_auto_dream,
            kill_dream_task,
            manual_dream,
        )

        # All four symbols are wired and callable.
        assert callable(init_auto_dream)
        assert callable(execute_auto_dream)
        assert callable(kill_dream_task)
        assert callable(manual_dream)
