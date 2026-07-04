"""Facade — transports/websocket_transport.py has been moved to extensions/ports/transports/.

The full reconnecting WebSocket transport for the v1 (Session-Ingress) bridge
path now lives in :mod:`extensions.ports.transports.websocket_v1` (renamed
from ``websocket_transport.py`` to disambiguate from the v2 transport).
This module re-exports the public surface so existing
``from src.transports.websocket_transport import ...`` callers keep working.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__``.
"""

import extensions.ports.transports.websocket_v1 as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
