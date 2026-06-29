"""Tests for the REPL opt-in wrapper and orchestrator gateway client (P5)."""

from __future__ import annotations

import pytest
from types import SimpleNamespace

from clawcodex_ext.frontend.repl_gateway import QueueFull, ReplGatewayClient
from clawcodex_ext.messaging.semantics import CommandRouter, ControlBridge
from clawcodex_ext.services.im_gateway.models import InboundMessage, MessageSemantics
from extensions.orchestrator.im_gateway_client import (
    OrchestratorGatewayClient,
    OrchestratorHandlers,
)


# -- ReplGatewayClient (capacity + dedup, no live UDS) -----------------


def _make_repl_client(capacity=3):
    enqueued: list[str] = []
    size = [0]

    def enqueue(text: str) -> None:
        enqueued.append(text)
        size[0] += 1

    client = ReplGatewayClient(
        "/tmp/gw.sock",
        session_id="repl_main",
        origin="wechat:direct:default:u",
        enqueue=enqueue,
        queue_size=lambda: size[0],
        queue_capacity=capacity,
    )
    return client, enqueued


def test_repl_can_enqueue_under_capacity() -> None:
    client, _ = _make_repl_client(capacity=5)
    assert client.can_enqueue() is True


@pytest.mark.asyncio
async def test_repl_on_pushed_deliver_enqueues_into_repl(monkeypatch) -> None:
    """A server-pushed DELIVER frame (gateway→REPL) lands in the prompt queue."""
    client, enqueued = _make_repl_client(capacity=5)

    async def _fake_ack(*, delivery_id, layer, message=None):
        return None

    monkeypatch.setattr(client._client, "ack", _fake_ack)

    # simulate the IPC read loop delivering a pushed frame
    from clawcodex_ext.services.im_gateway.ipc_protocol import GatewayFrame

    frame = GatewayFrame.deliver(
        delivery_id="d_push",
        session_id="repl_main",
        origin="wechat:direct:default:u",
        text="hello from wechat",
    )
    await client._on_pushed_deliver(frame)
    assert enqueued == ["hello from wechat"]


def test_im_reply_controller_sends_when_loop_is_not_running() -> None:
    """OUTBOUND must be scheduled even when ``_cron_loop`` is stopped.

    After ``chat()`` returns the REPL is between ``run_until_complete``
    calls so ``_cron_loop.is_running()`` is ``False``. If the controller
    guards on ``is_running()``, the OUTBOUND frame is never scheduled and
    WeChat never receives the assistant reply. ``run_coroutine_threadsafe``
    is designed for this case — it queues the coroutine and the loop
    executes it on the next ``run_until_complete``.
    """
    import asyncio
    import collections

    from clawcodex_ext.frontend.repl_extensions import _ImReplyController

    sent: list[tuple[str, str]] = []

    class _FakeIpc:
        async def send_outbound(self, *, origin, text):
            sent.append((origin, text))

    class _FakeClient:
        def __init__(self):
            self._client = _FakeIpc()
            self._reply_origins = collections.deque(["wechat:direct:a:u1"])

        def pop_reply_origin(self) -> str | None:
            return self._reply_origins.popleft() if self._reply_origins else None

    class _FakeRepl:
        def __init__(self, text):
            self._text = text
            self._cron_loop = asyncio.new_event_loop()

        def _get_last_assistant_text(self):
            return self._text

    repl = _FakeRepl("agent reply")
    controller = _ImReplyController(repl, _FakeClient(), "wechat:direct:*:*")

    # Simulate the post-chat() state: loop is NOT running
    assert not repl._cron_loop.is_running()

    # Controller must schedule send_outbound even though loop is stopped
    controller.on_assistant_turn_complete()

    # Run the loop briefly so the scheduled send_outbound actually executes
    try:
        import time

        deadline = time.time() + 1.0
        while not sent and time.time() < deadline:
            repl._cron_loop.run_until_complete(asyncio.sleep(0.02))
    finally:
        repl._cron_loop.close()
    assert sent == [("wechat:direct:a:u1", "agent reply")], (
        "OUTBOUND must be sent when loop is NOT running (the post-chat() state)"
    )


