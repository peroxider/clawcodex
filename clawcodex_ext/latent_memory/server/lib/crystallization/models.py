"""Normalization helper functions and structured asset models."""

from __future__ import annotations

import json
import re
from typing import Any

from clawcodex_ext.latent_memory.server.lib.crystallization.prompts import ASSET_TYPES, FACET_KEYS

KNOWLEDGE_TYPES = {"preference", "fact", "skill", "relationship", "temporal"}

TYPE_TO_ASSET_TYPE = {
    "preference": "preference_profile",
    "fact": "summary",
    "skill": "skill_card",
    "relationship": "relation_edge",
    "temporal": "temporal_fact",
}

ASSET_TYPE_TO_TYPE = {
    "preference_profile": "preference",
    "summary": "fact",
    "skill_card": "skill",
    "rule_card": "fact",
    "relation_edge": "relationship",
    "temporal_fact": "temporal",
}

ABSORB_COMPATIBLE_ASSET_TYPES = {
    "preference_profile": {"preference_profile", "summary"},
    "skill_card": {"skill_card", "rule_card", "summary"},
    "rule_card": {"rule_card", "skill_card", "summary"},
    "relation_edge": {"relation_edge", "summary"},
    "temporal_fact": {"temporal_fact", "summary"},
    "summary": {"summary"},
}

UNKNOWN_ASSET_TYPE = "unknown"

_SUBJECT_STOPWORDS = {
    "a",
    "an",
    "and",
    "he",
    "i",
    "it",
    "she",
    "the",
    "they",
    "this",
    "user",
    "we",
}

_RELATIVE_TIME_PATTERNS = (
    re.compile(
        r"昨天|前天|今天|明天|后天|上周|上星期|本周|这周|下周|下星期|上个月|这个月|本月|下个月|"
        r"去年|今年|明年|最近|近期|目前|当前|现在|刚才|稍后|当时|上次|下次|这次|"
        r"(?:\d+|[一二三四五六七八九十两]+)\s*(?:天|周|个月|月|年)(?:前|后)"
    ),
    re.compile(
        r"\b(?:yesterday|today|tomorrow|recently|currently|now|earlier|later|"
        r"last\s+(?:week|month|year|night|time)|this\s+(?:week|month|year)|"
        r"next\s+(?:week|month|year|time)|(?:in\s+)?\d+\s+(?:days?|weeks?|months?|years?)\s+"
        r"(?:ago|later)|in\s+\d+\s+(?:days?|weeks?|months?|years?))\b",
        re.IGNORECASE,
    ),
)

_CONTEXT_DEPENDENT_PATTERNS = (
    re.compile(
        r"这次|此次|这里|那里|当时|上述|前述|前面提到的|刚才|"
        r"本次(?:对话|会话|任务)|当前(?:对话|会话|页面)|"
        r"(?:这个|那个|该|本)(?:项目|任务|问题|文件|接口|方案|页面)"
    ),
    re.compile(
        r"\b(?:here|there|this\s+time|that\s+time|the\s+above|above-mentioned|"
        r"aforementioned|as\s+discussed|(?:this|that)\s+(?:project|task|issue|"
        r"file|interface|plan|page|conversation))\b",
        re.IGNORECASE,
    ),
)


def _normalize_facets(raw_facets: Any) -> dict[str, list[str]]:
    """Normalize facets provided by the LLM/user into the known list-valued keys."""
    facets: dict[str, list[str]] = {key: [] for key in FACET_KEYS}
    if not isinstance(raw_facets, dict):
        return facets
    for key in FACET_KEYS:
        value = raw_facets.get(key, [])
        if isinstance(value, str):
            values = [value]
        elif isinstance(value, list):
            values = value
        else:
            values = []
        seen: set[str] = set()
        for item in values:
            text = str(item).strip()
            if not text:
                continue
            marker = text.lower()
            if marker in seen:
                continue
            seen.add(marker)
            facets[key].append(text)
    return facets


