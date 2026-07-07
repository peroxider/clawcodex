# F-151 Prompt-Integrated Method Reuse

## Goal

让 `TaskDecompose` 工具在 system prompt 中注入方法库摘要，引导 LLM **复用方法模板而非凭空生成**，从源头减少幻觉与不一致分解。具体目标：

1. LLM 在分解时优先匹配已注册的 `EngineeringMethod`。
2. LLM 输出中的 `ProposedTask` 携带 `method_ref` 字段（指向具体 method_id），便于后续审计与回溯。
3. 提示词体积可控（<2K tokens 摘要），避免方法库膨胀后撑爆上下文。

## Scope

### In-Scope

- `method_to_prompt_summary()` 函数：把 `EngineeringMethod` 列表压缩为 LLM-friendly 摘要文本。
- 摘要策略：
  - 按 `pattern` 关键字索引（hash 索引，O(1) 查找）。
  - 摘要包含：method_id / pattern / 一句话描述 / 子任务角色序列 / 关键 assumption。
  - 不展开 acceptance_template 全文（LLM 自生成）。
- `TaskDecomposer._system_prompt()` 改造：动态注入摘要。
- `DecompositionPlan` 透出 `method_references: tuple[str, ...]` 字段（去重 method_id 列表）。
- 评估钩子：记录本次分解中 LLM 引用的 method_id 与纯自由生成分解的占比。

### Out-of-Scope

- 方法库的自动扩展（属于 F-153）。
- LLM 端的方法选择策略训练（依赖 prompt + 评估，不做 fine-tune）。
- 多语言摘要（仅英文 + 中文双版本，MVP 阶段按 locale 切换）。

## 当前基线

- F-149 的 `TaskDecomposer._system_prompt()` 是**静态**的，明确告诉 LLM "返回 JSON、不要 markdown"等格式约束，不包含任何领域知识。
- F-149 的 `_build_prompt()` 已经支持 `context` / `acceptance_criteria` / `existing_tasks` 三类输入，但**不包含方法库摘要**。
- LLM 当前在分解时会从零生成 task subject / acceptance criteria，**没有引导锚点**。

## 实施进度

### Phase 1 — 摘要生成器（~0.5 周）

1. 新建 `clawcodex_ext/logical_kanban/method_prompt.py`：
   - `summarize_methods(methods: tuple[EngineeringMethod, ...], *, max_tokens: int = 1800) -> str`。
   - 摘要格式：
     ```
     ## Engineering Methods (use these templates when applicable)
     - [M-add-middleware-001] Add Middleware: design → core impl → integrate → test → docs. Assumes: has-router, has-redis.
     - [M-fix-bug-001] Fix Bug: reproduce → root-cause → fix → regression-test → release-note.
     ...
     ```
   - token 估算：每 method 平均 30 tokens，含 60 methods 仍 <2K tokens。
2. `select_methods_by_pattern(goal: str, library: tuple[EngineeringMethod, ...], *, top_k: int = 10) -> tuple[EngineeringMethod, ...]`：
   - 基于 pattern 关键字的轻量匹配（substring + Levenshtein distance）。
   - 返回 top_k 个最相关 method。

### Phase 2 — Prompt 注入（~0.5 周）

1. `TaskDecomposer.__init__` 新增 `method_library` 参数（默认 `METHOD_LIBRARY`）。
2. `_system_prompt()` 改造：
   - 在 JSON 格式说明之后、goal 描述之前，注入 `select_methods_by_pattern(goal, library) -> summarize_methods(...)`。
   - 添加提示语："If a method below matches your goal, prefer it. Carry `method_ref` in lkbMetadata."
3. `_build_prompt()` 保持不变（用户输入不受影响）。

### Phase 3 — 解析 method_ref（~0.5 周）

1. 扩展 `_extract_and_validate_plan()`：
   - 接受新字段 `lkbMetadata.method_ref`（string，引用 method_id）。
   - 校验 method_ref 必须存在于 `method_library`（否则 warning，不阻断）。
2. **白名单扩展（必做，沿用 F-150 的扩展）**：本 F-N 不再重复扩展 `_LKB_METADATA_KEYS`，依赖 F-150 已在白名单中加入 `"method_ref"` 并扩展 `_validate_lkb_metadata`。实施时需确认 F-150 已合入，否则本 F-N 无法通过解析层。
3. `ProposedTask.lkbMetadata` 透出 `method_ref` 字段（dataclass 字段在 `decomposer.py`）。
4. `DecompositionPlan` 增加 `method_references: tuple[str, ...]` 字段（dataclass 在 `decomposer.py`）。

### Phase 4 — 评估钩子（~0.5 周）

1. `audit.py` 新增事件类型 `lkb_method_referenced`，payload 含 `decomposition_run_id` / `method_id` / `task_count`。
2. `TaskDecomposer.decompose()` 完成后，若 plan 包含 method_ref 则发出事件。
3. 单元测试覆盖事件发射。

### Phase 5 — 测试与评估（~1 周）

