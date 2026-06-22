"""Compatibility facade — see :mod:`clawcodex_ext.services.chrome.recording`.

Module-identity swap. ``tests/services/chrome/test_recording.py``
patches ``_try_import_pillow`` on the
``src.services.chrome.recording`` module object (e.g.
``monkeypatch.setattr(rec_module, "_try_import_pillow", ...)``).
The canonical implementation is registered under the legacy
import path via ``sys.modules`` so those patches take effect
on the real module.
"""

from __future__ import annotations

import sys

from clawcodex_ext.services.chrome import recording as _recording

sys.modules[__name__] = _recording

__all__ = getattr(_recording, "__all__", [])
