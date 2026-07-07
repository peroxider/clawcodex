# F-155 Acceptance Template Registry

> **修订记录**
> - v1.0：初稿（含 F-150/151/153/154 复用路径 + 否决清单 8 项 + 实施 Phase 1-8）
> - v1.1（本次）：显式追加 spaCy word vectors + spaCy 库本体 + RDFLib/owlrl 至否决清单；Out-of-Scope / 验收标准同步强化。回应用户问题："模糊 / 歧义检测中 spaCy word vectors + cosine，https://github.com/RDFLib/owlrl 还有必要作为特性增强集成吗？"

## Goal

把现有 `AcceptanceTemplate`（F-150 中绑定在 `EngineeringMethod.subtask_templates[i].acceptance_template` 的字段）**提升为顶层 LKB 概念**，让"接受准则模板"可以独立于 method 注册、复用、外部导入。**强约束**：不引入任何新的形式化推理库（OWL/Datalog/Drools/owlrl 等），不引入任何机器学习模型（嵌入模型 / NER / 分类模型 / spaCy word vectors），不引入 spaCy 库本体（与 F-134 `FuzzyPatternLibrary` 等价）。

设计核心：**复用 F-151 / F-153 / F-154 的现有路径**，只新增"模板可见性"和"独立持久化"，避免架构发散。

## Scope

### In-Scope

- `AcceptanceTemplate` dataclass 从 `EngineeringMethod` 内部提升为顶层（仅提升可见性，不重写 schema）。
- `AcceptanceTemplateRegistry`：顶层注册表 API（`register / get / list / save / load`）。
- 持久化路径：`~/.cache/clawcodex/lkb/acceptance_templates/` + 项目级 `.lkb/acceptance_templates/`。
- 复用 F-153 `method_governance` 状态机（简化版）：`draft → approved / rejected → deprecated`，同样禁止边约束。
- 复用 F-154 `ExternalConfigImporter`：增加新文件类型 `acceptance_template`（YAML / JSON）。
- 复用 F-154 `entry_points["lkb.configs"]`：第三方包可发布预打包 acceptance template。
- 复用 F-151 `method_prompt.py`：新增 `acceptance_template_summary()` 函数注入到 `TaskDecomposer._system_prompt()`。
- `Layer1RuleEngine` 新增 `R-METHOD-006`：`ProposedTask.lkbMetadata.assertions` 若引用 acceptance_template_id，模板必须存在于 registry；缺失记 `warning`（不阻断，仅记录）。
- 审计事件 `lkb_acceptance_template_registered` 与 `lkb_acceptance_template_referenced`。
- CLI 复用 F-153 `clawcodex-dev lkb method` 子命令组下加 `template` 子组（与 `method` 平级）：
  ```
  clawcodex-dev lkb template list [--status=approved]
  clawcodex-dev lkb template show <template_id>
  clawcodex-dev lkb template propose --from-plan=<decomposition_run_id>
  clawcodex-dev lkb template approve <proposal_id>
  clawcodex-dev lkb template reject <proposal_id> --reason="..."
  clawcodex-dev lkb template deprecate <template_id> [--replacement=T-yyy]
  clawcodex-dev lkb template coverage
  ```

### Out-of-Scope

- 引入 OWL / RDFLib / Pellet / HermiT 做本体推理（与 Z3 重叠，详见"已拟定的设计决定"§ 否决决策清单）。
- 引入 Datalog / Soufflé / pyDatalog 做递归规则推导（与 Layer1RuleEngine 重叠）。
- 引入 Drools / CLIPS 做业务规则（与 Layer1RuleEngine 同质）。
- 引入嵌入模型 / NER 模型 / 任何 ML 模型。
- 引入 spaCy 库本体（即便不加载 word vectors 模型）— 与 F-134 `FuzzyPatternLibrary` 等价；tokenizer 用 `str.split` / `re` 即可；增加依赖无 ROI（详见否决清单）。
- 引入 RDFLib / owlrl 做 OWL-RL 推理 — 与 F-142 Z3 能力重叠；F-154 ontology 推理通过 Z3 + Turtle→SMT 编码完成。
- 引入新的 SMT / ATP 后端（F-142 已有 Z3 / Vampire / Prover9）。
- 性能基线 / 安全合规等**业务级**断言（依赖外部审计，不在 LKB 范围）。

