"""IM 侧斜杠命令白名单门禁。

在 InboundDispatcher.process 中，对 opt-in runtime 的 origin 执行白名单检查：
只放行白名单内的斜杠命令，其余斜杠命令在网关层直接拒绝。非斜杠命令
（普通文本）不受影响，直接放行。

REPL 白名单覆盖 IM 交互真正需要的会话控制与只读查询命令。Orchestrator
白名单覆盖 README 暴露给 IM 的 issue 子命令，以及唯一允许的 server status。
"""

from __future__ import annotations

# 白名单（含别名）。判定标准：
# - 中断/清空会话、设置目标（用户明确放行）
# - 只读查询类命令
REPL_ALLOWED_COMMANDS: frozenset[str] = frozenset(
    {
        # 会话控制（用户明确放行）
        '/stop',
        '/clear',
        '/reset',
        '/new',
        '/goal',
        # 只读查询
        '/help',
        '/?',
        '/cost',
        '/history',
        '/context',
        '/recap',
        '/btw',
        '/cron-list',
        '/cron-status',
        '/cron-runs',
        '/tools',
        '/skills',
        '/diff',
        '/mcp',
        '/tasks',
        '/idle',
        '/doctor',
        '/release-notes',
    }
)

ORCHESTRATOR_ALLOWED_COMMANDS: frozenset[str] = frozenset(
    {
        '/server status',
        '/issue list',
        '/issue show',
        '/issue tail',
        '/issue stop',
        '/issue pause',
        '/issue resume',
        '/issue takeover',
        '/issue clarify',
        '/issue inject',
        '/issue workspace',
    }
)


def _block_reason(cmd_token: str) -> str:
    """构造拒绝消息，回显被拒绝的命令。"""
    return f'`{cmd_token}` 非命令白名单，已被 gateway 禁止执行。'


def _unsupported_reason(command_display: str) -> str:
    return f'不支持 {command_display} 执行'


def _slash_parts(text: str) -> list[str]:
    stripped = (text or '').strip()
    if not stripped.startswith('/'):
        return []
    return stripped.split(maxsplit=2)


def check_repl_command(text: str) -> tuple[bool, str]:
    """Return (allowed, reason). 只检查斜杠命令，非斜杠输入直接放行。

    带参数的命令（如 /goal finish）按命令名前缀判定；纯命令（如 /stop）
    直接匹配。非斜杠输入返回 (True, "")。单独的 ``/``（无命令名）放行，
    REPL 侧会将其处理为 slash palette 入口。
    """
    parts = _slash_parts(text)
    if not parts:
        return True, ''
    # 取第一个 token 作为命令名（含前导 /），小写比较
    cmd_token = parts[0].lower()
    # 单独的 "/"（无命令名）放行，REPL 侧处理为 slash palette
    if cmd_token == '/':
        return True, ''
    if cmd_token in REPL_ALLOWED_COMMANDS:
        return True, ''
    return False, _block_reason(cmd_token)


def check_orchestrator_command(text: str) -> tuple[bool, str]:
    """Return (allowed, reason) for orchestrator IM slash commands.

    Only README-listed issue commands and ``/server status`` pass. Plain text
    remains pass-through so operator follow-up/context messages still work.
    """
    parts = _slash_parts(text)
    if not parts:
        return True, ''
    first = parts[0].lower()
    second = parts[1].lower() if len(parts) > 1 else ''
    command_display = first if not second else f'{first} {second}'
    command_key = command_display
    if command_key in ORCHESTRATOR_ALLOWED_COMMANDS:
        return True, ''
    return False, _unsupported_reason(command_display)


__all__ = [
    'ORCHESTRATOR_ALLOWED_COMMANDS',
    'REPL_ALLOWED_COMMANDS',
    'check_orchestrator_command',
    'check_repl_command',
]
