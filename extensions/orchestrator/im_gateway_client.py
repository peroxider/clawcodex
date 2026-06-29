"""OrchestratorGatewayClient — orchestrator opt-in IM dispatch (P5).

Registered per issue/run session via the gateway UDS. Splits inbound
semantics to existing orchestrator entry points — never invents new
synonyms:

  * ``followUp`` → ``queue_pending_message`` (the existing pending queue)
  * ``pause/resume/stop/takeover`` → control socket verbs
  * ``inject`` / ``contextOnly`` → ``issue inject`` / ``.operator_hints.md``
    (NOT the control-socket no-op)
  * ``command`` (``/agent retry|follow-up|unblock``) → existing
    ``parse_agent_command`` path

The client is a pure dispatcher with injectable handlers so it is
unit-testable without a live orchestrator. The daemon wiring binds the
real handlers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

from clawcodex_ext.services.im_gateway.models import (
    InboundMessage,
    MessageSemantics,
)
from clawcodex_ext.messaging.semantics import CommandRouter, ControlBridge

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorHandlers:
    queue_pending_message: Callable[[str, str], None]  # (issue_id, text) -> None
    control_verb: Callable[[str, str], None]  # (verb, issue_id) -> None
    issue_inject: Callable[[str, str], None]  # (issue_id, hint) -> None
    operator_hints: Callable[[str, str], None]  # (issue_id, text) -> None
    agent_intent: Callable[[str, str], None]  # (verb, issue_id) -> None
    issue_cli: Callable[[str, str, str], None]  # (verb, issue_id, payload) -> None
    bridge_interrupt: Callable[[str, str], None]  # (issue_id, payload) -> None


class OrchestratorGatewayClient:
    def __init__(
        self,
        handlers: OrchestratorHandlers,
        *,
        ipc_client=None,
        origin: str = '',
        command_router: CommandRouter | None = None,
        control_bridge: ControlBridge | None = None,
        pending_outbound_limit: int = 20,
        pending_retry_base_seconds: float = 60.0,
        pending_retry_max_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._h = handlers
        self._commands = command_router or CommandRouter()
        self._control = control_bridge or ControlBridge()
        self._ipc = ipc_client
        self._origin = origin
        self._pending_outbound: deque[str] = deque()
        self._pending_outbound_limit = max(1, pending_outbound_limit)
        self._flush_lock = asyncio.Lock()
        self._clock = clock
        self._pending_retry_base_seconds = max(0.0, pending_retry_base_seconds)
        self._pending_retry_max_seconds = max(
            self._pending_retry_base_seconds,
            pending_retry_max_seconds,
        )
        self._pending_retry_delay = self._pending_retry_base_seconds
        self._pending_next_flush_at = 0.0
        if ipc_client is not None:
            # Route server-pushed DELIVER frames through dispatch.
            ipc_client.on_deliver = self._on_pushed_deliver

    async def _on_pushed_deliver(self, frame) -> None:
        """Server-pushed DELIVER (gateway→orchestrator): classify + dispatch."""
        from clawcodex_ext.services.im_gateway.models import (
            InboundMessage,
            MessageSemantics,
        )

        semantic = None
        if frame.semantic:
            with __import__('contextlib').suppress(ValueError):
                semantic = MessageSemantics(frame.semantic)
        message = InboundMessage(
            origin=frame.origin or self._origin,
            text=frame.text or '',
            message_id=frame.delivery_id or '',
            channel='',
            semantic=semantic,
        )
        if semantic is None:
            message.semantic = self._classify(message)
            semantic = message.semantic
        try:
            status = self.dispatch(message, semantic)
            await self._flush_pending_outbound(force=True)
            logger.info(
                'orchestrator IM push dispatched: delivery_id=%s status=%s',
                (frame.delivery_id or '')[:16],
                status,
            )
        except Exception:  # noqa: BLE001
            logger.exception('orchestrator IM dispatch failed')

    def _classify(self, message):
        from clawcodex_ext.messaging.semantics import MessageClassifier

        return MessageClassifier().classify(message)

    async def send_outbound(self, text: str) -> None:
        """Send a reply / event back to the IM origin via the OUTBOUND frame.

        The origin is the opt-in origin (``wechat:direct:*:*`` wildcard for
        orchestrator); the gateway resolves the wildcard to a concrete
        sender at OUTBOUND time (the WeChat adapter's most-recent sender,
        else its persisted context tokens). The event is only queued when
        the send cannot complete right now — the IPC socket is not yet
        open (the orchestrator emits ``orchestrator.started`` before the
        heartbeat loop has connected) or the gateway NACKs the send (for
        example unresolved wildcard routing or channel rate limiting) — so
        it is delivered by a later flush instead of being stranded or
        raising.
        """
        if self._ipc is None or not self._origin:
            return
        if text in self._pending_outbound:
            logger.debug('orchestrator IM outbound deduped before send: %r', text[:60])
            await self._flush_pending_outbound()
            return
        if self._pending_outbound:
            self._queue_pending_outbound(text)
            await self._flush_pending_outbound()
            return
        sent = await self._send_to_origin(self._origin, text)
        if not sent:
            self._queue_pending_outbound(text)

    async def _send_to_origin(self, origin: str, text: str) -> bool:
        if self._ipc is None:
            return False
        try:
            response = await self._ipc.send_outbound(origin=origin, text=text)
        except RuntimeError as exc:
            # Not connected yet (heartbeat loop hasn't run / reconnected).
            # Queue so the post-register flush delivers it; never propagate
            # — IM must not break the orchestrator main loop.
            logger.debug(
                'orchestrator IM outbound not connected; queueing origin=%s (%s)', origin[:32], exc
            )
            return False
        if response is None:
            logger.warning('orchestrator IM outbound failed without ACK origin=%s', origin[:32])
            self._defer_pending_flush('timeout')
            return False
        response_type = getattr(getattr(response, 'type', None), 'value', None)
        if response_type == 'nack':
            reason = getattr(response, 'reason', '') or ''
            logger.warning(
                'orchestrator IM outbound rejected origin=%s reason=%s',
                origin[:32],
                reason,
            )
            self._defer_pending_flush(reason)
            return False
        self._reset_pending_flush_backoff()
        return True

    def _queue_pending_outbound(self, text: str) -> None:
        # Skip exact duplicates already waiting in the queue — e.g. the
        # orchestrator emits "clawcodex-orchestrator: IM notifications
        # enabled" on every reconnect, and if the gateway can't resolve
        # the wildcard origin (operator hasn't messaged recently), each
        # copy would queue and all would flush at once when the operator
        # finally sends a message.
        if text in self._pending_outbound:
            logger.debug('orchestrator IM outbound deduped: %r already queued', text[:60])
            return
        if len(self._pending_outbound) >= self._pending_outbound_limit:
            self._pending_outbound.popleft()
            logger.warning('orchestrator IM outbound pending queue full; dropped oldest event')
        self._pending_outbound.append(text)
        logger.info('orchestrator IM outbound queued (pending connection or send retry)')

    def _defer_pending_flush(self, reason: str) -> None:
        delay = self._pending_retry_delay
        self._pending_next_flush_at = self._clock() + delay
        self._pending_retry_delay = min(
            delay * 2 if delay > 0 else self._pending_retry_base_seconds,
            self._pending_retry_max_seconds,
        )
        logger.info(
            'orchestrator IM outbound retry deferred: delay=%.1fs reason=%s',
            delay,
            reason[:120],
        )

    def _reset_pending_flush_backoff(self) -> None:
        self._pending_retry_delay = self._pending_retry_base_seconds
        self._pending_next_flush_at = 0.0

    async def _flush_pending_outbound(self, *, force: bool = False) -> None:
        # Serialise flush calls — the heartbeat loop and the inbound push
        # handler can both call this concurrently; without a lock, both
        # peek self._pending_outbound[0] before an await, then both try
        # popleft(), causing IndexError: pop from an empty deque.
        async with self._flush_lock:
            if not self._pending_outbound:
                return
            origin = self._origin
            if not origin:
                return
            if force:
                self._reset_pending_flush_backoff()
            elif self._pending_next_flush_at > self._clock():
                logger.debug(
                    'orchestrator IM pending outbound flush deferred for %.1fs',
                    self._pending_next_flush_at - self._clock(),
                )
                return
            # Wildcard origins are flushed too: the gateway resolves them at
            # OUTBOUND time (recent sender, else persisted context tokens).
            while self._pending_outbound:
                text = self._pending_outbound[0]
                try:
                    sent = await self._send_to_origin(origin, text)
                    if not sent:
                        return
                except Exception:  # noqa: BLE001
                    logger.warning(
                        'orchestrator IM pending outbound flush failed origin=%s',
                        origin[:32],
                        exc_info=True,
                    )
                    return
                self._pending_outbound.popleft()

    def dispatch(self, message: InboundMessage, semantic: MessageSemantics) -> str:
        """Route ``message`` to the right existing orchestrator entry.

        Returns a short status string describing the dispatch (for ack).
        """
        issue_id = self._issue_id(message)
        if semantic is MessageSemantics.FOLLOW_UP:
            self._h.queue_pending_message(issue_id, message.text)
            return 'followup_queued'
        if semantic is MessageSemantics.CONTEXT_ONLY:
            self._h.operator_hints(issue_id, message.text)
            return 'context_only_recorded'
        if semantic is MessageSemantics.INTERRUPT:
            # interrupt maps to control verbs via the bridge
            ctrl = self._control.resolve(MessageSemantics.INTERRUPT, None)
            if ctrl is not None:
                self._h.bridge_interrupt(issue_id, ctrl.payload)
            return 'interrupt_dispatched'
        if semantic is MessageSemantics.COMMAND:
            route = self._commands.route(message)
            if route is None:
                return 'command_unroutable'
            if route.kind == 'agent_intent':
                self._h.agent_intent(route.verb, route.issue_hint or issue_id)
                return f'agent_{route.verb}'
            # control_verb
            ctrl = self._control.resolve(semantic, route)
            if ctrl is None:
                return 'command_unroutable'
            if ctrl.surface == 'control_socket':
                self._h.control_verb(ctrl.verb, ctrl.issue_hint or issue_id)
                return f'control_{ctrl.verb}'
            if ctrl.surface == 'issue_inject':
                self._h.issue_inject(ctrl.issue_hint or issue_id, route.payload)
                return 'inject_delivered'
            if ctrl.surface == 'issue_cli':
                self._h.issue_cli(ctrl.verb, ctrl.issue_hint or issue_id, ctrl.payload)
                return f'issue_cli_{ctrl.verb}'
            return f'issue_cli_{ctrl.verb}'
        # newPrompt / approval → leave to the host agent / approval binding
        return 'not_dispatched'

    @staticmethod
    def _issue_id(message: InboundMessage) -> str:
        if message.raw and isinstance(message.raw, dict):
            iid = message.raw.get('issue_id')
            if iid:
                return str(iid)
        return ''


__all__ = ['OrchestratorGatewayClient', 'OrchestratorHandlers']
