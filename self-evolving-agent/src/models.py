"""Core data structures for the self-evolving agent system."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import re
from enum import Enum
from typing import List, Optional


# ─── Enums ───────────────────────────────────────────────────────────────────


class StepType(Enum):
    TASK_UNDERSTANDING = "task_understanding"
    PLANNING = "planning"
    CODE_GENERATION = "code_generation"
    FILE_OPERATION = "file_operation"
    COMMAND_EXECUTION = "command_execution"
    DEBUGGING = "debugging"
    SELF_REVIEW = "self_review"
    FINAL_OUTPUT = "final_output"


class ProposalType(Enum):
    PROMPT_OPTIMIZATION = "prompt_optimization"
    SKILL_ADDITION = "skill_addition"
    SKILL_MODIFICATION = "skill_modification"
    CONFIG_ADJUSTMENT = "config_adjustment"
    WORKFLOW_OPTIMIZATION = "workflow_optimization"
    PLUGIN_GENERATION = "plugin_generation"
    LOOP_PARAMETER_ADJUSTMENT = "loop_parameter_adjustment"


class ProposalStatus(Enum):
    PENDING = "pending"
    VALIDATING = "validating"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEPLOYED = "deployed"


# ─── Data classes ────────────────────────────────────────────────────────────


@dataclass
class ToolCall:
    """A single tool invocation during a step."""
    tool_name: str
    arguments: dict = field(default_factory=dict)
    result: str = ""
    error: Optional[str] = None
    duration_ms: int = 0


@dataclass
class TraceStep:
    """A single step in an execution trace."""
    step_index: int
    step_type: StepType
    action: str
    input_data: str = ""
    output_data: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    thinking: str = ""
    errors: List[str] = field(default_factory=list)
    duration_ms: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ExecutionMetrics:
    """Execution quality metrics."""
    total_steps: int = 0
    total_duration_ms: int = 0
    error_count: int = 0
    tool_call_count: int = 0
    code_iterations: int = 0
    code_quality_score: float = 0.0
    efficiency_score: float = 0.0
    correctness_score: float = 0.0
    overall_score: float = 0.0


@dataclass
class ExecutionTrace:
    """Complete trace of a task execution."""
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    task_id: str = ""
    task_description: str = ""
    agent_version: str = ""
    config_snapshot: dict = field(default_factory=dict)
    steps: List[TraceStep] = field(default_factory=list)
    final_output: str = ""
    execution_metrics: ExecutionMetrics = field(default_factory=ExecutionMetrics)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class OptimizationProposal:
    """Proposal for optimizing a system component."""
    proposal_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    source_trace_id: str = ""
    proposal_type: ProposalType = ProposalType.PROMPT_OPTIMIZATION
    target: str = ""
    current_content: str = ""
    proposed_content: str = ""
    reason: str = ""
    expected_improvement: str = ""
    priority: int = 3
    status: ProposalStatus = ProposalStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ComparisonResult:
    """Result of comparing old vs new version executions."""
    comparison_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    task_id: str = ""
    old_version: str = ""
    new_version: str = ""
    old_execution: Optional["ExecutionTrace"] = None
    new_execution: Optional["ExecutionTrace"] = None
    steps_comparison: str = ""
    quality_comparison: str = ""
    efficiency_comparison: str = ""
    is_improved: bool = False
    improvement_summary: str = ""
    evaluator_notes: str = ""
    decision: str = "reject"
    decision_reason: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class VersionSnapshot:
    """A version snapshot of the full system configuration."""
    version: str = ""
    parent_version: str = ""
    config: dict = field(default_factory=dict)
    applied_proposals: List[str] = field(default_factory=list)
    description: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Task:
    """A task to be executed by the agent."""
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    description: str = ""
    priority: int = 5
    retry_count: int = 0
    max_retries: int = 3
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tags: List[str] = field(default_factory=list)


@dataclass
class AnalysisReport:
    """Report produced by analyzing an execution trace."""
    trace_id: str = ""
    task_description: str = ""
    errors: List[dict] = field(default_factory=list)
    efficiency_issues: List[dict] = field(default_factory=list)
    prompt_issues: List[dict] = field(default_factory=list)
    skill_issues: List[dict] = field(default_factory=list)
    # 4.2 节新增分析维度
    logic_errors: List[dict] = field(default_factory=list)
    prompt_effectiveness: List[dict] = field(default_factory=list)
    skill_usage_analysis: List[dict] = field(default_factory=list)
    duration_analysis: List[dict] = field(default_factory=list)
    # 压缩轨迹摘要
    compressed_summary: str = ""
    # 失败假设
    failure_hypotheses: List[dict] = field(default_factory=list)
    # 2.4 节：Skill 改进分析（仅 skill_improvement 模式下使用）
    skill_segments: List[dict] = field(default_factory=list)
    skill_failure_analysis: List[dict] = field(default_factory=list)
    # 综合
    overall_assessment: str = ""
    optimization_priority: str = ""
    needs_optimization: bool = False
    section_analyses: list["SectionAnalysis"] = field(default_factory=list)
    section_analyses_summary: str = ""

    # plugin code generation analysis
    uncovered_error_patterns: list[dict] = field(default_factory=list)
    hook_opportunities: list[dict] = field(default_factory=list)
    loop_termination_issues: list[dict] = field(default_factory=list)
    plugin_analysis_summary: str = ""



@dataclass
class SectionAnalysis:
    """Analysis of whether a ClawCodex system prompt section needs optimization."""
    section_id: str = ""
    section_content: str = ""
    needs_optimization: bool = False
    issues_found: list[str] = field(default_factory=list)
    suggested_improvement: str = ""
    reasoning: str = ""

@dataclass
class SkillAnalysisResult:
    """2.4 节：Skill 多维度失败分析结果"""
    skill_name: str = ""
    trace_id: str = ""
    segments: List[dict] = field(default_factory=list)
    knowledge_issues: List[str] = field(default_factory=list)
    tool_issues: List[str] = field(default_factory=list)
    clarify_issues: List[str] = field(default_factory=list)
    style_issues: List[str] = field(default_factory=list)
    revision_suggestions: List[str] = field(default_factory=list)
    verdict: str = ""  # "revise" | "merge" | "prune" | "keep"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ─── Serialization helpers ───────────────────────────────────────────────────


def dataclass_to_dict(obj) -> dict:
    """Convert a dataclass instance to a JSON-serializable dict."""
    result = asdict(obj)
    _convert_enums(result)
    return result


def _convert_enums(d: dict) -> None:
    """Recursively convert Enum/datetime values to JSON-safe types."""
    from datetime import datetime
    for k, v in d.items():
        if isinstance(v, Enum):
            d[k] = v.value
        elif isinstance(v, datetime):
            d[k] = v.isoformat()
        elif isinstance(v, dict):
            _convert_enums(v)
        elif isinstance(v, list):
            for i, item in enumerate(v):
                if isinstance(item, dict):
                    _convert_enums(item)
                elif isinstance(item, Enum):
                    v[i] = item.value
                elif isinstance(item, datetime):
                    v[i] = item.isoformat()