## 当前基线

- F-150 定义 `AcceptanceTemplate` dataclass（`assertion_template` / `proof_template` / `strict_acceptance` 默认值），但**仅作为** `EngineeringMethod.subtask_templates[i]` 的字段，绑定到 method，不能独立注册。
- F-149 LLM 在 `ProposedTask.lkbMetadata` 生成 `assertions` / `acceptance_proof` 字段，但**没有模板复用机制**——每次都从零生成。
- F-132 / F-142 提供 `Layer1RuleEngine` + `SolverPipeline`（Z3 / Vampire / Prover9）做形式化校验，能验证 LLM 生成的 assertion 是否一致、是否触发 cycle，但**没有模板层的引用校验**。
- F-134 / F-149 `AmbiguityDetector` 检测模糊措辞（"差不多"、"感觉上"等），不依赖任何 ML 模型。
- F-151 prompt 注入 method 摘要（不含 acceptance template）。
- F-153 method_governance 状态机 + 治理 CLI 完整可用。
- F-154 `ExternalConfigImporter` + `entry_points["lkb.configs"]` + 三层加载顺序完整可用。

**缺口**：
1. 接受准则模板只能绑定 method，无法独立复用（如"测试通过"模板应被所有"测试类"任务共享）。
2. 跨项目/跨组织的可复用 assertion 模板没有发布机制。
3. F-151 prompt 注入只含 method，不含 acceptance template——LLM 在生 acceptance criteria 时没有引导。

## 实施进度

### Phase 1 — 提升可见性（~0.5 周）

1. 在 `decomposer.py` 顶部（紧邻 `EngineeringMethod` 定义）增加 `AcceptanceTemplate` 的**顶层导入与别名**，明确文档化："同时作为 EngineeringMethod.subtask_templates[i] 的字段和顶层独立注册项使用"。
2. 新建 `clawcodex_ext/logical_kanban/acceptance_template.py`：
   - `AcceptanceTemplate` dataclass（与 F-150 现有定义完全相同，**不修改 schema**）：
     - `template_id: str`（命名规范 `T-<kebab-case>-NNN`）
     - `description: str`
     - `assertion_template: str`（如 `TestPasses({test_path})`）
     - `proof_template: str`（如 `pytest {test_path} exit code == 0`）
     - `strict_acceptance: bool`（默认 `True`）
     - `applies_to_roles: tuple[str, ...]`（如 `("test", "impl")`，限定可绑定哪些 subtask role）
     - `version: str`（SemVer）
     - `status: Literal["draft", "approved", "rejected", "deprecated"]`
     - **关于 `experimental` 状态**：F-150 `EngineeringMethod` 包含 `experimental` 状态；本 F-N **MVP 故意省略** `experimental`，只支持 `draft/approved/rejected/deprecated` 四态。理由：种子模板全部 `approved` 直接发布，避免双状态机复杂度；若未来需要实验性模板，回退到 F-150 五态 + 加迁移路径。
   - `AcceptanceTemplateRegistry`：
     - `register(template: AcceptanceTemplate) -> None`
     - `get(template_id: str) -> AcceptanceTemplate | None`
     - `list(*, status: str = "approved", role: str | None = None) -> tuple[AcceptanceTemplate, ...]`
     - `save(path: Path) -> None` / `load(path: Path) -> tuple[AcceptanceTemplate, ...]`
3. `__init__.py` 导出 `AcceptanceTemplate` / `AcceptanceTemplateRegistry`。

### Phase 2 — 持久化与加载顺序（~0.5 周）

1. 路径约定：
   - 项目级 `<cwd>/.lkb/acceptance_templates/*.json`
   - 用户级 `~/.cache/clawcodex/lkb/acceptance_templates/*.json`
   - 内置种子（`clawcodex_ext/logical_kanban/acceptance_template_seed.py`，约 15 条）
