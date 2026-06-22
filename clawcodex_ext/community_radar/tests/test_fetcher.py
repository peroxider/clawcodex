"""Tests for clawcodex_ext.community_radar.fetcher.

Uses a fake HTTP client so the suite never hits api.github.com.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from clawcodex_ext.community_radar.fetcher import Fetcher
from clawcodex_ext.community_radar.models import WatchSource


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        json_payload: Any = None,
        headers: dict[str, str] | None = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._json_payload = json_payload
        self.headers = headers or {}
        self.text = text

    def json(self) -> Any:
        if self._json_payload is None:
            raise ValueError("no JSON payload configured for this response")
        return self._json_payload


class _FakeClient:
    """Minimal stand-in for ``httpx.Client`` used in tests."""

    def __init__(self, pages: list[list[dict[str, Any]]]) -> None:
        self._pages = pages
        self._call_count = 0
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, *, params=None, headers=None):  # type: ignore[no-untyped-def]
        self._call_count += 1
        self.calls.append({
            "method": method,
            "url": url,
            "params": params or {},
            "headers": headers or {},
        })
        if not self._pages:
            return _FakeResponse(200, json_payload=[])
        page = self._pages.pop(0)
        return _FakeResponse(
            200,
            json_payload=page,
            headers={"ETag": f'W/"etag-{self._call_count}"'},
        )

    def close(self) -> None:  # pragma: no cover - noop
        return None


def _source(name: str = "aider") -> WatchSource:
    return WatchSource.from_dict({"name": name, "repo": "foo/bar"})


def test_fetch_releases_returns_records(tmp_path: Path) -> None:
    pages = [[{
        "tag_name": "v1.0.0",
        "name": "Release v1.0.0",
        "body": "## Added\n- new feature\n",
        "published_at": "2026-06-15T00:00:00Z",
        "html_url": "https://example.com/r1",
        "prerelease": False,
    }]]
    client = _FakeClient(pages)
    fetcher = Fetcher(cache_dir=tmp_path, client=client)
    try:
        releases = fetcher.fetch_releases(_source())
        assert len(releases) == 1
        assert releases[0].tag == "v1.0.0"
    finally:
        fetcher.close()

    # Caches should have been persisted to disk.
    cache = tmp_path / "releases" / "aider.json"
    assert cache.exists()


def test_fetch_releases_paginates_until_short_page(tmp_path: Path) -> None:
    full = [{
        "tag_name": f"v1.0.{i}",
        "name": f"v1.0.{i}",
        "body": "## Added\n- feature\n",
        "published_at": f"2026-06-1{i}T00:00:00Z",
        "html_url": f"https://example.com/{i}",
        "prerelease": False,
    } for i in range(3)]
    # Two pages of 3 → stops because the second page is short.
    pages = [full, [{"tag_name": "v1.0.99"}]]
    client = _FakeClient(pages)
    fetcher = Fetcher(cache_dir=tmp_path, client=client, page_size=3)
    try:
        releases = fetcher.fetch_releases(_source())
        assert len(releases) == 4
    finally:
        fetcher.close()


def test_fetch_releases_respects_tag_filter(tmp_path: Path) -> None:
    payload = [{
        "tag_name": "release-candidate",
        "name": "rc",
        "body": "",
        "published_at": "2026-06-15T00:00:00Z",
        "html_url": "https://example.com/rc",
        "prerelease": True,
    }]
    client = _FakeClient([payload])
    fetcher = Fetcher(cache_dir=tmp_path, client=client, page_size=10)
    try:
        source = WatchSource.from_dict({
            "name": "aider",
            "repo": "foo/bar",
            "release_tag_filter": r"\d+\.\d+\.\d+",
        })
        releases = fetcher.fetch_releases(source)
        assert releases == []  # filtered out by r"\d+\.\d+\.\d+"
    finally:
        fetcher.close()


def test_fetch_swallows_errors_into_result(tmp_path: Path) -> None:
    class _Boom:
        def request(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("network down")

        def close(self) -> None:
            return None

    fetcher = Fetcher(cache_dir=tmp_path, client=_Boom())
    try:
        result = fetcher.fetch(_source())
        assert result.errors
        assert result.releases == []
    finally:
        fetcher.close()


def test_fetch_releases_304_short_circuits(tmp_path: Path) -> None:
    """A 304 response should stop pagination and return cached cursor."""
    client = _FakeClient([])
    client.request = lambda *a, **kw: _FakeResponse(304, headers={})  # type: ignore[assignment]
    fetcher = Fetcher(cache_dir=tmp_path, client=client)
    try:
        releases = fetcher.fetch_releases(_source())
        assert releases == []
    finally:
        fetcher.close()


def test_cursors_persisted_across_runs(tmp_path: Path) -> None:
    client = _FakeClient([[{
        "tag_name": "v1.0.0",
        "name": "v1.0.0",
        "body": "",
        "published_at": "2026-06-15T00:00:00Z",
        "html_url": "https://example.com",
        "prerelease": False,
    }]])
    fetcher = Fetcher(cache_dir=tmp_path, client=client)
    try:
        fetcher.fetch_releases(_source())
    finally:
        fetcher.close()

    assert (tmp_path / "cursors.json").exists()
    cursor_data = (tmp_path / "cursors.json").read_text(encoding="utf-8")
    assert "aider" in cursor_data