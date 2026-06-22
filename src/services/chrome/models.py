"""Compatibility facade — see :mod:`clawcodex_ext.services.chrome.models`."""

from __future__ import annotations

from clawcodex_ext.services.chrome.models import *  # noqa: F401,F403
from clawcodex_ext.services.chrome.models import (  # noqa: F401
    ChromeActionResult,
    ChromeActionType,
)

__all__ = ["ChromeActionResult", "ChromeActionType"]
