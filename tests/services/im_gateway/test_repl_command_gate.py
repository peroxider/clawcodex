"""Tests for repl_command_gate: IM 侧 REPL 斜杠命令白名单门禁。

覆盖：
- 白名单内每个命令（含别名）放行 → (True, "")
- 带参数的命令放行
- 非白名单命令拒绝 → (False, reason)，reason 回显被拒绝的命令
- 非斜杠输入放行
- 大小写不敏感
"""

from __future__ import annotations

import pytest

from clawcodex_ext.services.im_gateway.repl_command_gate import (
    REPL_ALLOWED_COMMANDS,
    check_repl_command,
)


# -- 白名单内命令放行 --------------------------------------------------------


@pytest.mark.parametrize(
    'cmd',
    sorted(REPL_ALLOWED_COMMANDS),
    ids=lambda c: f'allowed:{c}',
)
def test_allowed_command_passes(cmd: str) -> None:
    allowed, reason = check_repl_command(cmd)
    assert allowed is True
    assert reason == ''


def test_allowed_command_with_args_passes() -> None:
    """带参数的命令按命令名前缀判定，应放行。"""
    for text in ['/goal finish the task', '/clear all', '/help me', '/stop now']:
        allowed, reason = check_repl_command(text)
        assert allowed is True, f'expected {text!r} to be allowed'
        assert reason == ''


# -- 非白名单命令拒绝 --------------------------------------------------------


@pytest.mark.parametrize(
    'cmd',
    [
        '/exit',
        '/quit',
        '/q',
        '/login',
        '/permissions',
        '/permission',
        '/model',
        '/provider',
        '/init',
        '/compact',
        '/save',
        '/load',
        '/resume',
        '/cron-run',
        '/cron-fire',
        '/cron-delete',
        '/tool',
        '/memory',
        '/rewind',
        '/advisor',
        '/telemetry',
        '/vim',
        '/tui',
        '/unknown-cmd-xyz',
    ],
    ids=lambda c: f'blocked:{c}',
)
def test_blocked_command_rejected(cmd: str) -> None:
    allowed, reason = check_repl_command(cmd)
    assert allowed is False
    # reason 必须回显被拒绝的命令
    assert cmd.lower() in reason
    assert '非命令白名单' in reason or '已被' in reason or '禁止' in reason


def test_blocked_command_reason_echoes_command_token() -> None:
    """拒绝消息必须包含被拒绝的命令 token（回显）。"""
    allowed, reason = check_repl_command('/exit')
    assert allowed is False
    assert '`/exit`' in reason


def test_blocked_command_with_args_rejected() -> None:
    """带参数的非白名单命令也应拒绝，reason 回显命令 token。"""
    allowed, reason = check_repl_command('/model gpt-4')
    assert allowed is False
    assert '`/model`' in reason


# -- 非斜杠输入放行 ----------------------------------------------------------


@pytest.mark.parametrize(
    'text',
    ['hello', '普通文本消息', '  /  ', '/', '', '   ', 'not a command'],
    ids=lambda t: f'passthrough:{t!r}',
)
def test_non_slash_input_passes(text: str) -> None:
    allowed, reason = check_repl_command(text)
    assert allowed is True
    assert reason == ''


# -- 大小写不敏感 ------------------------------------------------------------


@pytest.mark.parametrize(
    'cmd',
    ['/STOP', '/Clear', '/RESET', '/NEW', '/GOAL', '/Help', '/COST', '/DOCTOR'],
)
def test_case_insensitive(cmd: str) -> None:
    allowed, reason = check_repl_command(cmd)
    assert allowed is True, f'expected {cmd!r} (case-insensitive) to be allowed'
    assert reason == ''


def test_case_insensitive_blocked() -> None:
    """非白名单命令的大写形式也应拒绝。"""
    allowed, reason = check_repl_command('/EXIT')
    assert allowed is False
    assert '/exit' in reason  # reason 中回显的 token 是小写化后的