def test_im_reply_controller_skips_keyboard_turns() -> None:
    """Keyboard-initiated turns must NOT send replies to WeChat.

    When the user types at the REPL prompt (not driven by an IM message),
    ``_reply_origins`` is empty. The controller must check this BEFORE
    calling ``send_outbound`` — otherwise every keyboard interaction would
    attempt to send a reply to an invalid WeChat target.
    """
    import collections

    from clawcodex_ext.frontend.repl_extensions import _ImReplyController

    sent: list[tuple[str, str]] = []

    class _FakeIpc:
        async def send_outbound(self, *, origin, text):
            sent.append((origin, text))

    class _FakeClient:
        def __init__(self):
            self._client = _FakeIpc()
            self._reply_origins = collections.deque()  # empty = keyboard turn

        def pop_reply_origin(self) -> str | None:
            return self._reply_origins.popleft() if self._reply_origins else None

    class _FakeRepl:
        _cron_loop = None  # should never be accessed
        _last_sent = None

        def _get_last_assistant_text(self):
            return "keyboard reply"

    repl = _FakeRepl()
    controller = _ImReplyController(repl, _FakeClient(), "wechat:direct:*:*")

    controller.on_assistant_turn_complete()

    assert sent == [], "keyboard turn must NOT send OUTBOUND to WeChat"


def test_repl_all_private_binding_replies_to_actual_inbound_origin(monkeypatch) -> None:
    """Wildcard REPL bindings reply to the sender origin carried by DELIVER."""
    import asyncio

    from clawcodex_ext.frontend.repl_extensions import _ImReplyController
    from clawcodex_ext.services.im_gateway.ipc_protocol import GatewayFrame

    sent: list[tuple[str, str]] = []

    async def _fake_ack(*, delivery_id, layer, message=None):
        return None

    class _FakeInner:
        async def send_outbound(self, *, origin, text):
            sent.append((origin, text))

    class _FakeRepl:
        def __init__(self):
            self._text = "reply to sender"
            self._cron_loop = asyncio.new_event_loop()

        def _get_last_assistant_text(self):
            return self._text

    client, _ = _make_repl_client(capacity=5)
    client._origin = "wechat:direct:*:*"
    client._client = _FakeInner()
    monkeypatch.setattr(client, "_ack", _fake_ack, raising=False)
    monkeypatch.setattr(client._client, "ack", _fake_ack, raising=False)

    frame = GatewayFrame.deliver(
        delivery_id="d_sender",
        session_id="repl_main",
        origin="wechat:direct:acct:user_sender",
        text="hello",
    )
    asyncio.run(client._on_pushed_deliver(frame))

    repl = _FakeRepl()
    controller = _ImReplyController(repl, client, "wechat:direct:*:*")
    try:
        repl._cron_loop.call_soon(controller.on_assistant_turn_complete)
        import time

        deadline = time.time() + 1.0
        while not sent and time.time() < deadline:
            repl._cron_loop.run_until_complete(asyncio.sleep(0.02))
    finally:
        repl._cron_loop.close()

    assert sent == [("wechat:direct:acct:user_sender", "reply to sender")]


