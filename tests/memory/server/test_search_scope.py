from __future__ import annotations

import unittest
from typing import Any

from clawcodex_ext.latent_memory.server.schemas import SearchRequest
from clawcodex_ext.latent_memory.server.service import MemoryService, MissingMemoryScopeError


class RecordingBackend:
    ready = True

    def __init__(self) -> None:
        self.requests: list[SearchRequest] = []

    def search_memories(self, request: SearchRequest) -> dict[str, list[Any]]:
        self.requests.append(request)
        return {"results": []}


class SearchScopeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = RecordingBackend()
        self.service = MemoryService({}, backend=self.backend)

    def test_accepts_user_id_in_filters(self) -> None:
        request = SearchRequest(query="hello", filters={"user_id": "bench-user"})

        result = self.service.search_memories(request)

        self.assertEqual(result, {"results": []})
        self.assertEqual(self.backend.requests, [request])

    def test_rejects_search_without_scope(self) -> None:
        request = SearchRequest(query="hello")

        with self.assertRaises(MissingMemoryScopeError):
            self.service.search_memories(request)

        self.assertEqual(self.backend.requests, [])


if __name__ == "__main__":
    unittest.main()
