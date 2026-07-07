# F-153 Method Library Growth & Governance

## Goal

为 `METHOD_LIBRARY` 建立**持续沉淀与质量治理**机制。当 F-150 / F-151 跑通后，方法库会面临三个长期挑战：

1. **新方法从何而来**：LLM 在分解时会"借用"已有方法，但优秀分解结果如何反向沉淀为新方法？
2. **方法质量如何保证**：注册新方法是否会引入低质量 / 重复 / 命名冲突的方法？
3. **方法库膨胀如何控制**：20 → 200 → 2000 条方法时如何保持检索效率与黄金集命中率？

F-153 引入 **save-as-method workflow + 版本治理 + 覆盖率指标**，让方法库可演进且不失控。

## Scope

### In-Scope

- **Save-as-method workflow**：
  - 从 `DecompositionPlan` 反向提议方法。
  - 双层 gate：LKB 自动校验（结构）+ 人工审核（语义）。
  - 提议状态：`draft` → `approved` / `rejected`。
- **方法版本管理**：
  - `version: SemVer`（major / minor / patch）。
  - 不兼容变更：major bump + deprecation warning。
  - 兼容增强：minor bump，自动迁移。
  - 修订：patch bump，metadata-only 变更。
- **审批 workflow**：
  - CLI：`clawcodex-dev lkb method approve <method_id>` / `reject` / `deprecate`。
  - API：`approve_method()` / `reject_method()` / `deprecate_method()`。
- **覆盖率指标**：
  - 黄金集（10-20 个 goal）的方法命中率。
  - 方法复用率（基于 `lkb_method_referenced` 事件）。
  - 方法被引用的分布（top methods vs 长尾）。
- **持久化与发现**：
  - 默认位置：`~/.cache/clawcodex/lkb/methods/` 或项目级 `.lkb/methods/`。
  - 加载顺序：项目级 > 用户级 > 内置种子。
  - 冲突解决：项目级覆盖用户级覆盖内置。

### Out-of-Scope

- 方法的语义相似度去重（需 embedding + 聚类，超出 MVP 范围）。
- 跨项目方法共享（GitHub registry 等）。
- 方法的可视化编辑器（CLI 优先）。
- 自动方法发现（LLM 主动建议 vs 人工提议）——MVP 仅支持"完成 plan 后人工触发 save"。

## 当前基线

- F-150 引入 `EngineeringMethod` / `METHOD_LIBRARY`（25 条种子，in-memory only）。
- F-150 的状态枚举：`draft` / `approved` / `deprecated` / `experimental`，但**无 transition API**。
- F-151 引入 `lkb_method_referenced` 审计事件。
- 没有 CLI 命令管理方法库。
- 没有覆盖率指标或黄金集。

**缺口**：方法库目前是"只读 + 写时种子"的静态资源，无法从生产使用中学习。

## 实施进度

### Phase 1 — Save-as-method 提议生成器（~1 周）

1. `clawcodex_ext/logical_kanban/method_proposer.py`：
   - `propose_method_from_plan(plan: DecompositionPlan, *, method_id: str, pattern: str, description: str) -> EngineeringMethod`。
   - 自动提取：subtask templates（来自 `ProposedTask.subject` + `active_form` + `blocked_by`）、preconditions（来自 `lkbMetadata.assumptions`）、acceptance template（来自 `lkbMetadata.assertions`）。
   - 默认 `status=draft`，`version=0.1.0`。
2. `_validate_proposed_method(method: EngineeringMethod) -> list[ValidationIssue]`：
   - 结构校验：≥3 subtask、≥1 acceptance、preconditions 非空。
   - 命名校验：method_id 唯一、pattern 不与种子冲突。
   - 依赖校验：subtask 间的 blocked_by 形成 DAG（无 cycle）。

### Phase 2 — 审批 workflow（~1 周）

