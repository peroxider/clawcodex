"""Compatibility shim — delegate to lkb.method_proposer."""
from lkb.method_proposer import *  # noqa: F401, F403
from lkb.method_proposer import _check_dag_no_cycle, _validate_proposed_method  # noqa: F401 — private names used by tests