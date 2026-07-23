"""Default adapters for :class:`SkillProtocol` and :class:`SkillFrontmatterProtocol`.

Wraps ``clawcodex_ext.skills.model.Skill`` as a factory function and
``clawcodex_ext.skills.frontmatter.parse_frontmatter`` as a callable
so the SOP converter can work with skills without importing
``clawcodex_ext`` directly.

Field names are 1:1 between the upstream dataclass and the Protocol,
so no property aliasing is needed.

See ``docs/DECOUPLE_SOP_CONVERTER_PLAN.md`` §3.4.
"""

from __future__ import annotations

from typing import Any

from extensions.capabilities.skill_protocol import (
    SkillFrontmatterProtocol,
    SkillFrontmatterResultProtocol,
    SkillProtocol,
)

__all__ = [
    "default_skill_factory",
    "default_frontmatter_parser",
]


def default_skill_factory(**kwargs: Any) -> SkillProtocol:
    """Construct a ``Skill``-compatible instance.

    Accepts the same keyword arguments as
    ``clawcodex_ext.skills.model.Skill``.

    All keyword arguments are forwarded verbatim; the upstream dataclass
    field names match the Protocol exactly.
    """
    from clawcodex_ext.skills.model import Skill

    return Skill(**kwargs)


class _FrontmatterWrapper:
    """Wraps ``parse_frontmatter`` as a ``SkillFrontmatterProtocol``.

    The upstream ``FrontmatterParseResult`` dataclass already exposes
    ``.frontmatter`` (dict) and ``.body`` (str), so it trivially
    satisfies ``SkillFrontmatterResultProtocol`` at runtime without
    an adapter.
    """

    def __call__(self, markdown: str) -> SkillFrontmatterResultProtocol:
        from clawcodex_ext.skills.frontmatter import parse_frontmatter

        return parse_frontmatter(markdown)  # type: ignore[return-value]


default_frontmatter_parser: SkillFrontmatterProtocol = _FrontmatterWrapper()
"""Default frontmatter parser singleton.

Usage::

    result = default_frontmatter_parser(markdown_text)
    frontmatter = result.frontmatter  # dict
    body = result.body               # str
"""