1. `clawcodex_ext/logical_kanban/method_governance.py`：
   - `submit_method(method: EngineeringMethod) -> str`（返回 proposal_id）。
   - `approve_method(proposal_id: str, reviewer: str) -> None`。
   - `reject_method(proposal_id: str, reviewer: str, reason: str) -> None`。
   - `deprecate_method(method_id: str, replacement_id: str | None) -> None`。
2. 状态机：
   ```
   draft → approved   (审批通过)
   draft → rejected   (审批拒绝)
   approved → deprecated (弃用)
   experimental → approved (升级)
   experimental → deprecated (直接弃用)
   ```

   **禁止转换**（在 `transition()` 函数中显式校验，非法转换抛 `MethodStateError`）：
   - `approved → draft`（不允许降级；如需修改，先 deprecate 再 draft 新版本）
   - `approved → rejected`（approved 方法不需"拒绝"，用 deprecate）
   - `rejected → *`（终态；如需重新启用，必须新建 method_id）
   - `deprecated → approved`（终态；如需复活，必须新建 method_id）
   - `draft → deprecated`（草稿直接弃用应使用 `reject` 而非 `deprecate`）
3. 持久化提议：`~/.cache/clawcodex/lkb/proposals/{proposal_id}.json`。

### Phase 3 — 版本管理（~0.5 周）

1. `SemVer` 校验：`major >= 0`, `minor >= 0`, `patch >= 0`。
2. `bump_version(method: EngineeringMethod, kind: Literal["major", "minor", "patch"]) -> EngineeringMethod`。
3. 不兼容检测：比较两个版本，若 major 不同则不兼容。
4. 迁移规则：
   - `minor` 升级时，老方法的 subtask role 列表若为新方法的子集，LLM 引用老 method 自动迁移。
   - `major` 升级时，老 method 标 deprecated，新 method 顶替。

### Phase 4 — CLI 命令（~1 周）

1. 新建 `clawcodex_ext/cli/lkb_method_cmd/` 子目录（参考 `clawcodex_ext/cli/model_cmd/`、`channels_cmd/` 的多文件模块模式）：
   ```
   clawcodex-dev lkb method list [--status=approved] [--pattern-prefix=add_]
   clawcodex-dev lkb method show <method_id>
   clawcodex-dev lkb method propose --from-plan=<decomposition_run_id> [--method-id=M-xxx] [--pattern=add_xxx]
   clawcodex-dev lkb method approve <proposal_id> [--reviewer=alice]
   clawcodex-dev lkb method reject <proposal_id> --reason="..."
   clawcodex-dev lkb method deprecate <method_id> [--replacement=M-yyy]
   clawcodex-dev lkb method coverage [--golden-set=docs/feature_plan/09-logical-kanban/golden_set.json]
   ```
2. 在 `clawcodex_ext/cli/lkb_method_cmd/commands.py` 使用 `@register("lkb")` 装饰器（参考 `auth_cmd.py` 的 `@register("auth")` 风格），主入口 `run_lkb_command(args)` 解析 `method` 子命令后分发到具体 handler。
3. 在 `clawcodex_ext/cli/subcommand_registry.py:load_builtin_subcommands()` 增加 `from clawcodex_ext.cli.lkb_method_cmd import commands as _lkb_method_commands  # noqa: F401`，确保 CLI 启动时自动加载。
4. **不要**新建 `extensions/cli/` 子目录——`extensions/` 下不存在 `cli/`，CLI 注册机制全部位于 `clawcodex_ext/cli/`。

### Phase 5 — 覆盖率指标与黄金集（~1 周）

1. 黄金集定义：`docs/feature_plan/09-logical-kanban/golden_set.json`：
   ```json
   [
     {"goal": "Add JWT auth middleware", "expected_method_pattern": "add_middleware"},
     {"goal": "Fix N+1 query in /api/users", "expected_method_pattern": "fix_performance"},
     ...
   ]
   ```
