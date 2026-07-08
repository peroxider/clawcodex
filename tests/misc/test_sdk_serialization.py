"""Tests for SDK wrapper result serialization."""

from __future__ import annotations

import dataclasses
import json
import unittest

from extensions.sop_converter.sdk_serialization import dumps_sdk_result, to_jsonable


@dataclasses.dataclass
class _DemoConfig:
    name: str
    count: int = 0


class TestSdkSerialization(unittest.TestCase):
    def test_dataclass_to_jsonable(self) -> None:
        payload = to_jsonable(_DemoConfig(name="verify-bot", count=2))
        self.assertEqual(payload, {"name": "verify-bot", "count": 2})

    def test_dumps_sdk_result_is_valid_json(self) -> None:
        raw = dumps_sdk_result(_DemoConfig(name="x"))
        parsed = json.loads(raw)
        self.assertEqual(parsed["name"], "x")

    def test_pydantic_model_dump_when_available(self) -> None:
        try:
            from pydantic import BaseModel
        except ImportError:
            self.skipTest("pydantic not installed")

        class Card(BaseModel):
            id: str

        payload = to_jsonable(Card(id="verify-bot"))
        self.assertEqual(payload, {"id": "verify-bot"})


if __name__ == "__main__":
    unittest.main()
