"""Facade — hooks/exec_http_hook.py — sys.modules swap.

The test suite uses ``@patch("src.hooks.exec_http_hook.validate_hook_url", ...)``
and ``@patch("src.hooks.exec_http_hook.urlopen")`` decorators on
``TestHttpHookExecutor``. With a star-import facade, the patches
land on the facade but the call site in
``clawcodex_ext.hooks.exec_http_hook`` would still resolve
``validate_hook_url`` and ``urlopen`` against the ext module's
globals — SSRF protection runs against the real network and
``urlopen`` hits the real URL, breaking the test contract.

``sys.modules`` swap makes ``src.hooks.exec_http_hook`` literally
the same module object as ``clawcodex_ext.hooks.exec_http_hook``,
so the patches reach the real bindings.
"""

from __future__ import annotations

import importlib
import sys

_ext_mod = importlib.import_module('clawcodex_ext.hooks.exec_http_hook')
sys.modules[__name__] = _ext_mod