def test_im_reply_controller_sends_permission_prompt_without_consuming_origin(monkeypatch) -> None:
    """Permission menus shown during an IM turn must also be visible in WeChat.

    The permission prompt is not the final assistant reply, so sending it must
    peek at the current IM origin instead of popping it. Otherwise the final
    assistant reply would lose its WeChat target.

    The permission OUTBOUND leaves immediately via the one-shot thread path
    (the loop is NOT running during the permission wait — that is the whole
    point of the 1a fix). The final assistant reply is scheduled on
    ``_cron_loop`` and drained on the next ``run_until_complete``.
    """
    import asyncio
    import collections
    import time

    from clawcodex_ext.frontend.repl_extensions import _ImReplyController

    sent: list[tuple[str, str]] = []

    class _FakeOneShot:
        """Replaces GatewayIpcClient inside _send_outbound_text_from_thread."""

        def __init__(self, socket_path, instance_id=None, **_kwargs) -> None:
            pass

        async def connect(self) -> None:
            return None

        async def send_outbound(self, *, origin, text) -> None:
            sent.append((origin, text))

        async def close(self) -> None:
            return None

    monkeypatch.setattr(
        "clawcodex_ext.services.im_gateway.ipc_client.GatewayIpcClient",
        _FakeOneShot,
    )

    class _FakeIpc:
        async def send_outbound(self, *, origin, text):
            sent.append((origin, text))

    class _FakeClient:
        _socket_path = "/tmp/gw.sock"

        def __init__(self):
            self._client = _FakeIpc()
            self._reply_origins = collections.deque(["wechat:direct:a:u1"])

        def peek_reply_origin(self) -> str | None:
            return self._reply_origins[0] if self._reply_origins else None

        def pop_reply_origin(self) -> str | None:
            return self._reply_origins.popleft() if self._reply_origins else None

    class _FakeRepl:
        def __init__(self):
            self._cron_loop = asyncio.new_event_loop()
            self._text = "done"

        def _get_last_assistant_text(self):
            return self._text

    repl = _FakeRepl()
    client = _FakeClient()
    controller = _ImReplyController(repl, client, "wechat:direct:*:*")

    try:
        assert controller.send_permission_prompt(
            message="Tool Bash wants to delete files",
            options=[("y", "Yes, allow this action"), ("n", "No, deny this action")],
        )

        # Thread path delivers the permission menu without running _cron_loop.
        deadline = time.time() + 1.0
        while len(sent) < 1 and time.time() < deadline:
            time.sleep(0.02)

        # The permission menu used the origin without consuming it.
        assert list(client._reply_origins) == ["wechat:direct:a:u1"]

        controller.on_assistant_turn_complete()
        deadline = time.time() + 1.0
        while len(sent) < 2 and time.time() < deadline:
            repl._cron_loop.run_until_complete(asyncio.sleep(0.02))
    finally:
        repl._cron_loop.close()

    assert sent[0][0] == "wechat:direct:a:u1"
    assert "需要权限" in sent[0][1]
    assert "1. [y] 是，允许此操作" in sent[0][1]
    assert sent[1] == ("wechat:direct:a:u1", "done")


