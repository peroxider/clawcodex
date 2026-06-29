"""Inbound dispatcher.

Pipeline: dedupe → classify (six-class) → route → handle.

Classification uses :class:`MessageClassifier` (P5): structured
``deliverAs`` wins; ``/agent`` + control verbs → ``command``; busy
ordinary text → ``followUp`` (queue-as-followUp); idle plain text →
``newPrompt``. ``interrupt``/``contextOnly`` are never guessed from
natural language — only structured metadata or existing control/bridge
entry points.

The dispatcher delegates execution to a registered handler. Follow-up
semantics for unbound origins fall through to the default handler (stub
agent); opt-in hosts own their own queueing.
"""

from __future__ import annotations

import logging
import uuid
from typing import Awaitable, Callable

from clawcodex_ext.messaging.semantics import MessageClassifier

logger = logging.getLogger(__name__)

from .models import AckLayer, AckReceipt, InboundMessage, MessageSemantics
from .router import SessionRouter
from .store import ReliabilityStore

InboundHandler = Callable[[InboundMessage], Awaitable[AckReceipt | None]]
PushHandler = Callable[[InboundMessage], Awaitable[bool]]

# host_types that route to an opt-in peer over IPC push instead of the
# default in-process handler.
_OPT_IN_HOST_TYPES = frozenset({'repl', 'orchestrator', 'opt_in'})


class InboundDispatcher:
    def __init__(
        self,
        store: ReliabilityStore,
        router: SessionRouter,
        *,
        classifier: MessageClassifier | None = None,
    ) -> None:
        self._store = store
        self._router = router
        self._classifier = classifier or MessageClassifier()
        self._handler: InboundHandler | None = None
        self._push_handler: PushHandler | None = None

    def set_handler(self, handler: InboundHandler) -> None:
        self._handler = handler

    def set_push_handler(self, handler: PushHandler) -> None:
        """Register the IPC push callback used for opt-in origins.

        When an origin is bound to an opt-in peer (REPL/orchestrator), the
        dispatcher pushes the message over IPC instead of calling the
        default handler. ``handler`` returns True if a live peer received it.
        """
        self._push_handler = handler

    def classify(
        self, message: InboundMessage, *, is_busy: bool = False, has_pending_wait: bool = False
    ) -> MessageSemantics:
        return self._classifier.classify(
            message, is_busy=is_busy, has_pending_wait=has_pending_wait
        )

    async def process(self, message: InboundMessage) -> AckReceipt:
        delivery_id = str(uuid.uuid4())
        # 1. dedupe
        key = message.message_id or f'{message.origin}:{message.text}'
        if not self._store.check_and_record(key, message_id=message.message_id):
            return AckReceipt(delivery_id, AckLayer.ACCEPTED, message='duplicate; skipped')
        # 2. classify — honor a caller-supplied semantic (e.g. from a
        # busy-aware handler re-dispatch), else classify fresh.
        if message.semantic is None:
            message.semantic = self.classify(message)
        # 3. route — reject if opt-in target is offline (no offline payload store)
        if self._router.is_offline(message.origin):
            self._store.audit(
                'target_offline',
                delivery_id=delivery_id,
                origin=message.origin,
                message_id=message.message_id,
            )
            return AckReceipt(
                delivery_id,
                AckLayer.ACCEPTED,
                message='target_offline; rebind or use default session',
            )
        target = self._router.route(message.origin)
        logger.info(
            'im_gateway: route origin=%s semantic=%s target=%s host_type=%s',
            message.origin[:32],
            message.semantic.value if message.semantic else None,
            target.session_id[:32],
            target.host_type,
        )
        # 4. opt-in origin (REPL/orchestrator bound over IPC) → push the whole
        # message to the peer; the peer owns its own queueing/semantics. This
        # overrides the default in-process handler.
        if target.host_type in _OPT_IN_HOST_TYPES and self._push_handler is not None:
            try:
                delivered = await self._push_handler(message)
            except Exception:  # noqa: BLE001
                logger.exception('im_gateway: push_handler error origin=%s', message.origin)
                delivered = False
            if delivered:
                return AckReceipt(delivery_id, AckLayer.ENQUEUED, message='pushed to opt-in peer')
            # push failed (peer offline) → fall through to default handler
            logger.warning(
                'im_gateway: opt-in push failed origin=%s; falling back to default',
                message.origin[:32],
            )
        # 5. dispatch → handler
        if self._handler is not None:
            result = await self._handler(message)
            if result is not None:
                return result
        return AckReceipt(delivery_id, AckLayer.ACCEPTED, message='accepted')


__all__ = ['InboundDispatcher', 'InboundHandler']
