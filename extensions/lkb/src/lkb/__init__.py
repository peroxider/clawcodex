"""Persistent Plan Graph extension for ClawCodex.

Runtime integrations import the focused submodules directly.  Keeping the
package root intentionally empty prevents importing retired sidecar, solver,
and decomposition implementations as a side effect of ``import lkb``.
"""

__all__: list[str] = []
