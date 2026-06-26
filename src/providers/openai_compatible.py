"""Facade — providers/openai_compatible.py has been moved to clawcodex_ext/providers/openai_compatible.py.

Uses ``globals().update()`` so the test suite can still import private
helpers (e.g. ``from src.providers.openai_compatible import
_convert_anthropic_messages_to_openai``,
``_anthropic_image_block_to_openai``, etc.).
"""

import clawcodex_ext.providers.openai_compatible as _mod

globals().update(vars(_mod))
