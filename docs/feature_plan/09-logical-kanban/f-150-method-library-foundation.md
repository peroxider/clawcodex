# F-150 LKB Method Library Foundation

## Goal

为 Logical Kanban 建立一套 **工程方法库**（Engineering Method Library），把 HTN 规划系统中"method library"的概念移植到 LKB 现有数据结构中。方法库是一组**可复用的分解模板**：每条方法描述一个常见工程模式（"添加中间件"、"修复 bug"、"重构"），包含子任务模板、前置条件、显式假设与接受准则生成模板。

方法库的目标不是替代 LLM 的分解能力，而是**让 LLM 复用而非凭空生成**——减少幻觉、加速收敛、为后续的领域工程沉淀提供载体。

## Scope

### In-Scope

- `EngineeringMethod` / `SubtaskTemplate` / `AcceptanceTemplate` 数据类（frozen dataclass）。
- `METHOD_LIBRARY` 种子：20-30 个常见软件工程方法。
- 方法库的加载 / 注册 / 序列化 / 反序列化 API（in-memory + 可选持久化到 `.lkb/methods/`）。
- `Layer1RuleEngine` 扩展：能够基于 `method_id` 校验 `DecompositionPlan` 是否符合 method schema。
- 方法-任务关联的 LKB 元数据：每个 `ProposedTask.lkbMetadata` 增加可选的 `method_ref` 字段（注意：必须在 `_LKB_METADATA_KEYS` 白名单和 `_validate_lkb_metadata` 中显式登记，否则 `_extract_and_validate_plan` 会通过 `_reject_unknown_keys` 拒收，见 Phase 3）。
- 与 F-149 (`TaskDecomposer`) 的衔接：decomposer 能从方法库中查找候选方法。

### Out-of-Scope

- LLM 自动生成方法（属于 F-153 治理范畴）。
- PDDL / HDDL 工具链（不在 LKB 体系内，已被否决）。
- 跨项目 / 跨组织的方法共享（不在 MVP 范围）。
- 方法的可视化编辑器（CLI 优先，UI 后置）。

## 当前基线

- F-149 (`TaskDecomposer`) 已实现：LLM-driven 分解 → `DecompositionPlan` → LKB 校验。
- F-132 (`Layer1RuleEngine`) 提供 R-002 / R-004 / R-006 等基础规则，覆盖任务状态转换与依赖图。
- F-142 (`SolverPipeline`) 集成 Z3 / Vampire / Prover9 做形式化一致性证明。
- F-149 的 `lkbMetadata` 已支持 `assertions / acceptance_proof / assumptions / strict_acceptance` 四个字段。

**缺口**：分解完全依赖 LLM 自由生成，没有引导机制。多次执行相似任务会得到不一致的分解结果。

## 实施进度

### Phase 1 — 数据结构与种子（~1 周）

1. 创建 `clawcodex_ext/logical_kanban/method_library.py`：
   - `EngineeringMethod` dataclass：method_id / pattern / description / subtask_templates / preconditions / assumptions / acceptance_template / version / status。
   - `SubtaskTemplate` dataclass：template_id / role（design / impl / test / docs / review / deploy） / subject_template / description_template / acceptance_template / default_blocked_by。
   - `AcceptanceTemplate` dataclass：assertion_template / proof_template / strict_acceptance 默认值。
   - `METHOD_LIBRARY` 全局实例：`tuple[EngineeringMethod, ...]`，初始 25 条种子。
2. 创建 `clawcodex_ext/logical_kanban/method_seed.py`：种子方法的具体数据。
3. 扩展 `__init__.py` 导出 `EngineeringMethod` / `SubtaskTemplate` / `AcceptanceTemplate` / `METHOD_LIBRARY` / `register_method` / `get_method` / `list_methods`。

### Phase 2 — 注册与序列化（~0.5 周）

