"""ASCII rendering helpers inlined into the visualizer package.

Private module — not part of the public API. ``extensions.recording``
imports :func:`panel` from here for the asciicast dashboard adapter; the
visualizer's Web UI does not consume this helper at all (it renders
HTML via Jinja2 templates). Keeping the function as a private (``_``)
module makes the cross-package dependency intentional and avoids
advertising it as a stable surface.

Originally this helper lived in :mod:`extensions.recording.renderers`
(``extensions/recording/renderers.py:78-91``). This helper moved here as
part of the visualizer package-extraction effort so the recording
adapter can stay co-located with the recorder while the visualizer
package owns its rendering primitives.
"""

from __future__ import annotations

__all__ = ["panel"]


def panel(title: str, rows: list[str], width: int = 80) -> str:
    """Render a simple ASCII panel for the visualizer adapter.

    Mirrors the layout of the live HTML dashboard (``─`` rules, indented
    rows) using the same vocabulary the orchestrator dashboard already
    prints on the terminal. The visualizer's Web UI does not call this
    helper; only the asciicast dashboard adapter
    (``extensions.recording.visualizer_dashboard_source``) does.
    """
    rule = "─" * max(width, len(title) + 4)
    out = [rule, f"  {title}", rule]
    for row in rows:
        out.append(row)
    out.append(rule)
    return "\n".join(out)