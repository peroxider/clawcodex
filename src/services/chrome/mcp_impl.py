"""Compatibility facade — see :mod:`clawcodex_ext.services.chrome.mcp_impl`."""

from __future__ import annotations

from clawcodex_ext.services.chrome.mcp_impl import *  # noqa: F401,F403
from clawcodex_ext.services.chrome.mcp_impl import MCPChromeController  # noqa: F401

__all__ = ["MCPChromeController"]
