"""Templates service-layer exceptions."""

from __future__ import annotations


class TemplatesError(RuntimeError):
    """Base error for templates operations."""


class TemplateNotFoundError(TemplatesError):
    """Raised when a named template cannot be located in the registry."""


class TemplateAlreadyExistsError(TemplatesError):
    """Raised when registering a template id that is already present."""


class TemplateValidationError(TemplatesError):
    """Raised when a template payload fails domain validation.

    Distinct from a generic ``ValueError`` raised by ``__post_init__``:
    this is raised when a template is added to a registry or stored on
    disk in a state that violates the contracts documented in the plan.
    """


class TemplateCorruptError(TemplatesError):
    """Raised when a template file cannot be parsed on load.

    Triggered by malformed YAML, missing required keys, or a from_dict
    payload that fails strict validation. The original parse error is
    chained via ``__cause__`` so callers can surface it.
    """


class TemplateResolutionError(TemplatesError):
    """Raised when a resolver cannot reconcile a base + override pair.

    Example: an override references a field that is not declared by the
    base template, or the merge produces an inconsistent type (e.g.
    overriding a string with a dict).
    """