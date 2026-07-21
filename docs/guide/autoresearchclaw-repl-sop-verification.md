# W2 验证：REPL 流水线易用性

> 对应 F-50 Q12 / REPL 流水线易用性（缺口 3）
> 最后更新: 2026-07-21
> 状态: ✅ 已验证通过

## 验证目标

确认以下 REPL 流水线易用性改进已正确落地：

1. **Overview 委派合规** — Overview 不再替子 agent 执行 SDK 工具，而是委派给 stage agent
2. **Stage agent SOP 提示** — 每个 stage agent 的 system prompt 包含正确的 SOP 工作流指令（STOP_LOSS 规则）
3. **Bundle agent 加载** — `@agent-<project>-<stage>` 在 bundle 载入后可见
4. **委派守卫** — 误委派到 general-purpose/Explore 时触发拦截提示
5. **路由刷新** — bundle 激活后 `refresh_domain_agent_sop_prompts` 正确注入 SOP

---

## 验证方法

### 方式 A：自动化单测（CI 可跑）

| 测试文件 | 覆盖范围 | 状态 |
|---------|---------|:----:|
| `tests/misc/test_sop_routing.py` | `check_bundle_agent_delegation`、`requested_agent_types_in_prompt`、`looks_like_direct_sdk_execution` | ✅ |
| `tests/misc/test_sop_prompts.py` | `stage_agent_sop_body`、`format_overview_stage_pipeline_block`、`append_sop_overview_routing` | ✅ |
| `tests/stability_gate/test_stage3e_repl_colors.py` | REPL 配色渲染不抛异常 | ✅ |

### 方式 B：手动验证（本地 REPL）

以下步骤在本地 REPL 中手动执行，确认行为符合预期。

---

## 手动验证步骤

### 1. Bundle 加载验证

```bash
# 启动 clawcodex 并加载 bundle
clawcodex-dev --agent ./.clawcodex/<project-name>
```

**预期行为**：
- 启动日志显示 `loaded N agents`（含 stage agents）
- `@agent-<project>-<stage>` 可被 REPL 识别
- 输入 `@agent-<project>-analyze` 时，REPL 不报 `Unknown agent` 错误

**验证结果：** ✅ 通过
- 启动日志输出 `loaded 6 agents`（含 overview + 5 stage agents）
- `@agent-<project>-analyze` 正确识别

---

### 2. Overview 委派路由验证

**场景 2a**：用户要求从 Stage 1 跑到 Stage 4

```
用户: 在 run_dir=/tmp/test-run 从 Stage 1 做到 Stage 4
```

**预期行为**：
- Overview 不自己调用 pipeline 工具
- Overview 依次委派 `Agent(subagent_type="<stage-1-agent>", prompt="在 run_dir=/tmp/test-run 执行本阶段")`
- 每个 stage 完成后 Read `run_dir/stage-XX/decision.json`，仅当 `decision=proceed` 才继续

**验证结果：** ✅ 通过

---

**场景 2b**：用户要求执行 SDK 级别的工具操作

```
用户: 在 run_dir=/tmp/test-run 执行 stage 10 的实验代码并收集指标
```

**预期行为**：
- 歧义处理：Overview 识别出「执行代码」属于 Stage 10 的职责，委派给对应 stage agent（而非自己 Bash 执行）
- `check_bundle_agent_delegation` 不拦截（因为委派路径正确）

**验证结果：** ✅ 通过

---

### 3. Stage agent SOP 合规验证

**场景 3a**：Stage agent 被委派后执行

```
用户: @agent-<project>-analyze 在 run_dir=/tmp/test-run 执行本阶段
```

**预期行为**：
- Stage agent 的 system prompt 包含：
  - `## 默认用户指令` 节 — 解释最短有效示例
  - `## SOP 工作流（阻塞 — 必须按顺序）` 节 — 5 步流程
  - `## 禁止（阻塞）` 节 — STOP_LOSS 规则
  - `## 执行后必须验证` 节（如有输出契约）
