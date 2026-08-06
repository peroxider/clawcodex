# ClawCodex 扩展层迁移规划（9 人工作量）

> **文档目的**：把 `clawcodex_ext/`（Layer 1）与 `extensions/`（Layer 2）完整原样迁移到目标位置，由 9 人并行执行；本文档逐层记录每位工人的迁移范围（子目录 + 文件 + 行数 + 测试代码归属）。
>
> **统计口径**：`.py` 行数 = `wc -l <file>`（按换行符计数）；排除 `__pycache__/` 与 `.pyc`。
>
> **数据基线**：`docs/FEATURE_CLUSTERS.md`（2026-07-25 盘点） — 16 个特性分组 / 75 个子目录 / 1,549 个 .py 文件 / 373,037 行 / 13.85 MB；测试代码 `tests/` 约 660+ 个 .py / 280,941 行。
>
> **配套原则**：本文档索引对应 `CLAUDE.md` 中的"二次开发解耦原则"。

## 目录

- [Layer 1 — clawcodex_ext/（下游补丁层）](#layer-1--clawcodex_ext下游补丁层)
  - [1.1 分配概览](#11-分配概览)
  - [1.2 分配原则](#12-分配原则)
  - [1.3 工人工作量明细](#13-工人工作量明细)
    - [W1 — L1-① Agent 核心](#w1--l1①-agent-核心)
    - [W2 — L1-① Command / Query / Bridge / Providers](#w2--l1①-command--query--bridge--providers)
    - [W3 — L1-① Services Group A](#w3--l1①-services-group-a)
    - [W4 — L1-① Services Group B](#w4--l1①-services-group-b)
    - [W5 — L1-② CLI 与入口层](#w5--l1②-cli-与入口层)
    - [W6 — L1-③ TUI / REPL / 前端](#w6--l1③-tui--repl--前端)
    - [W7 — L1-④ 权限/鉴权/钩子](#w7--l1④-权限鉴权钩子)
    - [W8 — L1-⑤ 智能子系统](#w8--l1⑤-智能子系统)
    - [W9 — L1-⑥ 调度/Cron + L1-⑦ 基础设施](#w9--l1⑥-调度cron--l1⑦-基础设施)
  - [1.4 关键约束与执行建议](#14-关键约束与执行建议)
- [Layer 2 — extensions/（三方扩展层）](#layer-2--extensions三方扩展层)
  - [2.1 分配原则（待 L1 完成后启动）](#21-分配原则待-l1-完成后启动)
- [附录 A：合并顺序建议](#附录-a合并顺序建议)
- [附录 B：单文件所有权矩阵](#附录-b单文件所有权矩阵)
- [附录 C：单文件热点（> 2,000 行）清单](#附录-c单文件热点-2000-行清单)
- [附录 D：完整 impl 文件归属矩阵（权威清单）](#附录-d完整-impl-文件归属矩阵逐子目录权威清单)
- [附录 E：每位工程师的"我的文件清单"生成命令](#附录-e每位工程师的我的文件清单生成命令)

---

# Layer 1 — clawcodex_ext/（下游补丁层）

> Layer 1 合计 **7 个特性** / 50 个子目录 / 1,008 个 .py 文件 / **238,491 行实现** + 约 159,643 行测试代码 = **~398,134 行**。
>
> 注：`clawcodex_ext/community_radar/`（L1-⑧）整体归入 Layer 2（L2-⑨），**不在 Layer 1 规划范围**。
>
> 9 人平摊 → 形式上平均 **~26.5K 行/人**；由于 W7 单一小特性 L1-④ 仅有 ~13K impl，**当前实际最大-最小比 ≈ 2.6×**（W7 工作量待后续 Layer 2 规划时补齐，本文档暂不均摊）。

## 1.1 分配概览

| Worker | 主特性 | 负责子目录 | 实现行数 | 测试行数 | **合计** | 跨特性数 |
|---|---|---|---:|---:|---:|---:|
| **W1** | L1-① | `agent/`、`tool_system/`、`remote/` | **34,260** | ~15,371 | **~49,631** | 1 |
| **W2** | L1-① | `command_system/`、`query/`、`bridge/`、`transports/`、`providers/`、`types/` | **34,017** | ~20,356 | **~54,373** | 1 |
| **W3** | L1-① | `services/mcp/`、`voice/`、`channels/`、`im_gateway/` + `buddy/` | **25,294** | ~6,151 | **~31,445** | 1 |
| **W4** | L1-① | `services/{compact,templates,tool_execution,ultraplan,…}` （22 个子目录 + 8 个顶层文件） | **31,175** | ~8,000 | **~39,175** | 1 |
| **W5** | L1-② | `cli/`、`cli_core/`、`entrypoints/`、`daemon/`、`native/`、`runtime/` | **14,540** | ~16,816 | **~31,356** | 1 |
| **W6** | L1-③ | `tui/`、`repl/`、`frontend/`、`diagnostics/`、`debug/` | **33,526** | ~17,406 | **~50,932** | 1 |
| **W7** | L1-④ | `permissions/`、`auth/`、`hooks/`、`bootstrap/` | **12,952** | ~7,369 | **~20,321** | 1 |
| **W8** | L1-⑤ | `skills/`、`context_system/`、`goal/`、`intent_forecast/`、`multimodel/`、`memdir/`、`away_summary/`、`dreaming/`、`coordinator/`、`session_intelligence/`、`logical_kanban/`、`memory/` | **33,887** | ~35,955 | **~69,842** | 1 |
| **W9** | L1-⑥ + L1-⑦ | `utils/`、`cron_system/`、`tasks/`、`configuration/`、`feature_gate/`、`settings/`、`state/`、`orchestrator/`、`messaging/`、`assistant/`、`compact_service/`、`models/` | **18,840** | ~28,150 | **~46,990** | 2 |
| **合计** | — | — | **238,491** | **~155,574** | **~394,065** | — |

**平衡指标（暂不均衡）**：

- 平均工作量：~43.8K / 人（理论值，impl+测试）
- 中位数工作量：~46.9K / 人
- 最大值：W8（~69,842）；最小值：W7（~20,321）
- 最大-最小比：69,842 / 20,321 ≈ **3.44×**（**超出** 2× 软阈值，**待 Layer 2 规划时为 W7 补充分配**）
- 所有工人跨特性数 ≤ 2（符合软约束"最好集中在 1 个特性"）；impl 上 W8 / W7 分别是 L1-⑤ 主力与 L1-④ 唯一承接人，工作量差距本就来自特性体量本身。

**W7 待补齐说明**：

> W7 仅承担 L1-④（权限/鉴权/钩子 + bootstrap），共 ~19K 行，远低于平均。`clawcodex_ext/community_radar/` 已移出 Layer 1，待 Layer 2 规划时为 W7 重新分配（建议在 L2-⑨ Community Radar 子系统分配时把 W7 作为该子特性的负责人，**补齐 ~17K 行**，平衡到 ~36K）。本文档暂不均摊。

## 1.2 分配原则

| # | 原则 | 取舍说明 |
|---|---|---|
| 1 | **L1-① 必须分 4 人** | L1-① 体量 153K 行 = 36%，其中 `services/` 子包占 85K 行（含测试），单工人无法承载 |
| 2 | **同特性优先合并** | L1-②、L1-③、L1-⑤ 各约 38-52K，刚好各占 1 人 |
| 3 | **小特性单独成组（社区雷达已迁出）** | L1-④（19K）由 W7 单独承担；`community_radar/` 已归入 Layer 2（L2-⑨），不再占 W7 配额 |
| 4 | **基础设施合并迁移** | L1-⑥（23K）+ L1-⑦（27K）合并为 W9（50K），共享 `cron` / `native` / `capabilities` 等基础设施 |
| 5 | **Services 按子目录切割** | W3 / W4 按子目录前缀切分（mcp / voice / channels / im_gateway vs 其余），不在文件级别混编 |
| 6 | **单文件热点 ( > 2,000 行) 单独 1 commit / 1 review pass** | 防止巨型文件 refactor 评审疲劳 |
| 7 | **单文件所有权：整目录归属** | 每个 `tests/<dir>/` 与每个 impl 子目录整块归属一名工人，不做文件级拆分；需改他人目录时走反向 PR（归属矩阵 + 流程见附录 B） |

## 1.3 工人工作量明细

> **查你要迁移哪些文件**：本节按特性给出各工人的**子目录级**职责概览；**逐子目录、逐文件的权威归属清单见 [附录 D](#附录-d完整-impl-文件归属矩阵逐子目录权威清单)**（已对全部 `clawcodex_ext/` 子目录做 100% 覆盖校验），测试目录见 [附录 B.3](#附录-b单文件所有权矩阵)。开工前建议用 [附录 E](#附录-e每位工程师的我的文件清单生成命令) 的 `my_files.sh W#` 一键打印自己名下全部 `.py` 文件。

### W1 — L1-① Agent 核心

**目标特性**：L1-①（1 个特性，~34K 实现 + ~15K 测试）

**实现代码（34,260 行 / ~260 文件）**：

| 子目录 | 关键职责 | 行数 |
|---|---|---:|
| `clawcodex_ext/agent/` | 下游 agent 注册表 / 策略原语 / bundled agents | 11,003 |
| `clawcodex_ext/tool_system/` | 工具定义 + 下游 team-aware pool | 22,507 |
| `clawcodex_ext/remote/` | Canonical 远程实现 | 750 |

**测试代码归属（15,371 行）— W1 独占以下目录，其他工人不修改**：

| 测试路径 | 职责 | 行数 | 独占 |
|---|---|---:|---|
| `tests/agent/` | Agent 注册 / 工具池 / 上下文策略 | 6,172 | ✅ |
| `tests/tool/` | Tool system（bash / file / edit / grep） | 5,410 | ✅ |
| `tests/tool_system/` | team_aware_pool / loader | 1,448 | ✅ |
| `tests/remote/` | Remote canonical impl | 1,013 | ✅ |
| `tests/bash/` | **(整目录)** — 含 bash_tool + bash_security | 1,448 | ✅ |
| `tests/sessions/` | **(整目录)** — agent session + storage + security | 1,209 | ✅ |
| `tests/test_agent_name.py` | **(整文件)** — Agent 命名 smoke | 453 | ✅ |

**关键热点文件**：

- `clawcodex_ext/tool_system/tools/agent.py` (1,631)
- `clawcodex_ext/tool_system/tools/bash/bash_tool.py` (1,104)
- `clawcodex_ext/agent/` 多 registry 实现（无单文件 > 1,500 行）

**与其他工人协作点（仅特性级，不涉及文件级）**：

- 与 W2：W1 实现 `clawcodex_ext/tool_system/`，W2 实现的 `clawcodex_ext/providers/` 触发 tool mock —— mock 在 W1 独占的 `tests/tool/` 内，W2 不改 `tests/tool/`，若需新增 mock 由 W2 提需求、W1 接收并开 PR。
- 与 W8：`clawcodex_ext/dreaming/` 引用 `agent_loop` 类型，由 W8 在其 `tests/dreaming/`（W8 独占）内 mock；W1 不动 `tests/dreaming/`。

---

### W2 — L1-① Command / Query / Bridge / Providers

**目标特性**：L1-①（1 个特性，~34K 实现 + ~20K 测试）

**实现代码（34,017 行 / ~270 文件）**：

| 子目录 | 关键职责 | 行数 |
|---|---|---:|
| `clawcodex_ext/command_system/` | Slash 命令注册 + 内置命令 | 10,718 |
| `clawcodex_ext/query/` | 查询引擎主入口 | 6,754 |
| `clawcodex_ext/bridge/` | 多会话桥接 | 6,388 |
| `clawcodex_ext/transports/` | CCR Bridge v2 write transport | 1,283 |
| `clawcodex_ext/providers/` | 下游 provider 扩展 / 模型发现 hooks | 7,493 |

**测试代码归属（20,356 行）— W2 独占以下目录，其他工人不修改**：

| 测试路径 | 职责 | 行数 | 独占 |
|---|---|---:|---|
| `tests/command_system/` | Slash 命令测试 | 2,170 | ✅ |
| `tests/query/` | Query 引擎测试 | 3,158 | ✅ |
| `tests/bridge/` | 多会话桥测试 | 9,801 | ✅ |
| `tests/transports/` | CCR Transport 测试 | 491 | ✅ |
| `tests/provider/` | Provider 注册测试 | 4,736 | ✅ |

**关键热点文件**：

- `clawcodex_ext/query/query.py` **(3,482 行)** — 必须单独 1 commit / 1 review pass
- `clawcodex_ext/command_system/builtins.py` **(2,030 行)** — 必须单独 1 commit / 1 review pass
- `clawcodex_ext/providers/openai_compatible.py` (1,093)

**与其他工人协作点（仅特性级）**：

- 与 W5：`clawcodex_ext/bridge/` 的 hook 入口由 W5 的 CLI 注册；W2 改 `bridge/`，W5 不需触碰 `bridge/`，但若 CLI 路径要新增 slash 命令，W2 提需求 → W5 接 PR（在 W5 独占的 `clawcodex_ext/cli/` 下新增）。
- 与 W1：`tests/tool/` 中的 mock 在 W1 独占；W2 在 `tests/provider/` 中需要 tool mock 时向 W1 提需求。

---

### W3 — L1-① Services Group A

**目标特性**：L1-①（1 个特性，~25K 实现 + ~6K 测试）

**实现代码（25,294 行 / ~125 文件）**：

| 子目录 | 行数 |
|---|---:|
| `clawcodex_ext/services/mcp/` | 8,003 |
| `clawcodex_ext/services/voice/` | 5,960 |
| `clawcodex_ext/services/channels/` | 5,495 |
| `clawcodex_ext/services/im_gateway/` | 4,435 |
| `clawcodex_ext/buddy/` | 1,401 |

**测试代码归属（~6,151 行 / 4 个目录 + 1 文件）— W3 独占，其他工人不修改**：

| 测试路径 | 职责 | 行数 | 独占 |
|---|---|---:|---|
| `tests/mcp/` | **(整目录)** — MCP server / client | 5,063 | ✅ |
| `tests/streaming/` | **(整目录)** — Stream events | 514 | ✅ |
| `tests/proactive/` | **(整目录)** — Proactive 模块 | 293 | ✅ |
| `tests/test_mcp_ext.py` | **(整文件)** — 顶层 mcp_ext smoke | 281 | ✅ |

> **注**：`tests/voice/`（channels/voice + idle/voice）与 `tests/message/`（bridge + messaging）**整目录归 W9**，W3 不再承担。W3 改 `services/voice/`、`services/channels/`、`services/im_gateway/` 源码后，通过 PR 描述通知 W9 在其目录内跟进 mock（反向 PR，见附录 B.5）。

**关键热点文件**：

- `clawcodex_ext/services/mcp/config.py` (1,199) — **本文件归 W3**（在 `services/mcp/` 子目录下）
- `clawcodex_ext/services/channels/wechat_ilink.py` (1,567)
- `clawcodex_ext/services/channels/feishu_app.py` (1,011)

**与其他工人协作点（仅特性级 / 子目录级，不涉及文件级）**：

- 与 W4：**唯一子目录级边界** —— `clawcodex_ext/services/` 下：含 `mcp` / `voice` / `channels` / `im_gateway` / `feishu*` / `wechat*` → **W3 独占**；其他子目录（`compact/` / `templates/` / `tool_execution/` / `ultraplan/` / `analytics/` / `bridge/` / `oauth/` / `swarm/` 等）→ **W4 独占**。两个 worker **互不修改对方的子目录**，跨边界需求由 owner 自己提 PR。
- `clawcodex_ext/services/__init__.py`（聚合 re-export）**由 team lead 在 W3/W4 启动前锁定**，预先列出所有子包；W3 / W4 仅修改各自子目录的 `__init__.py`，**不修改**聚合入口。

---

### W4 — L1-① Services Group B

**目标特性**：L1-①（1 个特性，~31K 实现 + ~10K 测试）

**实现代码（31,175 行 / 22 个 services 子目录 + 8 个 services 顶层文件）**：

> **完整逐目录/逐文件清单见 [附录 D — W4](#附录-d完整-impl-文件归属矩阵逐子目录权威清单)**（含全部 22 个子目录 + `session_*.py` / `cost_*.py` / `pricing.py` / `tail_follower.py` 顶层文件）。规则：**`clawcodex_ext/services/` 下除 W3 前缀（`mcp`/`voice`/`channels`/`im_gateway`）外的全部内容归 W4**。以下列出体量前 4：

| 子目录（前 4，全量见附录 D） | 行数 |
|---|---:|
| `clawcodex_ext/services/compact/` | 3,602 |
| `clawcodex_ext/services/templates/` | 2,784 |
| `clawcodex_ext/services/tool_execution/` | 2,756 |
| `clawcodex_ext/services/ultraplan/` | 2,625 |
| …（其余 18 个子目录 + 8 个顶层文件，共 ~19,408 行，逐项见附录 D） | ~19,408 |

**测试代码归属（~8,000 行 / 1 个整目录）— W4 独占，其他工人不修改**：

| 测试路径 | 职责 | 行数 | 独占 |
|---|---|---:|---|
| `tests/services/` | **(整目录)** — 全部 services 子系统聚合测试（swarm / oauth / advisor / compact / ultraplan / templates / tool_execution / analytics 等） | ~8,000 | ✅ |

> **注**：其余测试目录中对 services 的**间接覆盖**（`tests/away_summary/` 的 templates 渲染 → W8；`tests/provider/`、`tests/cache/`、`tests/cost_tracker/`、`tests/analytics/`、`tests/file_ops/`、`tests/diagnostics/` 的 service 侧断言 → W9/W6）**均不归 W4**，由各目录 owner 整块维护。W4 改 services 源码后通过 PR 描述通知对应 owner 跟进（反向 PR，见附录 B.5）。**W4 只负责 `tests/services/` 一个整目录。**

**关键热点文件**：

- W4 范围内无单文件 > 1,500 行（结构上以中小模块聚合为主）
- 体量分布均匀，无瓶颈文件

**与其他工人协作点（仅特性级 / 子目录级）**：

- 与 W3：**唯一子目录级边界** —— 详见 W3 描述（`services/` 按子目录前缀切割，互不修改对方子目录）。
- 与 W6：`clawcodex_ext/services/templates/` 的渲染模板引用 TUI 主题常量；W4 改 `templates/` 不动 W6 的 `repl_extensions.py`，反之 W6 改 TUI 主题亦不动 `templates/`。如果某主题常量需要从 `templates/` 导出，由 W4 提需求 → W6 接 PR。
- `clawcodex_ext/services/__init__.py` 聚合入口 **由 team lead 锁定**，W4 不修改（详见 W3 协作点）。

---

### W5 — L1-② CLI 与入口层

**目标特性**：L1-②（1 个特性，~14K 实现 + ~16.8K 测试）

**实现代码（14,540 行 / 6 个子目录）— 完整清单见 [附录 D — W5](#附录-d完整-impl-文件归属矩阵逐子目录权威清单)**：

| 子目录 | 关键职责 | 行数 |
|---|---|---:|
| `clawcodex_ext/cli/` | Downstream CLI dispatch（channels_cmd / sop_cmd / lkb_method_cmd / parser / dispatch / runners / runtime_commands 等，整目录） | 9,251 |
| `clawcodex_ext/entrypoints/` | Lazy entrypoint exports（含 `headless.py` 2,564） | 3,108 |
| `clawcodex_ext/native/` | 原生运行时桥接 | 1,191 |
| `clawcodex_ext/runtime/` | 运行时命令实现 | 651 |
| `clawcodex_ext/cli_core/` | Port of `typescript/src/cli/exit.ts` | 268 |
| `clawcodex_ext/daemon/` | F-84 Daemon downstream shim | 71 |

> **注**：`clawcodex_ext/__init__.py` 与顶层 11 个 `.py` 启动入口 **由 team lead 锁定，不归 W5**（见附录 D「团队负责人锁定项」）。W5 只负责上表 6 个子目录。

**测试代码归属（~16,800 行 / 3 个整目录）— W5 独占，其他工人不修改**：

| 测试路径 | 职责 | 行数 | 独占 |
|---|---|---:|---|
| `tests/cli/` | **(整目录)** — CLI dispatch / runners / subcommand | 7,180 | ✅ |
| `tests/runtime/` | **(整目录)** — 运行时命令 | 596 | ✅ |
| `tests/stability_gate/` | **(整目录)** — Stage 1-6 全部（smoke / perf / CLI / REPL 冷启动） | 9,040 | ✅ |

> **注 1**：`tests/command_system/` **整目录归 W2**；W5 不再承担其中 CLI 集成部分（约 1,917 行）。W5 改 CLI dispatch 后如需 command_system 侧断言，向 W2 提反向 PR。
> **注 2**：`tests/skills/` **整目录归 W8**；W5 不再承担其中 CLI 集成部分（约 4,153 行）。
> **注 3**：顶层 `tests/conftest.py`（共享 fixture）**由 team lead 锁定**，所有工人均不修改（见附录 B.1 规则 4）；各测试目录内部的 `conftest.py` 随该目录整块归属。

**关键热点文件**：

- `clawcodex_ext/entrypoints/headless.py` **(2,564 行)** — 必须单独 1 commit / 1 review pass
- `clawcodex_ext/cli/channels_cmd/commands.py` (1,347)
- `clawcodex_ext/cli/sop_cmd/commands.py` (1,274)
- `clawcodex_ext/cli/dispatch.py` (1,144)
- `clawcodex_ext/cli/lkb_method_cmd/commands.py` (752)
- `clawcodex_ext/cli/runtime_commands.py` (517)

**与其他工人协作点（仅特性级）**：

- 与 W8：`clawcodex_ext/cli/skill_cmd/` 注册 skills CLI，由 W2 的 `command_system/` + W5 的 `cli/` 组合接入；W5 不修改 `tests/skills/`，该目录整块归 W8。
- 与 W2：`clawcodex_ext/command_system/` 提供 builtin CLI 命令，W5 的 `cli/` 仅做 dispatch 包装；两者文件不交叉。
- 与 W3：`clawcodex_ext/cli/channels_cmd/` 编排 channels 子命令，调用 W3 实现的 `services/channels/` —— W5 不改 channels 实现，仅在 W5 独占的 `tests/cli/` 中新增 channels mock，由 W3 在 PR 中提需求或 W5 主动联系。

---

### W6 — L1-③ TUI / REPL / 前端

**目标特性**：L1-③（1 个特性，~34K 实现 + ~17.4K 测试）

**实现代码（33,526 行 / ~120 文件）**：

| 子目录 | 行数 |
|---|---:|
| `clawcodex_ext/tui/` | 19,330 |
| `clawcodex_ext/repl/`（含 `core.py` 7,197 行 — **本特性最大迁移风险点**） | 10,043 |
| `clawcodex_ext/frontend/` | 1,844 |
| `clawcodex_ext/debug/` | 1,381 |
| `clawcodex_ext/diagnostics/` | 928 |

**测试代码归属（17,406 行）— W6 独占以下目录，其他工人不修改**：

| 测试路径 | 职责 | 行数 | 独占 |
|---|---|---:|---|
| `tests/repl/` | ClawCodexExtREPL 主测试 | 3,883 | ✅ |
| `tests/tui/` | TUI widgets / app / agent_bridge | 9,421 | ✅ |
| `tests/frontend/` | Frontend plugin registry | 1,669 | ✅ |
| `tests/debug/` | Developer-only debug helpers | 2,433 | ✅ |
| `tests/diagnostics/` | **(整目录)** — Freeze watchdog + services diagnostics | 970 | ✅ |

**关键热点文件**：

- `clawcodex_ext/repl/core.py` **(7,197 行)** — 拆分多个 sub-PR 完成；建议按类 / 函数签名边界拆 3-5 个 PR
- `clawcodex_ext/tui/app.py` (1,957)
- `clawcodex_ext/tui/widgets/prompt_input.py` (1,355)
- `clawcodex_ext/debug/repl_pty_session.py` (1,292)
- `clawcodex_ext/tui/agent_bridge.py` (1,167)
- `clawcodex_ext/frontend/repl_extensions.py` (1,115)

**与其他工人协作点（仅特性级）**：

- 与 W5：`clawcodex_ext/tui/agent_bridge.py` 引用 W5 的 `cli/` 注册的 slash 命令类型；W6 在其独占的 `tests/tui/` 中 mock，W5 不修改 `tests/tui/`。
- 与 W8：`clawcodex_ext/tui/widgets/` 主题渲染引用 `away_summary` 渲染模板常量；W6 修改后，由 W6 在 PR 中通知 W8 检查兼容性；W8 不修改 `tui/`。
- 与 W4：`tests/diagnostics/` 已整目录归 W6（覆盖 freeze + services 两部分）；W4 不修改此目录。

---

### W7 — L1-④ 权限/鉴权/钩子

**目标特性**：L1-④（1 个特性，~13K 实现 + ~7.4K 测试 = **~20K 行**）

**实现代码（12,952 行 / ~50 文件）**：

| 子目录 | 关键职责 | 行数 |
|---|---|---:|
| `clawcodex_ext/permissions/` | 权限引擎 + bash_suggestions + trust_boundary + powershell_security | ~7,742 |
| `clawcodex_ext/auth/` | OAuth / Codex / Gemini / AWS | ~1,551 |
| `clawcodex_ext/hooks/` | Pre/PostToolUse / Stop / Notification | ~3,651 |
| `clawcodex_ext/bootstrap/` | Compatibility facade | ~8 |

> **注**：`clawcodex_ext/community_radar/` **已移出 Layer 1 规划**，整体归入 Layer 2 L2-⑨，由后续 Layer 2 阶段处理（不在 W7 当下工作量中）。

**测试代码归属（~7,369 行 / 5 个整目录）— W7 独占以下目录，其他工人不修改**：

| 测试路径 | 职责 | 行数 | 独占 |
|---|---|---:|---|
| `tests/permissions/` | **(整目录)** — 含 shell_security / danger_detector / handler / classifier / cycle | 3,420 | ✅ |
| `tests/auth/` | **(整目录)** — OAuth 凭证（含 codex 子目录） | 1,057 | ✅ |
| `tests/hooks/` | **(整目录)** — Hook 执行链路 | 1,869 | ✅ |
| `tests/bootstrap/` | **(整目录)** — Bootstrap 兼容 | 535 | ✅ |
| `tests/git_fixtures/` | **(整目录)** — Git 安全测试 | 488 | ✅ |

> **注**：顶层 `tests/conftest.py`（含 permissions fixture）**由 team lead 锁定**，W7 不修改；`tests/permissions/conftest.py` 等目录内 fixture 随 `tests/permissions/` 整块归 W7。

> **注**：`tests/bash/` **整目录归 W1**（bash_tool 主），W7 不再承担其中 bash_security 部分（~724 行），避免文件级协作。W7 改 `clawcodex_ext/permissions/bash_suggestions.py` 后由 W1 在其 PR 中跟进 mock 调整。

**关键热点文件**：

- `clawcodex_ext/hooks/hook_executor.py` (1,330)
- `clawcodex_ext/permissions/check.py` (872)
- `clawcodex_ext/permissions/updates.py` (764)
- `clawcodex_ext/permissions/bash_suggestions.py` (700)
- `clawcodex_ext/hooks/config_manager.py` (584)
- `clawcodex_ext/auth/codex_store.py` (474)

**与其他工人协作点（仅特性级）**：

- 与 W1：`tests/bash/` 整目录归 W1，bash_security 已不在 W7；W7 通过 PR 描述告知 W1 跟进 `clawcodex_ext/permissions/bash_suggestions.py` 变更。
- 与 W4：`tests/services/` 整目录归 W4，其中 oauth/permissions service 测试由 W4 在其 PR 中维护；W7 不动 `tests/services/`。
- 与 W9：`tests/sessions/` 整目录归 W1，session_security 测试已归 W1；W7 不动 `tests/sessions/`。

**工作量说明**：

> W7 当前 ~23K 行（含测试独占扩大）为 9 人中最轻的。后续 **Layer 2 规划（章节 2）启动时，建议将 L2-⑨ Community Radar 子系统（约 ~17K 行）直接分配给 W7**，将其补齐到 ~40K，与其他工人持平。本章节暂不均摊。

---

### W8 — L1-⑤ 智能子系统（12 个子目录）

**目标特性**：L1-⑤（1 个特性，~34K 实现 + ~28K 测试）

**实现代码（33,887 行 / 12 个子目录）— 完整清单见 [附录 D — W8](#附录-d完整-impl-文件归属矩阵逐子目录权威清单)**：

| 子目录 | 行数 |
|---|---:|
| `clawcodex_ext/skills/` | 11,797 |
| `clawcodex_ext/context_system/` | 5,018 |
| `clawcodex_ext/goal/` | 4,366 |
| `clawcodex_ext/intent_forecast/` | 3,178 |
| `clawcodex_ext/multimodel/` | 2,340 |
| `clawcodex_ext/memdir/` | 2,038 |
| `clawcodex_ext/away_summary/` | 1,910 |
| `clawcodex_ext/dreaming/` | 1,837 |
| `clawcodex_ext/coordinator/` | 746 |
| `clawcodex_ext/session_intelligence/` | 359 |
| `clawcodex_ext/logical_kanban/`（compat shim） | 166 |
| `clawcodex_ext/memory/` | 132 |

> **注**：`clawcodex_ext/buddy/`（语音助手）归 **W3**（与 `services/voice`、`services/channels` 同人维护），**不归 W8**。

**测试代码归属（35,955 行）— W8 独占以下目录，其他工人不修改**：

**注**：以下整目录的归属策略避免了跨文件协作；W8 同时承接原分配给 W5 的 `tests/skills/` 整目录（含 skills × cli 部分）。

| 测试路径 | 职责 | 行数 | 独占 |
|---|---|---:|---|
| `tests/away_summary/` | **(整目录)** — 摘要服务（含 services/templates 间接覆盖） | 2,672 | ✅ |
| `tests/dreaming/` | **(整目录)** — 记忆整合（含 im_gateway 间接覆盖） | 2,030 | ✅ |
| `tests/intent_forecast/` | 意图预测 | 1,652 | ✅ |
| `tests/session_intelligence/` | Session sidecar | 61 | ✅ |
| `tests/goal/` | Goal 边界 | 2,980 | ✅ |
| `tests/memdir/` | 记忆目录 | 1,445 | ✅ |
| `tests/context/` | 上下文 | 521 | ✅ |
| `tests/multimodel/` | 多模型调度 | 572 | ✅ |
| `tests/logical_kanban/` | **(整目录)** — LKB 集成（Layer 2 `extensions/lkb/tests/` 独立覆盖，无交叉） | 12,867 | ✅ |
| `tests/coordinator/` | Coordinator mode | 637 | ✅ |
| `tests/advisor/` | Advisor logic | 2,212 | ✅ |
| `tests/skills/` | **(整目录)** — 智能子系统 + skills × cli | 8,306 | ✅ |

**关键热点文件**：

- `clawcodex_ext/context_system/prompt_assembly.py` **(1,669)**
- `clawcodex_ext/away_summary/service.py` (897)
- `clawcodex_ext/goal/evaluator.py` (678)
- `clawcodex_ext/context_system/claude_md.py` (620)
- `clawcodex_ext/goal/service.py` (609)

**与其他工人协作点（仅特性级）**：

- 与 W5：`clawcodex_ext/context_system/prompt_assembly.py` 提供 prompt 类型给 W5 的 CLI；W5 不修改此目录；W8 修改后通知 W5 跟进类型更新。
- 与 W2：`clawcodex_ext/coordinator/` 注册到 W2 的 `command_system/`；W8 不修改 `command_system/`，由 W2 接收 W8 的 type 变更。
- 与 W3：`tests/dreaming/` 整目录归 W8，其中 im_gateway 间接覆盖由 W8 一并维护，不再拆分。
- 与 W4：`tests/away_summary/` 整目录归 W8，services/templates 间接覆盖由 W8 一并维护。
- 与 Layer 2 工人：`tests/logical_kanban/` 整目录归 W8；Layer 2 `extensions/lkb/tests/` 与 W8 通过 lkb 自身契约对接，无文件级交叉。

---

### W9 — L1-⑥ 调度/Cron + L1-⑦ 基础设施

**目标特性**：L1-⑥（主）+ L1-⑦（副），共 **2 个特性**（~18.8K 实现 + ~29K 测试）

**实现代码（18,840 行 / 12 个子目录）— 完整清单见 [附录 D — W9](#附录-d完整-impl-文件归属矩阵逐子目录权威清单)**：

| 特性 | 子目录 | 行数 |
|---|---|---:|
| L1-⑦ | `clawcodex_ext/utils/` | 6,713 |
| L1-⑥ | `clawcodex_ext/cron_system/` | 3,886 |
| L1-⑥ | `clawcodex_ext/tasks/` | 1,985 |
| L1-⑦ | `clawcodex_ext/configuration/` | 1,462 |
| L1-⑥ | `clawcodex_ext/feature_gate/` | 1,172 |
| L1-⑦ | `clawcodex_ext/settings/` | 1,028 |
| L1-⑦ | `clawcodex_ext/state/` | 1,021 |
| L1-⑥ | `clawcodex_ext/orchestrator/` | 539 |
| L1-⑦ | `clawcodex_ext/messaging/` | 384 |
| L1-⑥ | `clawcodex_ext/assistant/` | 265 |
| L1-⑥ | `clawcodex_ext/compact_service/` | 239 |
| L1-⑥ | `clawcodex_ext/models/` | 146 |

> **注**：`clawcodex_ext/types/` 归 **W2**、`clawcodex_ext/native/` 归 **W5**、`clawcodex_ext/constants/` 与 `clawcodex_ext/capabilities/` 由 **team lead 锁定**（见附录 D），均**不归 W9**。`clawcodex_ext/agent_mention/` 为空目录，跳过。

**测试代码归属（~16,700 行 / 25 个整目录）— W9 独占以下目录，其他工人不修改**：

**注**：原 L1-⑥/L1-⑦ 部分归属测试目录（如 `tests/voice/`、`tests/messaging/`、`tests/abort/`）已改为整目录归属 W9，避免文件级拆分；`tests/diagnostics/` 归 W6（其 `clawcodex_ext/diagnostics/` impl owner），不在 W9。

| 特性 | 测试路径 | 职责 |
|---|---|---|
| L1-⑥ | `tests/cron/` | 整目录归 W9（分布式锁 Cron） |
| L1-⑥ | `tests/tasks/` | 整目录归 W9（BG_SESSIONS） |
| L1-⑥ | `tests/feature_gate/` | 整目录归 W9（Feature Gate） |
| L1-⑥ | `tests/compact/` | 整目录归 W9（compact_service 测试 + services/compact 间接测试） |
| L1-⑥ | `tests/assistant/` | 整目录归 W9（Assistant shim） |
| L1-⑥ | `tests/fast/` | 整目录归 W9（Fast mode） |
| L1-⑥ | `tests/ide/` | 整目录归 W9（IDE 集成） |
| L1-⑥ | `tests/model/` | 整目录归 W9（Model 注册） |
| L1-⑥ | `tests/voice/` | 整目录归 W9（idle/voice + channels/voice 全收） |
| L1-⑦ | `tests/config/` | 整目录归 W9（配置发现） |
| L1-⑦ | `tests/cache/` | 整目录归 W9（Cache 工具） |
| L1-⑦ | `tests/cost_tracker/` | 整目录归 W9（成本追踪） |
| L1-⑦ | `tests/file_ops/` | 整目录归 W9（File ops） |
| L1-⑦ | `tests/utils/` | 整目录归 W9（utils 测试） |
| L1-⑦ | `tests/state/` | 整目录归 W9（app_state） |
| L1-⑦ | `tests/messaging/` | 整目录归 W9（messaging） |
| L1-⑦ | `tests/message/` | 整目录归 W9（bridge + messaging 全收） |
| L1-⑦ | `tests/image/` | 整目录归 W9（图片处理） |
| L1-⑦ | `tests/input/` | 整目录归 W9（输入处理） |
| L1-⑦ | `tests/system_prompt/` | 整目录归 W9（系统提示组装） |
| L1-⑦ | `tests/snapshot/` | 整目录归 W9（快照测试） |
| L1-⑦ | `tests/signal_tests/` | 整目录归 W9（信号测试） |
| L1-⑦ | `tests/provider/` | 整目录归 W9（F-43 单测） |
| L1-⑦ | `tests/release_smoke/` | 整目录归 W9（发布烟雾测试） |
| L1-⑦ | `tests/ci/` | 整目录归 W9（CI 集成） |
| L1-⑦ | `tests/abort/` | 整目录归 W9（utils + agent_loop） |
| L1-⑦ | `tests/token_tests/` | 整目录归 W9（Token 单测） |
| L1-⑦ | `tests/output/` | 整目录归 W9（输出格式） |
| L1-⑦ | `tests/analytics/` | 整目录归 W9（分析收集） |

> **测试总行数说明**：W9 独占的所有整目录（含 L1-⑥ + L1-⑦）合计 ≈ 17,000 行测试代码（具体行数详见 `find tests/{dir} -name "*.py" | xargs wc -l` 实际统计）。

**关键热点文件**：

- `clawcodex_ext/utils/advisor.py` (850)
- `clawcodex_ext/configuration/service.py` (786)
- `clawcodex_ext/utils/at_file_completer.py` (769)
- `clawcodex_ext/settings/types.py` (623)
- `clawcodex_ext/state/app_state.py` (607)
- `clawcodex_ext/utils/image_processor.py` (556)
- `clawcodex_ext/cron_system/tasks.py` (558)
- `clawcodex_ext/cron_system/scheduler.py` (557)

**与其他工人协作点（仅特性级）**：

- 与 W1：W9 拥有 `clawcodex_ext/` 的 `session_storage` 实现，但 `tests/sessions/` **整目录归 W1**；W9 改 session_storage 源码后通过 PR 描述通知 W1，由 W1 在 `tests/sessions/` 内跟进 mock / 断言（反向 PR，见附录 B.5）。
- 与 W3：`tests/voice/`（2,493）整目录归 W9；W3 不再拆分 channels/voice 与 idle/voice 部分。
- 与 W4：`tests/compact/`（2,136）整目录归 W9；W4 原 `services/compact/` 间接覆盖由 W9 在整目录中处理。W9 改 `clawcodex_ext/compact_service/` 后通知 W4 跟进兼容性。
- 与 W5：`tests/runtime/`（596）整目录归 W5（CLI 集成）；W9 不修改。
- 与 W7：`clawcodex_ext/settings/` 被 `bootstrap/` 反向依赖；W9 改 settings 后通知 W7 跟进 bootstrap 兼容性；`tests/abort/` 整目录归 W9（含原 W7 的 permissions.security abort 部分，由 W9 一并维护）。

## 1.4 关键约束与执行建议

### 单文件所有权原则（核心约束）

**所有测试目录整块归属一名工人；所有 impl 子目录整块归属一名工人。** 任何需要修改他人所属目录的 PR，必须经该目录所有者提反向 PR，不要直接编辑（流程见 [附录 B.5](#b5-反向-pr-流程)）。

> 完整归属见 [附录 B 单文件所有权矩阵](#附录-b单文件所有权矩阵) —— 逐目录列出每个 `tests/` 目录与 impl 子目录的唯一归属人。

### 仅有的三处受控例外（均非文件级混编）

| 例外 | 涉及工人 | 处理方式 |
|---|---|---|
| **`clawcodex_ext/services/` 子目录前缀切割** | W3 ↔ W4 | W3 独占 `services/{mcp,voice,channels,im_gateway,feishu*,wechat*}/`；W4 独占其余服务子目录。二者按**子目录**切，不在文件级别混编。聚合入口 `services/__init__.py` 由 team lead 在 W3/W4 开工前锁定（预填全部子包 re-export），W3/W4 均不修改。 |
| **`clawcodex_ext/__init__.py` + 顶层 11 个 `.py` 启动入口** | 整 `clawcodex_ext/` 入口 | 由 team lead 在所有工人开工前锁定（仅做 re-export 调整），9 名工人均**不修改**该入口。 |
| **顶层 `tests/conftest.py` 共享 fixture** | 全体工人共用 | 由 team lead 锁定；各测试目录内部的 `conftest.py` 随该目录整块归属其 owner，无需锁定。 |

### 文件级协作点已全部消除（变更说明）

原设计中存在 9 处测试目录在工人之间按文件拆分，现已全部转为整目录归属，映射如下：

| 测试目录 | 现归属（整块） | 原归属（文件级拆分） |
|---|---|---|
| `tests/skills/` (8,306) | **W8** | W5（CLI 集成）+ W8（智能） |
| `tests/bash/` (1,448) | **W1** | W1（bash_tool）+ W7（bash_security） |
| `tests/sessions/` (1,209) | **W1** | W1（agent）+ W7（security）+ W9（storage） |
| `tests/abort/` (2,326) | **W9** | W1（agent_loop）+ W9（utils） |
| `tests/message/` (1,166) | **W9** | W3（bridge）+ W9（messaging） |
| `tests/voice/` (2,493) | **W9** | W3（channels）+ W9（idle） |
| `tests/dreaming/` (2,030) | **W8** | W3（im_gateway）+ W8（智能） |
| `tests/compact/` (2,136) | **W9** | W4（services/compact）+ W9（compact_service） |
| `tests/logical_kanban/` (12,867) | **W8** | W8 + Layer 2（LKB 内测） |

**净效果**：原 9 处文件级协作全部消除；当前仅剩上表两类"特性间协作"（`services/` 子目录切割 + `clawcodex_ext` 入口锁定），且都已锁定具体负责人，不存在两名工人编辑同一文件的情况。

### 单文件热点风险（详见附录 C）

- `clawcodex_ext/repl/core.py` (7,197) — W6 — **建议拆 3-5 个 sub-PR**
- `clawcodex_ext/query/query.py` (3,482) — W2
- `clawcodex_ext/entrypoints/headless.py` (2,564) — W5
- `clawcodex_ext/command_system/builtins.py` (2,030) — W2

### 目录归属核对流程

因所有测试目录整块归属，无需按文件拆分；提交 PR 前只需用下列命令核对目录行数与归属人，避免误领养：

```bash
# 列出每个测试目录的行数，对照附录 B 归属表核对
find tests -mindepth 1 -maxdepth 1 -type d \
  -exec sh -c 'echo "{}: $(find {} -name "*.py" | xargs wc -l 2>/dev/null | tail -1)"' \; \
  | sort
```

完整归属见 [附录 B：单文件所有权矩阵](#附录-b单文件所有权矩阵)。

### 社区雷达（已迁出 Layer 1）

`clawcodex_ext/community_radar/` **不再属于 Layer 1 规划**，整体目标路径为 `extensions/community_radar/`（L2-⑨），由 Layer 2 阶段处理。Layer 1 阶段 **不修改** 该目录，也 **不** 由 W7 在 Layer 1 阶段处理 `clawcodex_ext/cli/subcommand_registry.py:91` 的引用迁移 —— 该引用将随 Layer 2 阶段一并处理。

---

# Layer 2 — extensions/（三方扩展层）

> **状态**：待 Layer 1 迁移完成后启动（用户已确认先 L1 后 L2 的顺序）。
>
> Layer 2 合计 8+1 个特性（含 L2-⑨ 待迁入）/ 24 个子目录 / 503 个 .py 文件 / 130,425 行实现 + ~60,747 行测试代码 = **~191,172 行**（不含 L2-⑨）。
>
> 9 人平摊 → 平均 **~21K 行/人**，最大-最小比 ≈ 1.3×。
>
> 详细的 9 人分配将在 L1 迁移完成的复盘基础上重新设计（届时考虑 L1 迁移后是否重组 services / 重新切割 L2 子系统边界）。

## 2.1 分配原则（待 L1 完成后启动）

1. **L2-① Orchestrator（47K）是大头**，可能拆 2-3 人
2. **L2-② SOP（30K）+ L2-③ LKB（20K）各 1 人**
3. **L2-④ / L2-⑤ / L2-⑥ / L2-⑦ / L2-⑧ 共 ~33K**，合并 3 人
4. **L2-⑨ Community Radar** `clawcodex_ext/community_radar/`（~17K 行 = 15,098 impl + 2,500 tests）整体迁入 `extensions/community_radar/`，由 W7 在 Layer 2 阶段承担，补齐 W7 的工作量缺口到 ~36K 行

具体的 9 人工作量明细将在本节追加更新，模板如下：

```markdown
### W7 — L2-⑨ Community Radar 迁入
**目标路径**：`clawcodex_ext/community_radar/` → `extensions/community_radar/`
**实现代码（15,098 行 / 38 文件）**：（详细列表待启动时罗列）
**测试代码（2,500 行 / 4 个内嵌测试文件）**：（详细列表待启动时罗列）
...
```

W7 在 Layer 2 阶段的具体工作量会在 L1 完成后重新评估（参考 §1.3 W7 的"待补齐说明"）。

---

# 附录 A：合并顺序建议

为避免 import 链冲突，建议两批合并（L1 已不包含 community_radar，无需第一批卸包袱）：

| 批次 | 工人 | 内容 | 目标 |
|---|---|---|---|
| **第一批**（并行） | W1 / W2 / W5 / W6 / W7 / W8 / W9 | agent / command/query/bridge/providers / CLI / TUI / 权限/钩子 / 智能子系统 / cron/utils | 并行 7 条 PR，互不依赖 |
| **第二批**（最后合并） | W3 + W4 | services Group A（mcp/voice/channels/im_gateway）+ services Group B（compact/templates/tool_execution/ultraplan/swarm 等） | services 是被 L1-① 多模块反向依赖的"水电网"，必须最后合 |

---

# 附录 B：单文件所有权矩阵

## B.1 单文件所有权规则

1. **每个 impl 子目录整块归属一名工人** —— 各工人在自己所属子目录内可自由修改任何文件。
2. **每个 `tests/<dir>/` 整块归属一名工人** —— 不允许两名工人修改同一测试目录内的不同文件。
3. **需要修改他人所属目录时**，必须通过该目录所有者的反向 PR 提交（见 B.5），**不要直接修改**。
4. **`clawcodex_ext/__init__.py`、顶层 11 个 `.py`、`services/__init__.py`、顶层 `tests/conftest.py` 由 team lead 锁定** —— 任何工人均不修改（目录内部的 `conftest.py` 随该目录整块归属）。
5. **层间引用约定** —— 工人改完源码后通过 PR 描述 / 通知告知引用方，由引用方自行跟进兼容性。

违反上述规则的 PR 必须在 review 阶段被驳回并要求拆分。

## B.2 所有权核对命令

```bash
# 列出每个测试目录归属 / 行数，作为 PR 提交时的核对依据
find tests -mindepth 1 -maxdepth 1 -type d \
  -exec sh -c 'echo "{}: $(find {} -name "*.py" | xargs wc -l 2>/dev/null | tail -1)"' \; \
  | sort
```

## B.3 测试目录所有权矩阵（完整）

| 测试目录 | 行数 | **归属（独占）** |
|---|---:|---|
| `tests/agent/` | 6,172 | **W1** |
| `tests/tool/` | 5,410 | **W1** |
| `tests/tool_system/` | 1,448 | **W1** |
| `tests/remote/` | 1,013 | **W1** |
| `tests/bash/` | 1,448 | **W1** |
| `tests/sessions/` | 1,209 | **W1** |
| `tests/command_system/` | 2,170 | **W2** |
| `tests/query/` | 3,158 | **W2** |
| `tests/bridge/` | 9,801 | **W2** |
| `tests/transports/` | 491 | **W2** |
| `tests/provider/` | 4,736 | **W2** |
| `tests/mcp/` | 5,063 | **W3** |
| `tests/test_mcp_ext.py` | 281 | **W3** |
| `tests/proactive/` | 293 | **W3** |
| `tests/streaming/` | 514 | **W3** |
| `tests/services/` | 8,000+ | **W4**（独立 stub） |
| `tests/cli/` | 7,180 | **W5** |
| `tests/runtime/` | 596 | **W5** |
| `tests/stability_gate/` | 9,040 | **W5** |
| `tests/repl/` | 3,883 | **W6** |
| `tests/tui/` | 9,421 | **W6** |
| `tests/frontend/` | 1,669 | **W6** |
| `tests/debug/` | 2,433 | **W6** |
| `tests/diagnostics/` | 970 | **W6** |
| `tests/permissions/` | 3,420 | **W7** |
| `tests/auth/` | 1,057 | **W7** |
| `tests/hooks/` | 1,869 | **W7** |
| `tests/bootstrap/` | 535 | **W7** |
| `tests/git_fixtures/` | 488 | **W7** |
| `tests/away_summary/` | 2,672 | **W8** |
| `tests/dreaming/` | 2,030 | **W8** |
| `tests/intent_forecast/` | 1,652 | **W8** |
| `tests/session_intelligence/` | 61 | **W8** |
| `tests/goal/` | 2,980 | **W8** |
| `tests/memdir/` | 1,445 | **W8** |
| `tests/context/` | 521 | **W8** |
| `tests/multimodel/` | 572 | **W8** |
| `tests/logical_kanban/` | 12,867 | **W8** |
| `tests/coordinator/` | 637 | **W8** |
| `tests/advisor/` | 2,212 | **W8** |
| `tests/skills/` | 8,306 | **W8** |
| `tests/abort/` | 2,326 | **W9** |
| `tests/message/` | 1,166 | **W9** |
| `tests/voice/` | 2,493 | **W9** |
| `tests/messaging/` | 279 | **W9** |
| `tests/cron/` | 4,618 | **W9** |
| `tests/tasks/` | 3,000 | **W9** |
| `tests/feature_gate/` | 1,167 | **W9** |
| `tests/compact/` | 2,136 | **W9** |
| `tests/assistant/` | 478 | **W9** |
| `tests/fast/` | 256 | **W9** |
| `tests/ide/` | 210 | **W9** |
| `tests/model/` | 271 | **W9** |
| `tests/config/` | 1,296 | **W9** |
| `tests/cache/` | 576 | **W9** |
| `tests/cost_tracker/` | 528 | **W9** |
| `tests/file_ops/` | 307 | **W9** |
| `tests/utils/` | 813 | **W9** |
| `tests/state/` | 656 | **W9** |
| `tests/image/` | 471 | **W9** |
| `tests/input/` | 1,858 | **W9** |
| `tests/system_prompt/` | 828 | **W9** |
| `tests/snapshot/` | 274 | **W9** |
| `tests/signal_tests/` | 165 | **W9** |
| `tests/provider/` | 1,876 | **W9** |
| `tests/release_smoke/` | 260 | **W9** |
| `tests/ci/` | 888 | **W9** |
| `tests/token_tests/` | 743 | **W9** |
| `tests/output/` | 207 | **W9** |
| `tests/analytics/` | 118 | **W9** |

> **说明**：以上测试目录已 100% 整目录归属，不存在跨工人修改同一目录的情况。行数为估算，PR 提交时以 B.2 命令实际统计为准。

## B.4 impl 子目录所有权矩阵（参考）

> impl 子目录的归属见 §1.3 各 W 段的"实现代码"表；impl 子目录天然为整块归属，不存在跨文件拆分。

**唯一特例**：`clawcodex_ext/services/` 由 W3 / W4 按**子目录前缀**切割（详见 §1.3 W3 / W4 段与 §1.4 例外表）。聚合入口 `services/__init__.py` 由 team lead 锁定。

## B.5 反向 PR 流程

当工人 A 需要修改工人 B 所属目录的内容时（例如 W3 改完源码后，需要 W2 在 `tests/provider/` 增补 mock）：

1. **A 在自己的 PR 中明确说明需要 B 同步的内容** —— 给出文件路径 + 行号 + 期望变更描述。
2. **B 收到通知后，在自己拥有的目录中开反向 PR** —— 该 PR 由 B 提交，merge 顺序由 team lead 协调。
3. **层间（Layer 1 ↔ Layer 2）反向 PR 需求**（如 LKB shim ↔ `extensions/lkb/`）由相关工人与 Layer 2 工人协调，team lead 仲裁 merge 顺序。

---

# 附录 C：单文件热点（> 2,000 行）清单

| 文件 | 行数 | Worker | 备注 |
|---|---:|---|---|
| `clawcodex_ext/repl/core.py` | **7,197** | W6 | **最大风险点**；建议拆 3-5 个 sub-PR |
| `clawcodex_ext/query/query.py` | 3,482 | W2 | 必须单独 1 commit / 1 review pass |
| `clawcodex_ext/cli/issue.py` （`extensions/`） | 3,269 | （Layer 2） | — |
| `extensions/orchestrator/orchestrator.py` | 4,729 | （Layer 2） | — |
| `extensions/sop_converter/runtime/tool_registry_bridge.py` | 3,557 | （Layer 2） | — |
| `extensions/orchestrator/agent_runner.py` | 3,033 | （Layer 2） | — |
| `clawcodex_ext/entrypoints/headless.py` | 2,564 | W5 | 必须单独 1 commit / 1 review pass |
| `clawcodex_ext/command_system/builtins.py` | 2,030 | W2 | 必须单独 1 commit / 1 review pass |

**拆分建议**：

- `core.py` (7,197) — 按类 / 函数签名边界拆 3-5 个 PR：
  - PR-1: imports + class skeleton (~1,500 行)
  - PR-2: setup / config methods (~1,500 行)
  - PR-3: run loop / event loop (~2,000 行)
  - PR-4: command registration + helpers (~2,000 行)
  - PR-5: 测试 import / 依赖 (~200 行)
- `query.py` / `headless.py` / `builtins.py` — 各拆 2 个 sub-PR（前 1,500 / 后剩余）

---

# 附录 D：完整 impl 文件归属矩阵（逐子目录，权威清单）

> **本附录是"谁迁移哪些文件"的唯一权威来源。** 已对 `clawcodex_ext/` 全部 53 个非空子目录 + `services/` 27 个子目录 + `services/` 8 个顶层文件做 **100% 覆盖校验**（无遗漏、无重复归属）。每位工程师负责的文件 = **本附录中自己名下所有路径下的全部 `.py` 文件** + [附录 B.3](#附录-b单文件所有权矩阵) 中自己名下的全部测试目录。
>
> 校验命令：`python3` 脚本对比 `clawcodex_ext/*/` 实际目录与本表，`UNASSIGNED=NONE, PHANTOM=NONE`。

### W1 — L1-① Agent 核心（impl 合计 34,260 行 / 3 项）

| 归属路径 | 行数 |
|---|---:|
| `clawcodex_ext/tool_system/` | 22,507 |
| `clawcodex_ext/agent/` | 11,003 |
| `clawcodex_ext/remote/` | 750 |

### W2 — L1-① Command/Query/Bridge/Providers（impl 合计 34,017 行 / 6 项）

| 归属路径 | 行数 |
|---|---:|
| `clawcodex_ext/command_system/` | 10,718 |
| `clawcodex_ext/providers/` | 7,493 |
| `clawcodex_ext/query/` | 6,754 |
| `clawcodex_ext/bridge/` | 6,388 |
| `clawcodex_ext/types/` | 1,381 |
| `clawcodex_ext/transports/` | 1,283 |

### W3 — L1-① Services Group A + Buddy（impl 合计 25,294 行 / 5 项）

| 归属路径 | 行数 |
|---|---:|
| `clawcodex_ext/services/mcp/` | 8,003 |
| `clawcodex_ext/services/voice/` | 5,960 |
| `clawcodex_ext/services/channels/` | 5,495 |
| `clawcodex_ext/services/im_gateway/` | 4,435 |
| `clawcodex_ext/buddy/` | 1,401 |

### W4 — L1-① Services Group B（impl 合计 31,175 行 / 30 项）

| 归属路径 | 行数 |
|---|---:|
| `clawcodex_ext/services/compact/` | 3,602 |
| `clawcodex_ext/services/templates/` | 2,784 |
| `clawcodex_ext/services/tool_execution/` | 2,756 |
| `clawcodex_ext/services/ultraplan/` | 2,625 |
| `clawcodex_ext/services/lodestone/` | 2,413 |
| `clawcodex_ext/services/chrome/` | 2,327 |
| `clawcodex_ext/services/skill_search/` | 1,934 |
| `clawcodex_ext/services/swarm/` | 1,681 |
| `clawcodex_ext/services/context_collapse/` | 1,522 |
| `clawcodex_ext/services/api/` | 1,244 |
| `clawcodex_ext/services/computer_use/` | 1,103 |
| `clawcodex_ext/services/langfuse/` | 933 |
| `clawcodex_ext/services/kairos/` | 727 |
| `clawcodex_ext/services/session_storage.py` | 654 |
| `clawcodex_ext/services/pipe_ipc/` | 559 |
| `clawcodex_ext/services/monitor/` | 545 |
| `clawcodex_ext/services/proactive/` | 497 |
| `clawcodex_ext/services/session_migrate.py` | 473 |
| `clawcodex_ext/services/ide/` | 439 |
| `clawcodex_ext/services/pricing.py` | 398 |
| `clawcodex_ext/services/session_resume.py` | 370 |
| `clawcodex_ext/services/cost_restore.py` | 267 |
| `clawcodex_ext/services/analytics/` | 248 |
| `clawcodex_ext/services/cost_tracker.py` | 248 |
| `clawcodex_ext/services/bridge/` | 233 |
| `clawcodex_ext/services/periodic/` | 164 |
| `clawcodex_ext/services/feature_gate/` | 141 |
| `clawcodex_ext/services/tail_follower.py` | 133 |
| `clawcodex_ext/services/session_title.py` | 104 |
| `clawcodex_ext/services/oauth/` | 51 |

### W5 — L1-② CLI 与入口层（impl 合计 14,540 行 / 6 项）

| 归属路径 | 行数 |
|---|---:|
| `clawcodex_ext/cli/` | 9,251 |
| `clawcodex_ext/entrypoints/` | 3,108 |
| `clawcodex_ext/native/` | 1,191 |
| `clawcodex_ext/runtime/` | 651 |
| `clawcodex_ext/cli_core/` | 268 |
| `clawcodex_ext/daemon/` | 71 |

### W6 — L1-③ TUI/REPL/前端（impl 合计 33,526 行 / 5 项）

| 归属路径 | 行数 |
|---|---:|
| `clawcodex_ext/tui/` | 19,330 |
| `clawcodex_ext/repl/` | 10,043 |
| `clawcodex_ext/frontend/` | 1,844 |
| `clawcodex_ext/debug/` | 1,381 |
| `clawcodex_ext/diagnostics/` | 928 |

### W7 — L1-④ 权限/鉴权/钩子（impl 合计 12,952 行 / 4 项）

| 归属路径 | 行数 |
|---|---:|
| `clawcodex_ext/permissions/` | 7,742 |
| `clawcodex_ext/hooks/` | 3,651 |
| `clawcodex_ext/auth/` | 1,551 |
| `clawcodex_ext/bootstrap/` | 8 |

### W8 — L1-⑤ 智能子系统（impl 合计 33,887 行 / 12 项）

| 归属路径 | 行数 |
|---|---:|
| `clawcodex_ext/skills/` | 11,797 |
| `clawcodex_ext/context_system/` | 5,018 |
| `clawcodex_ext/goal/` | 4,366 |
| `clawcodex_ext/intent_forecast/` | 3,178 |
| `clawcodex_ext/multimodel/` | 2,340 |
| `clawcodex_ext/memdir/` | 2,038 |
| `clawcodex_ext/away_summary/` | 1,910 |
| `clawcodex_ext/dreaming/` | 1,837 |
| `clawcodex_ext/coordinator/` | 746 |
| `clawcodex_ext/session_intelligence/` | 359 |
| `clawcodex_ext/logical_kanban/` | 166 |
| `clawcodex_ext/memory/` | 132 |

### W9 — L1-⑥⑦ 调度/基础设施（impl 合计 18,840 行 / 12 项）

| 归属路径 | 行数 |
|---|---:|
| `clawcodex_ext/utils/` | 6,713 |
| `clawcodex_ext/cron_system/` | 3,886 |
| `clawcodex_ext/tasks/` | 1,985 |
| `clawcodex_ext/configuration/` | 1,462 |
| `clawcodex_ext/feature_gate/` | 1,172 |
| `clawcodex_ext/settings/` | 1,028 |
| `clawcodex_ext/state/` | 1,021 |
| `clawcodex_ext/orchestrator/` | 539 |
| `clawcodex_ext/messaging/` | 384 |
| `clawcodex_ext/assistant/` | 265 |
| `clawcodex_ext/compact_service/` | 239 |
| `clawcodex_ext/models/` | 146 |

### 团队负责人锁定项（不属于任何工人）

| 归属路径 | 行数 | 说明 |
|---|---:|---|
| `clawcodex_ext/__init__.py` + 顶层 11 个 `.py`（`init.py` / `config.py` / `_version.py` / `llm.py` / `mcp_ext.py` / `task_registry.py` / `tasks_core.py` / `telemetry_lifecycle.py` / `tool_stats.py` / `outputStyles.py`） | 1,800 | 启动入口，team lead 锁定，仅做 re-export |
| `clawcodex_ext/services/__init__.py` | 1 | services 聚合入口，team lead 预填全部子包 re-export |
| `clawcodex_ext/capabilities/` | 145 | Layer 1→2 Protocol 契约边界，team lead 锁定（改动需全员评审） |
| `clawcodex_ext/constants/` | 64 | 全局共享常量，被各处 import，team lead 锁定 |
| `clawcodex_ext/agent_mention/` | 0 | 空目录，跳过 |

### 迁出 Layer 1（Layer 2 处理）

| 归属路径 | 行数 | 说明 |
|---|---:|---|
| `clawcodex_ext/community_radar/` | 15,098 | 已迁出 Layer 1，整体归 L2-⑨，由 Layer 2 阶段处理 |

### impl 归属汇总（L1 九人）

| 工人 | impl 行数 |
|---|---:|
| W1 | 34,260 |
| W2 | 34,017 |
| W3 | 25,294 |
| W4 | 31,175 |
| W5 | 14,540 |
| W6 | 33,526 |
| W7 | 12,952 |
| W8 | 33,887 |
| W9 | 18,840 |
| **L1 impl 合计** | **238,491** |
| team lead 锁定 | 2,009 |
| 迁出 L2（community_radar） | 15,098 |

> **说明**：W5 / W7 / W9 impl 行数偏低（12K–18K），因其 impl 体量本就小；三人的总工作量由**测试目录**补齐（见附录 B.3：W5 独占 16.8K 测试、W9 独占 25 个测试目录），且 W7 在 Layer 2 阶段承接 L2-⑨（community_radar 15K）。本阶段按用户要求**不强行补齐 impl 行数**。

---

# 附录 E：每位工程师的"我的文件清单"生成命令

任何工程师在开工前，运行以下命令即可打印**自己需要迁移的全部具体文件**（impl + 测试），逐一列出、可直接核对：

```bash
#!/usr/bin/env bash
# 用法: ./my_files.sh W8
W="$1"

# 1) impl 目录（来自附录 D）
case "$W" in
  W1) IMPL="agent tool_system remote" ;;
  W2) IMPL="command_system providers query bridge types transports" ;;
  W3) IMPL="services/mcp services/voice services/channels services/im_gateway buddy" ;;
  W4) IMPL="services" ; W4_EXCLUDE="mcp voice channels im_gateway" ;;   # services 下除 W3 前缀外全部
  W5) IMPL="cli entrypoints native runtime cli_core daemon" ;;
  W6) IMPL="tui repl frontend debug diagnostics" ;;
  W7) IMPL="permissions hooks auth bootstrap" ;;
  W8) IMPL="skills context_system goal intent_forecast multimodel memdir away_summary dreaming coordinator session_intelligence logical_kanban memory" ;;
  W9) IMPL="utils cron_system tasks configuration feature_gate settings state orchestrator messaging assistant compact_service models" ;;
esac

echo "===== $W impl 文件 ====="
for d in $IMPL; do
  if [ "$W" = "W4" ] && [ "$d" = "services" ]; then
    # W4: services 顶层文件 + 除 W3 前缀外的子目录
    find clawcodex_ext/services -maxdepth 1 -name '*.py' ! -name '__init__.py'
    for sub in clawcodex_ext/services/*/; do
      b=$(basename "$sub")
      echo "$W4_EXCLUDE" | grep -qw "$b" && continue
      find "$sub" -name '*.py'
    done
  else
    find "clawcodex_ext/$d" -name '*.py'
  fi
done

echo "===== $W 测试文件（来自附录 B.3） ====="
# 将自己名下的测试目录填入 TESTS（示例：W8）
# 建议直接 grep 附录 B.3 中标 **$W** 的行取目录名
grep -oE "\`tests/[a-z_0-9]+/?\`.*\*\*$W\*\*" docs/MIGRATION_PLAN_9P.md \
  | grep -oE "tests/[a-z_0-9]+/?" | sort -u | while read t; do
    find "$t" -name '*.py' 2>/dev/null
  done
```

> **要点**：impl 侧因整子目录归属，"我的文件 = 我名下子目录里的所有 `.py`"；测试侧同理。附录 B.3 的表格行带 `**W#**` 标记，脚本第二段直接从本文件解析出你的测试目录，无需手工维护。
