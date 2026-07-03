"""Feishu application-level channel adapter.

Thin shell over ``lark_oapi.channel.FeishuChannel`` (SDK 1.7.0): lifecycle,
inbound dispatch, outbound send and card-action handling are delegated to the
SDK. Fork owns only the permission-approval state machine
(:class:`ApprovalCardManager`), the optional p2p allowlist, the
SDK→gateway ``InboundMessage`` translation, and the adapter-level send retry.

The SDK runs its WebSocket on a private background loop; inbound callbacks
fire there. ``_emit_inbound`` hops the gateway delivery back onto the daemon
main loop (captured in :meth:`start`) so the gateway never sees cross-loop
access.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from .capabilities import (
    CapabilityDescriptor,
    ChannelAdapter,
    ChannelCapability,
    ChannelCapabilitySet,
)
from .feishu_cards import (
    ApprovalCardManager,
    build_permission_card,
    build_resolved_permission_card,
)
from .feishu_events import translate_inbound
from .feishu_sdk import (
    FeishuDependencyMissingError,
    build_feishu_channel,
    feishu_dependencies_available,
    load_error_helpers,
)
from .feishu_settings import FeishuAppSettings
from .models import ChannelConfig, ChannelMessage
from .results import ChannelHealth, ChannelSendResult, ErrorCategory, ValidationResult
from .retry import DEFAULT_RETRY_POLICY, RetryPolicy, classify_exception

logger = logging.getLogger(__name__)

InboundHandler = Callable[[Any], Awaitable[None] | None]
ChannelFactory = Callable[[FeishuAppSettings], Any]
RetrySleep = Callable[[float], Awaitable[None]]

_MARKDOWN_HINT_RE = re.compile(r'(```)|(^#{1,6}\s)|(\*\*.+\*\*)|(^[-*]\s)', re.MULTILINE)

_FEISHU_CAPABILITIES = ChannelCapabilitySet.of(
    ChannelCapability.OUTBOUND_TEXT,
    ChannelCapability.INBOUND_POLLING,
    ChannelCapability.CONTEXT_REPLY,
    ChannelCapability.LOGIN_MANAGED,
    descriptors={
        ChannelCapability.OUTBOUND_TEXT: CapabilityDescriptor(
            ChannelCapability.OUTBOUND_TEXT,
            supports_markdown=True,
            max_text_length=4000,
            requires_login=True,
            extra={'approval_cards': True},
        )
    },
)


class FeishuAppChannelAdapter(ChannelAdapter):
    def __init__(
        self,
        config: ChannelConfig,
        *,
        channel_factory: ChannelFactory | None = None,
        retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
        clock: Callable[[], float] = time.time,
        retry_sleep: RetrySleep = asyncio.sleep,
        sender_store: Any | None = None,
    ) -> None:
        self._config = config
        self._settings = FeishuAppSettings.from_config(config)
        self._channel_factory = channel_factory or build_feishu_channel
        self._retry_policy = retry_policy
        self._clock = clock
        self._retry_sleep = retry_sleep
        self._sender_store = sender_store
        self._channel: Any | None = None
        self._on_inbound: InboundHandler | None = None
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._running = False
        self._connect_task: asyncio.Task[None] | None = None
        self._account_status = 'websocket:disconnected'
        self._last_error: str | None = None
        self._last_sender: str | None = None
        self._last_inbound_at: float | None = None
        self._last_outbound_at: float | None = None
        self.approval_manager = ApprovalCardManager(
            clock=self._clock,
            token_ttl_seconds=self._settings.action_token_ttl_seconds,
        )

    @property
    def channel_id(self) -> str:
        return self._config.name

    @property
    def config(self) -> ChannelConfig:
        return self._config

    @property
    def capabilities(self) -> ChannelCapabilitySet:
        return _FEISHU_CAPABILITIES

    @property
    def retry_policy(self) -> RetryPolicy:
        return self._retry_policy

    def validate_config(self) -> ValidationResult:
        errors = self._settings.validation_errors()
        if self._settings.connection_mode != 'websocket':
            errors.append('FeishuAppChannelAdapter requires connection_mode=websocket')
        if not feishu_dependencies_available() and self._channel_factory is build_feishu_channel:
            errors.append('missing lark_oapi; install with `uv sync --locked --extra feishu`')
        if errors:
            return ValidationResult.fail(errors)
        return ValidationResult.ok_result()

    async def health_check(self) -> ChannelHealth:
        healthy = self._running and self._account_status == 'websocket:connected'
        return ChannelHealth(
            healthy=healthy,
            channel_id=self.channel_id,
            circuit_state='closed',
            last_error=self._last_error,
            last_inbound_at=self._last_inbound_at,
            last_outbound_at=self._last_outbound_at,
            account_status=self._account_status,
            extra={
                'connection_mode': 'websocket',
                'domain': self._settings.domain,
                'bot_open_id': self._settings.bot_open_id,
                'approval_cards': 'supported'
                if self._settings.approval_cards_enabled
                else 'disabled',
            },
        )

    def set_inbound_handler(self, handler: InboundHandler) -> None:
        self._on_inbound = handler

    def last_known_sender(self) -> str | None:
        if self._last_sender:
            return self._last_sender
        get_last_sender = getattr(self._sender_store, 'get_feishu_last_sender', None)
        if callable(get_last_sender):
            return get_last_sender(self.channel_id)
        return None

    # -- lifecycle -------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            logger.debug('feishu adapter already running')
            return
        errors = self._settings.validation_errors()
        if errors:
            self._last_error = '; '.join(errors)
            self._account_status = 'credentials_missing'
            return
        self._running = True
        self._main_loop = asyncio.get_running_loop()
        self._account_status = 'websocket:connecting'
        try:
            await self._connect_once(ready_timeout=self._settings.startup_connect_timeout_seconds)
        except FeishuDependencyMissingError as exc:
            self._last_error = str(exc)
            self._account_status = 'dependency_missing'
            self._running = False
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            self._account_status = 'websocket:retrying'
            self._connect_task = asyncio.create_task(self._connect_loop())

    async def _connect_loop(self) -> None:
        """Background reconnect loop after the blocking startup attempt fails."""
        attempt = 1
        delay = 30.0
        max_delay = 300.0
        while self._running:
            await self._retry_sleep(delay)
            if not self._running:
                return
            try:
                await self._connect_once(
                    ready_timeout=self._settings.startup_connect_timeout_seconds
                )
                return
            except FeishuDependencyMissingError as exc:
                self._last_error = str(exc)
                self._account_status = 'dependency_missing'
                return
            except Exception as exc:  # noqa: BLE001
                attempt += 1
                self._last_error = str(exc)
                self._account_status = 'websocket:retrying'
                delay = min(30.0 * (2 ** (attempt - 1)), max_delay)

    async def _connect_once(self, *, ready_timeout: float | None) -> None:
        # FeishuChannel construction imports the large generated SDK package;
        # keep it off the event loop even though startup now waits for ready.
        channel = await asyncio.to_thread(self._channel_factory, self._settings)
        self._channel = channel
        self._register_handlers()
        await channel.connect_until_ready(timeout=ready_timeout)
        self._refresh_bot_identity()
        self._account_status = 'websocket:connected'
        self._last_error = None

    def _register_handlers(self) -> None:
        from lark_oapi.channel import Events  # noqa: PLC0415

        channel = self._channel
        if channel is None:
            return
        channel.on(Events.MESSAGE, self._on_message)
        channel.on(Events.CARD_ACTION, self._on_card_action)
        channel.on(Events.RECONNECTING, self._on_reconnecting)
        channel.on(Events.RECONNECTED, self._on_reconnected)

    def _refresh_bot_identity(self) -> None:
        channel = self._channel
        if channel is None:
            return
        identity = getattr(channel, 'bot_identity', None)
        open_id = getattr(identity, 'open_id', None) if identity is not None else None
        if open_id:
            name = getattr(identity, 'name', None) or self._settings.bot_name
            self._settings = replace(self._settings, bot_open_id=str(open_id), bot_name=name)

    def _on_reconnecting(self, *args: Any) -> None:
        self._account_status = 'websocket:reconnecting'

    def _on_reconnected(self, *args: Any) -> None:
        self._account_status = 'websocket:connected'
        self._last_error = None

    async def stop(self) -> None:
        self._running = False
        if self._connect_task is not None:
            self._connect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._connect_task
            self._connect_task = None
        channel = self._channel
        if channel is not None:
            with contextlib.suppress(Exception):  # noqa: BLE001
                await channel.disconnect()
            self._channel = None
        self._account_status = 'websocket:disconnected'

    # -- inbound ---------------------------------------------------------

    async def _on_message(self, inbound: Any) -> None:
        message = translate_inbound(inbound, self._settings)
        if message is None:
            return
        self._remember_sender(message.context_token or message.from_user_id)
        self._last_inbound_at = self._clock()
        await self._emit_inbound(message)

    async def _on_card_action(self, payload: Any) -> None:
        inbound = self.approval_manager.resolve_action(payload)
        if inbound is None:
            return
        self._remember_sender(inbound.context_token or inbound.from_user_id)
        await self._resolve_card(payload, inbound)
        await self._emit_inbound(inbound)

    async def _resolve_card(self, payload: Any, inbound: Any) -> None:
        channel = self._channel
        if channel is None:
            return
        message_id = getattr(payload, 'message_id', None) or ''
        if not message_id:
            return
        card = build_resolved_permission_card(
            choice=inbound.text,
            operator_open_id=inbound.from_user_id,
        )
        try:
            await channel.update_card(message_id, card)
        except Exception as exc:  # noqa: BLE001
            logger.warning('feishu update_card failed: %s', exc)

    async def _emit_inbound(self, message: Any) -> None:
        if self._on_inbound is None:
            return
        handler = self._on_inbound
        main_loop = self._main_loop
        if main_loop is None or main_loop is asyncio.get_running_loop():
            result = handler(message)
            if inspect.isawaitable(result):
                await result
            return
        # SDK callback runs on its private bg loop; hop to the daemon main loop
        # so the gateway inbound dispatcher never sees cross-loop access.
        future = asyncio.run_coroutine_threadsafe(_await_handler(handler, message), main_loop)
        try:
            future.result(timeout=5)
        except Exception as exc:  # noqa: BLE001
            logger.warning('feishu inbound delivery to gateway failed: %s', exc)

    def _remember_sender(self, sender: str | None) -> None:
        if not sender:
            return
        self._last_sender = sender
        set_last_sender = getattr(self._sender_store, 'set_feishu_last_sender', None)
        if callable(set_last_sender):
            set_last_sender(self.channel_id, sender)

    # -- outbound --------------------------------------------------------

    async def send(
        self,
        message: ChannelMessage,
        *,
        target: str | None = None,
        context_token: str | None = None,
    ) -> ChannelSendResult:
        chat_id = _resolve_send_chat_id(target=target, context_token=context_token)
        if not chat_id:
            return ChannelSendResult.nonretryable_error(
                self.channel_id,
                message='target or context_token chat_id is required for feishu send',
                category=ErrorCategory.CLIENT_ERROR,
            )
        if _is_permission_approval(message) and self._settings.approval_cards_enabled:
            return await self._send_permission_card(message, chat_id=chat_id)
        payload = _build_outbound_payload(message)
        result = await self._send_with_retry(chat_id, payload, raw_extra=None)
        if (
            not result.ok
            and payload.get('markdown') is not None
            and result.error_category is ErrorCategory.CLIENT_ERROR
        ):
            result = await self._send_with_retry(
                chat_id,
                {'text': message.text},
                raw_extra={'fallback': 'post_to_text'},
            )
        return result

    async def _send_permission_card(
        self,
        message: ChannelMessage,
        *,
        chat_id: str,
    ) -> ChannelSendResult:
        permission = dict((message.metadata or {}).get('permission') or {})
        options = _permission_options(permission)
        state = self.approval_manager.create_pending(
            origin=_origin_from_message(message, self._settings),
            chat_id=chat_id,
            allowed_user_open_id=self._settings.allowed_user_open_id,
            choices={str(option.get('value')) for option in options},
            ttl_seconds=int(
                permission.get('expires_in_seconds') or self._settings.decision_ttl_seconds
            ),
        )
        card_body = build_permission_card(
            message=str(permission.get('message') or message.text),
            suggestion=permission.get('suggestion'),
            options=options,
            approval_id=state.approval_id,
            nonce=state.nonce,
        )['content']
        return await self._send_with_retry(
            chat_id,
            {'card': card_body},
            raw_extra={'approval_id': state.approval_id},
        )

    async def _send_with_retry(
        self,
        chat_id: str,
        payload: dict[str, Any],
        *,
        raw_extra: dict[str, Any] | None,
    ) -> ChannelSendResult:
        if self._channel is None:
            return ChannelSendResult.nonretryable_error(
                self.channel_id,
                message='feishu channel is not connected',
                category=ErrorCategory.AUTH,
            )
        attempts = max(1, self._settings.sdk_send_attempts)
        timeout = max(1.0, self._settings.sdk_send_timeout_seconds)
        channel = self._channel
        for attempt in range(1, attempts + 1):
            try:
                result = await asyncio.wait_for(channel.send(chat_id, payload), timeout=timeout)
            except asyncio.TimeoutError:
                self._last_error = f'feishu send timed out after {timeout:.0f}s'
                logger.warning(
                    'feishu send timed out: chat_id=%s attempt=%d/%d timeout=%.0fs',
                    chat_id[:16],
                    attempt,
                    attempts,
                    timeout,
                )
                if attempt < attempts:
                    await asyncio.sleep(self._settings.sdk_send_backoff_base_seconds * attempt)
                    continue
                return ChannelSendResult.retryable_error(
                    self.channel_id,
                    message=f'feishu send timed out after {timeout:.0f}s',
                    category=ErrorCategory.TIMEOUT,
                    attempts=attempt,
                    raw=raw_extra,
                )
            except FeishuDependencyMissingError as exc:
                self._last_error = str(exc)
                return ChannelSendResult.nonretryable_error(
                    self.channel_id,
                    message=str(exc),
                    category=ErrorCategory.AUTH,
                    attempts=attempt,
                    raw=raw_extra,
                )
            except Exception as exc:  # noqa: BLE001
                category = classify_exception(exc)
                self._last_error = str(exc)
                if category in self._retry_policy.retryable_categories and attempt < attempts:
                    await asyncio.sleep(self._settings.sdk_send_backoff_base_seconds * attempt)
                    continue
                return _error_result_for(
                    self.channel_id,
                    str(exc),
                    category=category,
                    attempts=attempt,
                    raw_extra=raw_extra,
                )
            if getattr(result, 'success', False):
                self._last_outbound_at = self._clock()
                self._last_error = None
                return ChannelSendResult.success(
                    self.channel_id,
                    provider_receipt=str(getattr(result, 'message_id', None) or ''),
                    attempts=attempt,
                    raw={**(raw_extra or {}), 'response': _result_raw(result)},
                )
            error = getattr(result, 'error', None)
            category, retryable = _classify_send_error(error)
            self._last_error = _send_error_message(error)
            if retryable and attempt < attempts:
                await asyncio.sleep(self._settings.sdk_send_backoff_base_seconds * attempt)
                continue
            return _error_result_for(
                self.channel_id,
                self._last_error,
                category=category,
                attempts=attempt,
                raw_extra=raw_extra,
            )
        return ChannelSendResult.nonretryable_error(
            self.channel_id,
            message='feishu send failed',
            category=ErrorCategory.UNKNOWN,
            attempts=attempts,
            raw=raw_extra,
        )


async def _await_handler(handler: InboundHandler, message: Any) -> None:
    result = handler(message)
    if inspect.isawaitable(result):
        await result


def _build_outbound_payload(message: ChannelMessage) -> dict[str, Any]:
    text = message.text or ''
    if message.markdown and _MARKDOWN_HINT_RE.search(text):
        return {'markdown': text}
    return {'text': text}


def _classify_send_error(error: Any) -> tuple[ErrorCategory, bool]:
    """Map an SDK ``SendError`` to (category, retryable)."""
    errors = load_error_helpers()
    code = getattr(error, 'code', None)
    retryable = bool(errors.is_retryable(code)) if code is not None else False
    code_value = getattr(code, 'value', str(code or ''))
    if code_value == 'rate_limited':
        return ErrorCategory.RATE_LIMIT, True
    if code_value == 'format_error':
        return ErrorCategory.CLIENT_ERROR, False
    if code_value == 'permission_denied':
        return ErrorCategory.AUTH, retryable
    if code_value == 'target_revoked':
        return ErrorCategory.CLIENT_ERROR, False
    if code_value == 'send_timeout':
        return ErrorCategory.TIMEOUT, True
    return ErrorCategory.UNKNOWN, retryable


def _send_error_message(error: Any) -> str:
    if error is None:
        return 'feishu send failed'
    hint = getattr(error, 'hint', None) or getattr(error, 'code', None)
    return str(hint or 'feishu send failed')


def _result_raw(result: Any) -> dict[str, Any]:
    raw = getattr(result, 'raw', None)
    if isinstance(raw, dict):
        return raw
    return {}


def _error_result_for(
    channel_id: str,
    message: str,
    *,
    category: ErrorCategory,
    attempts: int,
    raw_extra: dict[str, Any] | None,
) -> ChannelSendResult:
    if category in DEFAULT_RETRY_POLICY.retryable_categories:
        return ChannelSendResult.retryable_error(
            channel_id,
            message=message,
            category=category,
            attempts=attempts,
            raw=raw_extra,
        )
    return ChannelSendResult.nonretryable_error(
        channel_id,
        message=message,
        category=category,
        attempts=attempts,
        raw=raw_extra,
    )


def _is_permission_approval(message: ChannelMessage) -> bool:
    return (message.metadata or {}).get('intent') == 'permission_approval'


def _origin_from_message(message: ChannelMessage, settings: FeishuAppSettings) -> str:
    metadata = message.metadata or {}
    origin = metadata.get('origin')
    if isinstance(origin, str) and origin:
        return origin
    return f'feishu:dm:{settings.app_id}:{settings.allowed_user_open_id}'


def _resolve_send_chat_id(*, target: str | None, context_token: str | None) -> str | None:
    if (
        context_token
        and target
        and _looks_like_chat_id(context_token)
        and _looks_like_open_id(target)
    ):
        return context_token
    return target or context_token


def _looks_like_chat_id(value: str) -> bool:
    return value.startswith(('oc_', 'chat_', 'feishu_chat_id:'))


def _looks_like_open_id(value: str) -> bool:
    return value.startswith('ou_')


def _permission_options(permission: dict[str, Any]) -> list[dict[str, str]]:
    options = permission.get('options')
    if isinstance(options, list) and options:
        return [
            {
                'value': str(item.get('value') or ''),
                'label': str(item.get('label') or item.get('value') or ''),
            }
            for item in options
            if isinstance(item, dict) and item.get('value')
        ]
    return [{'value': 'y', 'label': '允许'}, {'value': 'n', 'label': '拒绝'}]


__all__ = ['FeishuAppChannelAdapter']