2. 加载顺序：`builtin < project < user < explicit`（与 F-154 一致）。
3. 冲突解决：strict 默认拒绝；显式 `--force` 覆盖（CLI flag 在 Phase 5）。
4. 启动时自动加载，错误时 warning 而非崩溃（沿用 F-153 Phase 6 策略）。

### Phase 3 — 复用 F-153 治理流程（~0.5 周）

1. `clawcodex_ext/logical_kanban/acceptance_template_governance.py`：
   - **复用** `method_governance.py` 的状态机实现（提取为共享 `state_machine.py` 或 `method_governance.py` 暴露 `transition_status()` 公共函数）。
   - `propose_acceptance_template_from_plan(plan, *, template_id, description) -> AcceptanceTemplate`：从 `DecompositionPlan` 提取 `lkbMetadata.assertions` / `acceptance_proof` 自动生成模板（**复用 F-153 的 `propose_method_from_plan` 实现，参数化调用**）。
   - `submit_acceptance_template(template)` / `approve_acceptance_template(proposal_id)` / `reject_acceptance_template(proposal_id, reason)` / `deprecate_acceptance_template(template_id, replacement_id)`。
2. 状态机沿用 F-153 的禁止边：
   - `approved → draft` 禁止
   - `approved → rejected` 禁止（用 `deprecate`）
   - `rejected → *` 终态
   - `deprecated → approved` 终态
   - `draft → deprecated` 禁止（用 `reject`）
3. 持久化提议：`~/.cache/clawcodex/lkb/template_proposals/{proposal_id}.json`。

### Phase 4 — 复用 F-154 外部配置导入（~0.5 周）

1. `ExternalConfigImporter` 扩展：
   - 增加新 kind `"acceptance_template"`。
   - 增加新 handler `_load_acceptance_template_yaml(path) -> tuple[AcceptanceTemplate, ...]` / `_load_acceptance_template_json(path)`。
   - YAML 用 `PyYAML`（已是常见依赖，无新引入 ML 模型）。
2. lint 校验沿用 F-154 Phase 3 的方法：
   - `template_id` 命名规范（`T-<kebab-case>-NNN`）。
   - `assertion_template` 含合法占位符（仅允许 `{<identifier>}` 形式，避免 Python 注入）。
   - `applies_to_roles` 必须在 `("design", "impl", "test", "docs", "review", "deploy", "integrate")` 白名单内。
3. entry_points：第三方包可在 `pyproject.toml` 声明 `[project.entry-points."lkb.configs"]` 注册 acceptance templates（与 method library 共用 group，kind 字段区分）。
4. **不引入新的 lint 后端**——复用 F-154 的 `external_config_lint.py` 框架，扩展而非重写。

### Phase 5 — 复用 F-151 prompt 注入（~0.5 周）

1. `clawcodex_ext/logical_kanban/acceptance_template_prompt.py`：
   - `summarize_acceptance_templates(templates, *, max_tokens: int = 800) -> str`（**复用** F-151 `summarize_methods()` 的实现，参数化）。
     - **`max_tokens=800`（vs F-151 method 的 1800）的设计理由**：acceptance template 比 method 更短——method 需展开 role 序列与 assumption，template 仅需 `template_id` + 一句 `assertion_template`；预留更多 token 给 method 摘要，acceptance template 摘要压在 800 内，确保 `_system_prompt()` 总长可控。
   - `select_templates_by_goal(goal, registry, *, top_k: int = 8) -> tuple[AcceptanceTemplate, ...]`：
     - **检索方式**：基于 `applies_to_roles` 白名单 + `description` / `template_id` 关键字 substring + Levenshtein 距离的轻量匹配。
     - **明确不使用**：嵌入相似度、向量数据库、语义向量检索。任何此类设计变更需先修订本 F-N 的"否决决策清单"，避免违反强约束。
2. `TaskDecomposer._system_prompt()` 注入：
   - 在 method 摘要之后追加 acceptance template 摘要。
   - 添加提示语："Prefer these acceptance templates when defining `assertions` / `acceptance_proof`."
