"""GitHub fetcher for SR-5.1 Community Feature Radar.

Implements the ``Fetcher`` sketched in FEATURE_PLAN.md §10.1.5:

* Pulls Releases / Commits / PullRequests for each :class:`WatchSource`
  via the public GitHub REST API (``api.github.com``).
* Uses ETag / If-None-Match to short-circuit unchanged responses and
  persist cursors under ``cache_dir/cursors.json`` so the next scan
  only downloads what is new.
* Caches full release bodies under ``cache_dir/releases/{source}.json``
  (indefinite TTL — release notes are immutable) and lightweight
  commit / PR caches under ``cache_dir/{commits,prs}/{source}.json``
  with a TTL the caller controls.

The class is deliberately synchronous (httpx.Client) — the cron entry
point runs in a worker thread, and an async client would force every
caller to manage an event loop. A ``httpx`` import failure is handled
gracefully so unit tests can drop in a fake client via ``client=``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import quote

from .models import Commit, FetchResult, PullRequest, Release, WatchSource

_log = logging.getLogger(__name__)


GITHUB_API_ROOT = "https://api.github.com"
DEFAULT_PAGE_SIZE = 30
DEFAULT_REQUEST_TIMEOUT = 15.0  # seconds
DEFAULT_USER_AGENT = "clawcodex-community-radar/0.1"
DEFAULT_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days


# ---------------------------------------------------------------------------
# Cursor store (ETag + last-seen timestamp)
# ---------------------------------------------------------------------------


@dataclass
class _SourceCursor:
    etag: str | None = None
    last_release_published_at: str | None = None


def _load_cursors(cache_dir: Path) -> dict[str, _SourceCursor]:
    path = cache_dir / "cursors.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _log.warning("cursors.json unreadable (%s); ignoring", exc)
        return {}
    cursors: dict[str, _SourceCursor] = {}
    for source, payload in (raw or {}).items():
        if not isinstance(payload, dict):
            continue
        cursors[source] = _SourceCursor(
            etag=payload.get("etag"),
            last_release_published_at=payload.get("last_release_published_at"),
        )
    return cursors


def _save_cursors(cache_dir: Path, cursors: dict[str, _SourceCursor]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        name: {
            "etag": c.etag,
            "last_release_published_at": c.last_release_published_at,
        }
        for name, c in cursors.items()
    }
    (cache_dir / "cursors.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Cache helpers (per-source release bodies)
# ---------------------------------------------------------------------------


def _release_cache_path(cache_dir: Path, source: WatchSource) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", source.name) or "unknown"
    return cache_dir / "releases" / f"{safe}.json"


def _list_cache_path(cache_dir: Path, kind: str, source: WatchSource) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", source.name) or "unknown"
    return cache_dir / kind / f"{safe}.json"


def _read_cached_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_cached_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------


class Fetcher:
    """Pulls incremental upstream data for a list of WatchSources.

    ``client`` accepts an injectable HTTP client so tests can swap in a
    fake. Defaults to :class:`httpx.Client` with a sane User-Agent and
    timeout.
    """

    def __init__(
        self,
        github_token: str | None = None,
        cache_dir: Path | str = ".cache/community-radar",
        *,
        client: Any | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        timeout: float = DEFAULT_REQUEST_TIMEOUT,
        cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        self.github_token = github_token or os.environ.get("GITHUB_TOKEN")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.page_size = page_size
        self.timeout = timeout
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cursors = _load_cursors(self.cache_dir)
        self._owns_client = client is None
        self._client = client or self._build_client()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _build_client(self) -> Any:
        try:
            import httpx  # type: ignore
        except ImportError as exc:  # pragma: no cover - env dep
            raise RuntimeError(
                "httpx is required for the community radar fetcher. "
                "Install it with `pip install httpx`."
            ) from exc
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": DEFAULT_USER_AGENT,
        }
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"
        return httpx.Client(timeout=self.timeout, headers=headers, follow_redirects=True)

    def close(self) -> None:
        if self._owns_client:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001
                pass

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(self, source: WatchSource) -> FetchResult:
        """Fetch everything ``source`` requested. Always returns a result."""
        result = FetchResult(source=source.name)
        try:
            if source.track_releases:
                result.releases = self.fetch_releases(source)
            if source.track_commits:
                result.commits = self.fetch_commits(source)
            if source.track_prs:
                result.prs = self.fetch_prs(source)
        except Exception as exc:  # noqa: BLE001 — log + degrade gracefully
            _log.exception("fetch failed for source %s: %s", source.name, exc)
            result.errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            _save_cursors(self.cache_dir, self._cursors)
        return result

    def fetch_all(self, sources: Iterable[WatchSource]) -> list[FetchResult]:
        return [self.fetch(s) for s in sources]

    # ------------------------------------------------------------------
    # Releases
    # ------------------------------------------------------------------

    def fetch_releases(
        self, source: WatchSource, *, since: str | None = None
    ) -> list[Release]:
        """Fetch releases for ``source``.

        ``since`` is an ISO-8601 lower bound. When omitted the cursor
        stored for the source is used (incremental). On a cold cache the
        function walks pagination until either the first page returns
        304 or ``release_tag_filter`` rejects every release.

        Each release body is persisted to
        ``cache_dir/releases/{source}.json`` keyed by tag so the
        extractor can read bodies without re-hitting GitHub.
        """
        owner, name = source.repo.split("/", 1)
        cache_path = _release_cache_path(self.cache_dir, source)
        cached_bodies = _read_cached_json(cache_path) or {}

        cursor = self._cursors.get(source.name) or _SourceCursor()
        headers: dict[str, str] = {}
        if cursor.etag:
            headers["If-None-Match"] = cursor.etag

        params: dict[str, Any] = {
            "per_page": self.page_size,
            "page": 1,
        }
        if since:
            params["since"] = since
        elif cursor.last_release_published_at:
            # Encourage the API to short-circuit unchanged pages. We
            # still walk pagination because the cursor is per-source,
            # not per-page.
            params["since"] = cursor.last_release_published_at

        url = f"{GITHUB_API_ROOT}/repos/{quote(owner)}/{quote(name)}/releases"
        collected: list[Release] = []
        new_etag: str | None = cursor.etag
        newest_seen_at = cursor.last_release_published_at

        while True:
            response = self._request("GET", url, params=params, headers=headers)
            if response.status_code == 304:
                break
            if response.status_code != 200:
                msg = (
                    f"GitHub releases {response.status_code}: "
                    f"{response.text[:200] if hasattr(response, 'text') else ''}"
                )
                raise RuntimeError(msg)
            new_etag = response.headers.get("ETag", new_etag)
            try:
                payload = response.json()
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"invalid releases JSON: {exc}") from exc
            if not isinstance(payload, list) or not payload:
                break

            for entry in payload:
                if not isinstance(entry, dict):
                    continue
                tag = str(entry.get("tag_name") or "")
                if source.release_tag_filter and tag:
                    if not re.search(source.release_tag_filter, tag):
                        continue
                published_at = entry.get("published_at") or entry.get("created_at")
                body = entry.get("body") or ""
                release = Release(
                    tag=tag,
                    name=str(entry.get("name") or tag),
                    body=body,
                    published_at=published_at,
                    url=str(entry.get("html_url") or ""),
                    is_prerelease=bool(entry.get("prerelease")),
                )
                collected.append(release)
                cached_bodies[tag or release.url] = release.to_dict()
                if published_at and (
                    newest_seen_at is None or published_at > newest_seen_at
                ):
                    newest_seen_at = published_at

            if len(payload) < self.page_size:
                break
            params["page"] = int(params["page"]) + 1
            headers.pop("If-None-Match", None)

        _write_cached_json(cache_path, cached_bodies)
        self._cursors[source.name] = _SourceCursor(
            etag=new_etag,
            last_release_published_at=newest_seen_at,
        )
        # Persist cursors eagerly so callers that only invoke
        # ``fetch_releases`` (e.g. the pipeline tests) still benefit
        # from incremental state across runs.
        _save_cursors(self.cache_dir, self._cursors)
        return collected

    # ------------------------------------------------------------------
    # Commits / PRs (lightweight, optional)
    # ------------------------------------------------------------------

    def fetch_commits(
        self, source: WatchSource, *, since: str | None = None
    ) -> list[Commit]:
        owner, name = source.repo.split("/", 1)
        cache_path = _list_cache_path(self.cache_dir, "commits", source)
        cached = _read_cached_json(cache_path) or {"fetched_at": 0.0, "items": []}
        fetched_at = float(cached.get("fetched_at") or 0.0)
        if (
            not since
            and fetched_at
            and (time.time() - fetched_at) < self.cache_ttl_seconds
        ):
            return [Commit.from_dict(item) for item in cached.get("items", [])]

        params: dict[str, Any] = {"per_page": self.page_size, "page": 1}
        if since:
            params["since"] = since
        url = f"{GITHUB_API_ROOT}/repos/{quote(owner)}/{quote(name)}/commits"
        response = self._request("GET", url, params=params)
        if response.status_code != 200:
            raise RuntimeError(f"GitHub commits {response.status_code}")
        payload = response.json() or []
        commits = [
            Commit(
                sha=str(item.get("sha", "")),
                message=str(
                    (item.get("commit") or {}).get("message") or ""
                ),
                author=((item.get("commit") or {}).get("author") or {}).get("name"),
                committed_at=((item.get("commit") or {}).get("author") or {}).get("date"),
                url=str(item.get("html_url") or ""),
            )
            for item in payload
            if isinstance(item, dict)
        ]
        _write_cached_json(cache_path, {"fetched_at": time.time(), "items": [c.to_dict() for c in commits]})
        return commits

    def fetch_prs(self, source: WatchSource, *, since: str | None = None) -> list[PullRequest]:
        owner, name = source.repo.split("/", 1)
        cache_path = _list_cache_path(self.cache_dir, "prs", source)
        cached = _read_cached_json(cache_path) or {"fetched_at": 0.0, "items": []}
        fetched_at = float(cached.get("fetched_at") or 0.0)
        if (
            not since
            and fetched_at
            and (time.time() - fetched_at) < self.cache_ttl_seconds
        ):
            return [PullRequest.from_dict(item) for item in cached.get("items", [])]

        params: dict[str, Any] = {
            "state": "closed",
            "per_page": self.page_size,
            "page": 1,
            "sort": "updated",
            "direction": "desc",
        }
        if since:
            params["since"] = since
        url = f"{GITHUB_API_ROOT}/repos/{quote(owner)}/{quote(name)}/pulls"
        response = self._request("GET", url, params=params)
        if response.status_code != 200:
            raise RuntimeError(f"GitHub pulls {response.status_code}")
        payload = response.json() or []
        prs = [
            PullRequest(
                number=int(item.get("number") or 0),
                title=str(item.get("title") or ""),
                state=str(item.get("state") or ""),
                merged_at=item.get("merged_at"),
                url=str(item.get("html_url") or ""),
                body=str(item.get("body") or ""),
            )
            for item in payload
            if isinstance(item, dict)
        ]
        _write_cached_json(cache_path, {"fetched_at": time.time(), "items": [p.to_dict() for p in prs]})
        return prs

    # ------------------------------------------------------------------
    # Internal HTTP wrapper (also reused by tests via monkeypatch)
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        return self._client.request(method, url, params=params, headers=headers or {})


# ---------------------------------------------------------------------------
# Helpers usable from tests / CLI without constructing a full Fetcher
# ---------------------------------------------------------------------------


def make_fetcher(
    github_token: str | None = None,
    cache_dir: Path | str = ".cache/community-radar",
    *,
    client_factory: Callable[[], Any] | None = None,
) -> Fetcher:
    """Build a Fetcher; ``client_factory`` is honoured by tests only."""
    if client_factory is not None:
        # Tests inject a fake client. We mark ``_owns_client=False`` so
        # ``close()`` does not try to call ``.close()`` on the stub.
        fetcher = Fetcher(
            github_token=github_token,
            cache_dir=cache_dir,
            client=client_factory(),
        )
        return fetcher
    return Fetcher(github_token=github_token, cache_dir=cache_dir)


# ``PullRequest.from_dict`` shim — dataclass auto-generates one but it
# is not always picked up by ``make_dataclass`` discovery tooling.
def _attach_pr_from_dict() -> None:  # pragma: no cover
    if not hasattr(PullRequest, "from_dict"):
        def _from_dict(cls: type, data: dict[str, Any]) -> PullRequest:  # type: ignore[no-redef]
            return cls(
                number=int(data.get("number") or 0),
                title=str(data.get("title") or ""),
                state=str(data.get("state") or ""),
                merged_at=data.get("merged_at"),
                url=str(data.get("url") or ""),
                body=str(data.get("body") or ""),
            )
        PullRequest.from_dict = classmethod(_from_dict)  # type: ignore[attr-defined]


_attach_pr_from_dict()


def _attach_commit_from_dict() -> None:  # pragma: no cover
    if not hasattr(Commit, "from_dict"):
        def _from_dict(cls: type, data: dict[str, Any]) -> Commit:  # type: ignore[no-redef]
            return cls(
                sha=str(data.get("sha", "")),
                message=str(data.get("message") or ""),
                author=data.get("author"),
                committed_at=data.get("committed_at"),
                url=str(data.get("url") or ""),
            )
        Commit.from_dict = classmethod(_from_dict)  # type: ignore[attr-defined]


_attach_commit_from_dict()


def isoformat_now() -> str:
    """Convenience for callers that want a deterministic timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")