"""Facade — transports/serial_batch_event_uploader.py has been moved to extensions/ports/transports/.

The full serial batched POST queue with retry/backoff and backpressure now
lives in :mod:`extensions.ports.transports.serial_uploader` (renamed from
``serial_batch_event_uploader.py``). This module re-exports the public
surface so existing
``from src.transports.serial_batch_event_uploader import ...`` callers keep working.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__``.
"""

import extensions.ports.transports.serial_uploader as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
