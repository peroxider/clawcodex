"""Facade — hooks/hook_executor.py has been moved to clawcodex_ext/hooks/hook_executor.py.

Uses ``globals().update()`` so the test suite can still import private
helpers (e.g. ``from src.hooks.hook_executor import _run_hooks_for_event``,
``_get_hooks_from_snapshot``, ``_execute_command_hook``, ``_build_hook_env``).
"""

import clawcodex_ext.hooks.hook_executor as _mod

globals().update(vars(_mod))