def _flatten_facets(facets: dict[str, list[str]], max_items: int = 24) -> list[str]:
    """Return deduplicated facet values in a stable order, for embedding/validation."""
    flattened: list[str] = []
    seen: set[str] = set()
    for key in FACET_KEYS:
        for item in facets.get(key, []):
            text = str(item).strip()
            marker = text.lower()
            if text and marker not in seen:
                flattened.append(text)
                seen.add(marker)
                if len(flattened) >= max_items:
                    return flattened
    return flattened


def _display_text(item: dict[str, Any]) -> str:
    """For crystallized entries, prefer display_text over the embedding-augmented memory."""
    meta = item.get("metadata", {}) or {}
    display = meta.get("display_text") if isinstance(meta, dict) else None
    if isinstance(display, str) and display.strip():
        return display.strip()
    return str(item.get("memory", "")).strip()


def subject_key_for_memory(item: dict[str, Any]) -> str:
    """Return a lightweight subject key used for cluster boundary checks."""
    meta = item.get("metadata", {}) or {}
    if isinstance(meta, dict):
        for key in ("subject",):
            value = meta.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
        asset = meta.get("asset", {})
        if isinstance(asset, dict):
            subject = asset.get("subject")
            if isinstance(subject, str) and subject.strip():
                return subject.strip().lower()
        facets = _normalize_facets(meta.get("facets", {}))
        entities = facets.get("entities", [])
        if entities:
            return entities[0].strip().lower()

    text = str(item.get("memory", "") or "").strip()
    if not text:
        return ""
    if text.startswith("用户"):
        return "用户"
    match = re.match(r"^([A-Z][A-Za-z'-]{1,}(?:\s+[A-Z][A-Za-z'-]{1,})?)\b", text)
    if not match:
        return ""
    subject = match.group(1).strip()
    if subject.lower() in _SUBJECT_STOPWORDS:
        return ""
    return subject.lower()


def _build_embedding_text(display_text: str, facets: dict[str, list[str]]) -> str:
    """Append high-value facets to the text to be vectorized, while keeping display_text clean."""
    keywords = [
        item
        for item in _flatten_facets(facets, max_items=8)
        if item.lower() not in display_text.lower()
    ]
    if not keywords:
        return display_text
    return f"{display_text}\n\n关键词: {', '.join(keywords)}"


def _normalize_string_list(value: Any) -> list[str]:
    """Normalize any LLM JSON value into a compact list of strings."""
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        values = []
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        if isinstance(item, dict):
            text = json.dumps(item, ensure_ascii=False)
        else:
            text = str(item)
        text = text.strip()
        marker = text.lower()
        if text and marker not in seen:
            seen.add(marker)
            result.append(text)
    return result


def find_relative_time_references(value: Any) -> list[str]:
    """Find relative time expressions in candidate crystal fields."""
    texts: list[str] = []

    def collect(item: Any) -> None:
        if isinstance(item, str):
            texts.append(item)
        elif isinstance(item, dict):
            for nested in item.values():
                collect(nested)
        elif isinstance(item, (list, tuple, set)):
            for nested in item:
                collect(nested)

    collect(value)
    matches: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for pattern in _RELATIVE_TIME_PATTERNS:
            for match in pattern.finditer(text):
                reference = match.group(0).strip()
                marker = reference.casefold()
                if marker and marker not in seen:
                    seen.add(marker)
                    matches.append(reference)
    return matches


def find_context_dependent_references(value: Any) -> list[str]:
    """Find unresolved scene and conversation references in crystal fields."""
    texts: list[str] = []

    def collect(item: Any) -> None:
        if isinstance(item, str):
            texts.append(item)
        elif isinstance(item, dict):
            for nested in item.values():
                collect(nested)
        elif isinstance(item, (list, tuple, set)):
            for nested in item:
                collect(nested)

    collect(value)
    matches: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for pattern in _CONTEXT_DEPENDENT_PATTERNS:
            for match in pattern.finditer(text):
                reference = match.group(0).strip()
                marker = reference.casefold()
                if marker and marker not in seen:
                    seen.add(marker)
                    matches.append(reference)
    return matches


