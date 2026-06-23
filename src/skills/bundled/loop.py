"""Facade — src/skills/bundled/loop.py has been moved to clawcodex_ext/skills/bundled/loop.

Re-exports so ``from src.skills.bundled.loop import ...`` callers keep working.
"""

from clawcodex_ext.skills.bundled.loop import (  # noqa: F401
    ParsedLoopArgs,
    parse_loop_args,
)
