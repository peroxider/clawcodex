"""Content normalization and content_hash.

content_hash decides two things:
  1. Idempotency -- no new revision is produced when the input is unchanged, so crystallization
     runs can safely be retried
  2. Saving embeddings -- if the hash is unchanged, neither the body nor the structure moved,
     so projections can skip recomputation

Normalization must be deterministic: the same semantic content must always produce the same
hash regardless of dict key order or list order (for unordered sets). Otherwise idempotency
fails and the ledger accumulates meaningless revisions.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# Asset fields participating in the hash. When adding a new field, it must be listed here too,
# otherwise field changes will not trigger a new revision.
_ASSET_HASH_KEYS = (
    "claim",
    "subject",
    "predicate",
    "object",
    "conditions",
    "steps",
    "relations",
    "valid_from",
    "valid_to",
    "applicability",
)

# Semantically unordered list fields in asset: sort before hashing to avoid false revisions
# caused by jitter in the LLM output order
_ASSET_UNORDERED_KEYS = frozenset({"conditions", "relations"})


def _canonical_scalar(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    return str(value).strip()


def canonical_asset(asset: Any) -> dict[str, Any]:
    """Converge asset into a dict with a fixed key set and fixed order."""
    source = asset if isinstance(asset, dict) else {}
    result: dict[str, Any] = {}
    for key in _ASSET_HASH_KEYS:
        value = source.get(key)
        if key == "applicability":
            applicability = value if isinstance(value, dict) else {}
            result[key] = {
                field: sorted(
                    {
                        str(item).strip()
                        for item in applicability.get(field, [])
                        if str(item).strip()
                    }
                )
                for field in (
                    "applies_when",
                    "does_not_apply_when",
                    "known_exceptions",
                )
            }
            continue
        if isinstance(value, (list, tuple)):
            items = [str(item).strip() for item in value if str(item).strip()]
            # steps are ordered (step order is meaning), conditions / relations are unordered
            result[key] = sorted(items) if key in _ASSET_UNORDERED_KEYS else items
        else:
            result[key] = _canonical_scalar(value)
    return result


def canonical_facets(facets: Any) -> dict[str, list[str]]:
    """Converge facets into a dict with stable key order and deduplicated, sorted values."""
    source = facets if isinstance(facets, dict) else {}
    result: dict[str, list[str]] = {}
    for key in sorted(str(k) for k in source):
        value = source.get(key)
        if isinstance(value, str):
            values = [value]
        elif isinstance(value, (list, tuple)):
            values = list(value)
        else:
            values = []
        seen: set[str] = set()
        items: list[str] = []
        for item in values:
            text = str(item).strip()
            marker = text.lower()
            if text and marker not in seen:
                seen.add(marker)
                items.append(text)
        result[key] = sorted(items)
    return result


def content_hash(body: str, asset: Any, facets: Any) -> str:
    """Normalize (body, asset, facets) then take sha256.

    Deliberately excludes confidence / source_ids / timestamps:
    absorb often just appends sources to source_ids without changing the body or structure,
    in which case the hash should stay the same to skip embedding recomputation. Changes to
    source_ids are themselves recorded by the rev_id.
    """
    payload = {
        "body": str(body or "").strip(),
        "asset": canonical_asset(asset),
        "facets": canonical_facets(facets),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
