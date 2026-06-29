"""CommandRouter — map ``command`` semantic to existing entry points (P5).

Reuses the orchestrator's ``parse_agent_command`` for
``/agent retry|follow-up|unblock`` and recognizes the issue-CLI control
verbs (pause/resume/stop/inject/takeover/clarify/review/feedback). It
does NOT invent new synonyms — same names as the existing surfaces.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from clawcodex_ext.services.im_gateway.models import InboundMessage

_AGENT_CMD_RE = re.compile(r"^\s*/agent\s+(retry|follow-up|unblock)\b[^\n]*", re.IGNORECASE)
_CONTROL_VERB_RE = re.compile(
    r"^\s*/(?P<verb>pause|resume|stop|takeover|inject|detach|clarify|review|feedback)\b[^\n]*",
    re.IGNORECASE,
)


@dataclass
class CommandRoute:
    kind: str  # "agent_intent" | "control_verb"
    verb: str  # retry | follow-up | unblock | pause | resume | ...
    issue_hint: str | None = None
    payload: str = ""


class CommandRouter:
    def route(self, message: InboundMessage) -> CommandRoute | None:
        text = (message.text or "").strip()
        m = _AGENT_CMD_RE.match(text)
        if m:
            verb = m.group(1).lower()
            issue_hint = self._extract_issue(text)
            return CommandRoute(kind="agent_intent", verb=verb, issue_hint=issue_hint, payload=text)
        m = _CONTROL_VERB_RE.match(text)
        if m:
            verb = m.group("verb").lower()
            issue_hint = self._extract_issue(text)
            return CommandRoute(kind="control_verb", verb=verb, issue_hint=issue_hint, payload=text)
        return None

    @staticmethod
    def _extract_issue(text: str) -> str | None:
        # Loose match for issue ids like AGENTSDK-15, PROJ-128, etc.
        m = re.search(r"\b([A-Z][A-Z0-9_]+-\d+)\b", text)
        return m.group(1) if m else None


__all__ = ["CommandRoute", "CommandRouter"]