def _clip_text(text: Any, max_chars: int) -> str:
    """Limit the size of prompt inputs while retaining source_ids for full traceability."""
    value = str(text or "").strip()
    if max_chars <= 0 or len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip() + "..."


def _normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "pass", "passed", "合格", "通过"}
    return False


def _compact_text(text: str, max_chars: int = 420) -> str:
    """Limit the display text length of crystals without over-copying the details of each source."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    head = text[: max_chars + 1]
    for boundary in ("。", "！", "？", ".", "!", "?", "\n", "；", ";"):
        pos = head.rfind(boundary, 0, max_chars + 1)
        if pos >= max_chars * 0.45:
            return head[: pos + 1].strip()
    return head[:max_chars].rstrip(" ,，;；:：")


def infer_asset_type(knowledge_type: str, facets: dict[str, list[str]], text: str) -> str:
    """Infer an asset_type when the LLM omits or corrupts the asset_type."""
    return TYPE_TO_ASSET_TYPE.get(knowledge_type, "summary")


def asset_type_for_memory(item: dict[str, Any]) -> str:
    """Return the explicit asset_type of a raw or crystallized memory entry."""
    meta = item.get("metadata", {}) or {}
    if not isinstance(meta, dict):
        meta = {}
    asset_type = str(meta.get("asset_type") or "").strip()
    if asset_type in ASSET_TYPES:
        return asset_type
    knowledge_type = str(meta.get("knowledge_type") or "").strip()
    if knowledge_type in TYPE_TO_ASSET_TYPE:
        return TYPE_TO_ASSET_TYPE[knowledge_type]
    return UNKNOWN_ASSET_TYPE


def asset_types_absorb_compatible(target_asset_type: str, raw_asset_type: str) -> bool:
    """Conservative boundary: typed crystals should not absorb other claim shapes."""
    if target_asset_type == UNKNOWN_ASSET_TYPE or raw_asset_type == UNKNOWN_ASSET_TYPE:
        return True
    allowed = ABSORB_COMPATIBLE_ASSET_TYPES.get(target_asset_type, {"summary"})
    return raw_asset_type in allowed


def _normalize_asset(
    raw_asset: Any, *, text: str, knowledge_type: str, facets: dict[str, list[str]], asset_type: str
) -> dict[str, Any]:
    """Normalize the LLM's asset output and locally synthesize missing fields."""
    asset = raw_asset if isinstance(raw_asset, dict) else {}
    entities = facets.get("entities", [])
    preferences = facets.get("preferences", [])
    tools = facets.get("tools", [])
    subject = str(asset.get("subject") or (entities[0] if entities else "")).strip()
    predicate = str(asset.get("predicate") or knowledge_type).strip()
    obj = str(asset.get("object") or "").strip()
    if not obj:
        if asset_type == "preference_profile" and preferences:
            obj = "; ".join(preferences[:4])
        elif tools:
            obj = "; ".join(tools[:4])
    raw_applicability = asset.get("applicability")
    raw_applicability = raw_applicability if isinstance(raw_applicability, dict) else {}
    conditions = _normalize_string_list(asset.get("conditions", []))
    applicability = {
        "applies_when": _normalize_string_list(raw_applicability.get("applies_when", conditions)),
        "does_not_apply_when": _normalize_string_list(
            raw_applicability.get("does_not_apply_when", [])
        ),
        "known_exceptions": _normalize_string_list(raw_applicability.get("known_exceptions", [])),
    }
    return {
        "claim": str(asset.get("claim") or text).strip(),
        "subject": subject,
        "predicate": predicate,
        "object": obj,
        "conditions": conditions,
        "steps": _normalize_string_list(asset.get("steps", [])),
        "relations": _normalize_string_list(asset.get("relations", [])),
        "valid_from": str(asset.get("valid_from") or "").strip(),
        "valid_to": str(asset.get("valid_to") or "").strip(),
        "applicability": applicability,
    }


