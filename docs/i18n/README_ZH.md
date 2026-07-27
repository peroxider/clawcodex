<div align="center">

# ClawCodex DevMind

**`clawcodex` 的下游二开版本，把单个 agent 升级为一支可自主值守的工程团队 —— 编排器 + SOP 编译器 + 定时任务 + 桥接守护进程 + LiteLLM。**
*构建于上游 Claude Code 的 Python 重构版本之上。本仓库新增了多 agent 编排、调度、LLM 路由等上游尚未提供的能力层。*

> 📍 **仓库地址:** [`https://gitcode.com/chadwweng/clawcodex`](https://gitcode.com/chadwweng/clawcodex) —— 项目现已基于 MIT 许可证**开源**。欢迎公开贡献、提交 issue 和参与讨论。

[English](../../README.md) · [中文](README_ZH.md) · [上游原始 README](../../README.md.raw)

</div>

<!--

  ════════════════════════════════════════════════════════════════════════════
  AGENT / LLM 搜索元数据 — 请勿删除
  ════════════════════════════════════════════════════════════════════════════
  项目        : ClawCodex DevMind
  语言        : Python 3.11 - 3.13
  类型        : 下游衍生版 — 自主 agent 工程层
  基础        : Claude Code Python 重构版（clawcodex 上游）
  许可证      : MIT
  仓库        : https://gitcode.com/chadwweng/clawcodex
  ★ 能力（均已实现，经测试套件验证）★
  编排器守护进程:

    - 自主 Issue → PR 流水线（4 个 tracker：GitHub/Gitee/GitCode/Linear）

    - Issue 注册表状态机（pending/running/synced/completed/failed/abandoned）

    - 每 issue 的 worktree 生命周期、操作员接管、LiveView 仪表盘（HTTP/SSE）

    - PR 评审自动修复（F-37）：读取评审意见 + CI 日志，在同一分支上迭代

    - 验证门（F-38）：pre-commit / pre-push / post-sync pytest 门禁 + Markdown+JSON 报告

    - Issue 重跑（F-39）：agent:retry / agent:follow-up / agent:blocked 标签 + 评论命令

    - 共享/顺序工作区策略（F-42）：isolated | shared | sequential per-issue worktree

    - 澄清队列：13 状态，3 通道求解器（交互式 / 文件 / @提及）

    - 工具调用审计轨迹（F-45）：NDJSON 每工具决策日志 + 报告注册

  SOP 编译器:

    - 将 workflow.md 流程规范 → 多 agent 协同系统

    - SDK 解析器 + skill 分组器 + agent 构建器 + Jinja 模板

    - 输出：agent 定义、入口 skill、编排图

  定时任务系统:

    - 分布式文件锁调度器，可配置 jitter

    - 5 字段 cron 表达式 + @daily/@hourly/@reboot 别名

    - NDJSON 每任务运行历史、状态/通知

  桥接守护进程:

    - 多 session 守护进程（阶段 3/4/5/8/11）

    - HTTP/SSE 远程运行时、REPL 接管、headless 适配器

  协调器 / 团队工人:

    - TeamCreate / TeamDelete 工具化工人蜂群

    - SendMessage 同行私信、task-notification XML 路由

    - 轻量协调器工具集（F-41）：Read/WebSearch/WebFetch + Agent/SendMessage/TaskStop

  LiteLLM Provider:

    - 单一 --provider litellm → 100+ 个 LLM 后端（Bedrock、Vertex、Azure、Together、Anyscale……）

    - 跨 provider 块转换（Anthropic image/document → OpenAI-compat）

  工具系统:

    - 4 个 bundle：bare / default / clawcodex / all（冷启动更快、上下文更小）

    - 保留上游的 TF-IDF 语义工具搜索

  开源组件替代（已完成 7/10，-4,530 LOC）:

    - Pydantic Settings、python-frontmatter、tree-sitter-bash、GitPython、Pluggy、Outlines、LiteLLM

  CLI 表面:

    - clawcodex-dev orchestrator | cron | sop | coordinator 子命令

    - F-43：/provider 和 /model REPL/TUI 命令 + ModelRegistry 热切换

    - 所有上游标志（-p、--tui、--provider、--model、--permission-mode……）保持不变

  架构:

    - 三层：upstream/（git archive 快照）+ capabilities/（协议）+ clawcodex_ext/（下游）

    - CLI/TUI/Runtime 拆分（F-34），8 个扩展 TUI 钩子点

    - F-47：权限设置 Schema 含 PermissionsConfig 数据类

    - F-48：src/ 核心路径 10 文件解耦进行中

  ★ 准备好使用本项目了吗？参见下方"快速开始"。★
  ════════════════════════════════════════════════════════════════════════════
-->

<p align="center">

  <img src="https://img.shields.io/badge/python-3.11%2B-blue?logo=python" alt="Python 3.11+">

  <img src="https://img.shields.io/badge/license-MIT-green" alt="License MIT">

  <img src="https://img.shields.io/badge/status-active--development-yellow" alt="Status: active development">

  <img src="https://img.shields.io/badge/orchestrator-4%20trackers-8A2BE2" alt="4 issue-tracker adapters">

  <img src="https://img.shields.io/badge/LLM%20backends-100%2B-orange?logo=openai" alt="100+ LLM backends">

  <img src="https://img.shields.io/badge/replacement%20LOC--4.5k-brightgreen" alt="-4,530 LOC via open-source replacements">

  <img src="https://img.shields.io/badge/tests-270%2B%20passing-success" alt="270+ orchestration tests passing">

</p>

---

## 为什么需要这个 fork？

上游 `clawcodex` 已经提供了一个忠实的 Claude Code Python 移植：agent 循环、工具系统、MCP、hooks、权限、记忆、多 provider 对话、TUI/REPL。**本 fork 在其之上加了一层 —— 把 agent 嵌入真实工程工作流所需的那些东西，从「交互式聊天」变成「长时间自主值守」。**
具体来说，本仓库新增：

- 🤖 **编排器（Orchestrator）** —— 守护进程，自动轮询工单系统、拉分支、跑 agent、开 PR，全程无需人工
- 💬 **IM 消息网关** —— 让 REPL 和编排器在运行期接入微信/飞书私聊消息，把 agent 控制和回复带到 IM 渠道
- 🧩 **SOP 编译器** —— 把任何 `workflow.md` 流程化规范编译成多 agent 协同系统
- ⏰ **定时任务系统（Cron System）** —— 分布式锁调度，带 jitter 和 NDJSON 运行历史
- 🌉 **桥接守护进程扩展** —— 多 session 桥接、远程运行时、REPL/headless 适配器
- 🔌 **LiteLLM Provider** —— 一个 `--provider litellm` 接口，路由到 100+ LLM 后端
- 👥 **协调器 / 团队** —— `TeamCreate`/`TeamDelete` 工人群，`SendMessage` 同行私信
- 🩹 **PR 检视意见自动修复（F-37）** —— 读取评审意见 + CI 日志，在同一分支上迭代修复
- ✅ **验证门（F-38）** —— pre-commit / pre-push / post-sync 的 `pytest` 门禁，附 Markdown + JSON 报告
- 🔁 **Issue 重跑（F-39）** —— `agent:retry`/`agent:follow-up`/`agent:blocked` 三个标签驱动重跑
- 🧭 **逻辑看板（LKB）** —— 可选开启、按工作区隔离，并在现有 Task-v2 工具背后提供持久化任务图

上游的 REPL、TUI、工具系统、MCP、hooks、记忆、权限、provider 层都原样保留 —— 本 fork 是接在它们之上，不替换它们。

---

## 主要特性演示

```text
$ clawcodex-dev orchestrator server start --workflow ./workflow.md
✓ orchestrator daemon started · pid 18432 · tracker=gitcode · repo=chadwweng/AgentSDK
✓ max_concurrent_agents=3 · permission_mode=bypassPermissions
$ clawcodex-dev orchestrator issue list
ID                STATUS      BRANCH                     ATTEMPTS  PR
gitcode/AGENTSDK-7   done     clawcodex/AGENTSDK-7     1         https://gitcode.com/.../pulls/7
gitcode/AGENTSDK-12  running  clawcodex/AGENTSDK-12    1         -
gitcode/AGENTSDK-15  paused   clawcodex/AGENTSDK-15    2         https://gitcode.com/.../pulls/15
linear/PROJ-128      running  clawcodex/PROJ-128       1         -
$ clawcodex-dev orchestrator issue tail --id gitcode/AGENTSDK-15
14:02:11  ◐ Read src/services/lock.py · 132 lines
14:02:13  ◐ Grep "asyncio.Lock" · 3 hits
14:02:18  ◐ Edit src/services/lock.py · +18 -4
14:02:24  ◐ Bash pytest tests/test_lock.py · 4 passed
14:02:24  ✓ Verification gate OK (pytest -x)
14:02:25  ◐ Git commit -m "fix: per-key lock granularity in flush_batch"
14:02:26  ◐ Git push origin clawcodex/AGENTSDK-15
14:02:31  ✓ PR opened · auto-review-loop subscribed
# 4 小时后，PR 评审意见落地
$ clawcodex-dev orchestrator issue inject --id gitcode/AGENTSDK-15 "address review comments"
✓ agent resumed · re-reading PR comments · pushing fix commits
```

---

## 🎬 视频展示 / Video Showcase

> **1 分钟看完 clawcodex-dev 能干什么** —— 看视频比读文字更直观。

本项目有一份 4 章交互式视频演示（coldopen · orchestrator · sop-compiler · install），配套一个约 238 KB 的自包含单文件 React SPA（`vite-plugin-singlefile` 构建，JS/CSS 全部 inline，浏览器双击即跑）。

### 看视频

| 渠道 | 链接 | 备注 |
|---|---|---|
| 📺 GitCode Pages | [https://chadwweng.gitcode.com/clawcodex/assets/video-b/presentation/dist/index.html](https://chadwweng.gitcode.com/clawcodex/assets/video-b/presentation/dist/index.html) | 待仓库 Pages 启用后即可访问 |
| 📺 GitHub Pages | [https://peroxider.github.io/clawcodex/assets/video-b/presentation/article.html](https://peroxider.github.io/clawcodex/assets/video-b/presentation/article.html) | 镜像仓库可同步 |
| 🏃 本地预览 | `cd assets/video-b/presentation && npm install && npm run dev` → [http://localhost:5174](http://localhost:5174) | 需要 Node 18+ |
| 📦 单文件直开 | [`assets/video-b/presentation/article.html`](../../assets/video-b/presentation/article.html) | 离线 / 静态托管通用，238 KB |

> GitHub / GitCode 的 README 不允许 `<script>` 内嵌（会被 sanitize 剥离），所以走外链方式跳转。
> 静态截图缩略图可在 `assets/video-b/screenshots/` 下重新生成：`python3 scripts/capture_video_b_screenshots.py`。

---

## 快速开始

### 一键安装（Linux / macOS / Git Bash / WSL）

```bash
curl -fsSL https://raw.githubusercontent.com/peroxider/clawcodex/main/install.sh | bash
source ~/.bashrc                     # 或：source ~/.zshrc （或新开一个终端）
clawcodex-dev --version              # 验证安装
```

常用参数：

```bash
bash install.sh doctor               # 仅诊断环境，不实际安装
bash install.sh --dry-run            # 预览每一步，不实际改动
bash install.sh --no-venv --no-setup --yes --log-file /tmp/install.log  # CI / Docker
```

> 💡 **Windows 用户：** 如果你使用原生 PowerShell 5.1+ 或 pwsh，请改用下方的 [PowerShell 一键安装](#one-click-install-powershell)——无需 Git Bash 或 WSL。

### 一键安装（PowerShell / Windows）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "iwr https://raw.githubusercontent.com/peroxider/clawcodex/main/install.ps1 -UseBasicParsing -OutFile $env:TEMP\cc.ps1; & $env:TEMP\cc.ps1"
clawcodex-dev --version              # 验证安装（如有需要先新开一个 shell）
```

常用参数：

```powershell
.\install.ps1 doctor                 # 仅诊断环境
.\install.ps1 -DryRun                # 预览但不实际改动
.\install.ps1 -NoVenv -NoSetup -Force -LogFile C:\Temp\install.log  # CI / Docker
.\install.ps1 uninstall              # 卸载
```

### 手动安装（备选）

适用于在项目本身上做开发，或安装脚本不可用时：

```bash
git clone https://gitcode.com/chadwweng/clawcodex.git
cd clawcodex
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[dev]"
python scripts/ci/dev_setup.py
clawcodex-dev login                  # 配置 provider（一次性）
clawcodex-dev                        # REPL（与上游一致，外加 orchestrator 子命令）
clawcodex-dev orchestrator --help    # 查看所有编排器命令
```

## 环境要求

| 操作系统 | 状态 |
|---|---|
| Linux（Debian、Ubuntu、Fedora、RHEL、Arch……） | ✅ 支持 |
| macOS 12+（Monterey 及更新） | ✅ 支持 |
| WSL2（Windows 内的 Ubuntu / Debian） | ✅ 支持 |
| Windows：原生 PowerShell 5.1+ / pwsh | ✅ 支持——无需 Git Bash 或 WSL |

| 工具 | 最低版本 | 是否自动安装？ |
|---|---|---|
| **Git** | 任意 2.x | 通过系统包管理器安装 |
| **Python** | 3.11 - 3.13 | ✅ `uv` 按需安装 |
| **uv** | 任意 0.5+ | ✅ 首次运行从 `astral.sh` 下载 |
| **curl** 或 **wget** | 任意 | 安装 uv 和克隆仓库时需要 |

安装过程**完全用户本地**（无需 `sudo`），写入 `$HOME/.clawcodex/`、`$HOME/.local/bin/` 和 shell rc 文件。需要约 **500 MB** 磁盘空间。重复运行安装脚本安全——已存在的仓库会 fast-forward，venv 会复用。

---

## 二开特性

### 编排器（Orchestrator）—— 自主 Issue → PR 流水线

一个长时间运行的守护进程，持续轮询工单系统，拉取 issue、创建 worktree、跑 agent、做验证、提交、推送、开 PR——每一步都支持操作员介入覆盖。

**3 分钟启动：**

```bash
cp extensions/orchestrator/templates/workflow.template.md ./workflow.md
$EDITOR workflow.md    # 设置 tracker、repo、branch_prefix、provider、permission_mode
clawcodex-dev orchestrator server start --workflow ./workflow.md
clawcodex-dev orchestrator issue list
clawcodex-dev orchestrator issue tail --id <id>
clawcodex-dev orchestrator dashboard  # HTTP/SSE on :8080
```

**Issue 状态：** `pending` · `running` · `synced` · `completed` · `failed` · `abandoned`

**F-feature 增量：**

| 特性 | 说明 |
|---|---|
| **F-37 — PR 评审意见自动修复** | 订阅 PR 评审意见 + CI 日志；在**同一分支**上重跑 agent（不新开 PR），持续推修复 commit 直到问题解决。 |
| **F-38 — 验证门** | 在 pre-commit / pre-push / post-sync 三个检查点运行 `test_command`（默认 `pytest -x`）。失败即阻塞推送。Markdown + JSON 报告自动插入 PR 正文。 |
| **F-39 — Issue 重跑** | `agent:retry`（重置+关旧 PR+重跑）、`agent:follow-up`（保留 PR、追加 commit）、`agent:blocked`（永久跳过）。也支持 `/agent retry`/`/agent follow-up` 评论命令或 `clawcodex-dev orchestrator issue retry --id <id> --mode reset`。 |

**子命令一览：**

```bash
clawcodex-dev orchestrator server {start,status,stop} --workflow <file>
clawcodex-dev orchestrator issue list [--status <state>]
clawcodex-dev orchestrator issue show --id <id>
clawcodex-dev orchestrator issue tail --id <id>
clawcodex-dev orchestrator issue stop --id <id>
clawcodex-dev orchestrator issue pause --id <id> [--reason <text>]
clawcodex-dev orchestrator issue resume --id <id>
clawcodex-dev orchestrator issue takeover --id <id>
clawcodex-dev orchestrator issue clarify --id <id> --answer <text>
clawcodex-dev orchestrator issue inject --id <id> [hint]
clawcodex-dev orchestrator issue feedback --id <id> (--list|--approve|--dismiss)
clawcodex-dev orchestrator issue review --id <id> (--approve|--reject --feedback <text>)
clawcodex-dev orchestrator issue retry --id <id> --mode reset|followup|unblock
clawcodex-dev orchestrator issue workspace --id <id>
clawcodex-dev orchestrator dashboard [--port 8080]
```

**`extensions/orchestrator/` 内置模块：** `tracker.py` + linear/gitcode/gitee/github 适配器、`issue_registry.py`、`clarification.py`/`clarification_queue.py`、`agent_runner.py`、`git_sync.py`、`status_dashboard.py`、`workspace.py`/`workspace_locator.py`、`review_feedback.py`、`progress_reporter.py`、`approval_policy.py`、`orchestrator.py`、`workflow.py`/`workflow_store.py` + 模板。

---

### IM 消息网关

统一 IM 入口：把个人微信（Weixin iLink）与 Feishu App WebSocket 双向消息，以及 legacy Feishu/Slack/Discord 单向推送，经同一个能力门控网关分发。

- 目前支持 **飞书** 和 **微信** 两个连接渠道，但不推荐微信，因为微信存在主动发送消息数量的限制。

- 以**独立守护进程**运行（`extensions/im_gateway/`），REPL/orchestrator 经 POSIX UDS opt-in 接入。
- **运行仅限 POSIX/WSL/Git Bash**（Unix domain socket）。

**快速开始：**

```bash
clawcodex-dev gateway start|stop|status|restart # IM 消息网关生命周期控制
clawcodex-dev gateway setup # IM 消息网关快速配置；完成后自动重启守护进程

# 飞书配置（推荐）
uv sync --locked --extra feishu # 安装 Feishu App SDK 与终端二维码依赖；开发环境 --extra dev 已包含
clawcodex-dev gateway status feishu # 查看 Feishu 连接模式、健康状态和审批卡片支持

# 微信配置（暂不推荐，存在主动发送消息限制）
clawcodex-dev gateway restart wechat # 重启 WeChat IM 渠道
clawcodex-dev gateway status wechat # 查看 WeChat 登录健康状态和 REPL/orchestrator 连接状态
```

gateway 守护进程运行且某个双向 app 渠道登录后，先正常启动 REPL 或 orchestrator，再把该运行时接入 IM 渠道。WeChat direct/private 私信或 Feishu p2p 私聊都可以驱动 agent，回复会回流到实际发送者。Feishu setup 优先使用二维码 scan-to-create 注册；扫码拒绝、过期或无法完成时，会回退到手动填写应用凭证。setup 向导正常退出后会自动重启整个 gateway 守护进程，让所有渠道变更在新进程中加载。

处理飞书消息期间，ClawCodex 会在原消息上添加 `Typing` 表情回应；成功或取消时删除，失败时替换为 `CrossMark`。可设置 `FEISHU_REACTIONS=false`，或把飞书 channel 的 `extra.reactions` 设为 `false` 来关闭。手动创建的飞书应用需要授予“发送、删除消息表情回复”权限（`im:message.reactions:write_only`）。

**连接网关：**

```bash
# REPL：启动时直接连接
clawcodex-dev --gateway

# REPL：也可正常恢复/新建后再连接
clawcodex-dev
clawcodex-dev --resume <session-id>
/gateway connect
/gateway status
/gateway disconnect

# Orchestrator：启动时直接连接
clawcodex-dev orchestrator server start --workflow path/to/workflow.md --gateway

# Orchestrator：也可连接已经运行中的守护进程
clawcodex-dev orchestrator server start --workflow path/to/workflow.md
clawcodex-dev orchestrator server connect-gateway
clawcodex-dev orchestrator server disconnect-gateway
```

启动时的 `--gateway` 与运行期连接都会默认绑定所有已启用双向 IM app 渠道下的 direct/private 发送者，WeChat 与 Feishu WebSocket 可以同时运行。同一时间只有一个运行域能拥有这组共享绑定：连接 REPL 会断开 orchestrator 绑定，连接 orchestrator 会断开 REPL 绑定。Legacy Feishu/Slack/Discord webhook 仍是 outbound-only。`CLAWCODEX_GATEWAY_SOCK` 可覆盖 daemon socket；特定 origin 绑定仅保留给定向调试或未来多 origin 自动化。

**命令控制：**

| 运行域 | IM 白名单命令 |
|---|---|
| REPL | `/stop`、`/clear`、`/reset`、`/new`、`/goal`、`/help`、`/?`、`/cost`、`/history`、`/context`、`/recap`、`/btw`、`/cron-list`、`/cron-status`、`/cron-runs`、`/tools`、`/skills`、`/diff`、`/mcp`、`/tasks`、`/idle`、`/doctor`、`/release-notes` |
| Orchestrator | `/server status`；`/issue list`、`/issue show`、`/issue tail`、`/issue stop`、`/issue pause`、`/issue resume`、`/issue clarify`、`/issue inject`、`/issue feedback`、`/issue review`、`/issue retry`、`/issue workspace` |

可在 `~/.clawcodex/gateway/channels.yaml` 中手动编辑 `command_allowlists.repl` 与 `command_allowlists.orchestrator`，随后重启 gateway；省略某个列表时保留其默认值，显式配置空列表则禁用该运行域的全部斜杠命令。

Orchestrator IM 命令中，`/issue inject` 是实时、非阻断的 operator hint，agent 会继续运行；`/issue clarify` 用于回答 agent 发起且正在暂停等待的澄清问题；`/issue feedback`、`/issue review` 与 `/issue retry` 是 issue 生命周期状态变更，可能调度新一轮 agent 运行。

Orchestrator 非白名单斜杠命令会返回 `不支持 /xxx 执行`。

**问题排查：**

用 INFO 日志重启 daemon 并跟踪 gateway 日志：

```bash
clawcodex-dev gateway restart --verbose
clawcodex-dev gateway status
tail -f ~/.clawcodex/gateway/gateway.log
```

---

### SOP 编译器

把 `workflow.md` 流程化规范编译成多 agent 协同运行时。

```bash
clawcodex-dev sop convert examples/sop/order_processing.md --out ./.clawcodex
```

产物：agent 定义（每个角色一个）、入口 skill、编排图。生成的 agent 之间可互发 `SendMessage`，通过上游 task-notification 路由在崩溃后恢复。

**模块：** `sdk_parser.py`、`skill_grouper.py`、`agent_builder.py`、`templates.py`。

---

### 协调器 / 团队工人

把上游的 team 原语暴露成可用的"工人蜂群"模型：

```text
clawcodex-dev coordinator team create --name build-team --members agent-1,agent-2,agent-3
clawcodex-dev coordinator team list
clawcodex-dev coordinator team delete --name build-team
```

在 agent 循环里暴露 `TeamCreate`/`TeamDelete` 工具。工人之间互发 `SendMessage`。Task-notification XML 路由把工人事件汇报回管理员。

---

### 逻辑看板（LKB）

> **当前状态：**实验性功能，需要显式开启；所需的 Feature Flag 默认处于关闭状态。

LKB 保留模型原本看到的 Task-v2 工具名称。持久化 Plan Graph 模式生效后，宿主适配器会把受支持的 Task-v2 调用路由到工作区 Graph Store 内“当前会话绑定的 Plan”，而不再把会话内的原生任务字典作为权威存储。

- 开启 LKB **不会**强制模型创建任务计划，Agent 仍然需要主动调用 Task 工具。
- 交互式 REPL/TUI 默认提供 Task-v2。Headless/SDK 会话默认改用`TodoWrite`；开启 `LKB_PLAN_GRAPH` 会在 headless 会话中自动同时启用 Task-v2 工具面，因此 headless 下使用 LKB 只需这一个开关，不再需要设置`CLAUDE_CODE_ENABLE_TASKS=1`（但它仍可以单独强制启用 Task-v2）。`TodoWrite` 本身不使用持久化 Plan Graph。
- 后台 Agent 会在父运行时具备对应工具时获得 `TaskCreate`、`TaskGet`、`TaskList`、`TaskUpdate` 和 `Lkb`。查询执行器还会在调用共享 Registry 前再次校验每个 Agent 经过过滤的工具集。
- Textual TUI 会在状态栏上方固定挂载任务进度面板，并在 Task、Agent 和 Lkb 返回后刷新。会话进行期间，它还会周期性从 Graph Store 重新加载当前 Plan 投影，因此子 Agent 在独立上下文中完成的进度也会显示在固定面板中。

**开启 LKB：**

在交互式会话中，也可以直接运行不带参数的 `/lkb`：它会打开一个交互式 on/off 选择菜单（类似 `/effort`），显示当前状态；按 Enter 切换开关并持久化选择结果。

如需持久化到用户配置：

```bash
clawcodex-dev feature set LKB_PLAN_GRAPH --on
clawcodex-dev feature get LKB_PLAN_GRAPH
```

- 配置保存在 `~/.clawcodex/features.json`。修改后应启动一个新的ClawCodex 进程。

Headless Task-v2 示例（只需这一个开关，它会同时启用 Task-v2 工具面）：

```bash
CLAWCODEX_FEATURE_LKB_PLAN_GRAPH=1 \
clawcodex-dev -p "请使用 LKB 规划并实现这个需求：……"
```

Feature 状态的优先级依次为：本次启动的 CLI override、环境变量、持久化 Feature 配置、代码注册的默认值。

**交互式 REPL/TUI 会话提供以下本地命令：**

```text
/lkb                       # 打开交互式 on/off 开关菜单（显示当前状态；按 Enter 切换并持久化）
/lkb board                 # 查看逻辑看板的 Board 面板
/lkb board --compact       # 查看紧凑 Board
/lkb status                # 查看派生状态；Plan Graph 模式下等价于紧凑 Board
/lkb explain <task_id>     # 解释 blocker、失效传播和最近一次验证
/lkb audit <task_id>       # 查看某个任务最近的 Audit Event
/lkb revalidate <task_id>  # 重新验证一个 needs_recheck 任务
/lkb plan current          # 查看当前会话绑定的 Plan
/lkb plan list             # 列出工作区 Board 中的 Plan
/lkb plan new [title]      # 创建并绑定一个新 Plan
/lkb plan use <plan_id>    # 显式绑定已有 Plan
/lkb plan suspend          # 挂起当前 Plan 并释放 Claim
/lkb plan complete         # 完成当前 Plan
/lkb plan abandon          # 放弃当前 Plan
/lkb plan archive          # 归档当前 Plan
/lkb plan reopen <plan_id> # 重新打开并绑定已停止的 Plan
```

---

## 架构（仅本 fork）

```text
              ┌──────────────────────────────────────────────┐
              │   clawcodex_ext/cli (clawcodex-dev 入口)     │
              │   parser · dispatch · runners · permissions  │
              └──────────┬──────────────┬─────────────┬──────┘
                         │              │             │
              ┌──────────▼────┐  ┌──────▼─────┐  ┌────▼────────────┐
              │   编排器      │  │ 定时任务    │  │ SOP 编译器      │
              │  + Dashboard  │  │ + Lock+    │  │ + SDK parser    │
              │  + LiveView   │  │   Jitter   │  │ + Agent builder │
              │  + Takeover   │  │ + Status   │  │ + Skill grouper │
              │  + Review FB  │  │ + Notify   │  │                 │
              └──────┬────┬───┘  └─────────────┘  └─────────────────┘
                     │    │ 事件 + 命令
                     │    ▼
                     │  ┌─────────────────────────────────────┐
                     │  │ IM Gateway / MessageGateway         │ ◄── CLI / REPL 显式接入
                     │  │ 双向 IM 通信 · 权限审批提示          │
                     │  │ 命令下达（/stop、/pause）            │
                     │  └──────────────────┬──────────────────┘
                     │                     ▼
                     │  ┌─────────────────────────────────────┐
                     │  │ 上游 IM 服务商：WeChat              │
                     │  └─────────────────────────────────────┘
                     │
       ┌─────────────┼─────────────┐
       │             │             │
┌──────▼─────┐ ┌─────▼──────┐ ┌────▼──────────┐
│ Trackers   │ │  Bridge    │ │  Coordinator  │
│ · Linear   │ │  Daemon    │ │  · TeamCreate │
│ · GitHub   │ │  Phases    │ │  · TeamDelete │
│ · Gitee    │ │  3,4,5,8,11│ │  · SendMessage│
│ · GitCode  │ │  + Remote  │ │  · Workers    │
└────────────┘ └────────────┘ └───────────────┘
                     │
                     ▼
       ┌─────────────────────────────────────┐
       │         上游 clawcodex              │
       │  query() · tool_system · providers  │
       │  TUI · REPL · MCP · Hooks · Memory  │
       │  （完整架构见 README.md.raw）        │
       └─────────────────────────────────────┘
```

`MessageGateway` 是本 fork 共享的 IM 边界：CLI/REPL 和编排器通过 gateway IPC 显式接入；平台相关投递细节收敛在 WeChat adapter 后面。

---

## 仓库结构（仅本 fork）

```text
extensions/                          # 本 fork 全部新增都在这里
├── orchestrator/                    #   - 自主 issue 处理器
│   ├── orchestrator.py              #   - 守护进程主循环
│   ├── tracker.py                   #   - tracker 抽象基类
│   ├── linear/                      #   - Linear 适配器
│   ├── issue_registry.py            #   - JSON 注册表
│   ├── clarification.py             #   - 三通道求解器
│   ├── clarification_queue.py       #   - 13 状态队列
│   ├── agent_runner.py              #   - 单 issue 的 agent 执行
│   ├── git_sync.py                  #   - commit / push / sync + 验证门
│   ├── review_feedback.py           #   - F-37 PR 评审自动修复
│   ├── status_dashboard.py          #   - HTTP/SSE LiveView
│   ├── workspace.py                 #   - worktree 生命周期
│   ├── workspace_locator.py
│   ├── progress_reporter.py
│   ├── approval_policy.py
│   ├── workflow.py + workflow_store.py
│   ├── templates/workflow.template.md
│   └── cli/                         #   - server、issue、dashboard 子命令
├── sop_converter/                   #   - SOP 编译器
│   ├── sdk_parser.py
│   ├── skill_grouper.py
│   ├── agent_builder.py
│   └── templates.py
├── providers_ext/
│   └── litellm_provider.py          #   - LiteLLM 兜底 provider
├── tool_system_ext/                 #   - 工具包 + 注册表扩展
│   ├── bundles.py
│   ├── registry_ext.py
│   └── agent_config.py
├── capabilities/                    #   - 横切协议
└── api/                             #   - 编排 + query 公开 API
clawcodex_ext/                       # 下游 CLI + 服务
├── cli/                             #   - clawcodex-dev 入口
├── cron_system/                     #   - 分布式 cron 调度器
├── frontend/                        #   - headless 前端
├── runtime/                         #   - RuntimeContext 工厂
└── tui/                             #   - 扩展 Textual TUI（8 个钩子点）
```

`src/` 全部归上游所有——上游架构图见 [`README.md.raw`](../../README.md.raw) 和 [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md)。

---

## 开发

```bash
git clone https://gitcode.com/chadwweng/clawcodex.git
cd clawcodex
pip install -e ".[dev]"
python scripts/ci/dev_setup.py
# 只跑本 fork 自己的测试
pytest tests/test_orchestrator.py -v
pytest tests/test_cron_system.py -v
pytest tests/test_sop_converter.py -v
pytest tests/test_bridge.py -v
# 或者跑除上游集成测试外的全部
pytest tests/ -m "not integration" -v
```

Git 钩子不会因为 `.pre-commit-config.yaml` 存在于克隆中而自动激活。`scripts/ci/dev_setup.py` 会在缺少时安装本地 pre-commit 钩子并创建 `.env` 模板。

- GitCode CI/CD 门禁可在本地模拟：
  ```bash
  python scripts/ci/local_ci.py --base "the fork's remote dev branch" --ui plain --failure-lines 120
  python scripts/ci/local_ci.py --base upstream/dev
  ```
- 不带 `--all` 时只 diff `HEAD~1..HEAD`。使用 `--base <ref>` 覆盖整段 PR diff。
- Pytest 门禁使用固定的 smoke 集合加上当前范围内变更的 `tests/**/test_*.py` 文件。

详细门禁说明见 [`docs/cicd/CICD_GATE.md`](../../docs/cicd/CICD_GATE.md)；[`CONTRIBUTING.md`](../../CONTRIBUTING.md) 涵盖 PR 规范。

---

## 许可证

[MIT](../../LICENSE) —— 与上游 `clawcodex` 相同。`extensions/` 和 `clawcodex_ext/` 内的下游新增也按相同的 MIT 条款发布。

---

## 致谢

- **clawcodex** —— 本 fork 所基于的上游 Claude Code Python 移植
- **Claude Code**（Anthropic）—— 原始 TypeScript 架构
- **Aider** · **Cline** · **Continue** · **OpenHands** —— CLI / TUI 模式参考
- **LiteLLM** —— 兜底 provider 层

---

<div align="center">

**如果你觉得当前项目有用，欢迎 Star ⭐ 支持本仓库。**
[⬆ 回到顶部](#clawcodex-devmind)

</div>
