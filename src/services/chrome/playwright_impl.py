"""Compatibility facade — see :mod:`clawcodex_ext.services.chrome.playwright_impl`.

Module-identity swap. ``tests/services/chrome/test_playwright_impl.py``
patches ``_try_import_playwright`` on the ``src.services.chrome.playwright_impl``
module object directly (e.g. ``monkeypatch.setattr(pw_module,
"_try_import_playwright", lambda: factory)``). The canonical
implementation is registered under the legacy import path via
``sys.modules`` so those patches take effect on the real module.
"""

from __future__ import annotations

import sys

from clawcodex_ext.services.chrome import playwright_impl as _impl

sys.modules[__name__] = _impl

__all__ = getattr(_impl, "__all__", [])
