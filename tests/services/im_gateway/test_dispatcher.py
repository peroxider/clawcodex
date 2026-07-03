"""Tests for InboundDispatcher REPL 白名单门禁集成。

覆盖 dispatcher.process 在 REPL 目标下的白名单检查：
- REPL 绑定的 origin 发送非白名单命令 → 返回拒绝 ack，_push_handler 不被调用
- REPL 绑定的 origin 发送白名单命令 → _push_handler 被调用
- REPL 绑定的 origin 发送普通文本 → _push_handler 被调用
- orchestrator 绑定的 origin 发送非白名单命令 → 白名单不生效，_push_handler 被调用
"""

from __future__ import annotations

import asyncio

import pytest

from clawcodex_ext.services.im_gateway.binding import BindingPolicy
from clawcodex_ext.services.im_gateway.dispatcher import InboundDispatcher
from clawcodex_ext.services.im_gateway.models import (
    AckLayer,
    InboundMessage,
    MessageSemantics,
    SessionTarget,
)
from clawcodex_ext.services.im_gateway.router import SessionRouter
from clawcodex_ext.services.im_gateway.store import ReliabilityStore


def _make_message(origin: str, text: str, *, message_id: str | None = None) -> InboundMessage:
    return InboundMessage(
        origin=origin,
        text=text,
        message_id=message_id or f'mid-{origin}-{abs(hash(text))}',
        channel='wechat',
    )


def _make_dispatcher(
    tmp_path,
    *,
    repl_origin: str = 'wechat:acct:user1',
    orchestrator_origin: str = 'wechat:acct:user2',
) -> tuple[InboundDispatcher, SessionRouter, list[InboundMessage]]:
    """构造一个 dispatcher，REPL 与 orchestrator 各绑定一个 origin。

    返回 (dispatcher, router, pushed_messages)。
    pushed_messages 记录 _push_handler 收到的所有消息，用于断言是否被调用。
    """
    store = ReliabilityStore(tmp_path)
    binding = BindingPolicy()
    binding.bind(repl_origin, SessionTarget(session_id='repl-sess', host_type='repl'))
    binding.bind(
        orchestrator_origin,
        SessionTarget(session_id='orch-sess', host_type='orchestrator'),
    )
    router = SessionRouter(binding, store)

    pushed: list[InboundMessage] = []

    async def push_handler(message: InboundMessage) -> bool:
        pushed.append(message)
        return True

    dispatcher = InboundDispatcher(store, router)
    dispatcher.set_push_handler(push_handler)
    return dispatcher, router, pushed


# -- REPL 目标：非白名单命令被拒绝 -------------------------------------------


@pytest.mark.asyncio
async def test_repl_blocked_command_not_pushed(tmp_path) -> None:
    """REPL 绑定的 origin 发送 /exit → 返回拒绝 ack，push_handler 不被调用。"""
    dispatcher, router, pushed = _make_dispatcher(tmp_path)
    msg = _make_message('wechat:acct:user1', '/exit')

    receipt = await dispatcher.process(msg)

    assert len(pushed) == 0, 'blocked command must not be pushed to REPL'
    assert receipt.layer == AckLayer.ACCEPTED
    assert '/exit' in (receipt.message or '')


@pytest.mark.asyncio
async def test_repl_blocked_command_with_args_not_pushed(tmp_path) -> None:
    """REPL 绑定的 origin 发送 /model gpt-4 → 拒绝，push_handler 不被调用。"""
    dispatcher, router, pushed = _make_dispatcher(tmp_path)
    msg = _make_message('wechat:acct:user1', '/model gpt-4')

    receipt = await dispatcher.process(msg)

    assert len(pushed) == 0
    assert receipt.layer == AckLayer.ACCEPTED
    assert '/model' in (receipt.message or '')


# -- REPL 目标：白名单命令被放行 ---------------------------------------------


@pytest.mark.asyncio
async def test_repl_allowed_command_pushed(tmp_path) -> None:
    """REPL 绑定的 origin 发送 /clear → push_handler 被调用。"""
    dispatcher, router, pushed = _make_dispatcher(tmp_path)
    msg = _make_message('wechat:acct:user1', '/clear')

    receipt = await dispatcher.process(msg)

    assert len(pushed) == 1
    assert pushed[0].text == '/clear'
    assert receipt.layer == AckLayer.ENQUEUED


@pytest.mark.asyncio
async def test_repl_allowed_command_with_args_pushed(tmp_path) -> None:
    """REPL 绑定的 origin 发送 /goal finish → push_handler 被调用。"""
    dispatcher, router, pushed = _make_dispatcher(tmp_path)
    msg = _make_message('wechat:acct:user1', '/goal finish the task')

    receipt = await dispatcher.process(msg)

    assert len(pushed) == 1
    assert receipt.layer == AckLayer.ENQUEUED


@pytest.mark.asyncio
async def test_repl_stop_command_pushed(tmp_path) -> None:
    """REPL 绑定的 origin 发送 /stop → push_handler 被调用（/stop 在白名单内）。"""
    dispatcher, router, pushed = _make_dispatcher(tmp_path)
    msg = _make_message('wechat:acct:user1', '/stop')

    receipt = await dispatcher.process(msg)

    assert len(pushed) == 1
    assert receipt.layer == AckLayer.ENQUEUED


# -- REPL 目标：普通文本放行 -------------------------------------------------


@pytest.mark.asyncio
async def test_repl_plain_text_pushed(tmp_path) -> None:
    """REPL 绑定的 origin 发送普通文本 → push_handler 被调用（白名单不影响非斜杠输入）。"""
    dispatcher, router, pushed = _make_dispatcher(tmp_path)
    msg = _make_message('wechat:acct:user1', '你好，请帮我写个函数')

    receipt = await dispatcher.process(msg)

    assert len(pushed) == 1
    assert receipt.layer == AckLayer.ENQUEUED


# -- orchestrator 目标：白名单不生效 -----------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_blocked_command_still_pushed(tmp_path) -> None:
    """orchestrator 绑定的 origin 发送 /exit → 白名单不生效，push_handler 被调用。

    白名单仅对 target.host_type == 'repl' 生效，orchestrator 不受影响。
    """
    dispatcher, router, pushed = _make_dispatcher(tmp_path)
    msg = _make_message('wechat:acct:user2', '/exit')

    receipt = await dispatcher.process(msg)

    assert len(pushed) == 1, 'orchestrator target must not be gated by REPL whitelist'
    assert receipt.layer == AckLayer.ENQUEUED


# -- 拒绝时记录 audit -------------------------------------------------------


@pytest.mark.asyncio
async def test_repl_blocked_command_records_audit(tmp_path) -> None:
    """REPL 绑定的 origin 发送非白名单命令 → audit.ndjson 记录 repl_command_blocked 事件。"""
    dispatcher, router, pushed = _make_dispatcher(tmp_path)
    msg = _make_message('wechat:acct:user1', '/exit')

    await dispatcher.process(msg)

    audit_entries = dispatcher._store.audit_entries()
    blocked_entries = [e for e in audit_entries if e.get('event_type') == 'repl_command_blocked']
    assert len(blocked_entries) == 1
    assert '/exit' in (blocked_entries[0].get('command') or '')