1. `register_method(method: EngineeringMethod) -> None`：校验 ID 唯一性、引用合法性。
2. `get_method(method_id: str) -> EngineeringMethod | None`。
3. `list_methods(*, status: str = "approved", pattern_prefix: str | None = None) -> tuple[EngineeringMethod, ...]`。
4. `save_method_library(path: Path) -> None` / `load_method_library(path: Path) -> tuple[EngineeringMethod, ...]`：基于 JSON 的序列化（向后兼容：缺字段时使用默认值）。
5. 状态枚举：`draft` / `approved` / `deprecated` / `experimental`。

### Phase 3 — 与规则引擎集成（~1 周）

1. `Layer1RuleEngine` 新增 `R-METHOD-001`：`DecompositionPlan` 中携带 `method_id` 的 `ProposedTask` 必须满足 method 的 `subtask_templates` 数量与角色分布。
2. `R-METHOD-002`：method 的 `preconditions` 必须在 `assumptions` 或环境上下文中成立。
3. `R-METHOD-003`：method 的 `acceptance_template` 生成的 `assertions` 必须出现在对应 `ProposedTask.lkbMetadata.assertions` 中（如果 `strict_acceptance=true`）。
4. 警告而非阻断：method 不匹配仅生成 `ValidationIssue`（severity=`warning`），不阻断 commit——MVP 阶段保证向后兼容。

### Phase 4 — 与 Decomposer 衔接（~0.5 周）

1. `TaskDecomposer.__init__` 接受可选 `method_library` 参数（默认 `METHOD_LIBRARY`）。
2. `decompose()` 方法返回的 `DecompositionPlan` 中，每个 `ProposedTask.lkbMetadata` 增加可选 `method_ref` 字段（如果 LLM 引用了 method）。
3. **白名单扩展（必做）**：修改 `decomposer.py` 顶部 `_LKB_METADATA_KEYS = {...}` 增加 `"method_ref"`；同步扩展 `_validate_lkb_metadata` 校验 method_ref 是字符串（可选字段）。否则 LLM 输出含 `method_ref` 会被 `_reject_unknown_keys` 直接拒收导致整个 plan 解析失败。
4. 不修改 prompt（prompt 注入属于 F-151）。

### Phase 5 — 测试（~1 周）

1. 单元测试覆盖：
   - 数据结构创建与序列化往返。
   - `register_method` 的 ID 唯一性校验。
   - 种子方法的字段完整性（每条 method ≥3 个 subtask templates）。
   - `Layer1RuleEngine` 的 method-scope 规则触发与不触发。
2. 黄金集测试：定义 5 个常见 goal（如"add middleware"、"fix N+1 query"），验证 `list_methods(pattern_prefix=...)` 能返回相关 method。

## 验收标准

- [ ] `EngineeringMethod` / `SubtaskTemplate` / `AcceptanceTemplate` 数据类齐全且 `frozen=True`。
- [ ] `METHOD_LIBRARY` 至少包含 20 条种子方法，覆盖以下模式：
  - `add_*` 系列：add_api_endpoint / add_middleware / add_cli_command / add_config_option / add_metric
  - `fix_*` 系列：fix_bug / fix_performance / fix_security_vulnerability / fix_race_condition
  - `refactor_*` 系列：refactor_module / refactor_extract_service / refactor_rename
  - `add_test_*` 系列：add_unit_test / add_integration_test / add_e2e_test
  - `add_doc_*` 系列：add_readme_section / add_api_doc / add_changelog
  - `migrate_*` 系列：migrate_dependency / migrate_database_schema / migrate_api_version
  - `add_ci_*` 系列：add_github_action / add_pre_commit_hook
  - `release_*` 系列：release_minor / release_major / hotfix
