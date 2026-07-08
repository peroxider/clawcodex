"""Stable canonical hashing for Logical Kanban IR.

Hashes cover the canonical JSON serialization of the IR, not any presentation
formatting.  The JSON is sorted by key and array order is preserved because the
IR itself is already canonical (variable order and argument order are part of
the logical statement).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .ir import CanonicalAssertion


def canonical_json(value: Any) -> str:
    """Return a stable, sorted JSON string for any JSON-serializable value."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def canonical_hash(value: Any, *, algorithm: str = "sha256") -> str:
    """Return ``algorithm:hexdigest`` for the canonical JSON of ``value``."""
    payload = canonical_json(value).encode("utf-8")
    if algorithm == "sha256":
        return f"sha256:{hashlib.sha256(payload).hexdigest()}"
    if algorithm == "sha512":
        return f"sha512:{hashlib.sha512(payload).hexdigest()}"
    raise ValueError(f"Unsupported hash algorithm: {algorithm}")


def assertion_hash(assertion: CanonicalAssertion, *, algorithm: str = "sha256") -> str:
    """Stable hash of a CanonicalAssertion based on its canonical JSON."""
    return canonical_hash(assertion.to_dict(), algorithm=algorithm)


__all__ = [
    "assertion_hash",
    "canonical_hash",
    "canonical_json",
]
