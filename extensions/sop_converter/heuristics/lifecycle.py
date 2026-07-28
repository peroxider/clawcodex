# Backward-compatibility stub — re-exports from core/heuristics/lifecycle.py
from extensions.sop_converter.core.heuristics.lifecycle import *  # noqa: F401, F403
from extensions.sop_converter.core.heuristics import lifecycle as _impl

for _name, _value in vars(_impl).items():
    if _name.startswith("_") and not _name.startswith("__"):
        globals()[_name] = _value
del _name, _value, _impl