3. `DecompositionPlan` 增加 `acceptance_template_references: tuple[str, ...]`（**复用** F-151 的 `method_references` 字段设计，命名一致）。

### Phase 6 — 与 Layer1RuleEngine 集成（~0.5 周）

1. 新增规则 **R-METHOD-006**：
   - `ProposedTask.lkbMetadata.assertions` 含 `template_ref: T-xxx` 引用时，模板必须存在于 `AcceptanceTemplateRegistry`。
   - 缺失记 `warning`（不阻断 commit，与 F-150 R-METHOD-001/002/003 的 warning-only 策略一致）。
2. **不新增规则** R-METHOD-007+ — 跨模板引用一致性已在 F-142 SolverPipeline + F-154 cross-reference lint 中覆盖。

### Phase 7 — CLI 与审计（~0.5 周）

1. `clawcodex_ext/cli/lkb_method_cmd/template_cmd.py`：
   - 7 个子命令（`list` / `show` / `propose` / `approve` / `reject` / `deprecate` / `coverage`）。
   - 使用 `@register("lkb")` 装饰器（与 F-153 / F-154 一致）。
   - **不新增** 顶层 CLI 命令，只在 `lkb template` 子组下挂。
2. `audit.py`：
   - 新增事件类型 `lkb_acceptance_template_registered`（payload: `template_id` / `source` / `version`）。
   - 新增事件类型 `lkb_acceptance_template_referenced`（payload: `template_id` / `decomposition_run_id` / `task_count`）。
3. 双源覆盖率指标（沿用 F-153 Phase 5）：
   - 字段层：`DecompositionPlan.acceptance_template_references`。
   - 事件层：`lkb_acceptance_template_referenced` 事件。
   - 差异时记 `template_coverage_integrity_warning`。

### Phase 8 — 种子与测试（~1 周）

1. 内置种子（约 16 条）：
   - `T-test-passes-001`：pytest exit code == 0
   - `T-coverage-threshold-001`：coverage ≥ 80%
   - `T-lint-clean-001`：ruff check exit code == 0
   - `T-type-check-clean-001`：mypy --strict exit code == 0
   - `T-docs-section-exists-001`：README 含目标 markdown section
   - `T-config-file-exists-001`：config file path exists
   - `T-deploy-success-001`：deploy script exit code == 0
   - `T-migration-applied-001`：DB migration version present
   - `T-metrics-emitted-001`：Prometheus metric 注册到 registry
   - `T-security-scan-clean-001`：trivy / bandit exit code == 0
   - `T-no-new-vulnerabilities-001`：pip-audit 0 high/critical
   - `T-api-contract-valid-001`：OpenAPI schema validate exit code == 0
   - `T-build-succeeds-001`：build command exit code == 0
   - `T-changelog-updated-001`：CHANGELOG.md 含当前 version
   - `T-rollback-tested-001`：rollback script smoke test pass
   - `T-feature-flag-rolled-out-001`：**业务级样例**，证明 LKB 可表达业务断言。LaunchDarkly / Unleash feature flag 100% rollout 验证：flag 在目标环境 `enabled_for_all_users=true`，且至少 1 小时无回滚事件。`applies_to_roles=("impl", "deploy", "review")`，`strict_acceptance=True`。
2. 单元测试（至少 25 个）：
   - 注册 / 列表 / 持久化往返。
   - 状态机合法 + 非法转换。
   - 跨 F-153 / F-154 / F-151 的复用是否生效（mock + 集成）。
   - R-METHOD-006 触发条件。
   - `summarize_acceptance_templates` token 预算。
