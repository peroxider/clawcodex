"""P4 reliability tests: audit redaction, followup persistence, target_offline, restart reload."""

from __future__ import annotations

import pytest

from clawcodex_ext.services.im_gateway.audit import hash_user, redact
from clawcodex_ext.services.im_gateway.binding import BindingPolicy
from clawcodex_ext.services.im_gateway.config import GatewayConfig, ReliabilityConfig
from clawcodex_ext.services.im_gateway.dispatcher import InboundDispatcher
from clawcodex_ext.services.im_gateway.models import (
    AckLayer,
    InboundMessage,
    OriginKey,
    SessionTarget,
)
from clawcodex_ext.services.im_gateway.router import SessionRouter
from clawcodex_ext.services.im_gateway.store import ReliabilityStore


# -- audit redaction ---------------------------------------------------


def test_redact_masks_tokens_and_hashes_users() -> None:
    out = redact(
        {
            "bot_token": "secret_tok",
            "context_token": "ctx_abc",
            "from_user_id": "user_gz",
            "webhook_url": "https://hooks.example.com/services/T/B/abcdef0123456789",
            "event_type": "send",
            "nested": {"token": "x", "ok": "keep"},
        }
    )
    assert out["bot_token"] == "***"
    assert out["context_token"] == "***"
    assert out["from_user_id"] == hash_user("user_gz")
    assert out["from_user_id"] != "user_gz"
    assert "***" in out["webhook_url"]
    assert "abcdef0123456789" not in out["webhook_url"]
    assert out["event_type"] == "send"
    assert out["nested"]["token"] == "***"
    assert out["nested"]["ok"] == "keep"


def test_store_audit_redacts_sensitive_fields(tmp_path) -> None:
    s = ReliabilityStore(tmp_path)
    s.audit(
        "wechat_send",
        channel="wechat-main",
        bot_token="supersecret",
        from_user_id="user_gz",
        context_token="ctx_xyz",
    )
    raw = (tmp_path / "audit.ndjson").read_text(encoding="utf-8")
    assert "supersecret" not in raw
    assert "ctx_xyz" not in raw
    assert "user_gz" not in raw
    assert "***" in raw


# -- target_offline ----------------------------------------------------


@pytest.mark.asyncio
async def test_dispatcher_rejects_when_target_offline(tmp_path) -> None:
    store = ReliabilityStore(tmp_path)
    bp = BindingPolicy()
    o = OriginKey.wechat("default", "user_gz")
    bp.bind(o, SessionTarget("repl_main", "repl"))
    bp.mark_offline(o)
    router = SessionRouter(bp, store)
    disp = InboundDispatcher(store, router)
    msg = InboundMessage(origin=str(o), text="hi", message_id="m1", channel="wechat-main")
    ack = await disp.process(msg)
    assert ack.layer is AckLayer.ACCEPTED
    assert "target_offline" in ack.message
    # audit recorded (redacted origin is the raw origin string here)
    assert any(e["event_type"] == "target_offline" for e in store.audit_entries())


def test_router_is_offline_flag(tmp_path) -> None:
    store = ReliabilityStore(tmp_path)
    bp = BindingPolicy()
    o = OriginKey.wechat("default", "u1")
    bp.bind(o, SessionTarget("repl_main", "repl"))
    router = SessionRouter(bp, store)
    assert not router.is_offline(o)
    bp.mark_offline(o)
    assert router.is_offline(o)
    bp.terminate(o)
    assert not router.is_offline(o)  # terminated → no binding → not offline (default route)


# -- restart reload hook ----------------------------------------------


def test_message_gateway_reload_channel_rebuilds(tmp_path) -> None:
    from clawcodex_ext.services.channels.capabilities import ChannelCapability
    from clawcodex_ext.services.channels.models import ChannelType
    from clawcodex_ext.services.im_gateway.gateway import MessageGateway

    cfg = GatewayConfig(state_dir=str(tmp_path))
    cfg.channels.append(
        __import__(
            "clawcodex_ext.services.channels.models", fromlist=["ChannelConfig"]
        ).ChannelConfig(
            type=ChannelType.WECHAT,
            webhook_url="https://ilinkai.weixin.qq.com/dummy",
            name="wechat-main",
            enabled=True,
            extra={"base_url": "https://ilinkai.weixin.qq.com"},
        )
    )
    gw = MessageGateway(cfg)
    assert gw.registry.get("wechat") is not None
    # reload_channel rebuilds the adapter entry and writes audit
    assert gw.reload_channel("wechat") is True
    assert gw.registry.get("wechat") is not None
    assert any(e["event_type"] == "channel_reload" for e in gw.store.audit_entries())
    assert gw.reload_channel("nope") is False
