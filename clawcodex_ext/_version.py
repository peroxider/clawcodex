"""Dynamic calendar-version — always reflects the current build/run date.

Usage
-----
    from clawcodex_ext._version import __version__

This module is the single source of truth for ClawCodex's version at
runtime.  The version is computed from ``date.today()`` in CalVer
format ``YYYY.M.D`` (e.g. ``2026.6.24``).

Package metadata (``pyproject.toml``) reads this attribute via
``tool.setuptools.dynamic.version.attr`` so that ``pip install`` and
``python -m build`` always embed the current date.

Static files that cannot be made dynamic (``install.sh``, ``uv.lock``)
are updated by ``scripts/ci/bump_version.py`` before a release tag.
"""

from datetime import date


def _calver() -> str:
    """Return today's date as a CalVer string ``YYYY.M.D``."""
    today = date.today()
    return f"{today.year}.{today.month}.{today.day}"


__version__ = _calver()
__version_info__ = tuple(int(x) for x in __version__.split("."))
