"""声明式工作流引擎 — 解释执行 workflow.yaml。

子模块:
- engine: DeclarativeWorkflowEngine 核心执行循环
- workflow_state: 工作流运行时状态
- event_bus: 事件总线 + State Journal 写入
- cost: CostTracker + CostBudget
- errors: 异常类型定义
- stage_runner: StageRunner 适配器 (F-111)
- gate_handler: GATE 门禁处理器 (F-112)
- gate_rollback: GATE 回滚处理器 (F-112)
- decision_handler: DECISION 决策处理器 (F-113)
- rollback: 阶段回滚管理器 (F-113)
- validators: 阶段契约验证器 (F-114)
- checkpoint: 检查点持久化 (F-115)
- observability: 工作流可观测性集成 (F-116)
"""

from __future__ import annotations

from .checkpoint import ArtifactResolver, Checkpoint, CheckpointManager, WorkflowResumer
from .cost import CostBudget, CostTracker
from .decision_handler import DecisionHandler, DecisionHistory, DecisionResult
from .engine import DeclarativeWorkflowEngine, EngineConfig, WorkflowResult, WorkflowSchema
from .errors import (
    CheckpointError,
    CostExceededError,
    RollbackError,
    StageFailureError,
    StageTimeoutError,
    ValidationError,
    WorkflowEngineError,
    WorkflowSchemaError,
)
from .event_bus import EventBus
from .gate_handler import GateHandler, GateMode, GateResult
from .gate_rollback import GateRollbackHandler, GateRollbackResult
from .observability import WorkflowObservability, WorkflowProgressSink
from .audit import WorkflowAuditEvent, WorkflowAuditWriter
from .rollback import RollbackManager, RollbackTarget, StageSnapshot
from .stage_runner import DecisionRunResult, GateRunResult, StageRunResult, StageRunner
from .validators import ContractValidator, ValidationResult
from .workflow_state import (
    StageKind,
    StageNode,
    StageResult,
    StageStatus,
    WorkflowState,
)

__all__ = [
    # Engine
    "DeclarativeWorkflowEngine",
    "EngineConfig",
    "WorkflowResult",
    "WorkflowSchema",
    # State
    "WorkflowState",
    "StageNode",
    "StageResult",
    "StageStatus",
    "StageKind",
    # Events
    "EventBus",
    # Cost
    "CostTracker",
    "CostBudget",
    # Errors
    "WorkflowEngineError",
    "WorkflowSchemaError",
    "StageTimeoutError",
    "StageFailureError",
    "CostExceededError",
    "ValidationError",
    "CheckpointError",
    "RollbackError",
    # StageRunner (F-111)
    "StageRunner",
    "StageRunResult",
    "GateRunResult",
    "DecisionRunResult",
    # GATE (F-112)
    "GateHandler",
    "GateMode",
    "GateResult",
    "GateRollbackHandler",
    "GateRollbackResult",
    # DECISION (F-113)
    "DecisionHandler",
    "DecisionHistory",
    "DecisionResult",
    # Rollback (F-113)
    "RollbackManager",
    "StageSnapshot",
    "RollbackTarget",
    # Validators (F-114)
    "ContractValidator",
    "ValidationResult",
    # Checkpoint (F-115)
    "Checkpoint",
    "CheckpointManager",
    "WorkflowResumer",
    "ArtifactResolver",
    # Observability (F-116)
    "WorkflowObservability",
    "WorkflowProgressSink",
    "WorkflowAuditEvent",
    "WorkflowAuditWriter",
]