2. `MethodCoverageEvaluator`：
   - 跑黄金集（用 stub provider 返回 method-aware plan）。
   - 计算：
     - `hit_rate`：plan 含 method_ref 且匹配 expected_pattern 的比例。
     - `top_method_usage`：top 10 methods 的引用频次。
     - `long_tail_methods`：被引用 <3 次的方法数量。
     - `dead_methods`：从未被引用且 status=approved 的方法数量。
   - **双源交叉验证**：指标同时基于
     - **字段层**：`DecompositionPlan.method_references`（由 F-151 透出，plan 含哪些 method_ref）
     - **事件层**：审计事件 `lkb_method_referenced`（F-151 发射，引用次数与上下文）

     两个来源出现差异时（如字段有值但未发射事件 / 反之），记 `coverage_integrity_warning` 并上报。优先以字段层为权威，事件层用于回放与时序分析。
3. 输出报告：`docs/feature_plan/09-logical-kanban/f-153-coverage-report.json`，包含 hit_rate、top_method_usage、dead_methods、coverage_integrity_warning。

### Phase 6 — 持久化与发现顺序（~0.5 周）

1. `method_library.py` 扩展：
   - `load_method_library(path: Path, *, merge_with: tuple[EngineeringMethod, ...] = METHOD_LIBRARY) -> tuple[EngineeringMethod, ...]`。
   - 加载顺序：项目级 `.lkb/methods/*.json` > 用户级 `~/.cache/clawcodex/lkb/methods/*.json` > 内置种子。
2. 启动时自动加载，错误时 warning 而非崩溃。
3. 文档化：`docs/feature_plan/09-logical-kanban/f-153-method-library-paths.md`。

### Phase 7 — 测试（~1 周）

1. 单元测试：
   - propose_method_from_plan 的字段提取正确性。
   - 状态机转换合法性（非法转换抛异常）。
   - 版本 bump 与不兼容检测。
   - CLI 命令的 happy path + 错误处理。
   - 覆盖率评估器的指标计算。
2. 集成测试：
   - 端到端：完成 plan → propose → approve → 加载 → LLM 引用新 method。
   - 项目级 method 覆盖内置种子的行为。
3. 黄金集测试：
   - 用 stub provider 跑黄金集，验证 hit_rate ≥70%（MVP 目标）。

## 验收标准

- [ ] `propose_method_from_plan()` 从 `DecompositionPlan` 提取 method，结构校验完整。
- [ ] 状态机：`draft → approved/rejected`、`approved → deprecated` 等转换合法。
- [ ] `SemVer` 校验 + 不兼容检测 + 迁移规则实现。
- [ ] CLI 6 个子命令（`list` / `show` / `propose` / `approve` / `reject` / `deprecate` / `coverage`）全部可用。
- [ ] 黄金集 ≥10 个 goal，覆盖率 hit_rate ≥70%（MVP）。
- [ ] 三层加载顺序（项目 / 用户 / 内置）实现，冲突解决：项目级覆盖用户级覆盖内置。
- [ ] 持久化路径在文档中明确：`docs/feature_plan/09-logical-kanban/f-153-method-library-paths.md`。
- [ ] 现有 319 + 13 + F-150/151/152 测试全部通过，无回归。
- [ ] 新增至少 30 个 F-153 单元测试。

## 风险与约束

| 风险 | 缓解 |
|------|------|
| 方法库膨胀失控 | 覆盖率指标 + deprecation workflow；dead_methods 自动告警 |
| 命名冲突 / 重复 method | propose 时校验 method_id 唯一；语义相似度去重延后 |
| 人工审核瓶颈 | LKB 自动化校验先过滤明显低质 method；人工只需 final pass |
| 黄金集过拟合 | 黄金集每季度 review；新方法入库前对黄金集回放 |
| 持久化路径冲突（多用户/多项目） | 用户级 + 项目级 + 内置三层；权限清晰 |
| 方法 deprecation 破坏现有引用 | deprecation 时保留方法 status=deprecated 而非删除；引用自动迁移到 replacement |

## 已拟定的设计决定

