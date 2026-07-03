"""REPL 侧斜杠命令白名单门禁。

在 InboundDispatcher.process 中，对 target.host_type == 'repl' 的 origin
执行白名单检查：只放行白名单内的斜杠命令，其余斜杠命令在网关层直接拒绝。
非斜杠命令（普通文本）不受影响，直接放行。

白名单设计标准：IM 侧 REPL 交互真正需要的命令——中断/清空会话、
设置目标、只读查询类命令。会修改凭证/权限/provider/model/持久化状态
的命令不在白名单内。
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


def _block_reason(cmd_token: str) -> str:
    """构造拒绝消息，回显被拒绝的命令。"""
    return f'`{cmd_token}` 非命令白名单，已被 gateway 禁止执行。'


def check_repl_command(text: str) -> tuple[bool, str]:
    """Return (allowed, reason). 只检查斜杠命令，非斜杠输入直接放行。

    带参数的命令（如 /goal finish）按命令名前缀判定；纯命令（如 /stop）
    直接匹配。非斜杠输入返回 (True, "")。单独的 ``/``（无命令名）放行，
    REPL 侧会将其处理为 slash palette 入口。
    """
    stripped = (text or '').strip()
    if not stripped.startswith('/'):
        return True, ''
    # 取第一个 token 作为命令名（含前导 /），小写比较
    cmd_token = stripped.split(maxsplit=1)[0].lower()
    # 单独的 "/"（无命令名）放行，REPL 侧处理为 slash palette
    if cmd_token == '/':
        return True, ''
    if cmd_token in REPL_ALLOWED_COMMANDS:
        return True, ''
    return False, _block_reason(cmd_token)


__all__ = ['REPL_ALLOWED_COMMANDS', 'check_repl_command']
