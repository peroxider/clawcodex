"""MessageGateway — the unified IM entry point.

Facade over the inbound dispatcher, outbound dispatcher, session router,
binding policy, capability gate, and reliability store. External callers
(Community Radar, Orchestrator event sink, REPL wrapper) use this API;
it does not reverse-import Orchestrator.

P1 ships the skeleton with working outbound send/broadcast, capability
fail-closed, session routing/binding, and a ``reload_channel`` hook for
``clawcodex-dev channels restart``. Inbound adapter lifecycle (WeChat)
lands in P2; full reliability hardening in P4; six-semantics in P5.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from typing import Awaitable, Callable

from clawcodex_ext.services.channels.capabilities import ChannelAdapter, ChannelCapability
from clawcodex_ext.services.channels.registry import (
    ChannelAdapterRegistry,
    build_default_registry,
)

from .binding import BindingEntry, BindingPolicy
from .capability_gate import CapabilityGate
from .config import GatewayConfig, load_config
from .dispatcher import InboundDispatcher, InboundHandler
from .models import InboundMessage, OutboundMessage
from .outbound import OutboundDispatcher
from .router import SessionRouter
from .store import ReliabilityStore

logger = logging.getLogger(__name__)


class MessageGateway:
    def __init__(
        self,
        config: GatewayConfig | None = None,
        *,
        registry: ChannelAdapterRegistry | None = None,
        store: ReliabilityStore | None = None,
    ) -> None:
        self.config = _normalize_config_channels(config or GatewayConfig())
        self.registry = registry or build_default_registry()
        self.store = store or ReliabilityStore(self.config.state_dir, self.config.reliability)
        self.binding = BindingPolicy(auditor=self._audit_binding)
        self.router = SessionRouter(self.binding, self.store)
        self.gate = CapabilityGate(self.registry)
        self.outbound = OutboundDispatcher(self.registry, self.gate, self.store, self.config)
        self.inbound = InboundDispatcher(self.store, self.router)
        self._inbound_adapters: list = []
        self._running = False
        self._load_channels()

    def _build_adapter(self, cfg) -> ChannelAdapter | None:
        """Build one adapter from a ChannelConfig (gateway-owned deps for WeChat)."""
        from pathlib import Path

        from clawcodex_ext.services.channels.models import ChannelType
        from clawcodex_ext.services.channels.transport import UrllibChannelTransport
        from clawcodex_ext.services.channels.wechat_ilink import (
            WeChatIlinkAuthStore,
            WeChatIlinkChannelAdapter,
            WeChatPairingStore,
        )

        if cfg.type is ChannelType.WECHAT:
            extra = cfg.extra or {}
            state_dir = Path(self.config.state_dir).expanduser()
            auth_path = _wechat_state_file(state_dir, cfg.name, 'auth')
            pairing_path = _wechat_state_file(state_dir, cfg.name, 'pairing')
            adapter = WeChatIlinkChannelAdapter(
                cfg,
                auth_store=WeChatIlinkAuthStore(
                    auth_path,
                    secret_env=self.config.reliability.secret_encryption_env,
                ),
                store=self.store,
                pairing=WeChatPairingStore(pairing_path),
                transport=UrllibChannelTransport(),
                allowed_users=extra.get('allowed_users'),
                account_id=extra.get('account_id', 'default'),
                base_url=extra.get('base_url', 'https://ilinkai.weixin.qq.com'),
                long_poll_timeout_ms=extra.get('long_poll_timeout_ms', 35000),
                max_consecutive_failures=extra.get('max_consecutive_failures', 10),
            )
            adapter.load_credentials()
            return adapter
        try:
            return self.registry.create(cfg)
        except Exception:  # noqa: BLE001
            return None

    def _attach_inbound(self, adapter) -> None:
        if adapter is not None and adapter.capabilities.has(ChannelCapability.INBOUND_POLLING):
            adapter.set_inbound_handler(self._on_inbound)
            self._inbound_adapters.append(adapter)

    def _load_channels(self) -> None:
        """Build adapters from config; WeChat needs gateway-owned deps."""
        for cfg in self.config.channels:
            if not cfg.enabled:
                continue
            adapter = self._build_adapter(cfg)
            if adapter is not None:
                self.registry.register(adapter)
                self._attach_inbound(adapter)

    async def _on_inbound(self, message) -> None:
        """Inbound hook called by channel adapters (WeChat poller)."""
        await self.inbound.process(message)

    # -- lifecycle -------------------------------------------------------
    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        # Start only adapters that declare inbound_polling (P2 wires WeChat).
        for adapter in self._inbound_adapters:
            await adapter.start()

    async def stop(self) -> None:
        if not self._running:
            return
        for adapter in self._inbound_adapters:
            try:
                await adapter.stop()
            except Exception:  # noqa: BLE001
                pass
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    # -- inbound ---------------------------------------------------------
    def register_inbound(self, adapter) -> None:
        self._inbound_adapters.append(adapter)

    def set_handler(self, handler: InboundHandler) -> None:
        self.inbound.set_handler(handler)

    def set_push_handler(self, handler) -> None:
        """Register the IPC push callback for opt-in origins (REPL/orchestrator)."""
        self.inbound.set_push_handler(handler)

    async def receive(self, message: InboundMessage):
        """Convenience: publish to the bus and process synchronously."""
        return await self.inbound.process(message)

    # -- outbound --------------------------------------------------------
    async def send(self, message: OutboundMessage):
        return await self.outbound.send(message)

    async def broadcast(self, message: OutboundMessage, *, channels: list[str] | None = None):
        return await self.outbound.broadcast(message, channels=channels)

    # -- channel management ---------------------------------------------
    def reload_channel(self, name: str) -> bool:
        """Rebuild a single adapter from config and hot-swap it (P4 live reload).

        Stops the old adapter's inbound loop, rebuilds via ``_build_adapter``,
        re-registers, and re-attaches the inbound handler. In-flight message
        safety is best-effort in v1 (the outbox preserves pending sends).
        """
        channel_cfg = self.config.get_channel(name)
        if channel_cfg is None:
            return False
        old = self.registry.get(name)
        if old is not None:
            _schedule_adapter_stop(old)
            self.registry.remove(name)
            if old in self._inbound_adapters:
                self._inbound_adapters.remove(old)
        adapter = self._build_adapter(channel_cfg)
        if adapter is None:
            return False
        self.registry.register(adapter)
        self._attach_inbound(adapter)
        if self._running and hasattr(adapter, 'start'):
            _schedule_adapter_start(adapter)
        self.store.audit('channel_reload', channel=name)
        return True

    # -- audit -----------------------------------------------------------
    def _audit_binding(
        self, action: str, entry: BindingEntry, previous: BindingEntry | None
    ) -> None:
        self.store.audit(
            action,
            origin=entry.origin,
            session_id=entry.target.session_id,
            host_type=entry.target.host_type,
        )
        # Schedule best-effort connection notification (async, never blocks
        # the binding transition). The auditor is called from the IPC server's
        # async handlers, so a running event loop is expected.
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._notify_connection_change(action, entry, previous))
        except RuntimeError:
            pass

    async def _notify_connection_change(
        self, action: str, entry: BindingEntry, previous: BindingEntry | None
    ) -> None:
        """Send a best-effort connection notification to the bound IM channel.

        When REPL or orchestrator connects/disconnects, the user is notified
        via the outbound dispatcher (e.g. ``"REPL已连接"`` / ``"orchestrator已断开"``).
        All failures are logged and swallowed — notifications must never block
        binding transitions or crash the gateway.
        """
        from .origin_utils import resolve_origin

        channel, target = resolve_origin(entry.origin, self)
        if channel is None or target is None:
            logger.debug(
                'connection notify: cannot resolve origin %s — skipping',
                (entry.origin or '')[:32],
            )
            return

        host_label = _host_label(entry.target.host_type)
        messages: list[str] = []
        if action == 'binding_created':
            messages.append(f'{host_label}已连接')
        elif action == 'binding_override' and previous is not None:
            if previous.connection_state == 'active':
                messages.append(f'{_host_label(previous.target.host_type)}已断开')
            messages.append(f'{host_label}已连接')
        elif action in ('binding_offline', 'binding_terminated'):
            messages.append(f'{host_label}已断开')

        for text in messages:
            try:
                result = await self.outbound.send(
                    OutboundMessage(text=text, channel=channel, target=target, markdown=False)
                )
                if result is not None and getattr(result, 'ok', True) is False:
                    error_category = getattr(result, 'error_category', '')
                    category_value = getattr(error_category, 'value', '') or str(
                        error_category or ''
                    )
                    logger.warning(
                        'connection notify: send failed for %r category=%s message=%s',
                        text,
                        category_value,
                        getattr(result, 'message', '') or '',
                    )
                    continue
                logger.info(
                    'connection notify: sent %r channel=%s target=%s',
                    text,
                    channel,
                    (target or '')[:16] + '…' if len(target or '') > 16 else target,
                )
            except Exception:  # noqa: BLE001
                logger.warning('connection notify: send failed for %r — best-effort', text)

    # -- health ----------------------------------------------------------
    async def health(self) -> dict:
        channel_health: list[dict] = []
        for adapter in self.registry.all_adapters():
            health_check = getattr(adapter, 'health_check', None)
            if not callable(health_check):
                continue
            try:
                health = await health_check()
            except Exception as exc:  # noqa: BLE001
                channel_health.append(
                    {
                        'channel_id': getattr(adapter, 'channel_id', ''),
                        'healthy': False,
                        'last_error': str(exc),
                    }
                )
                continue
            to_dict = getattr(health, 'to_dict', None)
            channel_health.append(to_dict() if callable(to_dict) else dict(health))
        return {
            'running': self._running,
            'channels': self.registry.names(),
            'channel_health': channel_health,
            'inbound_adapters': len(self._inbound_adapters),
            'outbox_pending': len(self.store.outbox_pending()),
            'dead_letter': len(self.store.dead_letter_entries()),
            'bindings': [
                {
                    'origin': entry.origin,
                    'session_id': entry.target.session_id,
                    'host_type': entry.target.host_type,
                    'connection_state': entry.connection_state,
                }
                for entry in self.binding.all_bindings()
            ],
        }


def _schedule_adapter_stop(adapter) -> None:
    """Stop an adapter's inbound loop on the running loop (best-effort)."""
    import asyncio

    if not hasattr(adapter, 'stop'):
        return
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        return
    if loop.is_running():
        loop.create_task(adapter.stop())


