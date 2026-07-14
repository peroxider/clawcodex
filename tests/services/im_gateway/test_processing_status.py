from __future__ import annotations

import pytest

from clawcodex_ext.services.channels.capabilities import (
    ChannelCapability,
    ChannelCapabilitySet,
    ProcessingOutcome,
)
from clawcodex_ext.services.im_gateway.binding import BindingPolicy
from clawcodex_ext.services.im_gateway.dispatcher import InboundDispatcher
from clawcodex_ext.services.im_gateway.models import (
    AckLayer,
    AckReceipt,
    InboundMessage,
    SessionTarget,
)
from clawcodex_ext.services.im_gateway.processing_status import ProcessingStatusManager
from clawcodex_ext.services.im_gateway.router import SessionRouter
from clawcodex_ext.services.im_gateway.store import ReliabilityStore


class _StatusAdapter:
    channel_id = "feishu"
    capabilities = ChannelCapabilitySet.of(ChannelCapability.PROCESSING_STATUS)

    def __init__(self) -> None:
        self.starts: list[str] = []
        self.completions: list[tuple[str, ProcessingOutcome]] = []
        self.complete_result = True
        self.raise_on_start = False
        self.raise_on_complete = False

    async def on_processing_start(self, message_id: str) -> bool:
        self.starts.append(message_id)
        if self.raise_on_start:
            raise RuntimeError("reaction add failed")
        return True

    async def on_processing_complete(
        self,
        message_id: str,
        outcome: ProcessingOutcome,
    ) -> bool:
        self.completions.append((message_id, outcome))
        if self.raise_on_complete:
            raise RuntimeError("reaction delete failed")
        return self.complete_result


class _Registry:
    def __init__(self, adapter: _StatusAdapter) -> None:
        self.adapter = adapter

    def get(self, name: str):
        return self.adapter if name == "feishu" else None


def _message(
    message_id: str = "om_1",
    origin: str = "feishu:dm:app:user",
    text: str = "hello",
) -> InboundMessage:
    return InboundMessage(
        origin=origin,
        text=text,
        message_id=message_id,
        channel="feishu",
    )


@pytest.mark.asyncio
async def test_processing_status_manager_is_idempotent_and_validates_origin() -> None:
    adapter = _StatusAdapter()
    manager = ProcessingStatusManager(_Registry(adapter))
    message = _message()

    assert await manager.start(message) is True
    assert await manager.start(message) is True
    assert adapter.starts == ["om_1"]
    assert await manager.complete("om_1", ProcessingOutcome.SUCCESS, origin="wrong") is False
    assert manager.has_pending("om_1") is True

    assert await manager.complete("om_1", ProcessingOutcome.SUCCESS, origin=message.origin) is True
    assert adapter.completions == [("om_1", ProcessingOutcome.SUCCESS)]
    assert manager.has_pending("om_1") is False


@pytest.mark.asyncio
async def test_processing_status_manager_retains_failed_completion_and_bounds_lru() -> None:
    adapter = _StatusAdapter()
    adapter.complete_result = False
    manager = ProcessingStatusManager(_Registry(adapter), max_pending=2)
    await manager.start(_message("om_1"))
    await manager.start(_message("om_2"))
    await manager.start(_message("om_3"))

    assert manager.has_pending("om_1") is False
    assert await manager.complete("om_2", ProcessingOutcome.FAILURE) is False
    assert manager.has_pending("om_2") is True


@pytest.mark.asyncio
async def test_dispatcher_completes_local_handler_and_keeps_opt_in_pending(tmp_path) -> None:
    adapter = _StatusAdapter()
    manager = ProcessingStatusManager(_Registry(adapter))
    store = ReliabilityStore(tmp_path)
    binding = BindingPolicy()
    router = SessionRouter(binding, store)
    dispatcher = InboundDispatcher(store, router, processing_status=manager)

    async def local_handler(message: InboundMessage) -> AckReceipt:
        return AckReceipt(message.message_id, AckLayer.PROCESSED, "done")

    dispatcher.set_handler(local_handler)
    await dispatcher.process(_message("om_local"))
    assert adapter.starts == ["om_local"]
    assert adapter.completions == [("om_local", ProcessingOutcome.SUCCESS)]

    origin = "feishu:dm:app:optin"
    binding.bind(origin, SessionTarget(session_id="repl-1", host_type="repl"))

    async def push_handler(message: InboundMessage) -> bool:
        return True

    dispatcher.set_push_handler(push_handler)
    receipt = await dispatcher.process(_message("om_optin", origin))
    assert receipt.layer is AckLayer.ENQUEUED
    assert manager.has_pending("om_optin") is True


@pytest.mark.asyncio
async def test_dispatcher_dedupe_and_blocked_command_do_not_start_status(tmp_path) -> None:
    adapter = _StatusAdapter()
    manager = ProcessingStatusManager(_Registry(adapter))
    store = ReliabilityStore(tmp_path)
    binding = BindingPolicy()
    origin = "feishu:dm:app:user"
    binding.bind(origin, SessionTarget(session_id="repl-1", host_type="repl"))
    dispatcher = InboundDispatcher(
        store,
        SessionRouter(binding, store),
        processing_status=manager,
    )

    await dispatcher.process(_message("om_blocked", origin=origin, text="/exit"))
    assert adapter.starts == []

    async def push_handler(message: InboundMessage) -> bool:
        return True

    dispatcher.set_push_handler(push_handler)
    accepted = _message("om_duplicate", origin=origin)
    await dispatcher.process(accepted)
    await dispatcher.process(accepted)
    assert adapter.starts == ["om_duplicate"]


@pytest.mark.asyncio
async def test_processing_hook_exceptions_do_not_block_local_handler(tmp_path) -> None:
    adapter = _StatusAdapter()
    adapter.raise_on_start = True
    adapter.raise_on_complete = True
    manager = ProcessingStatusManager(_Registry(adapter))
    store = ReliabilityStore(tmp_path)
    dispatcher = InboundDispatcher(
        store,
        SessionRouter(BindingPolicy(), store),
        processing_status=manager,
    )

    async def local_handler(message: InboundMessage) -> AckReceipt:
        return AckReceipt(message.message_id, AckLayer.PROCESSED, "text reply sent")

    dispatcher.set_handler(local_handler)
    receipt = await dispatcher.process(_message("om_reaction_error"))

    assert receipt.layer is AckLayer.PROCESSED
    assert manager.has_pending("om_reaction_error") is True