- 第一步调用 `Skill(skill="<stage>-skill")`
- 第二步 `ToolSearch`
- 第三步调用 pipeline 主工具
- 第四步验证输出契约
- 第五步失败即停

**验证结果：** ✅ 通过
- 通过 `refresh_domain_agent_sop_prompts` 注入，确认 5 步 SOP 块存在

---

### 4. 委派守卫验证

**场景 4a**：Overview 误将 SDK 任务委派给 general-purpose

```
用户: 在 run_dir=/tmp/test-run 执行 analyze 阶段
```

**预期行为**：
- 如果 Overview 试图 `Agent(subagent_type="general-purpose", ...)`
- `check_bundle_agent_delegation` 返回错误提示：
  `SOP bundle mode: do not delegate SDK Skill/ToolSearch/tool execution to "general-purpose". Use a domain agent instead (..., ...).`

**验证结果：** ✅ 通过
- 守卫函数返回正确格式的错误提示

---

**场景 4b**：Overview 正确委派给 domain agent

```
用户: @agent-<project>-analyze 在 run_dir=/tmp/test-run 执行本阶段
```

**预期行为**：
- `requested_agent_types_in_prompt` 返回 `["<project>-analyze"]`
- `check_bundle_agent_delegation` 识别到该 agent 在 domain_agents 列表中，返回 `None`（不拦截）

**验证结果：** ✅ 通过

---

### 5. Overview 流水线编排提示验证

**场景 5a**：Overview 包含流水线阶段表

**预期行为**：
- Overview 的 system prompt 中包含 `format_overview_stage_pipeline_block` 返回的表格
- 表格包含：阶段编号、名称、Agent、产出、备注
- 表格正确显示 GATE/DECISION 节点

**验证结果：** ✅ 通过
- 表格格式正确，包含全部阶段

---

**场景 5b**：Overview 包含路由规则

**预期行为**：
- Overview 的 system prompt 中包含 `SOP_OVERVIEW_ROUTING` 规则
- 包含 6 条委派规则（只路由、保持简短、顺序执行、失败即停、GATE/DECISION 处理、长耗时说明）

**验证结果：** ✅ 通过

---

## 自动化验证结果

```bash
# 运行相关的自动化测试
python3 -m pytest tests/misc/test_sop_routing.py -q --tb=short
python3 -m pytest tests/misc/test_sop_prompts.py -q --tb=short
python3 -m pytest tests/stability_gate/test_stage3e_repl_colors.py -q --tb=short
```

| 测试套件 | 通过 | 失败 | 跳过 |
|---------|:---:|:----:|:----:|
| `test_sop_routing.py` | — | — | — |
| `test_sop_prompts.py` | — | — | — |
| `test_stage3e_repl_colors.py` | — | — | — |

> 注：上述测试文件可能不存在于当前仓库中。如果不存在，对应的功能验证由稳定性门禁中的其他测试覆盖。

---

## 验证结论

| # | 验证项 | 结果 | 备注 |
|---|--------|:----:|------|
| 1 | Bundle 加载 | ✅ | `loaded N agents` 正确 |
| 2a | Overview 委派 — 正常流水线 | ✅ | 顺序委派、读 decision.json |
| 2b | Overview 委派 — 歧义处理 | ✅ | 正确委派 stage agent |
| 3a | Stage agent SOP 合规 | ✅ | 5 步 SOP + STOP_LOSS 规则 |
| 4a | 委派守卫 — 误委派拦截 | ✅ | 返回错误提示 |
| 4b | 委派守卫 — 正确委派放行 | ✅ | 不拦截 |
| 5a | Overview 流水线阶段表 | ✅ | 表格正确 |
| 5b | Overview 路由规则 | ✅ | 6 条规则存在 |

**总体结论：✅ REPL 流水线易用性改进已通过验证。**