# ClawCodex 上库方案

---

## 目录

1. [项目现状概述](#1-项目现状概述)
2. [策略一：全部合入（单体仓库，定期同步上游）](#2-策略一全部合入单体仓库定期同步上游)
3. [策略二：补丁安装（不上传源码，拉取源码+补丁安装）](#3-策略二补丁安装不上传源码拉取源码补丁安装)
4. [五模块脱离 clawcodex 可行性评估](#4-五模块脱离-clawcodex-可行性评估)
5. [推荐路径：策略对比与选择](#5-推荐路径策略对比与选择)
6. [附录：依赖关系图谱](#6-附录依赖关系图谱)

---

## 1. 项目现状概述

### 1.1 架构

ClawCodex 是 Claude Code 的 Python 移植版，采用三层解耦架构：

```
src/               Layer 0 — 上游 Claude Code 源码
clawcodex_ext/     Layer 1 — 适配层/扩展层（猴补丁、注册模式）
extensions/        Layer 2 — 二开功能模组（全新子系统）
```

### 1.2 代码量基线

| 层 | 路径 | 性质 | 文件数 | 代码行数 |
|---|------|------|--------|---------|
| Layer 0 | `src/` | 上游源码（Claude Code） | 3,884 | 179,062 |
| Layer 1 | `clawcodex_ext/` | 适配层/扩展层 | 1,075 | 262,658 |
| Layer 2 | `extensions/` | 二开功能模组 | 364 | 105,113 |
| **合计** | | | **5,323** | **546,833** |

其中 `src/` 有 **694 个文件（~18%）** 被二开直接修改过。

### 1.3 大特性模块清单(无对应开源项目)

| 模块 | 层级 | 代码量 | 文件数 | 说明 |
|------|------|--------|--------|------|
| orchestrator | Layer 2 | 43,643 | 101 | 编排器 daemon，自动处理 issue → PR |
| sop_converter | Layer 2 | 28,950 | 106 | SOP 编译器，markdown → 多 agent 协同 |
| logical_kanban | Layer 1 | 20,171 | 51 | 逻辑看板，任务分解/规则引擎/ATP 求解 |
| community_radar | Layer 1 | 15,098 | 38 | 社区雷达，监控 GitHub/Gitee 等平台 |
| visualizer | Layer 2 | 5,988 | 25 | 可视化仪表盘 |

**合计：5 个大特性 · 113,850 行 · 321 个文件**

### 1.4 核心基础设施（不可独立，需作为公共依赖）

| 模块 | 代码量 | 文件数 | 说明 |
|------|--------|--------|------|
| `clawcodex_ext.services` | 54,314 | 257 | 服务层（session_storage/voice/ultraplan/lodestone/...） |
| `clawcodex_ext.tool_system` | 20,428 | 76 | 工具系统（被几乎所有模块依赖） |
| `clawcodex_ext.tui` | 18,845 | 94 | TUI 界面 |
| `clawcodex_ext.agent` | 10,801 | 51 | 代理运行时 |
| `clawcodex_ext.command_system` | 10,450 | 34 | 斜杠命令系统 |
| `clawcodex_ext.repl` | 9,468 | 11 | REPL 界面 |
| `clawcodex_ext.cli` | 8,801 | 38 | CLI 入口 |
| `clawcodex_ext.permissions` | 6,892 | 25 | 权限系统 |
| `clawcodex_ext.providers` | 6,514 | 30 | LLM 提供者 |
| `clawcodex_ext.utils` | 6,418 | 30 | 共享工具函数 |
| `clawcodex_ext.bridge` | 6,384 | 30 | 多会话桥接 |
| `clawcodex_ext.query` | 4,775 | 12 | 查询引擎 |
| `clawcodex_ext.context_system` | 4,763 | 15 | 上下文构建 |

---

## 2. 策略一：全部合入（单体仓库，定期同步上游）

### 2.1 方案描述

将 `src/` + `clawcodex_ext/` + `extensions/` 全部作为一个仓库，但**不断开上游跟踪**。通过 `git remote add upstream <clawcodex>` + 定期 `git pull upstream main` 的方式持续获取上游更新，并将二开带来的冲突以补丁形式维护。

工作流：
```
1. 定期：git fetch upstream → git merge upstream/main → 解决冲突 → 提交
2. 冲突处理：每次 merge 后，将被修改文件的冲突逐一解决，生成补丁文件归档
3. 补丁管理：用 `git format-patch` 或自定义脚本将二开修改与上游 diff 分离存储
```

### 2.2 优点

-  **架构最简单** — 单一仓库、单一 `pip install`、单一 CI/CD 流水线，用户零配置
-  **完全可控** — 甚至可深度修改 `src/` 的任何行为，不受解耦约束
-  **持续获取上游收益** — 定期同步可获得上游的安全修复、性能改进和新功能
-  **版本管理清晰** — 一个 tag 对应一个完整可交付版本
-  **Fork & 改名自由** — 换 Logo、换包名、换许可证（需遵守上游 MIT 条款）无法律歧义

### 2.3 缺点

-  **上游同步成本高** — 被修改文件每次 merge 都可能冲突，需要人工逐一解决
-  **代码膨胀** — 仓库体积 54 万行，其中 33% 是上游代码
-  **补丁维护负担** — 冲突解决后需生成并维护补丁文件，积累越多同步成本越高
-  **知识产权边界模糊** — 上游 MIT 许可证要求保留版权声明，合入后需清晰标注

### 2.4 工作量估算（代码修改量）

| 阶段 | 内容 | 代码修改量 | 备注 |
|------|------|-----------|------|
| 初始迁移 | squash 历史、清理 `.git`、重写 `pyproject.toml`、重命名包、更新入口点 | ~500 行（配置/脚本） | 一次性操作 |
| 建立同步机制 | 配置 `git remote add upstream`、编写补丁管理脚本、编写冲突检测脚本 | ~800 行（shell+Python 脚本） | 一次性 |
| 首次冲突解决 | 处理被修改文件与上游最新版本的冲突 | 总计 ~5,000-15,000 行 | 最耗时步骤 |
| 每次后续同步 | 冲突解决取决于上游变更量，通常影响 10-50 个文件 | 每个周期 ~1,000-5,000 行 | 随上游活跃度变化 |
| 补丁文件维护 | 每次同步后更新补丁归档 | 每次 ~200-500 行 | 轻量 |

初始迁移代码修改量约 **1,300 行**（配置+脚本+补丁管理），首次冲突解决需要处理 **~5,000-15,000 行**冲突区域。后续每次上游同步（按上游 2-3 周发布一次估算）需要处理 **~1,000-5,000 行**冲突。

---

## 3. 策略二：补丁安装（不上传源码，拉取源码+补丁安装）

### 3.1 方案描述

**仓库不包含任何 `src/` 源码文件**，仅维护补丁文件（patch files）和二开模组代码。用户安装时，先通过 `pip install clawcodex` 或 `git clone upstream` 获取上游源码，然后应用补丁将二开修改叠加到上游源码之上。

工作流：
```
1. 仓库内容：clawcodex_ext/（补丁层） + extensions/（二开模组） + patches/（补丁文件）
2. 安装时：pip install clawcodex（上游源码）→ 应用 patches/ → 安装 clawcodex_ext/ + extensions/
3. 上游同步：定期检查上游新版本 → 更新 patches/ 中的补丁以适配新版本 API
4. 补丁生成：`git diff upstream/main...HEAD -- src/ > patches/v1.0.patch`
```

### 3.2 优点

-  **仓库精简** — 仓库仅含二开代码（~113,850 行大特性 + 基础设施），不含上游 179,062 行
-  **知识产权隔离** — 代码与上游 MIT 代码物理分离，许可证边界清晰
-  **上游同步零仓库冲突** — 上游更新不需要在仓库中解决 merge 冲突，只需更新补丁内容
-  **CI/CD 轻量** — 仓库 CI 只需跑补丁层和扩展层的测试

### 3.3 缺点

-  **安装复杂度高** — 用户需要两步安装（上游 + 补丁 + 二开模组），需要安装脚本自动化
-  **上游依赖脆弱性** — 产品运行时依赖上游仓库的可用性和版本兼容性
-  **被修改的 `src/` 文件需要补丁化** — 当前 18% 的上游文件被直接修改过，需要生成和维护对应补丁文件
-  **补丁版本锁定** — 仓库必须锁定上游版本号，补丁只适配特定版本，版本升级时需要重新适配补丁
-  **调试困难** — 用户报 bug 时，需要判断是上游、补丁层、还是二开模组的问题

### 3.4 工作量估算（代码修改量）

| 阶段 | 内容 | 代码修改量 | 备注 |
|------|------|-----------|------|
| 生成补丁文件 | 被修改的 `src/` 文件生成补丁（`git format-patch`） | 自动生成，需人工复核 ~5,000-15,000 行补丁内容 | 一次性 |
| 编写安装脚本 | 编写 `install.sh` 或 Python 安装器，完成「拉取上游 → 应用补丁 → 安装扩展」流程 | ~1,000 行（shell/Python） | 一次性 |
| 回迁未补丁化的修改 | 将部分无法通过补丁实现的修改（如新增文件、配置改动）提取到 `clawcodex_ext/` | ~2,000-5,000 行 | 关键路径 |
| 编写补丁适配脚本 | 自动检测上游版本变更，重新生成补丁或提示冲突 | ~800 行 | 一次性 |
| 每次上游同步 | 检查上游新版本，更新补丁适配新 API | 每个版本 ~500-2,000 行补丁更新 | 按上游发布节奏 |
| 测试验证 | 每次补丁更新后运行全部测试 | ~300 行（测试配置/脚本） | 轻量 |

初始建立补丁系统的代码修改量约 **3,800-6,800 行**（脚本+回迁代码+补丁复核），补丁文件本身 **~5,000-15,000 行**（自动生成需人工复核）。后续每次上游版本升级需要 **~500-2,000 行**补丁更新。

---

## 4. 大特性模块独立发布

### 4.2 耦合度分析

#### 4.2.1 community_radar —  零成本脱离

**零外部依赖**。所有 38 个文件只依赖 Python 标准库（httpx、json、pathlib、re、dataclasses 等）和内部模块。已有独立 CLI 入口。

脱离后可直接应用于：任何需要监控 GitHub/Gitee/GitCode issue 和 PR 的系统。

**MCP 支持**：新增 `community-radar` MCP server，暴露工具：
- `scan_community()` — 扫描社区源
- `list_sources()` — 列出监控源
- `get_digest()` — 获取社区摘要

**工作量**：~200-300 行（包抽取、独立 CLI 入口）

---

#### 4.2.2 visualizer — 已落地

依赖链条：`visualizer → capabilities.dashboard_entry/recorder → recording.renderers`

`capabilities` 是纯 Protocol 定义（无实现），`recording.renderers` 是渲染工具函数。

脱离后需：
1. 将 `capabilities.dashboard_entry` 和 `capabilities.recorder` 的 Protocol 内联或作为独立依赖
2. 将 `recording.renderers.panel` 内联到 visualizer 内部
3. 定义抽象的 `DashboardSink` 接口

**MCP 支持**：新增 `visualizer` MCP server，暴露工具：
- `render_dashboard()` — 渲染仪表盘
- `stream_panels()` — 流式面板更新

**工作量**：~1125 行（详见 F-167，已落地）。落地拆解：
- F-167-A/B：Dashboard/Recorder Protocol 内联到 `extensions/visualizer/protocols/`
- F-167-C：`panel()` 从 `recording.renderers` 迁到 `extensions/visualizer/_rendering.py`
- F-167-D：`asciicast_dashboard_source.py` 从 `extensions/visualizer/` 迁到 `extensions/recording/visualizer_dashboard_source.py`，反向调用 visualizer 的 Protocol + panel 原语
- F-167-E：`extensions/visualizer/pyproject.toml` 标注独立包元数据 + `clawcodex.commands` entry-points
- F-167-F/G：`cli.py` 改为 self-contained `register_viz_subcommand`，`subcommand_registry` 改为 try-import 包裹

详见 [`docs/feature_plan/04-architecture-sdk/f-167-visualizer-package-extract.md`](../feature_plan/04-architecture-sdk/f-167-visualizer-package-extract.md)。

---

#### 4.2.3 logical_kanban —  中低成本脱离 — 已落地

依赖 4 个 clawcodex 类型：
- `feature_gate` — 可用环境变量或简单 config 替代
- `providers.base.ChatMessage` — 纯数据类，可独立定义
- `tool_system.protocol.ToolResult` — 纯数据类，可独立定义
- `tool_system.context.ToolContext` — 仅用于 TYPE_CHECKING（类型注解），运行时只需要 workspace_root 和 LLM provider

核心逻辑（任务分解、规则引擎、ATP 求解器、模糊验证、IR 渲染等）完全不依赖 clawcodex 的任何运行时行为。

**MCP 支持**：新增 `lkb` MCP server，暴露工具：
- `decompose_task()` — 分解任务
- `validate_task()` — 验证任务状态转换
- `explain(task_id)` — 任务推理链解释
- `audit(task_id)` — 审计日志

**工作量**：~1,000-1,500 行（类型解耦、feature_gate 替换、CLI 桥接）

---

#### 4.2.4 orchestrator — 高成本但可行 — Phase 0+1+2 部分已落地

耦合点约 15 个，涉及 Agent 运行时、工具系统、消息类型、通信模块、Git 工具、流事件、录制等多个领域。

> ✅ **2026-07-23 Phase 0+1+2 已落地**（commit `2dcacba8`）：以**仓内子模块** `extensions/orchestrator_runtime/` 形态实现（12 Protocol 文件 / 30 symbols + 4 copy-down utils + clawcodex_compat 透明转发层）；20 新文件 / 5 改文件 / 9 处顶级 import 切换；详见 `docs/ORCHESTRATOR_DECOUPLING_DESIGN.md` §10.2 及 `memory/orchestrator_decoupling_p0p1p2_done.md`。剩余 Phase 3~6（核心迁移 + 适配层 + CLI/MCP + 切换废弃）待启动。

**需要定义的抽象接口**：

**MCP 支持**：orchestrator 自身就是 daemon，新增 MCP server 暴露工具：
- `list_issues()` — 列出待处理 issue
- `run_issue(issue_id)` — 处理单个 issue
- `get_status()` — 获取 orchestrator 状态
- `get_report(run_id)` — 获取运行报告

**工作量**：~5,000-8,000 行（AgentRuntime 抽象、ToolContext 抽象、消息类型抽象、通信解耦、配置独立）

---

#### 4.2.5 sop_converter — 高成本但可行

耦合点约 12 个，涉及 Agent 定义、工具规约、Provider、Skill、权限、录制等多个领域。

**关键洞察**：sop_converter 的**核心价值**是 SOP 编译（markdown → 多 agent 协同系统），这个逻辑本身不依赖 clawcodex。它依赖的是 Agent 的「执行环境」——而这正是抽象层需要提供的。

**MCP 支持**：新增 `sop` MCP server，暴露工具：
- `compile(workflow_path)` — 编译 SOP
- `list_workflows()` — 列出可用 SOP
- `get_workflow_status(workflow_id)` — 查询 SOP 执行状态

**工作量**：~4,000-7,000 行（AgentDefinition 抽象、ToolSpec 抽象、Skill 抽象、Provider 抽象、Permission 抽象）

---

## 5. 推荐路径：策略对比与选择

### 5.1 策略对比

| 维度 |   策略一：全部合入 + 定期同步    |       策略二：补丁安装（不上传源码）       |        策略三：大特性模块独立发布         |
|------|:--------------------:|:---------------------------:|:----------------------------:|
| **初始迁移代码修改量** | ~1,300 行（配置+脚本+补丁管理） | ~3,800-6,800 行（脚本+回迁+补丁复核）  | ~10,700-17,600 行（各模块解耦+抽象接口） |
| **仓库体积** |    54 万行（含上游 33%）    |  仅二开代码（~113,850 行 + 基础设施）   |       各模块独立仓库，仅含模块自身代码       |
| **知识产权隔离** |         边界模糊         |            物理隔离             |       完全隔离（独立 PyPI 包）        |
| **安装复杂度** | 单仓库 `pip install`  |    两步安装（上游 + 补丁 + 扩展）     |     按需 `pip install` 各模块     |
| **上游可用性依赖** |      不依赖上游仓库在线       |          依赖上游仓库可用性          |        不依赖上游（依赖基础设施层）        |
| **调试难度** |     单一仓库，问题定位简单      |        需要区分上游/补丁/二开         |        低，模块独立，问题定位清晰         |

---

## 6. 附录：依赖关系图谱

### 6.1 关键耦合点

| 模块 | 耦合 clawcodex 的具体类型 | 用途 |
|------|--------------------------|------|
| **orchestrator** | `ToolContext` | 工具执行上下文 |
| | `Session`, `Conversation`, `SessionStorage` | 代理会话管理 |
| | `GatewayIpcClient`, `OutboundMessage`, `CommandRouter` | IM 通信集成 |
| | `get_file_status`, `FileStatus` | Git 状态检查 |
| | `PhaseComplete`, `SessionComplete` | 流事件 |
| | `AsciicastCapture` | 录制 |
| | `TextBlock`, `ToolUseBlock`, `ToolResultBlock` | 消息类型 |
| **sop_converter** | `AgentDefinition`, `AgentSource`, `AgentRegistry` | Agent 定义 |
| | `AgentToolSpec`, `Tool`, `Tools`, `ToolRegistry` | 工具规约 |
| | `Skill`, `parse_frontmatter`, `load_skills` | 技能系统 |
| | `BaseProvider`, `ChatMessage` | LLM 提供者 |
| | `PermissionContext` | 权限上下文 |
| | `AsciicastCapture`, `TeeWriter` | 录制集成 |
| **logical_kanban** | `feature_gate` | 功能开关 |
| | `ChatMessage` | 消息类型 |
| | `ToolResult`, `ToolContext` | 工具结果/上下文 |
| **visualizer** | `dashboard_entry` (Protocol) | 仪表盘条目 |
| | `recorder` (Protocol) | 录制定义 |
| | `panel` | 渲染函数 |
| **community_radar** | （无） | |

