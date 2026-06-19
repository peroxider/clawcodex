"""Templates service layer (F-85 first iteration).

This package provides a thin service layer for reusable agent
configuration templates. The full CCB parity surface — CLI commands,
``agent: <template_id>`` parsing inside agent definitions, and built-in
defaults — lands in later rounds. This first iteration ships the
service primitives so the rest of the codebase can adopt templates
without a big-bang refactor:

* :mod:`models` — :class:`Template` dataclass with strict validation
  and ``to_dict`` / ``from_dict`` round-trip.
* :mod:`registry` — :class:`TemplateRegistry` for in-memory storage
  with optional disk discovery.
* :mod:`resolver` — :class:`TemplateResolver` for merging a base
  template with an inline override (deep dict merge, list-replace
  policy, shadow-key tracking).
* :mod:`persistence` — :class:`TemplateStateFile` with atomic save /
  load of the full registry, plus convenience helpers.

The layer deliberately has no upstream dependencies on
:mod:`src.agent` — the dataclass model is field-driven and
permission-mode / effort / etc. are passed through as opaque strings
or values, leaving the agent integration glue for a follow-up round.
"""

from __future__ import annotations

from .exceptions import (
    TemplateAlreadyExistsError,
    TemplateCorruptError,
    TemplateNotFoundError,
    TemplateResolutionError,
    TemplateValidationError,
    TemplatesError,
)
from .models import Template
from .persistence import (
    TemplateStateFile,
    load_registry,
    merge_registries,
    save_registry,
)
from .registry import TemplateRegistry
from .resolver import ResolvedTemplate, TemplateResolver

__all__ = [
    "ResolvedTemplate",
    "Template",
    "TemplateAlreadyExistsError",
    "TemplateCorruptError",
    "TemplateNotFoundError",
    "TemplateRegistry",
    "TemplateResolutionError",
    "TemplateResolver",
    "TemplateStateFile",
    "TemplateValidationError",
    "TemplatesError",
    "load_registry",
    "merge_registries",
    "save_registry",
]