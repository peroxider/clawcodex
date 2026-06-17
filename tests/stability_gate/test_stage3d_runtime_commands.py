"""Stage 3d — /model 和 /provider 运行时命令可用性测试（< 5 秒）。

覆盖 F-43 的 /model 和 /provider 斜杠命令在两种场景下的正确性：

- **有 runtime_context**：命令应显示当前 provider/model + 可用列表
- **无 runtime_context**：命令应降级显示列表（不抛异常 / 不报 Unknown command）

验证方式：直接通过 ``execute_command_sync`` 调用命令并断言返回值，
不经过 REPL 完整调度层，保持测试轻量快速。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _build_context(*, runtime_context: bool = False):
    """Build a minimal ``CommandContext`` for testing.

    Parameters
    ----------
    runtime_context : bool
        When *True*, attach a ``runtime_context`` namespace so the command
        shows the current-state header.  When *False* (default), omit it so
        the command must degrade gracefully.
    """
    from clawcodex_ext.command_system.engine import create_command_context

    provider = SimpleNamespace(
        model="test-model",
        get_available_models=lambda: ["test-model"],
    )
    kwargs: dict = dict(
        workspace_root=Path("/tmp"),
        provider=provider,
    )
    if runtime_context:
        kwargs["runtime_context"] = SimpleNamespace(
            provider_name="anthropic",
            options=SimpleNamespace(model="test-model"),
            provider=provider,
            tool_registry=None,
            tool_context=None,
            swap_provider=lambda p, m=None: None,
        )
    return create_command_context(**kwargs)


# ---------------------------------------------------------------------------
# 注册测试
# ---------------------------------------------------------------------------


class TestRuntimeCommandsRegistration:
    """register_runtime_commands 将 /model 和 /provider 注册为 LocalCommand。"""

    def test_register_runtime_commands_adds_model(self):
        """register_runtime_commands 为全局 registry 添加 model LocalCommand。"""
        from clawcodex_ext.command_system import get_command_registry
        from clawcodex_ext.command_system.types import CommandType

        get_command_registry().clear()
        from clawcodex_ext.cli.runtime_commands import register_runtime_commands

        register_runtime_commands(None)
        cmd = get_command_registry().get("model")
        assert cmd is not None, "model command should be registered"
        assert cmd.command_type == CommandType.LOCAL, (
            f"expected LOCAL, got {cmd.command_type}"
        )

    def test_register_runtime_commands_adds_provider(self):
        """register_runtime_commands 为全局 registry 添加 provider LocalCommand。"""
        from clawcodex_ext.command_system import get_command_registry
        from clawcodex_ext.command_system.types import CommandType

        get_command_registry().clear()
        from clawcodex_ext.cli.runtime_commands import register_runtime_commands

        register_runtime_commands(None)
        cmd = get_command_registry().get("provider")
        assert cmd is not None, "provider command should be registered"
        assert cmd.command_type == CommandType.LOCAL, (
            f"expected LOCAL, got {cmd.command_type}"
        )


# ---------------------------------------------------------------------------
# 命令执行测试 — 无 runtime_context（降级路径）
# ---------------------------------------------------------------------------


class TestRuntimeCommandsWithoutRuntimeContext:
    """/model 和 /provider 在缺少 runtime_context 时降级工作。"""

    def _ensure_registered(self):
        from clawcodex_ext.command_system import get_command_registry
        from clawcodex_ext.cli.runtime_commands import register_runtime_commands

        get_command_registry().clear()
        register_runtime_commands(None)

    def test_model_no_args_without_context(self):
        """/model 无参调用，无 runtime_context，返回成功和模型列表。"""
        self._ensure_registered()
        from clawcodex_ext.command_system.builtins import execute_command_sync

        success, result_text, error = execute_command_sync(
            "model", "", _build_context(runtime_context=False)
        )
        assert success is True, f"expected success, got error={error!r}"
        assert result_text is not None, "expected result text"
        assert "Models:" in result_text, "output should contain 'Models:'"
        assert "anthropic:" in result_text, "output should list providers"

    def test_provider_no_args_without_context(self):
        """/provider 无参调用，无 runtime_context，返回成功和提供商列表。"""
        self._ensure_registered()
        from clawcodex_ext.command_system.builtins import execute_command_sync

        success, result_text, error = execute_command_sync(
            "provider", "", _build_context(runtime_context=False)
        )
        assert success is True, f"expected success, got error={error!r}"
        assert result_text is not None, "expected result text"
        assert "Providers:" in result_text, "output should contain 'Providers:'"
        assert "anthropic" in result_text, "output should list providers"

    def test_model_no_args_without_context_no_unknown_command(self):
        """/model 不报 Unknown command。"""
        self._ensure_registered()
        from clawcodex_ext.command_system.builtins import execute_command_sync

        success, _, error = execute_command_sync(
            "model", "", _build_context(runtime_context=False)
        )
        assert success is True, (
            f"should not return Unknown command; got error={error!r}"
        )

    def test_provider_no_args_without_context_no_unknown_command(self):
        """/provider 不报 Unknown command。"""
        self._ensure_registered()
        from clawcodex_ext.command_system.builtins import execute_command_sync

        success, _, error = execute_command_sync(
            "provider", "", _build_context(runtime_context=False)
        )
        assert success is True, (
            f"should not return Unknown command; got error={error!r}"
        )


# ---------------------------------------------------------------------------
# 命令执行测试 — 有 runtime_context（完整路径）
# ---------------------------------------------------------------------------


class TestRuntimeCommandsWithRuntimeContext:
    """/model 和 /provider 在有 runtime_context 时正确显示当前状态。"""

    def _ensure_registered(self):
        from clawcodex_ext.command_system import get_command_registry
        from clawcodex_ext.cli.runtime_commands import register_runtime_commands

        get_command_registry().clear()
        register_runtime_commands(None)

    def test_model_no_args_with_context(self):
        """/model 无参调用，有 runtime_context，显示当前状态 + 模型列表。"""
        self._ensure_registered()
        from clawcodex_ext.command_system.builtins import execute_command_sync

        success, result_text, error = execute_command_sync(
            "model", "", _build_context(runtime_context=True)
        )
        assert success is True, f"expected success, got error={error!r}"
        assert result_text is not None, "expected result text"
        # 当前状态行
        assert "provider:" in result_text, "output should show current provider"
        assert "test-model" in result_text, "output should show current model"
        # 列表
        assert "Models:" in result_text, "output should contain 'Models:'"

    def test_provider_no_args_with_context(self):
        """/provider 无参调用，有 runtime_context，显示当前状态 + 提供商列表。"""
        self._ensure_registered()
        from clawcodex_ext.command_system.builtins import execute_command_sync

        success, result_text, error = execute_command_sync(
            "provider", "", _build_context(runtime_context=True)
        )
        assert success is True, f"expected success, got error={error!r}"
        assert result_text is not None, "expected result text"
        # 当前状态行
        assert "provider:" in result_text, "output should show current provider"
        assert "test-model" in result_text, "output should show current model"
        # 列表
        assert "Providers:" in result_text, "output should contain 'Providers:'"