def test_im_permission_prompt_sent_immediately_via_thread_path(monkeypatch) -> None:
    """1a: when ``_cron_loop`` is NOT running (the sync permission path, about
    to block on ``_safe_input``), the OUTBOUND permission menu must leave via
    the one-shot thread path immediately — NOT be queued on ``_cron_loop``.

    ``_cron_loop`` won't drain until ``chat()`` returns and the main loop
    re-enters ``run_until_complete``, i.e. AFTER the user already approved in
    the REPL. Queuing the OUTBOUND there is the stale-permission-notice bug.
    """
    import asyncio
    import collections
    import time

    from clawcodex_ext.frontend.repl_extensions import _ImReplyController

    sent: list[tuple[str, str]] = []

    class _FakeOneShot:
        """Replaces GatewayIpcClient inside _send_outbound_text_from_thread."""

        def __init__(self, socket_path, instance_id=None, **_kwargs) -> None:
            pass

        async def connect(self) -> None:
            return None

        async def send_outbound(self, *, origin, text) -> None:
            sent.append((origin, text))

        async def close(self) -> None:
            return None

    monkeypatch.setattr(
        "clawcodex_ext.services.im_gateway.ipc_client.GatewayIpcClient",
        _FakeOneShot,
    )

    class _FakeInner:
        async def send_outbound(self, *, origin, text) -> None:
            sent.append((origin, text))  # only reached by the buggy loop-queue path

    class _FakeClient:
        _socket_path = "/tmp/gw.sock"

        def __init__(self) -> None:
            self._client = _FakeInner()
            self._reply_origins = collections.deque(["wechat:direct:a:u1"])

        def peek_reply_origin(self) -> str | None:
            return self._reply_origins[0] if self._reply_origins else None

    class _FakeRepl:
        def __init__(self) -> None:
            self._cron_loop = asyncio.new_event_loop()  # NOT running

    repl = _FakeRepl()
    controller = _ImReplyController(repl, _FakeClient(), "wechat:direct:*:*")

    assert not repl._cron_loop.is_running()
    assert controller.send_permission_prompt(
        message="Tool Bash wants to delete files",
        options=[("y", "Yes, allow this action"), ("n", "No, deny this action")],
    )

    # Deliberately do NOT run _cron_loop. The thread path must deliver without it.
    deadline = time.time() + 1.0
    while len(sent) < 1 and time.time() < deadline:
        time.sleep(0.02)
    repl._cron_loop.close()

    assert sent, "permission OUTBOUND must be sent immediately via the thread path"
    assert sent[0][0] == "wechat:direct:a:u1"
    assert "需要权限" in sent[0][1]


def test_permission_prompt_renders_chinese_and_rebrands_claude() -> None:
    """The WeChat-facing permission prompt must be Chinese and self-refer as
    ClawCodex (not Claude). The upstream ``message`` ("Claude wants to use X.
    Allow?") and English option descriptions are translated/rebranded in
    ``_format_permission_prompt`` only — the REPL console is untouched."""
    from clawcodex_ext.frontend.repl_extensions import _ImReplyController

    text = _ImReplyController._format_permission_prompt(
        message="Claude wants to use Bash. Allow?",
        options=[
            ("y", "Yes, allow this action"),
            ("n", "No, deny this action"),
        ],
        suggestion="可在设置中开启 allow_docs",
        interactive=True,
    )
    assert "需要权限" in text
    assert "ClawCodex 想使用 Bash，是否允许？" in text
    assert "Claude" not in text
    assert "1. [y] 是，允许此操作" in text
    assert "2. [n] 否，拒绝此操作" in text
    assert "选项：" in text
    assert "建议：" in text
    assert "请回复选项编号或字母" in text

    # Enable-and-allow option form is translated for any setting name.
    text2 = _ImReplyController._format_permission_prompt(
        message="Claude wants to use Read. Allow?",
        options=[
            ("e", "Enable allow_docs and allow"),
            ("y", "Yes, allow this action"),
            ("n", "No, deny this action"),
        ],
        interactive=False,
    )
    assert "1. [e] 启用 allow_docs 并允许" in text2
    assert "请在 REPL 中选择对应的选项以继续" in text2


def test_handle_im_permission_reply_maps_choices_and_stop() -> None:
    """1b: the permission-reply probe maps menu choices and /stop correctly."""
    import threading

    from clawcodex_ext.frontend.repl_extensions import _handle_im_permission_reply

    def _repl_with_wait(valid):
        class _FakeRepl:
            pass

        r = _FakeRepl()
        r._im_permission_lock = threading.Lock()
        r._im_permission_wait = {
            "event": threading.Event(),
            "choice": None,
            "valid": set(valid),
        }
        return r

    valid = {"1", "2", "y", "n", "yes", "no"}

    # numeric choice → consumed, choice recorded, event set
    r = _repl_with_wait(valid)
    assert _handle_im_permission_reply(r, "1") is True
    assert r._im_permission_wait["choice"] == "1"
    assert r._im_permission_wait["event"].is_set()

    # letter choice
    r = _repl_with_wait(valid)
    assert _handle_im_permission_reply(r, "Y") is True  # case-insensitive
    assert r._im_permission_wait["choice"] == "y"

    # /stop during permission wait → deny
    r = _repl_with_wait(valid)
    assert _handle_im_permission_reply(r, "/stop") is True
    assert r._im_permission_wait["choice"] == "n"

    # non-choice → not consumed, fall through to enqueue
    r = _repl_with_wait(valid)
    assert _handle_im_permission_reply(r, "hello there") is False
    assert r._im_permission_wait["choice"] is None
    assert not r._im_permission_wait["event"].is_set()

    # no active wait → not consumed
    r = _repl_with_wait(valid)
    r._im_permission_wait = None
    assert _handle_im_permission_reply(r, "1") is False


