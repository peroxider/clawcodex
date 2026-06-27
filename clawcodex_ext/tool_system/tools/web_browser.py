"""WebBrowserTool — drive a real browser via Playwright.

F-71 B / P71-N: lets the agent visit a URL, click selectors, fill forms,
and capture HTML/PNG output. Built on top of Playwright's sync API
(``playwright.sync_api``) so the tool runs inside the existing agent
loop without spinning an extra asyncio event loop.

The tool is **opt-in**: the underlying ``playwright`` package and
Chromium browser binary are not required for clawcodex to function.
When ``playwright`` is missing or the browser binary has not been
installed (via ``playwright install chromium``), every call returns a
clean ``is_error=True`` result explaining the missing dependency,
rather than crashing the agent.

Implementation notes
--------------------
* The tool opens one Chromium page per call (no persistent context) so
  the cost is bounded; for high-frequency scraping, use the
  ``headless_reuse`` mode (F-71 follow-up).
* ``screenshot`` returns the PNG as a base64 string in the result
  payload; callers can save it via Bash or stream it back through the
  conversation.
* All selectors are CSS-only by design; xpath support is intentionally
  absent until we see a real use case.
"""

from __future__ import annotations

import base64
from typing import Any

from ..build_tool import Tool, ValidationResult, build_tool
from ..context import ToolContext
from ..protocol import ToolResult

try:  # Playwright is optional — soft dependency.
    from playwright.sync_api import (  # type: ignore[import-not-found]
        sync_playwright,
        TimeoutError as PlaywrightTimeoutError,
    )
    _PLAYWRIGHT_IMPORT_ERROR: str | None = None
except Exception as exc:  # pragma: no cover - exercised only without playwright
    sync_playwright = None  # type: ignore[assignment]
    PlaywrightTimeoutError = Exception  # type: ignore[assignment, misc]
    _PLAYWRIGHT_IMPORT_ERROR = str(exc)


DEFAULT_NAV_TIMEOUT_MS = 30_000
DEFAULT_ACTION_TIMEOUT_MS = 10_000


def _error(message: str) -> ToolResult:
    """Shorthand to return an error-shaped ToolResult."""
    return ToolResult(name="web_browser", output=message, is_error=True)


def _playwright_unavailable_message() -> str:
    if _PLAYWRIGHT_IMPORT_ERROR is not None:
        return (
            "WebBrowserTool: playwright is not installed in this environment "
            f"(import error: {_PLAYWRIGHT_IMPORT_ERROR}). "
            "Install with `pip install playwright && playwright install chromium` "
            "to enable browser automation."
        )
    return (
        "WebBrowserTool: playwright is not installed. "
        "Run `pip install playwright && playwright install chromium`."
    )


def _validate_url(url: str) -> ValidationResult:
    if not url:
        return ValidationResult.fail("url is required")
    if not (url.startswith("https://") or url.startswith("http://localhost")
            or url.startswith("http://127.0.0.1")):
        return ValidationResult.fail(
            "WebBrowserTool: only https:// (or http://localhost) URLs are accepted"
        )
    return ValidationResult.ok()


def _coerce_int(raw: Any, default: int, *, lo: int, hi: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(value, hi))


# ---------------------------------------------------------------------------
# Action dispatch
# ---------------------------------------------------------------------------


_ACTIONS = {"navigate", "click", "fill", "screenshot", "extract_text", "close"}


def _do_navigate(page: Any, args: dict[str, Any]) -> ToolResult:
    url = str(args.get("url") or "")
    validation = _validate_url(url)
    if not validation.result:
        return _error(validation.message)
    nav_timeout = _coerce_int(
        args.get("timeout_ms"), DEFAULT_NAV_TIMEOUT_MS, lo=1000, hi=120_000
    )
    page.set_default_navigation_timeout(nav_timeout)
    response = page.goto(url, wait_until="domcontentloaded")
    status = response.status if response is not None else None
    title = page.title()
    return ToolResult(name="web_browser",
        output=f"navigated to {url}\nstatus: {status}\ntitle: {title}",
        is_error=False,
    )


def _do_click(page: Any, args: dict[str, Any]) -> ToolResult:
    selector = str(args.get("selector") or "")
    if not selector:
        return _error("WebBrowserTool: 'selector' is required for click")
    action_timeout = _coerce_int(
        args.get("timeout_ms"), DEFAULT_ACTION_TIMEOUT_MS, lo=100, hi=60_000
    )
    page.set_default_timeout(action_timeout)
    page.click(selector)
    return ToolResult(name="web_browser", output=f"clicked {selector!r}", is_error=False)


