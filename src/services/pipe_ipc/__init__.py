"""Facade — services/pipe_ipc/__init__.py has been moved to clawcodex_ext.

Real implementations live in ``clawcodex_ext.services.pipe_ipc``.
Existing ``from src.services.pipe_ipc import …`` call sites continue to
work during the migration.  New code should import from
``clawcodex_ext.services.pipe_ipc`` directly.
"""

from clawcodex_ext.services.pipe_ipc import (  # noqa: F401
    PipeJsonCodec,
    PipeMessage,
    PipeMessageType,
    PipePeer,
    PipePermissionForwarder,
    PipeRegistry,
    UdsPipeClient,
    UdsPipeServer,
    decode_message,
    encode_message,
)

__all__ = [
    "PipeJsonCodec",
    "PipeMessage",
    "PipeMessageType",
    "PipePeer",
    "PipePermissionForwarder",
    "PipeRegistry",
    "UdsPipeClient",
    "UdsPipeServer",
    "decode_message",
    "encode_message",
]