@pytest.mark.asyncio
async def test_repl_deliver_permission_reply_intercepted_before_enqueue(monkeypatch) -> None:
    """1b: when a permission wait is active, a WeChat reply matching a valid
    menu choice is consumed by ``permission_probe`` (ack ``processed``) and is
    NOT enqueued as a new prompt. A non-choice message falls through normally."""
    client, enqueued = _make_repl_client(capacity=5)
    acks: list[tuple] = []

    def _probe(text: str) -> bool:
        return (text or "").strip().lower() in {"1", "2", "y", "n"}

    client._permission_probe = _probe  # injected by _install_im_gateway_client

    async def _fake_ack(*, delivery_id, layer, message=None):
        acks.append((delivery_id, layer, message))
        return None

    monkeypatch.setattr(client._client, "ack", _fake_ack)

    # valid choice → consumed, acked processed, NOT enqueued
    await client.deliver(delivery_id="d_perm", text="1", origin="wechat:direct:a:u")
    assert enqueued == []
    assert acks == [("d_perm", "processed", "permission reply")]

    # non-choice → falls through to enqueue
    await client.deliver(delivery_id="d_msg", text="hello", origin="wechat:direct:a:u")
    assert enqueued == ["hello"]


def test_repl_im_gateway_uses_runtime_options_and_registers_once(monkeypatch) -> None:
    """Runtime options opt into IM; init uses ReplGatewayClient.connect only once."""
    import asyncio

    from clawcodex_ext.frontend import repl_extensions

    monkeypatch.delenv("CLAWCODEX_IM_ORIGIN", raising=False)
    monkeypatch.delenv("CLAWCODEX_IM_GATEWAY_SOCK", raising=False)

    class _FakeInner:
        def __init__(self):
            self.raw_registers = []

        async def register(self, **kwargs):
            self.raw_registers.append(kwargs)

    class _FakeClient:
        def __init__(self, socket_path, **kwargs):
            self.socket_path = socket_path
            self.kwargs = kwargs
            self._client = _FakeInner()
            self.connect_calls = 0
            self.heartbeat_intervals = []

        async def connect(self):
            self.connect_calls += 1

        async def _heartbeat_loop(self, interval):
            self.heartbeat_intervals.append(interval)

    monkeypatch.setattr("clawcodex_ext.frontend.repl_gateway.ReplGatewayClient", _FakeClient)

    class _FakeRepl:
        _queued_prompts = []

        def _enqueue_prompt(self, text):
            return None

        def _wake_prompt_for_im(self):
            return None

    repl = _FakeRepl()
    ctx = SimpleNamespace(
        options=SimpleNamespace(
            im_gateway_origin="wechat:direct:default:user1",
            im_gateway_sock="/tmp/clawcodex-gateway.sock",
        )
    )
    repl_extensions._install_im_gateway_client(repl, ctx)

    client = repl._im_gateway_client
    assert client.socket_path == "/tmp/clawcodex-gateway.sock"
    assert client.kwargs["origin"] == "wechat:direct:default:user1"
    asyncio.run(repl._im_gateway_init(None))
    assert client.connect_calls == 1
    assert client._client.raw_registers == []
    assert callable(client.kwargs["control_handler"])