1. 单元测试：
   - `summarize_methods` 的 token 数限制。
   - `select_methods_by_pattern` 的关键字匹配。
   - `_system_prompt()` 包含方法摘要。
   - `_extract_and_validate_plan()` 接受 `method_ref` 字段。
   - 审计事件发射。
2. 黄金集评估（手动）：
   - 定义 10 个常见 goal（如"add JWT auth middleware"）。
   - 对比有/无 method 注入的 plan：
     - 方法复用率（method_ref 出现比例）。
     - plan 通过 LKB 校验的比例（应上升）。
     - 重复子任务比例（应下降）。
3. 评估报告写入 `docs/feature_plan/09-logical-kanban/f-151-evaluation-report.md`（实施时撰写）。

## 验收标准

- [ ] `summarize_methods()` 在 60 条 method 时仍 <2K tokens。
- [ ] `select_methods_by_pattern()` 对 "add middleware" 类输入返回相关 method（top-5 命中率 ≥80%）。
- [ ] `_system_prompt()` 注入摘要且不破坏现有 JSON 格式约束。
- [ ] `_extract_and_validate_plan()` 接受 `lkbMetadata.method_ref` 字段，未注册的 method_id 仅 warning。**前置依赖**：F-150 已扩展 `_LKB_METADATA_KEYS` 与 `_validate_lkb_metadata`（详见 `decomposer.py:101-106` 与 `decomposer.py:669-683`）；本 F-N 实施前必须确认 F-150 已合入。
- [ ] `DecompositionPlan.method_references` 字段透出去重 method_id 列表。
- [ ] 审计事件 `lkb_method_referenced` 在 plan 含 method_ref 时发射。
- [ ] 黄金集评估：方法复用率 ≥30%（10 个 goal 中 ≥3 个含 method_ref）。
- [ ] 现有 319 个 logical_kanban 测试 + 13 个 F-149 测试 + F-150 测试全部通过。
- [ ] 新增至少 15 个 F-151 单元测试。

## 风险与约束

| 风险 | 缓解 |
|------|------|
| Prompt 摘要过大撑爆上下文 | token 预算硬限制 + top_k=10 + method 摘要紧凑化 |
| LLM 忽略 method 强行自由发挥 | 不强制；通过评估指标观察，必要时在 prompt 加 "STRONGLY PREFER" |
| method_ref 字段被 LLM 乱填 | 校验 method_id 必须在 method_library 中；不在则 warning |
| 摘要语言切换不当 | MVP 仅英文；中文等通过 locale 参数切换，缺方法时 fallback 英文 |
| 摘要里包含敏感信息 | 种子方法无敏感信息；用户注册方法时通过 lint 校验 |

## 已拟定的设计决定

1. **注入位置在 system prompt 而非 user prompt**：system prompt 优先级高，LLM 更倾向遵循。
2. **method_ref 不强制**：MVP 阶段不阻断 commit；与 F-150 的 warning-only 策略一致。
3. **token 预算硬限制**：摘要超出 2K tokens 时截断（按 score 排序保留 top-k），不阻塞 LLM 调用。
4. **不存储 LLM 与 method 的对应关系**：仅记录引用，不做行为分析（避免过度工程）。

## 依赖与协同

**依赖**：
- F-150（method_library 必须先存在）
- F-149（DecompositionPlan / ProposedTask 数据结构）

**被依赖**：
- F-153（持续沉淀依赖本 F-N 暴露的 method_references 字段与审计事件）

**协同**：
- 与 F-134（fuzzy patterns）：method 摘要本身可能含模糊措辞，摘要生成时调用 `AmbiguityDetector` 过滤严重模糊 method。
- 与 F-144（todowrite fuzzy gate）：method 摘要与 todowrite gate 互补——前者引导分解，后者校验写入。

## 文件变更清单

```
NEW  clawcodex_ext/logical_kanban/method_prompt.py          # ~180 行
MOD  clawcodex_ext/logical_kanban/decomposer.py             # +40 行（prompt 注入 + method_ref 解析 + method_references 字段）
MOD  clawcodex_ext/logical_kanban/audit.py                  # +25 行（lkb_method_referenced 事件）
MOD  clawcodex_ext/tool_system/tools/task_decompose.py      # 无需改动（透传 method_references）
NEW  tests/logical_kanban/test_f151_method_reuse.py         # ~200 行
NEW  docs/feature_plan/09-logical-kanban/f-151-evaluation-report.md  # 评估时撰写
```

**注意**：`ProposedTask.lkbMetadata.method_ref` 与 `DecompositionPlan.method_references` 字段的 dataclass 定义都在 `decomposer.py`，不在 `types.py`。F-150 已在 `decomposer.py` 扩展 `_LKB_METADATA_KEYS` 与 `_validate_lkb_metadata`，本 F-N 不需要重复此步骤。

## 估算工作量

| 阶段 | 工时 |
|------|------|
| Phase 1 — 摘要生成器 | 0.5 周 |
| Phase 2 — Prompt 注入 | 0.5 周 |
| Phase 3 — 解析 method_ref | 0.5 周 |
| Phase 4 — 评估钩子 | 0.5 周 |
| Phase 5 — 测试与评估 | 1 周 |
| **总计** | **3 周** |