"""Facade — hooks/shell_invocation.py — sys.modules swap.

The test suite reaches into this module's namespace via
``monkeypatch.setattr("src.hooks.shell_invocation.shutil.which", ...)``
on every PowerShell-path test (TestFindPowerShellPath /
TestExecutorPowerShellPath). A star-import facade would lose the patch:
``shutil`` is not in ``__all__``, and the underlying call site in
``clawcodex_ext.hooks.shell_invocation`` would still resolve
``shutil.which`` against the ext module's globals — the patch would
land on the facade and the function would call the real one.

``sys.modules`` swap makes ``src.hooks.shell_invocation`` literally
the same module object as ``clawcodex_ext.hooks.shell_invocation``,
so string-path patches reach the real binding.
"""

from __future__ import annotations

import importlib
import sys

_ext_mod = importlib.import_module("clawcodex_ext.hooks.shell_invocation")
sys.modules[__name__] = _ext_mod