def test_repl_im_gateway_switch_registers_all_private_messages(monkeypatch) -> None:
    """--im-gateway binds REPL to all WeChat direct private messages by default."""
    from clawcodex_ext.frontend import repl_extensions

    monkeypatch.delenv("CLAWCODEX_IM_ORIGIN", raising=False)
    monkeypatch.delenv("CLAWCODEX_IM_GATEWAY_SOCK", raising=False)

    class _FakeClient:
        def __init__(self, socket_path, **kwargs):
            self.socket_path = socket_path
            self.kwargs = kwargs

    monkeypatch.setattr("clawcodex_ext.frontend.repl_gateway.ReplGatewayClient", _FakeClient)

    class _FakeRepl:
        _queued_prompts = []

        def _enqueue_prompt(self, text):
            return None

        def _wake_prompt_for_im(self):
            return None

    repl = _FakeRepl()
    ctx = SimpleNamespace(
        options=SimpleNamespace(
            im_gateway=True,
            im_gateway_origin=None,
            im_gateway_sock="/tmp/clawcodex-gateway.sock",
        )
    )
    repl_extensions._install_im_gateway_client(repl, ctx)

    assert repl._im_gateway_client.kwargs["origin"] == "wechat:direct:*:*"
    assert callable(repl._im_gateway_client.kwargs["control_handler"])


def test_repl_im_gateway_control_handler_stops_active_run(monkeypatch) -> None:
    """The installed REPL control callback maps IM /stop to active-run cancel."""
    from clawcodex_ext.frontend import repl_extensions

    monkeypatch.delenv("CLAWCODEX_IM_ORIGIN", raising=False)
    monkeypatch.delenv("CLAWCODEX_IM_GATEWAY_SOCK", raising=False)

    class _FakeClient:
        def __init__(self, socket_path, **kwargs):
            self.socket_path = socket_path
            self.kwargs = kwargs

    monkeypatch.setattr("clawcodex_ext.frontend.repl_gateway.ReplGatewayClient", _FakeClient)

    class _FakeRepl:
        _queued_prompts = []

        def __init__(self):
            self.interrupts: list[str] = []

        def _enqueue_prompt(self, text):
            raise AssertionError("/stop should not be enqueued as a normal prompt")

        def _wake_prompt_for_im(self):
            return None

        def _interrupt_active_chat_from_im(self) -> bool:
            self.interrupts.append("stop")
            return True

    repl = _FakeRepl()
    ctx = SimpleNamespace(
        options=SimpleNamespace(
            im_gateway_origin="wechat:direct:default:user1",
            im_gateway_sock="/tmp/clawcodex-gateway.sock",
        )
    )
    repl_extensions._install_im_gateway_client(repl, ctx)

    handler = repl._im_gateway_client.kwargs["control_handler"]
    assert handler("/stop", "wechat:direct:default:user1") is True
    assert repl.interrupts == ["stop"]


@pytest.mark.asyncio
async def test_repl_deliver_wakes_blocked_prompt_loop(monkeypatch) -> None:
    """Enqueuing an IM prompt must wake the REPL's blocked prompt loop.

    Without the wake, the enqueued prompt sits in ``_queued_prompts`` while
    the main loop is stuck in ``prompt_async('❯ ')`` — the message is never
    displayed, processed, or replied to (the "IM message reaches the REPL
    but nothing happens" symptom). ``deliver()`` must invoke the injected
    wake callback right after enqueueing so the loop iterates and drains.
    """
    client, enqueued = _make_repl_client(capacity=5)
    wakes: list[int] = []

    def _wake() -> None:
        wakes.append(1)

    client._wake = _wake  # injected by _install_im_gateway_client

    async def _fake_ack(*, delivery_id, layer, message=None):
        return None

    monkeypatch.setattr(client._client, "ack", _fake_ack)
    await client.deliver(delivery_id="d_wake", text="hello from wechat")
    assert enqueued == ["hello from wechat"]
    assert wakes == [1], "deliver() must wake the REPL prompt loop after enqueue"


