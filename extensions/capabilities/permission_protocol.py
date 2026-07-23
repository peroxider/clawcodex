"""PermissionContext Protocol — minimal boundary for SOP permission checks.

Mirrors the field subset that the SOP converter — specifically
``sop_exploration_guard`` — consumes today. The default adapter wraps
``clawcodex_ext.permissions.types.ToolPermissionContext`` (which
implements the same shape).

Field names follow the short aliases in
``docs/DECOUPLE_SOP_CONVERTER_PLAN.md`` §3.3:

* ``mode`` — current :class:`clawcodex_ext.permissions.types.PermissionMode` value.
* ``is_bypass`` — whether ``bypassPermissions`` may be selected. Maps to the
  upstream ``is_bypass_permissions_mode_available``.
* ``should_avoid_prompts`` — UI hint: do not show interactive prompts.
  Maps to the upstream ``should_avoid_permission_prompts``.
* ``blocks(tool_name)`` — predicate used by SOP exploration guards.

The shorter field names keep the Protocol surface compact; concrete
adapted instances (Phase 3+) expose ``is_bypass`` as a property that
reads ``is_bypass_permissions_mode_available``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["PermissionContextProtocol"]


PermissionModeLiteral = str


@runtime_checkable
class PermissionContextProtocol(Protocol):
    """Minimal contract for an SOP-visible permission context.

    Implementations MUST expose:

    * ``mode`` — current permission mode (``"default" | "plan" |
      "acceptEdits" | "bypassPermissions" | "dontAsk" | "auto" |
      "bubble"``).
    * ``is_bypass`` — ``True`` when ``bypassPermissions`` may be
      selected without a policy hook blocking it.
    * ``should_avoid_prompts`` — ``True`` when the agent should not
      surface interactive permission prompts.
    * ``blocks(tool_name)`` — predicate returning ``True`` when the
      named tool is on an ``always-deny`` list.
    """

    mode: PermissionModeLiteral
    is_bypass: bool
    should_avoid_prompts: bool

    def blocks(self, tool_name: str) -> bool: ...
