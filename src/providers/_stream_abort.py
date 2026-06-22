"""Facade — providers/_stream_abort.py has been moved to clawcodex_ext/providers/_stream_abort.py.

Uses ``globals().update()`` so the test suite can still import private
helpers (e.g. ``from src.providers._stream_abort import
StreamAbortGuard, _close_response_safely``).
"""

import clawcodex_ext.providers._stream_abort as _mod

globals().update(vars(_mod))