- [ ] 每个 method 至少 3 个 subtask templates + 1 个 acceptance template。
- [ ] `register_method` / `get_method` / `list_methods` / `save_method_library` / `load_method_library` API 齐全。
- [ ] `Layer1RuleEngine` 新增 R-METHOD-001/002/003 三条规则，单元测试覆盖。
- [ ] `ProposedTask.lkbMetadata` 增加可选 `method_ref` 字段（向后兼容）。**强约束**：`_LKB_METADATA_KEYS` 与 `_validate_lkb_metadata` 必须同步扩展，否则 LLM 输出含 `method_ref` 的 plan 会被 `_reject_unknown_keys` 拒收（这是 `decomposer.py:101-106` 与 `decomposer.py:669-683` 的硬编码白名单机制）。
- [ ] 现有 319 个 logical_kanban 测试 + 13 个 F-149 测试全部通过，无回归。
- [ ] 新增至少 30 个 F-150 单元测试。

## 风险与约束

| 风险 | 缓解 |
|------|------|
| 方法库膨胀失控 | F-153 引入治理与版本管理；MVP 仅 20-30 条种子 |
| 种子方法质量参差 | 引入 `experimental` 状态；只有 `approved` 进入黄金集 |
| 序列化版本不兼容 | JSON 字段缺失使用默认值；新增字段向后兼容 |
| Layer1RuleEngine 规则过严导致回归 | MVP 阶段 R-METHOD-* 仅产生 warning，不阻断 |
| method_id 与 F-149 lkbMetadata key 冲突 | 使用命名空间前缀（如 `M-add-middleware-001`） |

## 已拟定的设计决定

1. **不引入 PDDL/HDDL**：method 用 LKB 现有 dataclass + JSON 表达，不引入新工具链。
2. **method 是模板不是 ground truth**：method 仅作为 prompt 引导和 LKB 校验的参考，不强制 LLM 必须遵守。
3. **种子方法不依赖任何具体项目**：method 描述的是工程模式（如"添加中间件"），不绑定具体技术栈。
4. **Layer1RuleEngine 规则初始为 warning**：MVP 阶段不阻断 commit，避免破坏 F-149 现有用户。

## 依赖与协同

**依赖**：
- F-132（Layer1RuleEngine 必须先有）
- F-149（ProposedTask / DecompositionPlan 数据结构）

**被依赖**：
- F-151（prompt 注入依赖本 F-N 的方法库 API）
- F-153（持续沉淀依赖本 F-N 的版本/状态字段）

**协同**：
- 与 F-134（fuzzy patterns）平行：method library 提供结构化模板，fuzzy patterns 处理措辞模糊。
- 与 F-141（causal layer）衔接：未来 method 的 preconditions 可用因果断言表达。

## 文件变更清单

```
NEW  clawcodex_ext/logical_kanban/method_library.py        # ~250 行
NEW  clawcodex_ext/logical_kanban/method_seed.py           # ~400 行（25 条种子）
MOD  clawcodex_ext/logical_kanban/rule_engine.py           # +60 行（R-METHOD-001/002/003）
MOD  clawcodex_ext/logical_kanban/decomposer.py            # +20 行（_LKB_METADATA_KEYS 加 method_ref + _validate_lkb_metadata 扩展）
MOD  clawcodex_ext/logical_kanban/__init__.py              # +10 行（export）
NEW  tests/logical_kanban/test_f150_method_library.py      # ~250 行
```

**注意**：`ProposedTask` / `DecompositionPlan` 数据类定义在 `decomposer.py`（不是 `types.py`）；`types.py` 仅含 `FactsSnapshot` / `ValidationIssue` / `ValidationRun` / `ValidationResult`。方法库字段扩展应改 `decomposer.py` 顶部的 dataclass + `_LKB_METADATA_KEYS` 白名单，而非 `types.py`。

## 估算工作量

| 阶段 | 工时 |
|------|------|
| Phase 1 — 数据结构与种子 | 1 周 |
| Phase 2 — 注册与序列化 | 0.5 周 |
| Phase 3 — 与规则引擎集成 | 1 周 |
| Phase 4 — 与 Decomposer 衔接 | 0.5 周 |
| Phase 5 — 测试 | 1 周 |
| **总计** | **4 周** |