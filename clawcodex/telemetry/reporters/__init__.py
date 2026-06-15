"""Reporter package.

Public surface:

* :class:`Reporter`            — Protocol
* :class:`CompositeReporter`   — fan-out wrapper
* :class:`LocalFileReporter`   — writes ``reports/YYYY-MM-DD.md``
* :class:`DryRunReporter`      — in-memory, used by tests + CLI preview
"""
from __future__ import annotations

from .base import CompositeReporter, Reporter
from .dry_run import DryRunReporter
from .local_file import LocalFileReporter

__all__ = [
    "CompositeReporter",
    "DryRunReporter",
    "LocalFileReporter",
    "Reporter",
]
