"""Generic section builder registry for system prompt assembly.

Generalises the ``register_memory_section_builder`` pattern so that every
section (7 static + 11 dynamic) can be overridden or extended by downstream
code without modifying ``prompt_assembly.py``.

Provides the low-level builder registry (P119-A) and the high-level
override API (P119-B): ``override_section``, ``disable_section``,
``insert_section``.
"""

from __future__ import annotations

from enum import Enum
from typing import Callable, Protocol

from clawcodex_ext.context_system.system_prompt_cache import (
    CacheScope,
    DANGEROUS_uncachedSystemPromptSection,
    SystemPromptSection,
    system_prompt_section,
)


class SectionScope(str, Enum):
    """Cache scope for a section builder registration.

    Mirrors the values of ``CacheScope`` from
    ``clawcodex_ext.context_system.system_prompt_cache``, but is defined
    independently here to avoid a circular dependency at import time.
    """
    GLOBAL = "global"
    SESSION = "session"
    REQUEST = "request"


class SectionBuilder(Protocol):
    """A callable that builds a :class:`SystemPromptSection` or returns ``None``.

    Builders are called with no arguments.  Returning ``None`` signals
    "no override — use the default section", allowing the next builder
    (or the default) to be tried.
    """
    def __call__(self) -> "SystemPromptSection | None": ...


# ---------------------------------------------------------------------------
# Canonical section metadata (order, scope) for all 18 known sections.
# ---------------------------------------------------------------------------

_SECTION_ORDER: dict[str, int] = {
    # Static modules (0-6)
    "intro": 0,
    "system": 1,
    "doing_tasks": 2,
    "actions": 3,
    "using_tools": 4,
    "tone_style": 5,
    "output_efficiency": 6,
    # Dynamic modules (10-90)
    "tool_docs": 10,
    "environment": 20,
    "memory": 25,
    "mcp": 30,
    "agents": 40,
    "skills": 50,
    "output_style": 60,
    "proactive": 65,
    "plan_mode": 70,
    "non_interactive": 80,
    "tool_restrictions": 90,
    "iteration_meta": 95,
}

_SECTION_SCOPE: dict[str, SectionScope] = {
    "intro": SectionScope.GLOBAL,
    "system": SectionScope.GLOBAL,
    "doing_tasks": SectionScope.GLOBAL,
    "actions": SectionScope.GLOBAL,
    "using_tools": SectionScope.GLOBAL,
    "tone_style": SectionScope.GLOBAL,
    "output_efficiency": SectionScope.GLOBAL,
    "tool_docs": SectionScope.SESSION,
    "environment": SectionScope.REQUEST,
    "memory": SectionScope.REQUEST,
    "mcp": SectionScope.SESSION,
    "agents": SectionScope.SESSION,
    "skills": SectionScope.SESSION,
    "output_style": SectionScope.SESSION,
    "proactive": SectionScope.REQUEST,
    "plan_mode": SectionScope.REQUEST,
    "non_interactive": SectionScope.REQUEST,
    "tool_restrictions": SectionScope.REQUEST,
    "iteration_meta": SectionScope.REQUEST,
}


def get_section_order(section_id: str) -> int:
    """Return the canonical order for a known section, or 0 for unknown."""
    return _SECTION_ORDER.get(section_id, 0)


def get_section_scope(section_id: str) -> SectionScope:
    """Return the canonical scope for a known section, or SESSION for unknown."""
    return _SECTION_SCOPE.get(section_id, SectionScope.SESSION)


# ---------------------------------------------------------------------------
# Registry: section_id → list[SectionBuilder]
# ---------------------------------------------------------------------------

_section_builders: dict[str, list[SectionBuilder]] = {}


def register_section_builder(
    section_id: str,
    builder: SectionBuilder,
) -> None:
    """Register a section builder for *section_id*.

    Multiple builders can be registered for the same section; they are
    consulted in registration order and the first non-``None`` result
    wins.  This is the same semantics as the existing
    ``register_memory_section_builder``.

    The canonical order and scope are derived from the internal
    ``_SECTION_ORDER`` and ``_SECTION_SCOPE`` mappings — the caller does
    not need to specify them.
    """
    _section_builders.setdefault(section_id, []).append(builder)


def consult_section_builders(
    section_id: str,
) -> "SystemPromptSection | None":
    """Consult registered builders for *section_id*.

    Builders are called in registration order.  The first non-``None``
    result is returned.  If no builder is registered, or all return
    ``None``, returns ``None`` — the caller should fall back to its
    default section.
    """
    builders = _section_builders.get(section_id)
    if builders is None:
        return None
    for builder in builders:
        result = builder()
        if result is not None:
            return result
    return None


# ---------------------------------------------------------------------------
# Inserted sections — new sections injected between known sections (P119-B).
# ---------------------------------------------------------------------------

_inserted_sections: list["SystemPromptSection"] = []


def register_inserted_section(section: "SystemPromptSection") -> None:
    """Register a new section to be inserted into the prompt.

    Unlike :func:`register_section_builder` which overrides an existing
    slot, this adds a brand-new section with a custom id and order. The
    section is appended to the prompt after all known sections are built,
    and sorted by order alongside them.
    """
    _inserted_sections.append(section)