def _do_fill(page: Any, args: dict[str, Any]) -> ToolResult:
    selector = str(args.get("selector") or "")
    value = str(args.get("value") or "")
    if not selector:
        return _error("WebBrowserTool: 'selector' is required for fill")
    page.fill(selector, value)
    return ToolResult(name="web_browser", output=f"filled {selector!r} with {len(value)} chars", is_error=False)


def _do_screenshot(page: Any, args: dict[str, Any]) -> ToolResult:
    full_page = bool(args.get("full_page") or False)
    path = args.get("path")
    png_bytes = page.screenshot(full_page=full_page, path=path, type="png")
    if path:
        return ToolResult(name="web_browser",
            output=f"screenshot saved to {path} ({len(png_bytes)} bytes)",
            is_error=False,
        )
    encoded = base64.b64encode(png_bytes).decode("ascii")
    return ToolResult(name="web_browser",
        output=f"data:image/png;base64,{encoded}",
        is_error=False,
    )


def _do_extract_text(page: Any, args: dict[str, Any]) -> ToolResult:
    selector = args.get("selector")
    text = (
        page.locator(str(selector)).all_inner_texts()
        if selector
        else page.locator("body").inner_text()
    )
    if isinstance(text, list):
        joined = "\n\n".join(text)
    else:
        joined = str(text)
    truncated = len(joined) > 8000
    if truncated:
        joined = joined[:8000] + "\u2026 [truncated]"
    return ToolResult(name="web_browser", output=joined, is_error=False)


def _do_close(_browser: Any) -> ToolResult:
    """Closing is handled by the outer context manager; this is a no-op."""
    return ToolResult(name="web_browser", output="close is a no-op (handled per-call)", is_error=False)


# ---------------------------------------------------------------------------
# Top-level call
# ---------------------------------------------------------------------------


def web_browser_call(payload: dict[str, Any], context: ToolContext) -> ToolResult:
    if sync_playwright is None:
        return _error(_playwright_unavailable_message())

    action = str(payload.get("action") or "navigate").lower()
    if action not in _ACTIONS:
        return _error(
            f"WebBrowserTool: unknown action {action!r}; expected one of {sorted(_ACTIONS)}"
        )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                if action == "navigate":
                    return _do_navigate(page, payload)
                if action == "click":
                    return _do_click(page, payload)
                if action == "fill":
                    return _do_fill(page, payload)
                if action == "screenshot":
                    return _do_screenshot(page, payload)
                if action == "extract_text":
                    return _do_extract_text(page, payload)
                # action == "close"
                return _do_close(browser)
            finally:
                browser.close()
    except PlaywrightTimeoutError as exc:
        return _error(f"WebBrowserTool: timeout {exc}")
    except Exception as exc:
        return _error(f"WebBrowserTool: {type(exc).__name__}: {exc}")


def web_browser_activity(payload: dict[str, Any] | None) -> str | None:
    if payload is None:
        return None
    action = payload.get("action") if isinstance(payload, dict) else None
    return f"browser {action}" if action else "browser"


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


web_browser_tool: Tool = build_tool(
    name="web_browser",
    description=(
        "Drive a headless Chromium browser via Playwright. Supports "
        "navigate, click, fill, screenshot, extract_text, and close "
        "actions. Requires `playwright` plus `playwright install chromium`."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["navigate", "click", "fill", "screenshot", "extract_text", "close"],
                "description": "Browser action to perform. Defaults to navigate.",
            },
            "url": {
                "type": "string",
                "description": "Target URL (https:// or http://localhost). Required for navigate.",
            },
            "selector": {
                "type": "string",
                "description": "CSS selector for click / fill / extract_text.",
            },
            "value": {
                "type": "string",
                "description": "Text to fill (for action=fill).",
            },
            "path": {
                "type": "string",
                "description": "Filesystem path for screenshot. If omitted, returns base64 PNG.",
            },
            "full_page": {
                "type": "boolean",
                "description": "Capture full scrollable page (for action=screenshot).",
            },
            "timeout_ms": {
                "type": "integer",
                "description": "Per-action timeout. Defaults to 30s navigate / 10s action.",
            },
        },
        "required": ["action"],
    },
    call=web_browser_call,
    get_activity_description=web_browser_activity,
    aliases=("WebBrowserTool", "browser"),
    is_destructive=lambda _p: True,  # opens outbound connection
    search_hint="browser web click screenshot",
)


__all__ = ["web_browser_tool", "web_browser_call"]