"""Facade — services/compact/* moved to clawcodex_ext/services/compact/.

The full compact pipeline machinery (``PipelineConfig``,
``run_compact_pipeline``, ``snip_compact``, ``ContextCollapseStore``,
``apply_tool_result_budget``, ``auto_compact``, etc.) now lives in
:mod:`clawcodex_ext.services.compact`. This module re-exports the
``pipeline`` submodule verbatim so existing ``from
src.services.compact.pipeline import ...`` callers keep working.
"""

from clawcodex_ext.services.compact.pipeline import *  # noqa: F401,F403