def get_inserted_sections() -> list["SystemPromptSection"]:
    """Return all registered inserted sections.

    The caller should append these to the sections list before sorting.
    """
    return list(_inserted_sections)


def clear_section_registry() -> None:
    """Clear all registered builders and inserted sections.

    Primarily used in tests to ensure clean state between test cases.
    """
    _section_builders.clear()
    _inserted_sections.clear()


def _clear_builders_for(section_id: str) -> None:
    """Remove all builders registered for *section_id*.

    Used by the override API (P119-B) to ensure that ``override_section``
    and ``disable_section`` take highest priority — they clear any
    previously registered builders before registering their own.
    """
    _section_builders.pop(section_id, None)


# ---------------------------------------------------------------------------
# High-level override / insert / disable API (P119-B)
# ---------------------------------------------------------------------------

#: Sentinel content value for disabled sections.  When
#: ``consult_section_builders`` returns a section with this as content,
#: the caller treats it as ``None`` (section suppressed).
_DISABLE_SENTINEL = ""


def _to_cache_scope(scope: SectionScope) -> CacheScope:
    """Convert a :class:`SectionScope` to the equivalent :class:`CacheScope`."""
    return CacheScope(scope.value)


def override_section(
    section_id: str,
    content: str,
    *,
    cache_scope: CacheScope | None = None,
    order: int | None = None,
    reason: str = "downstream override",
) -> SystemPromptSection:
    """Replace the content of *section_id* with *content*.

    The section is built as *cache-breaking* (recomputed every turn) to
    prevent stale cached content from leaking through.  The override is
    registered via the generic section builder registry and takes effect
    on the next ``build_full_system_prompt`` call.

    The *reason* parameter is required by the
    ``DANGEROUS_uncachedSystemPromptSection`` factory — it forces code
    review to acknowledge that a cache break is being introduced.

    Returns the created :class:`SystemPromptSection` so callers can
    inspect or chain it.
    """
    canonical_order = order if order is not None else get_section_order(section_id)
    canonical_scope = get_section_scope(section_id)

    section = DANGEROUS_uncachedSystemPromptSection(
        name=section_id,
        content=content,
        reason=reason,
        cache_scope=cache_scope or _to_cache_scope(canonical_scope),
        order=canonical_order,
    )
    # P119-B: override takes highest priority — clear any previously
    # registered builders for this section before registering ours.
    _clear_builders_for(section_id)
    register_section_builder(section_id, lambda: section)
    # P119-F: immediately invalidate the cache for this section so the
    # override takes effect on the very next build.  Only invalidate(id)
    # is needed — the build path checks cache first, and a cache miss
    # causes it to consult builders (which will find the override).
    from clawcodex_ext.context_system.prompt_assembly import get_system_prompt_cache

    get_system_prompt_cache().invalidate(section_id)
    return section


def disable_section(section_id: str) -> None:
    """Suppress *section_id* from the prompt.

    Registers a builder that returns a section with empty content.  When
    ``consult_section_builders`` returns a non-``None`` section whose
    ``content`` is empty, the caller treats it as disabled (same as if
    the section returned ``None``).

    Note: this only works because the assembly layer filters out sections
    with falsy ``content`` via ``if s.content`` guards.
    """
    canonical_order = get_section_order(section_id)
    canonical_scope = get_section_scope(section_id)

    disabled = system_prompt_section(
        name=section_id,
        content=_DISABLE_SENTINEL,
        cache_scope=_to_cache_scope(canonical_scope),
        order=canonical_order,
    )
    # P119-B: disable takes highest priority — clear any previously
    # registered builders for this section before registering ours.
    _clear_builders_for(section_id)
    register_section_builder(section_id, lambda: disabled)
    # P119-F: invalidate cache so the disable takes effect immediately.
    from clawcodex_ext.context_system.prompt_assembly import get_system_prompt_cache

    get_system_prompt_cache().invalidate(section_id)


def insert_section(
    after_id: str,
    new_id: str,
    content: str,
    *,
    cache_scope: CacheScope = CacheScope.SESSION,
    reason: str = "downstream insertion",
) -> SystemPromptSection:
    """Insert a new section *new_id* after the section *after_id*.

    The new section's order is set to *after_id*'s order + 0.5, so it
    sorts directly after *after_id* in the prompt (all known sections
    use integer orders).

    Unlike ``override_section``, the new section does NOT go through the
    builder registry (it has no corresponding ``_build_*_section``
    function to consult).  Instead, it is stored in the
    ``_inserted_sections`` list and appended by the assembly layer.

    Returns the created :class:`SystemPromptSection`.
    """
    base_order = get_section_order(after_id)
    new_order = base_order + 0.5

    section = DANGEROUS_uncachedSystemPromptSection(
        name=new_id,
        content=content,
        reason=reason,
        cache_scope=cache_scope,
        order=new_order,
    )
    register_inserted_section(section)
    return section