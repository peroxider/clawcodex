"""Facade — services/pipe_ipc/codec.py has been moved to clawcodex_ext.

Real implementation lives in ``clawcodex_ext.services.pipe_ipc.codec``.
Existing ``from src.services.pipe_ipc.codec import …`` call sites
continue to work during the migration.  New code should import from
``clawcodex_ext.services.pipe_ipc.codec`` directly.
"""

from clawcodex_ext.services.pipe_ipc.codec import (  # noqa: F401
    PipeJsonCodec,
    decode_message,
    encode_message,
)

__all__ = [
    "PipeJsonCodec",
    "decode_message",
    "encode_message",
]