3. 黄金集评估：
   - **acceptance-template-specific 黄金集**：本 F-N 新增 `tests/logical_kanban/fixtures/f155_golden_set.json`，含 10 个 goal（与 F-153 黄金集不重叠，专门针对 acceptance 维度）。每个 goal 含 `expected_template_pattern` 字段（如 `T-test-passes` / `T-coverage-threshold`）。
   - **不复用 F-153 黄金集**：F-153 黄金集针对 method 命中率，方法库 vs 模板库是不同评估维度，避免评估混淆。
   - 评估方式：跑黄金集（stub provider 返回 template-aware plan），计算 `template_hit_rate = (plan 含 acceptance_template_references 且匹配 expected_template_pattern) / total`。MVP 目标 `template_hit_rate ≥ 40%`。
   - 输出报告：`docs/feature_plan/09-logical-kanban/f-155-coverage-report.json`。

## 验收标准

- [ ] `AcceptanceTemplate` 顶层暴露于 `__init__.py`，与 F-150 现有 schema 完全兼容（不修改 dataclass 字段）。
- [ ] `AcceptanceTemplateRegistry` 完整 API（register / get / list / save / load）可用。
- [ ] 持久化三层加载顺序 `builtin < project < user < explicit` 实现。
- [ ] 复用 F-153 治理：状态机、提议、审批、deprecate 流程与 method library 一致；5 条禁止边沿用。
- [ ] 复用 F-154：`ExternalConfigImporter` 增加 `acceptance_template` kind；`entry_points["lkb.configs"]` 注册可用；lint 校验沿用 F-154 框架。
- [ ] 复用 F-151：`summarize_acceptance_templates()` 注入 `_system_prompt()`；token 预算 <800。
- [ ] `Layer1RuleEngine` 新增 R-METHOD-006 规则，warning 级。
- [ ] CLI 7 个子命令（`list` / `show` / `propose` / `approve` / `reject` / `deprecate` / `coverage`）可用，挂载在 `lkb template` 子组下。
- [ ] 审计事件 `lkb_acceptance_template_registered` 与 `lkb_acceptance_template_referenced` 在合适时机发射。
- [ ] 现有 319 + 13 + F-150/151/152/153/154 测试全部通过，无回归。
- [ ] 新增至少 25 个 F-155 单元测试。
- [ ] 黄金集模板命中率 ≥40%。
- [ ] **不引入任何新 ML 模型**（嵌入 / NER / 分类 / 序列标注）。
- [ ] **不引入任何新形式化推理后端**（OWL / Datalog / Drools / 新 SMT 后端 / owlrl）。
- [ ] **不引入 spaCy / spaCy word vectors / RDFLib**：模糊检测沿用 F-134 `AmbiguityDetector` + 关键词匹配；ontology 推理沿用 F-142 Z3 + Turtle→SMT 编码。

## 风险与约束

| 风险 | 缓解 |
|------|------|
| AcceptanceTemplate 与 EngineeringMethod 双绑定导致概念混淆 | 文档化明确两种用法；`applies_to_roles` 字段强制限定使用范围 |
| 复用 F-153 / F-154 时抽象过早（premature abstraction） | 优先复制粘贴 1-2 个函数后再抽象；MVP 阶段不抽公共 state_machine.py |
| 种子模板质量低污染 LKB | 种子 status 全部 `approved` 但允许 experimental 子类；F-153 治理可 deprecate |
| YAML 解析引入 PyYAML 依赖 | PyYAML 是常见依赖；如担心可限制为 JSON only |
| R-METHOD-006 误报（模板已存在但 registry 未加载） | 启动时 eager-load 三层；加载错误时 warning 而非静默 |
| 覆盖率指标双源失真（字段有值但未发射事件） | 沿用 F-153 的 `coverage_integrity_warning` 机制 |
| AcceptanceTemplate 与 F-154 模板冲突 | `template_id` 命名空间 `T-*` 与 `M-*` 隔离；不冲突 |

## 已拟定的设计决定

### 否决决策清单（强约束，避免未来重复讨论）

