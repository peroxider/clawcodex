"""Stable canonical hashing for Plan Graph JSON values."""

from __future__ import annotations

import hashlib
import json
from typing import Any


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


__all__ = [
    "canonical_hash",
    "canonical_json",
]
