from __future__ import annotations

import pytest

from clawcodex_ext.services.pipe_ipc import PipeJsonCodec, PipeMessage, PipeMessageType, decode_message, encode_message


def test_encode_message_uses_jsonl() -> None:
    msg = PipeMessage(type=PipeMessageType.BROADCAST, source_id="alice", payload={"text": "hi"})

    raw = encode_message(msg)

    assert raw.endswith(b"\n")
    restored = decode_message(raw)
    assert restored.type is PipeMessageType.BROADCAST
    assert restored.payload == {"text": "hi"}


@pytest.mark.parametrize("raw", [b"not-json", b"[1, 2, 3]", b"null"])
def test_decode_rejects_invalid_or_non_object_json(raw: bytes) -> None:
    with pytest.raises(ValueError):
        PipeJsonCodec.decode_message(raw)


def test_decode_rejects_unknown_message_type() -> None:
    with pytest.raises(ValueError, match="Invalid PipeMessage type"):
        decode_message(b'{"type":"unknown","source_id":"alice"}\n')


def test_decode_rejects_non_object_payload() -> None:
    with pytest.raises(ValueError, match="payload"):
        decode_message(b'{"type":"reply","source_id":"alice","payload":[]}\n')