def _schedule_adapter_start(adapter) -> None:
    """Start an adapter's inbound loop on the running loop (best-effort)."""
    import asyncio

    if not hasattr(adapter, 'start'):
        return
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        return
    if loop.is_running():
        loop.create_task(adapter.start())


def _normalize_config_channels(config: GatewayConfig) -> GatewayConfig:
    """Ensure direct GatewayConfig construction cannot bypass type uniqueness."""
    normalized = replace(config, channels=[])
    for channel in config.channels:
        normalized.replace_channel(channel)
    return normalized


def _wechat_state_file(state_dir, channel_name: str, suffix: str):
    path = state_dir / 'wechat' / f'{channel_name}_{suffix}.json'
    if path.exists() or channel_name != 'wechat':
        return path
    legacy = state_dir / 'wechat' / f'wechat-main_{suffix}.json'
    if legacy.exists():
        return legacy
    matches = sorted((state_dir / 'wechat').glob(f'*_{suffix}.json'))
    return matches[0] if matches else path


__all__ = ['MessageGateway']


_HOST_LABELS = {
    'repl': 'clawcodex-REPL',
    'orchestrator': 'clawcodex-orchestrator',
    'opt_in': 'opt-in',
}


def _host_label(host_type: str) -> str:
    """Map a binding host_type to a user-facing label for notifications."""
    return _HOST_LABELS.get(host_type, host_type)
