"""Facade — services/compact/* moved to clawcodex_ext/services/compact/.

The full compact pipeline machinery (``CompressionPipeline``,
``apply_tool_result_budget``, ``snip_compact``, ``ContextCollapseStore``,
``auto_compact_if_needed``, etc.) now lives in
:mod:`clawcodex_ext.services.compact`. This module re-exports it
verbatim so existing ``from src.services.compact import ...`` callers
keep working.
"""

from clawcodex_ext.services.compact import *  # noqa: F401,F403
