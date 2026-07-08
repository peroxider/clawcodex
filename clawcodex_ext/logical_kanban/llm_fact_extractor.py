"""Runtime LLM-derived fact extraction for Logical Kanban (F-143 L1).

The extractor runs before the Layer-1 rule engine and augments the facts
snapshot with additional facts produced by the agent's LLM.  All extracted
facts are validated against the predicate glossary; unknown predicates are
dropped and audited.  No raw natural-language text is passed to a solver.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from clawcodex_ext.providers.base import ChatMessage

from .audit import (
    AuditLog,
    append_event_once,
    event_for_fact_dropped,
    event_for_fact_extracted,
)
from .flags import is_llm_facts_enabled
from .glossary import BUILT_IN_GLOSSARY, Glossary
from .ir import CanonicalAssertion, IRVariable, pred
from .ir_hash import assertion_hash
from .metrics import record_llm_facts_dropped, record_llm_facts_extracted
from .predicate_extractor import validate_assertion
from .solver_adapter import encode_solver_literal

if TYPE_CHECKING:
    from clawcodex_ext.providers.base import BaseProvider

    from .types import FactsSnapshot


logger = logging.getLogger(__name__)

_AssumptionSource = frozenset(
    {
        "user_input",
        "default_kb",
        "inferred",
        "user_clarified",
        "datalog_derived",
        "llm_extracted",
        "web_search",
        "agent_inferred",
    }
)


class LlmFactExtractor:
    """Extract canonical facts from an LLM given a snapshot and task text."""

    def __init__(self, provider: "BaseProvider | None" = None) -> None:
        self.provider = provider

    def run(
        self,
        snapshot: "FactsSnapshot",
        glossary: Glossary = BUILT_IN_GLOSSARY,
        *,
        task_text: str | None = None,
        model_version: str = "llm-knowledge-v1",
        audit_log: AuditLog | None = None,
        timeout_seconds: float = 30.0,
    ) -> tuple[CanonicalAssertion, ...]:
        """Return extracted facts that pass the glossary gate.

        When the feature flag is off, the provider is missing, or the model
        returns no facts, this returns an empty tuple without blocking the
        commit path.
        """
        del timeout_seconds  # Reserved for future per-call timeout plumbing.
        if not is_llm_facts_enabled() or self.provider is None:
            return ()

        text = task_text or self._task_text_from_snapshot(snapshot)
        if not text:
            return ()

        prompt = self._build_prompt(snapshot, glossary, text)
        try:
            response = self.provider.chat([ChatMessage(role="user", content=prompt)])
            raw = response.content
            model_id = getattr(response, "model", model_version) or model_version
        except Exception as exc:  # noqa: BLE001 - extraction must not break validation
            logger.debug("LlmFactExtractor provider call failed: %s", exc)
            return ()

        facts = self._parse_response(raw)
        accepted: list[CanonicalAssertion] = []
        dropped = 0
        for fact in facts:
            source = fact.get("source", "llm_extracted")
            if source not in _AssumptionSource:
                source = "llm_extracted"
            assertion = self._fact_to_assertion(fact, model_id)
            if assertion is None:
                dropped += 1
                continue
            extraction = validate_assertion(assertion, glossary)
            if extraction.status == "needs_glossary_review":
                dropped += 1
                if audit_log is not None:
                    append_event_once(
                        audit_log,
                        event_for_fact_dropped(
                            assertion_hash=assertion_hash(assertion),
                            reason="unknown_predicate",
                            unknown_predicates=tuple(sorted(extraction.unknown)),
                            model_id=model_id,
                            actor="system",
                        ),
                    )
                continue
            accepted.append(assertion)
            if audit_log is not None:
                append_event_once(
                    audit_log,
                    event_for_fact_extracted(
                        assertion_hash=assertion_hash(assertion),
                        source=source,
                        confidence=self._clamp_confidence(fact.get("confidence", 0.6)),
                        model_id=model_id,
                        glossary_status="valid",
                        actor="system",
                    ),
                )

        if accepted:
            record_llm_facts_extracted(len(accepted))
        if dropped:
            record_llm_facts_dropped(dropped, reason="unknown_predicate")
        return tuple(accepted)

    def _task_text_from_snapshot(self, snapshot: "FactsSnapshot") -> str:
        parts: list[str] = []
        for task in snapshot.normalized_tasks.values():
            subject = task.get("subject") or ""
            description = task.get("description") or ""
            if subject:
                parts.append(subject)
            if description:
                parts.append(description)
        return "\n".join(parts)

    def _build_prompt(
        self,
        snapshot: "FactsSnapshot",
        glossary: Glossary,
        task_text: str,
    ) -> str:
        facts_summary = json.dumps(
            {
                "tasks": [
                    {
                        "id": tid,
                        "status": t.get("status"),
                        "subject_ref": encode_solver_literal(t.get("subject", "")),
                        "description_ref": encode_solver_literal(t.get("description", "")),
                    }
                    for tid, t in snapshot.normalized_tasks.items()
                ],
                "facts": list(snapshot.facts),
            },
            sort_keys=True,
            default=str,
        )
        predicates = sorted(glossary.predicate_names())
        return (
            "You are a fact extractor for a logical kanban system. "
            "Given the current task snapshot and the allowed predicate glossary, "
            "emit additional atomic facts that help decide whether the task can advance. "
            "Only use predicates from the glossary. "
            "Return strictly JSON with this shape:\n"
            '{"facts": [{"predicate": "Requires", "args": ["taskA", "taskB"], '
            '"source": "llm_extracted", "confidence": 0.6}], "model_id": "model-name"}\n'
            "Allowed sources: user_input, default_kb, inferred, user_clarified, "
            "datalog_derived, llm_extracted, web_search, agent_inferred.\n"
            "Confidence must be between 0.0 and 1.0.\n"
            f"Allowed predicates: {predicates}\n"
            f"Snapshot summary: {facts_summary}\n"
            f"Task text: {task_text}\n"
            "JSON:"
        )

    def _parse_response(self, raw: str) -> tuple[dict[str, Any], ...]:
        """Parse the LLM response into a tuple of fact dictionaries."""
        if not isinstance(raw, str):
            return ()
        text = raw.strip()
        if text.startswith("```"):
            # Strip markdown code fences if present.
            lines = text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return ()
        if not isinstance(parsed, dict):
            return ()
        facts = parsed.get("facts")
        if not isinstance(facts, list):
            return ()
        return tuple(fact for fact in facts if isinstance(fact, dict))

    def _fact_to_assertion(
        self,
        fact: dict[str, Any],
        model_id: str,
    ) -> CanonicalAssertion | None:
        predicate = fact.get("predicate")
        if not isinstance(predicate, str):
            return None
        raw_args = fact.get("args")
        if not isinstance(raw_args, (list, tuple)):
            return None
        source = fact.get("source", "llm_extracted")
        if source not in _AssumptionSource:
            source = "llm_extracted"
        confidence = self._clamp_confidence(fact.get("confidence", 0.6))
        encoded_args = tuple(encode_solver_literal(str(arg)) for arg in raw_args)
        assertion = CanonicalAssertion(
            role="axiom",
            kind="prerequisite",
            body=pred(predicate, *encoded_args),
            quantifier="forall",
            vars=tuple(
                IRVariable(name=f"arg_{i}", type="Entity") for i in range(len(encoded_args))
            ),
            schema_version="1.0",
        )
        # Attach provenance through a lightweight annotation on the returned
        # assertion.  The CanonicalAssertion dataclass is frozen/slotted, so we
        # cannot add arbitrary fields; callers use the audit log for source
        # attribution.
        del model_id
        return assertion

    @staticmethod
    def _clamp_confidence(value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            confidence = 0.6
        return max(0.0, min(1.0, confidence))


def extract_facts(
    snapshot: "FactsSnapshot",
    glossary: Glossary = BUILT_IN_GLOSSARY,
    *,
    provider: "BaseProvider | None" = None,
) -> tuple[CanonicalAssertion, ...]:
    """Synchronous convenience wrapper around :class:`LlmFactExtractor`."""
    return LlmFactExtractor(provider=provider).run(
        snapshot,
        glossary,
        task_text=None,
        model_version="llm-knowledge-v1",
        audit_log=None,
    )


__all__ = ["LlmFactExtractor", "extract_facts"]
