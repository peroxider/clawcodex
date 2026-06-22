"""Compatibility facade — see :mod:`clawcodex_ext.services.chrome.factory`.

Module-identity swap. Tests in ``tests/services/chrome/test_factory.py``
and ``test_chrome_tools.py`` grab ``src.services.chrome.factory`` via
``import ... as factory_module`` and patch private helpers such as
``_get_or_build_controller`` / ``_build_playwright_controller`` on
that module object. To keep those patches effective without
rewriting the tests, the canonical implementation is also
registered under the legacy import path via ``sys.modules``.
"""

from __future__ import annotations

import sys

from clawcodex_ext.services.chrome import factory as _factory

sys.modules[__name__] = _factory

__all__ = getattr(_factory, "__all__", [])