@pytest.mark.asyncio
async def test_repl_stop_command_uses_priority_control_path(monkeypatch) -> None:
    """IM /stop should interrupt the active REPL run instead of waiting in queue."""
    client, enqueued = _make_repl_client(capacity=5)
    calls: list[tuple[str, str | None]] = []

    def _control(text: str, origin: str | None = None) -> bool:
        calls.append((text, origin))
        return True

    client._control_handler = _control

    async def _fake_ack(*, delivery_id, layer, message=None):
        return None

    monkeypatch.setattr(client._client, "ack", _fake_ack)
    await client.deliver(
        delivery_id="d_stop",
        text="/stop",
        origin="wechat:direct:default:u",
        semantic="command",
    )
    await client.deliver(
        delivery_id="d_interrupt",
        text="please stop",
        origin="wechat:direct:default:u",
        semantic="interrupt",
    )

    assert calls == [
        ("/stop", "wechat:direct:default:u"),
        ("please stop", "wechat:direct:default:u"),
    ]
    assert enqueued == []


@pytest.mark.asyncio
async def test_repl_rejects_at_capacity_without_silent_drop(monkeypatch) -> None:
    client, enqueued = _make_repl_client(capacity=2)

    async def _fake_deliver(*, delivery_id, session_id, origin, text, semantic=None):
        return None

    monkeypatch.setattr(client._client, "deliver", _fake_deliver)
    # simulate a full queue
    client._queue_size = lambda: 2
    with pytest.raises(QueueFull):
        await client.deliver(delivery_id="d1", text="a")
    assert enqueued == []  # not silently dropped


@pytest.mark.asyncio
async def test_repl_dedups_by_delivery_id(monkeypatch) -> None:
    client, enqueued = _make_repl_client(capacity=5)

    async def _fake_ack(*, delivery_id, layer, message=None):
        return None

    monkeypatch.setattr(client._client, "ack", _fake_ack)
    # first deliver enqueues "a"
    await client.deliver(delivery_id="d1", text="a")
    # second with same id → deduped, returns None, no extra enqueue
    res = await client.deliver(delivery_id="d1", text="a")
    assert res is None
    assert len(enqueued) == 1


@pytest.mark.asyncio
async def test_repl_ack_uses_ack_frame_not_deliver(monkeypatch) -> None:
    client, enqueued = _make_repl_client(capacity=5)
    calls: list[tuple] = []

    async def _fake_ack(*, delivery_id, layer, message=None):
        calls.append(("ack", delivery_id, layer, message))
        return None

    async def _bad_deliver(**_kwargs):
        raise AssertionError("REPL enqueue ack must not send a second DELIVER frame")

    monkeypatch.setattr(client._client, "ack", _fake_ack, raising=False)
    monkeypatch.setattr(client._client, "deliver", _bad_deliver)
    await client.deliver(delivery_id="d1", text="a")
    assert enqueued == ["a"]
    assert calls == [("ack", "d1", "enqueued", "enqueued")]


# -- OrchestratorGatewayClient -----------------------------------------


def _handlers():
    calls: list[tuple] = []

    def queue_pending_message(issue, text):
        calls.append(("queue_pending", issue, text))

    def control_verb(verb, issue):
        calls.append(("control", verb, issue))

    def issue_inject(issue, hint):
        calls.append(("inject", issue, hint))

    def operator_hints(issue, text):
        calls.append(("hints", issue, text))

    def agent_intent(verb, issue):
        calls.append(("intent", verb, issue))

    def issue_cli(verb, issue, payload):
        calls.append(("issue_cli", verb, issue, payload))

    def bridge_interrupt(issue, payload):
        calls.append(("bridge_interrupt", issue, payload))

    return OrchestratorHandlers(
        queue_pending_message=queue_pending_message,
        control_verb=control_verb,
        issue_inject=issue_inject,
        operator_hints=operator_hints,
        agent_intent=agent_intent,
        issue_cli=issue_cli,
        bridge_interrupt=bridge_interrupt,
    ), calls