1. **人工审核是必经环节**：MVP 不做"自动 approve"。LLM 提议 → LKB 校验 → 人工 final approve。
2. **方法以 JSON 文件持久化**：人类可读 / 可 diff / 可 Git 追踪；不引入数据库。
3. **黄金集作为方法质量的 ground truth**：每个 method approve 前必须对黄金集回放且不降低 hit_rate。
4. **覆盖率指标写入 PROGRESS.md**：每季度更新，作为方法库健康度的关键指标。
5. **方法 deprecation 而非删除**：保留历史，支持回滚与审计。

## 依赖与协同

**依赖**：
- F-150（method_library 基础 API）
- F-151（lkb_method_referenced 审计事件、method_references 字段）
- F-149（DecompositionPlan 用于 propose）

**被依赖**：
- （后续 F-N）方法库作为其他特性的领域知识源

**协同**：
- 与 F-137（persistence audit events）：方法审批事件复用现有 audit pipeline。
- 与 F-141（causal layer）：方法可携带因果约束（subtask A 失败则 subtask B 失效）。
- 与 F-149（automatic task decomposition）：propose 流程的输入。

## 文件变更清单

```
NEW  clawcodex_ext/logical_kanban/method_proposer.py        # ~150 行
NEW  clawcodex_ext/logical_kanban/method_governance.py      # ~280 行（含状态机禁止边校验）
NEW  clawcodex_ext/logical_kanban/method_coverage.py        # ~180 行（双源交叉验证）
NEW  clawcodex_ext/cli/lkb_method_cmd/__init__.py           # ~5 行
NEW  clawcodex_ext/cli/lkb_method_cmd/commands.py           # ~300 行（@register("lkb") + 子命令分发）
MOD  clawcodex_ext/logical_kanban/method_library.py         # +60 行（加载顺序、版本 API）
MOD  clawcodex_ext/cli/subcommand_registry.py               # +3 行（load_builtin_subcommands 注册）
NEW  docs/feature_plan/09-logical-kanban/golden_set.json    # ~50 行
NEW  docs/feature_plan/09-logical-kanban/f-153-method-library-paths.md
NEW  tests/logical_kanban/test_f153_method_governance.py    # ~350 行
```

**注意**：
- **CLI 模块位置**：CLI 注册机制全部在 `clawcodex_ext/cli/`，**不要**新建 `extensions/cli/`（该目录不存在）。本 F-N 遵循 `clawcodex_ext/cli/model_cmd/` / `channels_cmd/` 的多文件子目录模式 + `@register` 装饰器（参考 `auth_cmd.py` 的 `@register("auth")` 用法）。
- **`DecompositionPlan.method_references` 字段**：dataclass 在 `decomposer.py`（不在 `types.py`），由 F-151 已扩展。
- **`lkb_method_referenced` 审计事件**：由 F-151 已在 `audit.py` 定义并发射，本 F-N 复用即可。

## 估算工作量

| 阶段 | 工时 |
|------|------|
| Phase 1 — 提议生成器 | 1 周 |
| Phase 2 — 审批 workflow | 1 周 |
| Phase 3 — 版本管理 | 0.5 周 |
| Phase 4 — CLI 命令 | 1 周 |
| Phase 5 — 覆盖率指标与黄金集 | 1 周 |
| Phase 6 — 持久化与发现 | 0.5 周 |
| Phase 7 — 测试 | 1 周 |
| **总计** | **6 周** |

## 总体里程碑

F-150 → F-151 → F-152 → F-153 顺序执行（部分可并行）：

| 阶段 | 累计工时 | 关键交付 |
|------|---------|---------|
| F-150 | 4 周 | METHOD_LIBRARY 25 条种子 + Layer1RuleEngine method-scope 规则 |
| F-151 | +3 周 | TaskDecompose 注入方法摘要 + 黄金集评估 |
| F-152 | +5 周（可与 F-153 部分并行） | SchedulingSolver + 可选调度集成 |
| F-153 | +6 周（依赖 F-150/151） | Save-as-method + CLI + 覆盖率指标 |

**MVP 总计**：~14 周（含并行）。如需压缩，F-152 可后置，F-153 的黄金集覆盖率初期可放宽至 50%。