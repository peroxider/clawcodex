"""MessageClassifier — six-class inbound semantics (P5).

Classification rules (no natural-language auto-judgment for
``interrupt``/``contextOnly`` — those require structured metadata or
existing control/bridge entry points):

  1. structured ``deliverAs`` metadata → that semantic (explicit)
  2. ``/agent retry|follow-up|unblock`` → ``command``
  3. leading control verb ``/pause /resume /stop /takeover /inject`` → ``command``
  4. plain text while session busy → ``followUp`` (queue-as-followUp)
  5. otherwise → ``newPrompt``

``approval`` is only set via structured metadata (``deliverAs=approval``
or a bound wait-point reply) — a bare "yes" is ``newPrompt`` unless
bound, to avoid misrouting approvals.
"""

from __future__ import annotations

import re
from typing import Any

from clawcodex_ext.services.im_gateway.models import InboundMessage, MessageSemantics

_AGENT_CMD_RE = re.compile(r"^\s*/agent\s+(retry|follow-up|unblock)\b", re.IGNORECASE)
_CONTROL_VERB_RE = re.compile(
    r"^\s*/(pause|resume|stop|takeover|inject|detach|clarify|review|feedback)\b", re.IGNORECASE
)

_DELIVER_AS_MAP = {
    "newPrompt": MessageSemantics.NEW_PROMPT,
    "command": MessageSemantics.COMMAND,
    "followUp": MessageSemantics.FOLLOW_UP,
    "approval": MessageSemantics.APPROVAL,
    "interrupt": MessageSemantics.INTERRUPT,
    "contextOnly": MessageSemantics.CONTEXT_ONLY,
}


class MessageClassifier:
    def classify(
        self,
        message: InboundMessage,
        *,
        is_busy: bool = False,
        has_pending_wait: bool = False,
    ) -> MessageSemantics:
        # 1. structured deliverAs wins (explicit, no NL guessing)
        deliver_as = self._deliver_as(message)
        if deliver_as is not None:
            return deliver_as
        # 2. explicit control verbs / agent commands
        text = (message.text or "").strip()
        if _AGENT_CMD_RE.match(text):
            return MessageSemantics.COMMAND
        if _CONTROL_VERB_RE.match(text):
            return MessageSemantics.COMMAND
        # 3. approval only via structured metadata or bound wait-point
        if has_pending_wait and message.semantic_tags and "approval" in message.semantic_tags:
            return MessageSemantics.APPROVAL
        # 4. busy ordinary text → queue-as-followUp
        if is_busy:
            return MessageSemantics.FOLLOW_UP
        # 5. default
        return MessageSemantics.NEW_PROMPT

    def _deliver_as(self, message: InboundMessage) -> MessageSemantics | None:
        raw = None
        if message.raw and isinstance(message.raw, dict):
            raw = message.raw.get("deliverAs")
        if raw is None:
            # semantic_tags may carry an explicit semantic
            for tag in message.semantic_tags or []:
                if tag in _DELIVER_AS_MAP:
                    return _DELIVER_AS_MAP[tag]
        if isinstance(raw, str) and raw in _DELIVER_AS_MAP:
            return _DELIVER_AS_MAP[raw]
        return None


__all__ = ["MessageClassifier"]
