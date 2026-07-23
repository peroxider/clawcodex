"""Compatibility shim — delegate to lkb.audit."""
from lkb.audit import *  # noqa: F401, F403
from lkb.audit import _new_event_id  # noqa: F401 — private name used by test_audit.py