def normalize_merged_crystal(
    merged: dict[str, Any], *, max_text_chars: int = 420
) -> dict[str, Any]:
    """Validate and normalize the LLM's merge/repair output, using local fallback logic when necessary."""
    text = merged.get("text", "")
    if not isinstance(text, str):
        text = str(text) if text is not None else ""
    text = text.strip()
    if not text:
        raise ValueError("LLM 返回的 text 为空")
    text = _compact_text(text, max_text_chars)

    raw_knowledge_type = merged.get("type", "fact")
    knowledge_type = raw_knowledge_type
    if knowledge_type not in KNOWLEDGE_TYPES:
        knowledge_type = "fact"

    confidence = merged.get("confidence", 0.8)
    if not isinstance(confidence, (int, float)):
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.8
    if not (0.0 <= confidence <= 1.0):
        confidence = max(0.0, min(1.0, confidence))

    facets = _normalize_facets(merged.get("facets", {}))
    raw_asset = merged.get("asset", {})
    raw_asset = raw_asset if isinstance(raw_asset, dict) else {}
    asset_type = str(merged.get("asset_type") or "").strip()
    if asset_type not in ASSET_TYPES:
        asset_type = infer_asset_type(knowledge_type, facets, text)
    if raw_knowledge_type in KNOWLEDGE_TYPES and asset_type != TYPE_TO_ASSET_TYPE.get(
        knowledge_type
    ):
        knowledge_type = ASSET_TYPE_TO_TYPE.get(asset_type, knowledge_type)
    asset = _normalize_asset(
        raw_asset,
        text=text,
        knowledge_type=knowledge_type,
        facets=facets,
        asset_type=asset_type,
    )

    return {
        "text": text,
        "type": knowledge_type,
        "confidence": confidence,
        "facets": facets,
        "asset_type": asset_type,
        "asset": asset,
        "subject": asset.get("subject", ""),
    }


def aggregate_crystal_composition(
    crystals: list[dict[str, Any]], user_ids: list[str]
) -> dict[str, Any]:
    """Aggregate crystal metadata into a composition snapshot."""
    by_asset_type: dict[str, int] = {}
    by_knowledge_type: dict[str, int] = {}
    version_distribution: dict[str, int] = {}
    confidence_sum = 0.0
    confidence_count = 0
    source_id_set: set[str] = set()
    for crystal in crystals:
        metadata = crystal.get("metadata", {}) or {}
        if not isinstance(metadata, dict):
            metadata = {}
        asset_type = str(metadata.get("asset_type") or "unknown")
        knowledge_type = str(metadata.get("knowledge_type") or "unknown")
        version = int(metadata.get("version", 1) or 1)
        by_asset_type[asset_type] = by_asset_type.get(asset_type, 0) + 1
        by_knowledge_type[knowledge_type] = by_knowledge_type.get(knowledge_type, 0) + 1
        version_key = f"v{version}"
        version_distribution[version_key] = version_distribution.get(version_key, 0) + 1
        confidence = metadata.get("confidence")
        if isinstance(confidence, (int, float)):
            confidence_sum += float(confidence)
            confidence_count += 1
        source_ids = metadata.get("source_ids", [])
        if isinstance(source_ids, list):
            source_id_set.update(
                source_id for source_id in source_ids if isinstance(source_id, str) and source_id
            )

    return {
        "user_ids": user_ids,
        "user_count": len(user_ids),
        "total": len(crystals),
        "by_asset_type": by_asset_type,
        "by_knowledge_type": by_knowledge_type,
        "avg_confidence": round(confidence_sum / confidence_count, 3) if confidence_count else 0.0,
        "unique_source_ids": len(source_id_set),
        "version_distribution": version_distribution,
    }
