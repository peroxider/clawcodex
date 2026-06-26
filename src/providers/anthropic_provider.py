"""Facade — providers/anthropic_provider.py — sys.modules swap.

The real implementation now lives in
``clawcodex_ext.providers.anthropic_provider`` (containing both
``AnthropicProvider`` and ``ClawcodexAnthropicProvider``).  This
module is kept as a ``sys.modules`` swap so:

* String-path test patches such as
  ``@patch("src.providers.anthropic_provider.anthropic.Anthropic")``
  resolve to the same module object as the canonical
  ``clawcodex_ext.providers.anthropic_provider`` and land on the
  real PEP 562 ``__getattr__`` / ``_F99_READ_TIMEOUT`` binding.
* Private symbols re-exported by tests (e.g.
  ``from src.providers.anthropic_provider import _F99_READ_TIMEOUT``)
  continue to work.
* ``from src.providers.anthropic_provider import AnthropicProvider``
  used by 27 test files keeps working.
* The lazy provider registration
  (``src.providers.get_provider_class`` returns ``AnthropicProvider``)
  still resolves to the real class.

A ``globals().update(vars(_mod))`` facade would lose the test
``@patch`` target (string-path patches look up the attribute on the
module object they were given — a re-exported binding through
``globals().update`` is not the same object the patch is trying to
replace).  ``sys.modules`` swap makes the two module identities
literally identical, which is the only reliable fix here.
"""

from __future__ import annotations

import importlib
import sys

_ext_mod = importlib.import_module('clawcodex_ext.providers.anthropic_provider')
sys.modules[__name__] = _ext_mod
