"""
PatternExtractor — 配置驱动的自定义 Pipeline 提取器

====================================================
  SOP converter 的正式、可复用工作流提取器。
====================================================

设计目标
--------
为任意 SDK/项目提供一个可配置的 WorkflowExtractorBase 子类，
将项目中的 pipeline 定义（阶段枚举、状态转移、关卡、决策、契约）
解析为 WorkflowGraph IR。

与 ArcExtractor 的关键区别
--------------------------
旧 ArcExtractor 将 AutoResearchClaw 的所有约定硬编码在类中：
  - 路径: ``researchclaw/pipeline/``
  - 变量名: ``STAGE_SEQUENCE``, ``NEXT_STAGE``, ``DECISION_ROLLBACK`` 等
  - 枚举成员名: ``RESEARCH_DECISION``
  - 无缓存: 每个提取方法独立解析文件

本实现通过 ``PipelineConfig`` 将所有 SDK 约定参数化，并通过
``SourceScanContext`` 复用 AST 解析结果，使其可适配任意项目。

扩展点
------
1. 替换 ``SourceScanContext`` → 支持非 Python 项目（YAML / TOML / JSON）
2. 添加新的提取方法 → 覆盖 ``WorkflowExtractorBase`` 的抽象方法
3. 自定义降级策略 → 修改 ``_fallback_stages_*`` 方法
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from extensions.sop_converter.workflow_mode.ast_helpers import (
    _to_kebab,
    extract_docstring_first_para,
    find_dict_mapping_assignments,
    find_enum_classes,
    find_frozenset_assigns,
    get_enum_members_ordered,
    parse_ast,
    parse_contracts_dict,
    parse_enum_dict_mapping_from_expr,
    parse_enum_to_name_dict,
    parse_frozenset_members,
    parse_stage_sequence_from_expr,
    parse_string_to_stage_dict,
)
from extensions.sop_converter.workflow_mode.extractors.base import (
    WorkflowExtractorBase,
)
from extensions.sop_converter.workflow_mode.extractors.models import (
    DecisionSpec,
    ExtractedStage,
    GateSpec,
    OutcomeSpec,
    StageContract,
    Transition,
)
from extensions.sop_converter.workflow_mode.scan_context import SourceScanContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PipelineConfig — 将所有 SDK 特定约定参数化
# ---------------------------------------------------------------------------

@dataclass
class PipelineConfig:
    """描述一个 SDK/项目的 pipeline 约定的配置。

    使用者通过此配置告诉提取器：
    - 去哪里找 pipeline 定义文件
    - 变量名使用什么模式
    - 特定枚举成员叫什么名字

    属性说明:
        name: 配置名称（用于日志/调试）
        description: 配置描述

        pipeline_marker_files: 标识 pipeline 目录的文件列表。
            每个元素为 ``(filename, directory_relative_glob)``。
            例如 ``("stages.py", "pipeline")`` 表示在 ``{source_dir}/pipeline/stages.py``。
            提取器会按顺序检查，找到第一组匹配即确定 pipeline 目录。

        executor_table_patterns: 执行器映射表的变量名列表。
            例如 ``["STAGE_EXECUTORS", "_STAGE_EXECUTORS"]``。

        sequence_var_pattern: 阶段序列变量的名称（精确匹配）。
            例如 ``"STAGE_SEQUENCE"``。

        transition_var_pattern: 状态转移变量的正则模式。
            变量名匹配此模式的字典被视为阶段间转移定义。
            例如 ``"NEXT_STAGE|PREVIOUS_STAGE"``。

        gate_var_pattern: 关卡变量的正则模式。
            变量名匹配此模式的 frozenset 被视为关卡定义。
            例如 ``"GATE"``。

        decision_var_pattern: 决策变量的正则模式。
            变量名匹配此模式的字典被视为决策/回退定义。
            例如 ``"DECISION_ROLLBACK"``。

        contract_var_pattern: 契约变量的正则模式。
            变量名匹配此模式的字典被视为契约定义。
            例如 ``"CONTRACT"``。

        decision_stage_names: 决策阶段名称回退列表。
            按顺序检查，第一个匹配的枚举成员被视为决策阶段。
            例如 ``["RESEARCH_DECISION", "DECISION"]``。
    """
    name: str = "default"
    description: str = ""

    # Pipeline 目录发现
    pipeline_marker_files: list[tuple[str, str]] = field(default_factory=lambda: [
        ("stages.py", "pipeline"),
        ("contracts.py", "pipeline"),
    ])

    # 变量名模式
    executor_table_patterns: list[str] = field(default_factory=lambda: [
        "STAGE_EXECUTORS", "_STAGE_EXECUTORS",
    ])
    sequence_var_pattern: str = "STAGE_SEQUENCE"
    transition_var_pattern: str = "NEXT_STAGE|PREVIOUS_STAGE"
    gate_var_pattern: str = "GATE"
    decision_var_pattern: str = "DECISION_ROLLBACK"
    contract_var_pattern: str = "CONTRACT"

    # 决策阶段发现
    decision_stage_names: list[str] = field(default_factory=lambda: [
        "RESEARCH_DECISION", "DECISION",
    ])

    # 阶段枚举后缀（用于启发式发现）
    stage_enum_suffixes: list[str] = field(default_factory=lambda: [
        "Stage", "Step",
    ])


# ---------------------------------------------------------------------------
# 预置配置 — 可直接使用的 SDK 配置
# ---------------------------------------------------------------------------

# 旧 AutoResearchClaw 风格的配置（供参考 / 向后兼容）
ARC_COMPAT_CONFIG = PipelineConfig(
    name="arc-compat",
    description="AutoResearchClaw 兼容配置（参考用）",
    pipeline_marker_files=[
        ("stages.py", "researchclaw/pipeline"),
        ("contracts.py", "researchclaw/pipeline"),
        ("stages.py", "pipeline"),
        ("contracts.py", "pipeline"),
    ],
    executor_table_patterns=["_STAGE_EXECUTORS", "STAGE_EXECUTORS"],
    sequence_var_pattern="STAGE_SEQUENCE",
    transition_var_pattern="NEXT_STAGE|PREVIOUS_STAGE",
    gate_var_pattern="GATE",
    decision_var_pattern="DECISION_ROLLBACK",
    contract_var_pattern="CONTRACT",
    decision_stage_names=["RESEARCH_DECISION", "DECISION"],
)


# ---------------------------------------------------------------------------
# 辅助函数 — Pipeline 目录发现
# ---------------------------------------------------------------------------

def _resolve_pipeline_dir(source_dir: str | Path, config: PipelineConfig) -> Path | None:
    """根据 *config.pipeline_marker_files* 定位 pipeline 目录。

    对每个 ``(filename, relative_glob)`` 组合，在 ``source_dir`` 下查找
    ``relative_glob/filename`` 是否存在。``relative_glob`` 可以包含路径分隔符，
    例如 ``"researchclaw/pipeline"``。

    如果所有 marker 文件存在，则返回该目录；否则继续检查下一个组合。
    """
    root = Path(source_dir).resolve()
    for filename, rel_glob in config.pipeline_marker_files:
        candidate = root / rel_glob
        if (candidate / filename).is_file():
            return candidate
    # 兜底：递归搜索（慢，但覆盖文件结构不标准的项目）
    for stages_py in root.rglob("stages.py"):
        parent = stages_py.parent
        if (parent / "contracts.py").is_file():
            return parent
    return None


# ---------------------------------------------------------------------------
# PatternExtractor — 主提取器类
# ---------------------------------------------------------------------------

class PatternExtractor(WorkflowExtractorBase):
    """配置驱动的 Pipeline 提取器。

    接收一个 ``PipelineConfig`` 描述 SDK 约定，然后从项目目录中提取
    工作流定义（阶段、转移、关卡、决策、契约）。

    用法::

        config = PipelineConfig(
            name="my-sdk",
            pipeline_marker_files=[("stages.py", "pipeline")],
        )
        ext = PatternExtractor(config=config, mode="fwa")
        graph = ext.extract("/path/to/project")
    """

    # 默认配置（当用户不传时使用）
    _DEFAULT_CONFIG: ClassVar[PipelineConfig] = PipelineConfig()

    def __init__(
        self,
        *args,
        config: PipelineConfig | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._config: PipelineConfig = config or self._DEFAULT_CONFIG
        self._pipeline_dir: Path | None = None
        self._enum_class: str | None = None
        self._member_to_value: dict[str, int] = {}
        self._member_order: list[tuple[str, int]] = []
        self._stage_sequence: list[int] = []
        self._executor_rel: str | None = None
        self._executor_by_stage: dict[int, str] = {}
        self._scan: SourceScanContext | None = None  # 覆盖父类的 _scan

    # ------------------------------------------------------------------
    # 初始化与缓存
    # ------------------------------------------------------------------

    def _ensure_scan(self, source_dir: Path) -> None:
        """确保 SourceScanContext 已构建（懒加载，重复调用不重复解析）。"""
        if self._scan is None:
            self._scan = SourceScanContext.build(source_dir)
        self._populate_enum_info(source_dir)

    def _populate_enum_info(self, source_dir: Path) -> None:
        """从 pipeline 目录解析阶段枚举、序列、执行器映射。

        这是提取器的核心初始化步骤：
        1. 定位 pipeline 目录（通过 marker 文件）
        2. 解析阶段枚举类（成员名 → ID 映射）
        3. 解析 STAGE_SEQUENCE（阶段执行顺序）
        4. 解析执行器映射表（阶段 → 执行函数）

        此方法安全失败：如果 pipeline 目录不存在或文件不完整，
        设置 ``_pipeline_dir = None``，后续提取方法会返回空值。
        """
        pipeline = _resolve_pipeline_dir(source_dir, self._config)
        if pipeline is None:
            return
        self._pipeline_dir = pipeline

        stages_tree = parse_ast(pipeline / "stages.py")
        if stages_tree is None:
            return

        # 找到第一个枚举类作为阶段枚举
        for cls in find_enum_classes(stages_tree):
            members = get_enum_members_ordered(cls)
            if not members:
                continue
            self._enum_class = cls.name
            self._member_order = members
            self._member_to_value = dict(members)
            break

        if not self._member_to_value:
            return

        enum_names = {self._enum_class} if self._enum_class else set()
        module_assigns = dict(find_dict_mapping_assignments(stages_tree))

        # 阶段序列
        seq_var = self._config.sequence_var_pattern
        if seq_var in module_assigns:
            self._stage_sequence = parse_stage_sequence_from_expr(
                module_assigns[seq_var],
                enum_class_names=enum_names,
                enum_members_ordered=self._member_order,
                module_assigns=module_assigns,
            )
        if not self._stage_sequence:
            self._stage_sequence = [v for _, v in self._member_order]

        # 执行器映射表
        executor_path = pipeline / "executor.py"
        if executor_path.is_file():
            self._executor_rel = executor_path.relative_to(
                Path(source_dir).resolve()
            ).as_posix()
            exec_tree = parse_ast(executor_path)
            if exec_tree is not None:
                for var_name, dict_expr in find_dict_mapping_assignments(exec_tree):
                    if var_name in self._config.executor_table_patterns:
                        self._executor_by_stage = parse_enum_to_name_dict(
                            dict_expr, enum_names, self._member_to_value,
                        )

    # ------------------------------------------------------------------
    # 提取方法
    # ------------------------------------------------------------------

    def extract_stages(self, source_dir: Path) -> list[ExtractedStage]:
        """提取阶段列表。

        策略:
        1. 精确提取：从 pipeline 目录的 ``stages.py`` 中解析枚举类
        2. 目录推断：按目录结构推断阶段（见 ``_fallback_stages_from_directory``）
        3. 粗粒度扫描：仅当 ``allow_coarse=True`` 时，按文件内容推断

        扩展点: 覆盖 ``_fallback_stages_from_*`` 方法以支持自定义降级策略。
        """
        self._ensure_scan(source_dir)
        if self._pipeline_dir is None:
            return self._fallback_stages(source_dir)

        pipeline = self._pipeline_dir
        stages_tree = parse_ast(pipeline / "stages.py")
        stage_enum_cls = None
        if stages_tree:
            for cls in find_enum_classes(stages_tree):
                if cls.name == self._enum_class:
                    stage_enum_cls = cls
                    break

        desc = (
            extract_docstring_first_para(stage_enum_cls)
            if stage_enum_cls else ""
        )
        stages: list[ExtractedStage] = []
        for name, value in self._member_order:
            entry_fn = self._executor_by_stage.get(value)
            stages.append(
                ExtractedStage(
                    id=value,
                    name=_to_kebab(name),
                    label=name,
                    source_class=self._enum_class,
                    source_value=value,
                    file_path=self._executor_rel,
                    entry_function=entry_fn,
                    description=desc,
                )
            )
        return stages

    def extract_transitions(self, source_dir: Path) -> list[Transition]:
        """提取阶段间转移关系。

        从 ``stages.py`` 中查找匹配 ``transition_var_pattern`` 的字典映射，
        解析为 ``(from_stage, to_stage)`` 对。

        如果未找到显式转移定义，则按 ``STAGE_SEQUENCE`` 推导线性顺序。
        """
        self._ensure_scan(source_dir)
        if self._pipeline_dir is None or not self._member_to_value:
            return []

        pipeline = self._pipeline_dir
        stages_tree = parse_ast(pipeline / "stages.py")
        if stages_tree is None:
            return []

        enum_names = {self._enum_class} if self._enum_class else set()
        transitions: list[Transition] = []
        seen: set[tuple[int, int]] = set()
        trans_pattern = re.compile(self._config.transition_var_pattern, re.IGNORECASE)

        for var_name, dict_expr in find_dict_mapping_assignments(stages_tree):
            if trans_pattern.search(var_name):
                pairs = parse_enum_dict_mapping_from_expr(
                    dict_expr,
                    enum_names,
                    self._member_to_value,
                    stage_sequence=self._stage_sequence,
                )
                for from_id, to_id in pairs:
                    key = (from_id, to_id)
                    if key not in seen:
                        seen.add(key)
                        transitions.append(
                            Transition(
                                from_stage=from_id,
                                to_stage=to_id,
                                condition=var_name,
                                is_default=True,
                            )
                        )

        # 降级：按 STAGE_SEQUENCE 推导线性顺序
        if not transitions and self._stage_sequence:
            for idx, sid in enumerate(self._stage_sequence):
                if idx + 1 < len(self._stage_sequence):
                    nxt = self._stage_sequence[idx + 1]
                    transitions.append(
                        Transition(
                            from_stage=sid,
                            to_stage=nxt,
                            condition=self._config.sequence_var_pattern,
                            is_default=True,
                        )
                    )
        return transitions

    def extract_gates(self, source_dir: Path) -> dict[int, GateSpec]:
        """提取关卡（需要人工审批的阶段）。

        从 ``stages.py`` 中查找匹配 ``gate_var_pattern`` 的 frozenset 赋值，
        将其成员标记为关卡。
        """
        self._ensure_scan(source_dir)
        if self._pipeline_dir is None or not self._member_to_value:
            return {}

        pipeline = self._pipeline_dir
        stages_tree = parse_ast(pipeline / "stages.py")
        if stages_tree is None:
            return {}

        gates: dict[int, GateSpec] = {}
        enum_names = {self._enum_class} if self._enum_class else set()
        gate_pattern = re.compile(self._config.gate_var_pattern, re.IGNORECASE)

        for var_name, value_expr in find_frozenset_assigns(stages_tree):
            if not gate_pattern.search(var_name):
                continue
            stage_ids = parse_frozenset_members(
                value_expr, enum_names, self._member_to_value,
            )
            for sid in stage_ids:
                gates[sid] = GateSpec(
                    stage_id=sid,
                    approval_mode="manual",
                    description=f"Gate from {var_name}",
                    source_name=var_name,
                )
        return gates

    def extract_decisions(self, source_dir: Path) -> dict[int, DecisionSpec]:
        """提取决策节点（分支/回退逻辑）。

        从 ``stages.py`` 中查找匹配 ``decision_var_pattern`` 的字典映射，
        解析为回退目标。决策阶段通过 ``decision_stage_names`` 配置发现。

        扩展点: 如果 SDK 使用函数定义而非字典映射来表示决策，
        可以覆盖此方法或添加 ``_fallback_decision_funcs()``。
        """
        self._ensure_scan(source_dir)
        if self._pipeline_dir is None or not self._member_to_value:
            return {}

        pipeline = self._pipeline_dir
        stages_tree = parse_ast(pipeline / "stages.py")
        if stages_tree is None:
            return {}

        enum_names = {self._enum_class} if self._enum_class else set()
        decisions: dict[int, DecisionSpec] = {}
        decision_pattern = re.compile(
            self._config.decision_var_pattern, re.IGNORECASE,
        )

        for var_name, dict_expr in find_dict_mapping_assignments(stages_tree):
            if not decision_pattern.search(var_name):
                continue
            rollback = parse_string_to_stage_dict(
                dict_expr, enum_names, self._member_to_value,
            )
            # 发现决策阶段：按配置的 `decision_stage_names` 列表顺序查找
            decision_stage = self._resolve_decision_stage()
            if decision_stage is None:
                continue
            outcomes = {
                name: OutcomeSpec(next_stage=sid, max_times=2)
                for name, sid in rollback.items()
            }
            decisions[decision_stage] = DecisionSpec(
                stage_id=decision_stage,
                outcomes=outcomes,
                source_func=var_name,
                inferred=False,
            )
        return decisions

    def extract_contracts(self, source_dir: Path) -> dict[int, StageContract]:
        """提取阶段契约（输入/输出文件定义）。

        从 ``contracts.py`` 中查找匹配 ``contract_var_pattern`` 的字典映射，
        解析为 ``StageContract``。
        """
        self._ensure_scan(source_dir)
        if self._pipeline_dir is None or not self._member_to_value:
            return {}

        pipeline = self._pipeline_dir
        contracts_path = pipeline / "contracts.py"
        tree = parse_ast(contracts_path)
        if tree is None:
            return {}

        enum_names = {self._enum_class} if self._enum_class else set()
        contracts: dict[int, StageContract] = {}
        contract_pattern = re.compile(
            self._config.contract_var_pattern, re.IGNORECASE,
        )

        for var_name, dict_expr in find_dict_mapping_assignments(tree):
            if not contract_pattern.search(var_name):
                continue
            parsed = parse_contracts_dict(
                dict_expr, enum_names, self._member_to_value,
            )
            for stage_id, (inp, out, call_name, dod) in parsed.items():
                contracts[stage_id] = StageContract(
                    stage_id=stage_id,
                    input_files=inp,
                    output_files=out,
                    dod=dod,
                    source_class=call_name,
                )
        return contracts

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    def _resolve_decision_stage(self) -> int | None:
        """按 ``decision_stage_names`` 配置顺序查找决策阶段 ID。

        如果未找到，遍历所有成员找包含 "DECISION" 的成员。
        """
        for name in self._config.decision_stage_names:
            sid = self._member_to_value.get(name)
            if sid is not None:
                return sid
        for member, value in self._member_to_value.items():
            if "DECISION" in member.upper():
                return value
        return None

    def _fallback_stages(self, source_dir: Path) -> list[ExtractedStage]:
        """降级：当精确提取失败时，尝试其他策略。

        当前实现：
        1. 尝试 ``_fallback_stages_from_directory`` — 按目录结构推断
        2. 如果 ``allow_coarse=True``，尝试 ``_fallback_stages_coarse`` —
           按文件内容推断

        扩展点: 添加新的降级策略，例如从 YAML/TOML 配置文件解析。
        """
        stages = self._fallback_stages_from_directory(source_dir)
        if stages:
            return stages
        if self._allow_coarse:
            return self._fallback_stages_coarse(source_dir)
        return []

    def _fallback_stages_from_directory(
        self, source_dir: Path,
    ) -> list[ExtractedStage]:
        """按目录结构推断阶段。

        查找以 ``stage_`` 或 ``step_`` 开头的子目录，
        每个子目录视为一个阶段。
        """
        root = Path(source_dir).resolve()
        stages: list[ExtractedStage] = []
        for entry in sorted(root.iterdir(), key=lambda p: p.name):
            if not entry.is_dir():
                continue
            name = entry.name
            if not (name.startswith("stage_") or name.startswith("step_")):
                continue
            stages.append(
                ExtractedStage(
                    id=len(stages) + 1,
                    name=name,
                    label=name.replace("_", " ").title(),
                    inferred=True,
                    file_path=entry.relative_to(root).as_posix(),
                )
            )
        return stages

    def _fallback_stages_coarse(self, source_dir: Path) -> list[ExtractedStage]:
        """粗粒度推断：扫描 Python 文件中的类/函数定义。

        适用于仅有少量线索的项目，提取结果精度较低但不会完全失败。
        """
        scan = self._scan or SourceScanContext.build(source_dir)
        stages: list[ExtractedStage] = []
        seen_names: set[str] = set()

        for tree in scan.trees.values():
            for cls in find_enum_classes(tree):
                for suffix in self._config.stage_enum_suffixes:
                    if cls.name.endswith(suffix) and cls.name not in seen_names:
                        seen_names.add(cls.name)
                        stages.append(
                            ExtractedStage(
                                id=len(stages) + 1,
                                name=_to_kebab(cls.name),
                                label=cls.name,
                                source_class=cls.name,
                                inferred=True,
                                description=extract_docstring_first_para(cls),
                            )
                        )
        return stages
