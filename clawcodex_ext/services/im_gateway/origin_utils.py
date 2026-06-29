"""Origin resolution helpers shared by the IPC server and the gateway.

Maps an IM origin key (``wechat:direct:{account}:{user}`` or the wildcard
``wechat:direct:*:*``) to a concrete ``(channel_name, target_user_id)``
pair for outbound delivery. Extracted from ``ipc_server.py`` so the
gateway's connection-notification logic can resolve origins without
importing the IPC server module.
"""

from __future__ import annotations

from typing import Any


def resolve_origin(origin: str, gateway=None) -> tuple[str | None, str | None]:
    """Map an IM origin key to ``(channel_name, target_user_id)`` for outbound.

    ``wechat:direct:{account}:{user}`` → the registered WeChat channel name
    + the user id. The channel name is resolved from the gateway config's
    unique WeChat entry first, then from adapter config if available, then
    from the v1 default name.

    The wildcard ``wechat:direct:*:*`` is resolved here to a concrete
    sender so opt-in hosts (orchestrator/REPL) can emit OUTBOUND without
    knowing the operator's WeChat user id. The WeChat adapter is the single
    source: its ``last_known_sender`` returns the most recent real inbound
    sender (in-memory, current lifetime), falling back to its persisted
    context-token users (survives a gateway restart with no new inbound).
    If none is known, returns ``(None, None)`` and the caller NACKs — an
    operator who has never messaged genuinely cannot be addressed.
    """
    parts = origin.split(":")
    if is_concrete_wechat_direct_origin(origin):
        target = parts[3]
        channel = configured_wechat_channel(gateway)
        if channel is not None:
            return channel, target
        adapter = wechat_adapter(gateway)
        if adapter is not None:
            return adapter.channel_id, target
        return "wechat", target
    if parts[:2] == ["wechat", "direct"] and origin == "wechat:direct:*:*":
        adapter = wechat_adapter(gateway)
        if adapter is not None:
            last_known = getattr(adapter, "last_known_sender", None)
            user = last_known() if callable(last_known) else None
            if user:
                account = getattr(adapter, "_account_id", "") or "default"
                return resolve_origin(f"wechat:direct:{account}:{user}", gateway)
        return None, None
    return None, None


def wechat_adapter(gateway: Any):
    """Return the gateway's registered WeChat adapter, or None."""
    registry = getattr(gateway, "registry", None)
    if registry is None or not hasattr(registry, "all_adapters"):
        return None
    try:
        from clawcodex_ext.services.channels.models import ChannelType
    except Exception:  # noqa: BLE001
        return None
    for adapter in registry.all_adapters():
        cfg = getattr(adapter, "config", None) or getattr(adapter, "_config", None)
        if cfg is not None and getattr(cfg, "type", None) is ChannelType.WECHAT:
            return adapter
    return None


def configured_wechat_channel(gateway: Any) -> str | None:
    """Return the configured WeChat channel name from gateway config, or None."""
    config = getattr(gateway, "config", None)
    get_by_type = getattr(config, "get_channel_by_type", None)
    if not callable(get_by_type):
        return None
    try:
        channel = get_by_type("wechat")
    except Exception:  # noqa: BLE001
        return None
    return getattr(channel, "name", None) if channel is not None else None


def is_concrete_wechat_direct_origin(origin: str) -> bool:
    """True for ``wechat:direct:{account}:{user}`` with non-wildcard fields."""
    parts = origin.split(":")
    return (
        len(parts) >= 4
        and parts[0] == "wechat"
        and parts[1] == "direct"
        and parts[2] not in ("", "*")
        and parts[3] not in ("", "*")
    )


__all__ = [
    "configured_wechat_channel",
    "is_concrete_wechat_direct_origin",
    "resolve_origin",
    "wechat_adapter",
]
