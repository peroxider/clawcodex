"""Skill + Frontmatter Protocols — interface for SOP-convertible skills.

Two Protocols serve the SOP converter surface:

* :class:`SkillProtocol` — mirrors ``clawcodex_ext.skills.model.Skill``,
  the loader-side dataclass for parsed skill markdown. The SOP
  converter consumes the field subset listed in
  ``docs/DECOUPLE_SOP_CONVERTER_PLAN.md`` §3.3; non-essential fields
  remain optional and use ``| None`` for duck-typed compatibility.
* :class:`SkillFrontmatterProtocol` — the ``parse_frontmatter`` boundary
  used by both ``bundle_agents.py`` and ``bundle_skills.py``. The
  returned :class:`SkillFrontmatterResultProtocol` keeps the
  ``(frontmatter, body)`` tuple shape of
  ``clawcodex_ext.skills.frontmatter.FrontmatterParseResult`` so callers
  can read either ``.frontmatter`` (dict) or ``.body`` (str) without
  caring about the concrete dataclass.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Protocol, runtime_checkable

__all__ = [
    "SkillProtocol",
    "SkillFrontmatterProtocol",
    "SkillFrontmatterResultProtocol",
]


@runtime_checkable
class SkillProtocol(Protocol):
    """Protocol for a parsed skill that the SOP converter can read.

    Field names align 1:1 with ``clawcodex_ext.skills.model.Skill`` so
    runtime ``isinstance(x, SkillProtocol)`` checks pass without an
    adapter. Optional fields stay optional — the SOP converter rarely
    needs ``hooks`` / ``shell`` / ``progress_message``, but
    ``bundle_skills`` may forward them through.
    """

    name: str
    description: str
    content: str
    source: str
    loaded_from: str
    user_invocable: bool
    disable_model_invocation: bool
    content_length: int
    is_hidden: bool
    skill_root: Optional[str]
    aliases: list[str]
    allowed_tools: list[str]
    argument_hint: Optional[str]
    argument_names: list[str]
    when_to_use: Optional[str]
    version: Optional[str]
    model: Optional[str]
    context: str
    agent: Optional[str]
    effort: Optional[str | int]
    paths: Optional[list[str]]
    display_name: Optional[str]
    has_user_specified_description: bool
    base_dir: Optional[str]
    markdown_content: str
    progress_message: str
    hooks: Optional[dict]
    shell: Optional[str]
    get_prompt_for_command: Optional[Callable[[str], str]]
    is_enabled_fn: Optional[Callable[[], bool]]

    def user_facing_name(self) -> str: ...

    def get_prompt(self, args: str = "") -> str: ...

    def is_enabled(self) -> bool: ...


@runtime_checkable
class SkillFrontmatterResultProtocol(Protocol):
    """Result of parsing a markdown frontmatter block.

    Mirrors the shape of
    ``clawcodex_ext.skills.frontmatter.FrontmatterParseResult`` while
    staying duck-typed — concrete implementations may be the upstream
    dataclass or any object exposing ``.frontmatter`` / ``.body``.
    """

    frontmatter: dict[str, Any]
    body: str


@runtime_checkable
class SkillFrontmatterProtocol(Protocol):
    """Frontmatter parser boundary used by ``bundle_agents`` / ``bundle_skills``.

    Implementations MUST return a value exposing ``.frontmatter`` (dict)
    and ``.body`` (str). The default implementation wraps
    ``clawcodex_ext.skills.frontmatter.parse_frontmatter`` directly.
    """

    def __call__(self, markdown: str) -> SkillFrontmatterResultProtocol: ...
