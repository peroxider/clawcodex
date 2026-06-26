"""NullChannel tests: it must never touch the network."""

from __future__ import annotations

import pytest

from src.services.channels import (
    ChannelConfig,
    ChannelMessage,
    ChannelType,
    MessageLevel,
    NullChannel,
)


def _config() -> ChannelConfig:
    # Loopback hostname is not validated by NullChannel by design.
    return ChannelConfig(
        type=ChannelType.SLACK,
        webhook_url="https://localhost/hook/abcdef0123456789",
        name="null-1",
    )


def test_null_channel_constructs_with_loopback_url() -> None:
    # If NullChannel ran the URL safety check, this would raise — it must not.
    channel = NullChannel(_config())
    assert channel.name == "null-1"
    assert channel.enabled is True


@pytest.mark.asyncio
async def test_null_channel_send_records_payload() -> None:
    channel = NullChannel(_config())
    msg = ChannelMessage(text="hi", level=MessageLevel.WARN)
    ok = await channel.send(msg)
    assert ok is True

    log = channel.log
    assert len(log) == 1
    entry = log[0]
    assert entry.message is msg
    # Body is JSON; verify it round-trips and includes the level.
    import json

    payload = json.loads(entry.body.decode("utf-8"))
    assert payload["text"] == "hi"
    assert payload["level"] == "warn"
    assert entry.headers.get("Content-Type") == "application/json"


@pytest.mark.asyncio
async def test_null_channel_clear_empties_log() -> None:
    channel = NullChannel(_config())
    await channel.send(ChannelMessage(text="x"))
    assert len(channel.log) == 1
    channel.clear()
    assert channel.log == []


@pytest.mark.asyncio
async def test_null_channel_send_is_thread_safe() -> None:
    import asyncio

    channel = NullChannel(_config())
    n = 50

    async def fire(i: int) -> None:
        await channel.send(ChannelMessage(text=f"m{i}"))

    await asyncio.gather(*(fire(i) for i in range(n)))
    assert len(channel.log) == n


def test_null_channel_does_not_touch_transport_calls() -> None:
    # The internal _NullTransport records network calls; default channel
    # should be using it, not the urllib transport.
    from src.services.channels.null_channel import _NullTransport

    channel = NullChannel(_config())
    assert isinstance(channel.transport, _NullTransport)
    assert channel.transport.calls == []
