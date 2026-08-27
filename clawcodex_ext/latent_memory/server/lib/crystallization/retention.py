"""Retention judgment and repair helper functions."""

from __future__ import annotations

import json
from typing import Any, Callable

from clawcodex_ext.latent_memory.server.lib.crystallization.models import (
    _normalize_bool,
    _normalize_string_list,
    find_context_dependent_references,
    find_relative_time_references,
    normalize_merged_crystal,
)
from clawcodex_ext.latent_memory.server.lib.crystallization.prompts import (
    MERGE_JSON_SCHEMA,
    REPAIR_SYSTEM_PROMPT,
    REPAIR_USER_TEMPLATE,
    RETENTION_JUDGE_JSON_SCHEMA,
    RETENTION_JUDGE_SYSTEM_PROMPT,
    RETENTION_JUDGE_USER_TEMPLATE,
    _RETENTION_MISSING_TOLERANT,
    detect_dominant_language,
)


def validate_retention_judge(judge: dict[str, Any]) -> dict[str, Any]:
    """Normalize the output of the LLM's retention judgment."""
    missing = _normalize_string_list(judge.get("missing_important_claims", []))
    unsupported = _normalize_string_list(judge.get("unsupported_claims", []))
    topic_drift = _normalize_bool(judge.get("topic_drift", False))
    asset_type_mismatch = _normalize_bool(judge.get("asset_type_mismatch", False))
    reusable_value = _normalize_bool(judge.get("reusable_value", True))
    context_dependent = _normalize_string_list(judge.get("context_dependent_claims", []))
    relative_time = _normalize_string_list(judge.get("relative_time_references", []))
    suggested_asset_type = str(judge.get("suggested_asset_type", "") or "").strip()
    if asset_type_mismatch and not suggested_asset_type:
        suggested_asset_type = "summary"
    passed = (
        _normalize_bool(judge.get("passed", False))
        and not topic_drift
        and not unsupported
        and not asset_type_mismatch
        and reusable_value
        and not context_dependent
        and not relative_time
        and len(missing) <= _RETENTION_MISSING_TOLERANT
    )
    return {
        "passed": passed,
        "missing_important_claims": missing,
        "unsupported_claims": unsupported,
        "topic_drift": topic_drift,
        "asset_type_mismatch": asset_type_mismatch,
        "reusable_value": reusable_value,
        "context_dependent_claims": context_dependent,
        "relative_time_references": relative_time,
        "suggested_asset_type": suggested_asset_type,
        "acceptable_compressions": _normalize_string_list(judge.get("acceptable_compressions", [])),
        "rationale": str(judge.get("rationale", "") or "").strip(),
    }


def judge_retention(
    llm_fn: Callable[[str, str, dict[str, Any]], dict[str, Any]],
    *,
    old_text: str,
    old_facets: dict[str, list[str]],
    old_asset: dict[str, Any],
    new_texts: list[str],
    merged: dict[str, Any],
) -> dict[str, Any]:
    """Ask the LLM whether the candidate crystal retains important value."""
    judge = llm_fn(
        RETENTION_JUDGE_SYSTEM_PROMPT,
        RETENTION_JUDGE_USER_TEMPLATE.format(
            old_text,
            json.dumps(old_facets, ensure_ascii=False),
            json.dumps(old_asset, ensure_ascii=False),
            "\n".join(f"- {t}" for t in new_texts),
            merged["text"],
            json.dumps(merged["facets"], ensure_ascii=False),
            json.dumps(merged["asset"], ensure_ascii=False),
        ),
        RETENTION_JUDGE_JSON_SCHEMA,
    )
    check = validate_retention_judge(judge)
    candidate_fields = {
        "text": merged.get("text", ""),
        "facets": merged.get("facets", {}),
        "asset": merged.get("asset", {}),
    }
    detected_context = find_context_dependent_references(candidate_fields)
    if detected_context:
        check["context_dependent_claims"] = list(
            dict.fromkeys(check["context_dependent_claims"] + detected_context)
        )
        check["passed"] = False
    detected_relative_time = find_relative_time_references(candidate_fields)
    if detected_relative_time:
        check["relative_time_references"] = list(
            dict.fromkeys(check["relative_time_references"] + detected_relative_time)
        )
        check["passed"] = False
    return check


def validate_or_repair_retention(
    llm_fn: Callable[[str, str, dict[str, Any]], dict[str, Any]],
    *,
    old_text: str,
    old_facets: dict[str, list[str]],
    old_asset: dict[str, Any],
    new_texts: list[str],
    merged: dict[str, Any],
    max_text_chars: int = 420,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Use the LLM judge to ensure important information value is retained."""
    check = judge_retention(
        llm_fn,
        old_text=old_text,
        old_facets=old_facets,
        old_asset=old_asset,
        new_texts=new_texts,
        merged=merged,
    )
    check["repaired"] = False
    if check["passed"]:
        return merged, check
    if not check.get("reusable_value", True):
        raise ValueError(
            "retention judge rejected candidate without reusable value: "
            + json.dumps(check, ensure_ascii=False)
        )

    missing = check.get("missing_important_claims", [])
    unsupported = check.get("unsupported_claims", [])
    asset_type_mismatch = check.get("asset_type_mismatch", False)
    suggested_asset_type = check.get("suggested_asset_type", "")
    if asset_type_mismatch and not suggested_asset_type:
        suggested_asset_type = "summary"
    repaired = llm_fn(
        REPAIR_SYSTEM_PROMPT,
        REPAIR_USER_TEMPLATE.format(
            old_text,
            "\n".join(f"- {t}" for t in new_texts),
            json.dumps(merged, ensure_ascii=False),
            "\n".join(f"- {m}" for m in missing) or "（无）",
            "\n".join(f"- {u}" for u in unsupported) or "（无）",
            str(check.get("topic_drift", False)),
            str(asset_type_mismatch),
            suggested_asset_type or "（无）",
            "\n".join(f"- {item}" for item in check.get("context_dependent_claims", []))
            or "（无）",
            "\n".join(f"- {item}" for item in check.get("relative_time_references", []))
            or "（无）",
            str(check.get("reusable_value", True)),
            check.get("rationale", "") or "（无）",
            language=("中文" if detect_dominant_language(old_text, *new_texts) == "zh" else "英文"),
        ),
        MERGE_JSON_SCHEMA,
    )
    repaired = normalize_merged_crystal(repaired, max_text_chars=max_text_chars)
    repaired_check = judge_retention(
        llm_fn,
        old_text=old_text,
        old_facets=old_facets,
        old_asset=old_asset,
        new_texts=new_texts,
        merged=repaired,
    )
    repaired_check["repaired"] = True
    relaxed_pass = (
        not repaired_check.get("unsupported_claims")
        and not repaired_check.get("topic_drift")
        and repaired_check.get("reusable_value", True)
        and not repaired_check.get("context_dependent_claims")
        and not repaired_check.get("relative_time_references")
        and len(repaired_check.get("missing_important_claims", []))
        <= _RETENTION_MISSING_TOLERANT * 2
    )
    if not relaxed_pass:
        raise ValueError(
            "retention judge failed after repair: " + json.dumps(repaired_check, ensure_ascii=False)
        )
    repaired_check["passed"] = True
    return repaired, repaired_check
