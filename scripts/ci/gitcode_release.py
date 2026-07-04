"""Create/update a GitCode release and upload distribution assets.

This script uses only stdlib modules so release workflows do not need an extra
GitCode client dependency. It reads tokens from the process environment and
falls back to the repository's ignored ``.env`` file for local release testing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from env_loader import ensure_dotenv, load_dotenv


API_ROOT = os.environ.get("GITCODE_API_ROOT", "https://api.gitcode.com")


def _token() -> str:
    token = os.environ.get("GITCODE_TOKEN")
    if not token:
        raise SystemExit("GITCODE_TOKEN is required")
    return token


def _display_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if not parsed.query:
        return url
    sensitive = {"access_token", "token", "private_token", "signature", "accesskeyid"}
    query_keys = {key.lower() for key in urllib.parse.parse_qs(parsed.query)}
    if not query_keys.intersection(sensitive):
        return url
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, "<redacted>", parsed.fragment)
    )


def _request(
    method: str,
    path_or_url: str,
    *,
    data: bytes | None = None,
    content_type: str = "application/json",
    allow_404: bool = False,
    skip_auth: bool = False,
    extra_headers: dict[str, str] | None = None,
) -> dict:
    url = path_or_url if path_or_url.startswith("http") else f"{API_ROOT}{path_or_url}"
    headers: dict[str, str] = {}
    if not skip_auth:
        token = _token()
        headers["Authorization"] = f"Bearer {token}"
        headers["PRIVATE-TOKEN"] = token
    if data is not None:
        headers["Content-Type"] = content_type
    if extra_headers:
        headers.update(extra_headers)
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        # HTTPError exposes a one-shot stream; read it once and reuse for
        # the not-found heuristic and the failure detail.
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        except Exception:
            detail = ""
        if allow_404:
            if exc.code == 404:
                return {}
            # GitCode API quirk: "resource not found" is sometimes returned
            # as HTTP 400 with ``error_code: 404`` in the JSON body. Treat
            # those as a not-found response so callers can fall back to
            # create-on-miss logic.
            payload: dict = {}
            if detail:
                try:
                    parsed = json.loads(detail)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict):
                    payload = parsed
            if payload.get("error_code") in (404, "404") or "Release Not Found" in detail:
                return {}
        raise SystemExit(
            f"GitCode API {method} {_display_url(url)} failed: {exc.code} {detail}"
        ) from exc
    if not body:
        return {}
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return {"raw": body.decode("utf-8", errors="replace")}


def _json_request(method: str, path: str, payload: dict) -> dict:
    return _request(method, path, data=json.dumps(payload).encode("utf-8"))


def _ensure_release(
    owner: str, repo: str, tag: str, target: str, body: str, prerelease: bool
) -> None:
    payload = {
        "tag_name": tag,
        "target_commitish": target,
        "name": tag,
        "body": body,
        "prerelease": prerelease,
    }
    encoded_tag = urllib.parse.quote(tag, safe="")
    get_path = f"/api/v5/repos/{owner}/{repo}/releases/tags/{encoded_tag}"
    release = _request("GET", get_path, allow_404=True)
    if release and "tag_name" in release:
        _json_request("PATCH", f"/api/v5/repos/{owner}/{repo}/releases/{encoded_tag}", payload)
    else:
        _json_request("POST", f"/api/v5/repos/{owner}/{repo}/releases", payload)


def _upload_file(owner: str, repo: str, tag: str, path: Path) -> None:
    encoded_tag = urllib.parse.quote(tag, safe="")
    encoded_filename = urllib.parse.quote(path.name, safe="")
    # GitCode API quirk: ``/upload_url`` requires ``file_name`` as a query
    # parameter on the GET request so it can mint a pre-signed upload URL
    # for that specific asset. Without it the endpoint returns HTTP 400.
    upload_info = _request(
        "GET",
        f"/api/v5/repos/{owner}/{repo}/releases/{encoded_tag}/upload_url"
        f"?file_name={encoded_filename}",
    )
    upload_url = (
        upload_info.get("url")
        or upload_info.get("upload_url")
        or upload_info.get("uploadUrl")
        or upload_info.get("raw")
    )
    if not upload_url:
        raise SystemExit(f"Release upload URL not found in response: {upload_info!r}")

    # GitCode returns a pre-signed OBS upload URL plus headers that are part
    # of the signature. Do not append extra query parameters to that URL.
    extra_headers: dict[str, str] = {
        str(k): str(v)
        for k, v in (upload_info.get("headers") or {}).items()
        if isinstance(v, (str, int, float))
    }
    content_type = (
        extra_headers.pop("Content-Type", None)
        or extra_headers.pop("content-type", None)
        or mimetypes.guess_type(path.name)[0]
        or "application/octet-stream"
    )

    if "{filename}" in upload_url:
        upload_url = upload_url.replace("{filename}", encoded_filename)

    _request(
        "PUT",
        upload_url,
        data=path.read_bytes(),
        content_type=content_type,
        skip_auth=True,
        extra_headers=extra_headers,
    )
    print(f"Uploaded {path.name}")


def _write_checksums(files: list[Path], output: Path) -> None:
    lines = []
    for path in files:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.name}")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    env_path, _ = ensure_dotenv()
    load_dotenv(env_path)

    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", default=os.environ.get("GITCODE_OWNER", ""))
    parser.add_argument("--repo", default=os.environ.get("GITCODE_REPO", ""))
    parser.add_argument("--tag", required=True)
    parser.add_argument(
        "--target", default=os.environ.get("GITCODE_TARGET", "dev-decoupling-refactor-0573f4c")
    )
    parser.add_argument("--dist", default="dist")
    parser.add_argument("--body", default="Automated ClawCodex release")
    parser.add_argument("--prerelease", action="store_true")
    args = parser.parse_args()

    dist = Path(args.dist)
    assets = sorted(p for p in dist.iterdir() if p.is_file())
    if not assets:
        raise SystemExit(f"No release assets found in {dist}")

    checksums = dist / "SHA256SUMS"
    _write_checksums([p for p in assets if p.name != "SHA256SUMS"], checksums)
    assets = sorted(p for p in dist.iterdir() if p.is_file())

    _ensure_release(args.owner, args.repo, args.tag, args.target, args.body, args.prerelease)
    for asset in assets:
        _upload_file(args.owner, args.repo, args.tag, asset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