def test_orchestrator_followup_to_queue_pending_message() -> None:
    h, calls = _handlers()
    c = OrchestratorGatewayClient(h)
    msg = InboundMessage("o", "more notes", "m1", "wechat-main", raw={"issue_id": "AGENTSDK-15"})
    status = c.dispatch(msg, MessageSemantics.FOLLOW_UP)
    assert status == "followup_queued"
    assert calls[0][0] == "queue_pending"
    assert calls[0][1] == "AGENTSDK-15"


def test_orchestrator_control_verb_to_control_socket() -> None:
    h, calls = _handlers()
    c = OrchestratorGatewayClient(h)
    msg = InboundMessage(
        "o", "/pause AGENTSDK-15", "m1", "wechat-main", raw={"issue_id": "AGENTSDK-15"}
    )
    status = c.dispatch(msg, MessageSemantics.COMMAND)
    assert status == "control_pause"
    assert calls[0] == ("control", "pause", "AGENTSDK-15")


def test_orchestrator_inject_to_issue_inject_not_control_socket() -> None:
    """inject must NOT hit the control-socket no-op."""
    h, calls = _handlers()
    c = OrchestratorGatewayClient(h)
    msg = InboundMessage(
        "o", "/inject fix the tests", "m1", "wechat-main", raw={"issue_id": "AGENTSDK-15"}
    )
    status = c.dispatch(msg, MessageSemantics.COMMAND)
    assert status == "inject_delivered"
    assert calls[0][0] == "inject"
    assert calls[0][1] == "AGENTSDK-15"
    # no control-socket call
    assert not any(c0[0] == "control" for c0 in calls)


def test_orchestrator_agent_intent() -> None:
    h, calls = _handlers()
    c = OrchestratorGatewayClient(h)
    msg = InboundMessage(
        "o", "/agent retry AGENTSDK-15", "m1", "wechat-main", raw={"issue_id": "AGENTSDK-15"}
    )
    status = c.dispatch(msg, MessageSemantics.COMMAND)
    assert status == "agent_retry"
    assert calls[0] == ("intent", "retry", "AGENTSDK-15")


def test_orchestrator_context_only_to_operator_hints() -> None:
    h, calls = _handlers()
    c = OrchestratorGatewayClient(h)
    msg = InboundMessage("o", "ctx note", "m1", "wechat-main", raw={"issue_id": "AGENTSDK-15"})
    status = c.dispatch(msg, MessageSemantics.CONTEXT_ONLY)
    assert status == "context_only_recorded"
    assert calls[0][0] == "hints"


def test_orchestrator_interrupt_to_control_verb() -> None:
    h, calls = _handlers()
    c = OrchestratorGatewayClient(h)
    msg = InboundMessage(
        "o", "x", "m1", "wechat-main", raw={"issue_id": "AGENTSDK-15", "deliverAs": "interrupt"}
    )
    status = c.dispatch(msg, MessageSemantics.INTERRUPT)
    assert status == "interrupt_dispatched"
    assert calls[0][0] == "bridge_interrupt"


def test_orchestrator_issue_cli_commands_call_handler() -> None:
    for verb in ("clarify", "review", "feedback"):
        h, calls = _handlers()
        c = OrchestratorGatewayClient(h)
        msg = InboundMessage(
            "o",
            f"/{verb} AGENTSDK-15 approve",
            "m1",
            "wechat-main",
            raw={"issue_id": "AGENTSDK-15"},
        )
        status = c.dispatch(msg, MessageSemantics.COMMAND)
        assert status == f"issue_cli_{verb}"
        assert calls[0][0] == "issue_cli"
        assert calls[0][1] == verb
        assert calls[0][2] == "AGENTSDK-15"
