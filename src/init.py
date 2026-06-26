"""Bootstrap init — facade re-export.

The implementation has moved to ``clawcodex_ext/init.py``. We re-export
the public symbols by direct import so callers continue to write
``from src.init import init`` (the legacy entry point used by REPL,
headless, bridge, TUI, SDK, and CLI).

The @cache-wrapped ``init`` travels as a single object — direct
re-export keeps the cached function identity intact, which is required
by ``reset_init_for_test_only`` (it calls ``init.cache_clear()``).
A lazy ``__getattr__`` proxy would also work, but a direct import is
cheaper (one line, no attribute lookup at call time) and leaves no
room for identity drift between src/ and clawcodex_ext/.
"""

from clawcodex_ext.init import (  # noqa: F401 — public re-export
    init,
    run_pre_action,
    reset_init_for_test_only,
)

__all__ = ['init', 'run_pre_action', 'reset_init_for_test_only']
