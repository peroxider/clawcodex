"""Compatibility shim — delegate to lkb.solver_pipeline."""
from lkb.solver_pipeline import *  # noqa: F401, F403
from lkb.solver_pipeline import _merge_responses  # noqa: F401 — private name used by tests