| 候选库 | 否决理由 |
|--------|---------|
| **OWL / RDFLib / Pellet / HermiT** | 功能与 F-142 Z3/Vampire/Prover9 重叠；OWL DL 推理 = 一阶逻辑子集；不增加可验证能力 |
| **Datalog / Soufflé / pyDatalog** | 功能与 F-132 Layer1RuleEngine 重叠；递归规则推导已有 Z3 + RuleEngine 覆盖 |
| **Drools / CLIPS** | 业务规则引擎与 Layer1RuleEngine 同质；增加 JVM 依赖或 C 库依赖 |
| **嵌入模型（BERT / RoBERTa / SBERT 等）** | 与 LKB 架构冲突；性能 / 部署成本 / 模型治理负担远超收益；LLM 已覆盖语义理解 |
| **NER 模型（spaCy NER / Stanza / etc）** | LLM 已能抽取实体；专用 NER 模型需训练数据 + 模型版本治理 |
| **分类模型（sentence-transformers classifier）** | 模糊检测已有 F-134 `AmbiguityDetector` 模式匹配 + LLM 校验；专用分类器增加复杂度 |
| **新 SMT 后端（CVC5 / Yices）** | F-142 已有 3 后端；再加冗余；测试矩阵爆炸 |
| **PDDL / HDDL / UP / PANDA** | F-149 / F-150 / F-153 已否决；引入表达力不足且与解耦原则冲突 |
| **通用向量基座（spaCy core / FastText / ELMo）** | 与嵌入模型同理；通用向量/语言模型基座与 LLM 能力重叠，但缺少 LLM 的指令跟随能力，性价比低 |
| **向量数据库（Chroma / Weaviate / FAISS / Qdrant / Pinecone）** | LKB 不做嵌入相似度检索；`select_templates_by_goal` 仅用关键词匹配；引入向量库会触发嵌入模型依赖 |
| **知识图谱嵌入（TransE / DistMult / ComplEx / GraphSAGE）** | 与 OWL 本体推理边界模糊；KG 嵌入需要训练数据 + 推理服务，与 LKB 部署形态冲突 |
| **spaCy word vectors + cosine similarity** | 需要 `en_core_web_lg` / `md`（几百 MB）违反"不引入额外模型"约束；与 F-134 模式匹配 + LLM 校验重叠；弱匹配难区分"差不多"（模糊）与"差不多吧"（语气） |
| **spaCy 库本体（即便不加载 word vectors 模型）** | 与 F-134 `FuzzyPatternLibrary` 等价（`matcher: Callable[[str], bool]`）；tokenizer 用 Python `str.split` / `re` 即可；rule-based Matcher 用现有库已实现；引入仅增加依赖与维护负担 |
| **RDFLib / owlrl** | F-142 Z3 已支持 SROIQ（OWL DL 的逻辑基础），能力 ⊇ OWL-RL；F-154 ontology 推理通过 Z3 + Turtle→SMT 编码完成；引入新推理后端增加测试矩阵与依赖维护 |

### 通过的决策

1. **AcceptanceTemplate 提升为顶层而非重写**：保留 F-150 现有 schema，仅调整可见性与注册入口。
2. **复用 F-153 状态机与治理流程**：不创建独立的 governance 子系统；只新增 `acceptance_template_governance.py` 薄封装。
3. **复用 F-154 外部配置**：不创建独立的 importer；只扩展 `ExternalConfigImporter` 的 kind 与 handler。
4. **复用 F-151 prompt 注入**：不创建独立的 prompt 子系统；只新增 `acceptance_template_prompt.py` 摘要函数。
5. **种子模板 status = approved**：MVP 不需要 experimental 子类；治理流程已支持 deprecate。
6. **R-METHOD-006 warning-only**：与 R-METHOD-001/002/003 一致，不阻断 F-149 现有用户。
7. **CLI 挂在 `lkb template` 子组**：与 `lkb method` 平级，避免在 `lkb` 顶层命令爆炸。

## 依赖与协同

**依赖**：
- F-150（`AcceptanceTemplate` schema 定义）
- F-151（prompt 注入与覆盖率指标）
- F-153（method_governance 状态机与治理 CLI）
- F-154（ExternalConfigImporter + entry_points + 三层加载顺序）

**被依赖**：
- （后续）第三方 acceptance template 包（`lkb-config-fastapi-acceptance` 等）

