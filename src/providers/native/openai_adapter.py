"""Facade — providers/native/openai_adapter.py has been moved to clawcodex_ext/providers/native/openai_adapter.py.

Uses ``sys.modules`` swap so that
``monkeypatch.setattr("src.providers.native.openai_adapter.OpenAI", ...)``
keeps targeting the real implementation module — the test suite relies
on that string-path monkeypatch to inject a fake SDK without
``openai`` being installed.
"""

from __future__ import annotations

import importlib
import sys

_ext_mod = importlib.import_module("clawcodex_ext.providers.native.openai_adapter")
sys.modules[__name__] = _ext_mod