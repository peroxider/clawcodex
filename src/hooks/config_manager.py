"""Facade — hooks/config_manager.py has been moved to clawcodex_ext/hooks/config_manager.py.

Uses ``globals().update()`` so the test suite can still import private
helpers (e.g. ``from src.hooks.config_manager import _parse_hook_config``).
"""

import clawcodex_ext.hooks.config_manager as _mod

globals().update(vars(_mod))