**协同**：
- 与 F-134（fuzzy patterns）：acceptance_template 的 `assertion_template` 中的模糊措辞由 `AmbiguityDetector` 过滤（沿用现有 lint 钩子）。
- 与 F-141（causal layer）：未来 acceptance_template 可携带因果约束（如"task A 失败 → task B acceptance 自动作废"），但 MVP 不实现。
- 与 F-152（scheduling solver）：`applies_to_roles` 包含 "deploy" 时，调度器可识别该任务的 duration 来自 acceptance_template。

## 文件变更清单

```
NEW  clawcodex_ext/logical_kanban/acceptance_template.py            # ~250 行（dataclass + registry）
NEW  clawcodex_ext/logical_kanban/acceptance_template_seed.py        # ~200 行（15 条种子）
NEW  clawcodex_ext/logical_kanban/acceptance_template_governance.py  # ~180 行（复用 F-153 状态机）
NEW  clawcodex_ext/logical_kanban/acceptance_template_prompt.py     # ~80 行（复用 F-151 摘要函数）
MOD  clawcodex_ext/logical_kanban/external_config.py                # +40 行（acceptance_template kind + handler）
MOD  clawcodex_ext/logical_kanban/external_config_lint.py           # +50 行（template_id / assertion_template lint）
MOD  clawcodex_ext/logical_kanban/decomposer.py                     # +20 行（R-METHOD-006 + 顶层 AcceptanceTemplate 别名 + acceptance_template_references 字段）
MOD  clawcodex_ext/logical_kanban/rule_engine.py                    # +25 行（R-METHOD-006 实现）
MOD  clawcodex_ext/logical_kanban/audit.py                          # +50 行（2 个新事件类型 + payload）
MOD  clawcodex_ext/logical_kanban/__init__.py                        # +8 行（export 新符号）
MOD  clawcodex_ext/cli/lkb_method_cmd/commands.py                   # +150 行（lkb template 子组 7 子命令）
NEW  tests/logical_kanban/test_f155_acceptance_template.py          # ~300 行
```

## 估算工作量

| 阶段 | 工时 |
|------|------|
| Phase 1 — 提升可见性 | 0.5 周 |
| Phase 2 — 持久化与加载顺序 | 0.5 周 |
| Phase 3 — 复用 F-153 治理 | 0.5 周 |
| Phase 4 — 复用 F-154 外部配置 | 0.5 周 |
| Phase 5 — 复用 F-151 prompt 注入 | 0.5 周 |
| Phase 6 — 与 Layer1RuleEngine 集成 | 0.5 周 |
| Phase 7 — CLI 与审计 | 0.5 周 |
| Phase 8 — 种子与测试 | 1 周 |
| **总计** | **4.5 周** |

## 与其他 F-N 的依赖图（最终）

```
F-149 DecompositionPlan / ProposedTask / TaskDecomposer
   │
   ▼
F-150 method_library + EngineeringMethod + 白名单扩展
   │
   ├─▶ F-151 prompt 注入 + method_ref 字段
   │
   ├─▶ F-152 SchedulingSolver + Schedule 字段
   │
   ├─▶ F-153 治理 + CLI + 覆盖率（依赖 F-150 + F-151）
   │
   ├─▶ F-154 外部配置导入（依赖 F-150 + F-153）
   │
   └─▶ F-155 AcceptanceTemplate 顶层化（依赖 F-150 + F-151 + F-153 + F-154）
        │
        └─ 复用 F-151 prompt / F-153 治理 / F-154 导入 / F-150 schema
        └─ 显式否决：OWL / Datalog / Drools / 嵌入模型 / NER / 分类模型
```

## 推荐实施顺序

1. **F-150 / F-151 / F-153 / F-154 全部完成**——F-155 是这 4 个 F-N 的复合复用。
2. **F-155 启动**（4.5 周）。

如需提前部分能力（如仅 prompt 注入），可拆分为：
- **F-155a**（MVP，~2 周）：Phase 1-3-5-7（顶层化 + 治理 + prompt + CLI）
- **F-155b**（增强，~2.5 周）：Phase 4-6-8（外部配置 + R-METHOD-006 + 种子 + 测试）