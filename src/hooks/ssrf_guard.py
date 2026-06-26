"""Facade — hooks/ssrf_guard.py — sys.modules swap.

The test suite uses
``mock.patch("src.hooks.ssrf_guard._resolve_hostname", ...)`` in
``tests/misc/test_ssrf_guard.py::test_dns_resolution_public`` to
control DNS resolution. With a star-import or ``globals().update()``
facade, the patch lands on the facade but the call site inside
``validate_hook_url`` (in ``clawcodex_ext.hooks.ssrf_guard``) would
still resolve ``_resolve_hostname`` from the ext module's globals —
real DNS lookup runs and the assertion fails.

``sys.modules`` swap makes ``src.hooks.ssrf_guard`` literally the
same module object as ``clawcodex_ext.hooks.ssrf_guard``, so the
string-path patch reaches the real binding.
"""

from __future__ import annotations

import importlib
import sys

_ext_mod = importlib.import_module('clawcodex_ext.hooks.ssrf_guard')
sys.modules[__name__] = _ext_mod
