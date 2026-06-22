"""Ultraplan service primitives (F-83 first iteration).

This package ships a hierarchical plan model (Plan → SubPlan → Step)
with strict dataclass validation, an atomic JSON store, a step state
machine executor, an adjuster for mid-execution changes, and a
sandboxed acceptance-criteria verifier. LLM-driven prompt generation
(P83-A) and the ``/ultraplan`` CLI command (P83-B) are explicitly
deferred to later iterations; this layer provides the safe service
foundation both can build on.
"""

from __future__ import annotations

from .adjuster import PlanAdjuster
from .exceptions import (
    DuplicateStepIdError,
    DuplicateSubPlanIdError,
    IllegalStepTransitionError,
    PlanCorruptError,
    PlanNotFoundError,
    StepHasDependentsError,
    StepNotFoundError,
    SubPlanNotFoundError,
    UltraplanError,
    UnknownCheckKindError,
    UnsafeCheckExpressionError,
    VerificationCheckFailedError,
)
from .executor import PlanExecutor, Progress, StepTransition
from .models import (
    AcceptanceCriteria,
    CheckKind,
    Plan,
    PlanStatus,
    Step,
    StepKind,
    StepStatus,
    SubPlan,
)
from .store import PlanStore
from .verifier import (
    AcceptanceVerifier,
    CheckResult,
    DEFAULT_SHELL_TIMEOUT_SECONDS,
)

__all__ = [
    "DEFAULT_SHELL_TIMEOUT_SECONDS",
    "AcceptanceCriteria",
    "AcceptanceVerifier",
    "CheckKind",
    "CheckResult",
    "DuplicateStepIdError",
    "DuplicateSubPlanIdError",
    "IllegalStepTransitionError",
    "Plan",
    "PlanAdjuster",
    "PlanCorruptError",
    "PlanExecutor",
    "PlanNotFoundError",
    "PlanStatus",
    "PlanStore",
    "Progress",
    "Step",
    "StepHasDependentsError",
    "StepKind",
    "StepNotFoundError",
    "StepStatus",
    "StepTransition",
    "SubPlan",
    "SubPlanNotFoundError",
    "UltraplanError",
    "UnknownCheckKindError",
    "UnsafeCheckExpressionError",
    "VerificationCheckFailedError",
]
