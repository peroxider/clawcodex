"""Thin forwarding seam — see :mod:`clawcodex_ext.bridge.repl_bridge_transport`.

P3-out-2: real implementation moved to ``clawcodex_ext/bridge/repl_bridge_transport.py``.
This file now re-exports the public surface so the legacy
``from src.bridge.repl_bridge_transport import ...`` path (upstream
snapshots under ``src/upstream/*`` and tests) continues to work.
"""
from clawcodex_ext.bridge.repl_bridge_transport import *  # noqa: F401,F403
