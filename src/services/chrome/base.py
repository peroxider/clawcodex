"""Compatibility facade — see :mod:`clawcodex_ext.services.chrome.base`."""

from __future__ import annotations

from clawcodex_ext.services.chrome.base import *  # noqa: F401,F403
from clawcodex_ext.services.chrome.base import ChromeController, ChromeError  # noqa: F401

__all__ = ["ChromeController", "ChromeError"]
