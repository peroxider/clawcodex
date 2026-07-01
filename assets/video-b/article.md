# ClawCodex DevMind · 项目展示视频 · 源材料

> 本文件是视频口播稿（script.md）的**事实底座**。chapter agent 在写每章画面时应
> **回到本文件抽细节**（双源原则）。口播稿决定节拍，本文件决定画面密度。

---

## 0. 一句话定位

**ClawCodex DevMind** 是一个把单个 agent 升级为一支**可值守工程团队**的 Python 项目。

- 它是 [clawcodex](https://gitcode.com/chadwweng/clawcodex) 的下游 fork —— 在 Claude Code Python 重构版之上，新增**编排器 · SOP 编译器**等上游未提供的能力层。
- 形态：**长跑守护进程** + **声明式 workflow.md** + **多 agent 协同**
- 目标：让 AI 工程师 7×24 自驱——自己接 issue、自己写代码、自己跑测试、自己开 PR、自己改 review 意见。
- License: MIT
- Python 3.10+（3.11 推荐）
- 一键安装：3 个平台（macOS/Linux/WSL · PowerShell · 源码）

---

## 1. 核心叙事：两个不可替代的能力

### 1.1 编排器（Orchestrator）—— 自主 issue → PR 流水线

**一句话**：长跑守护进程轮询 issue 跟踪器，复制 workspace，让 agent 接手写代码，跑测试，提交，推送，开 PR——**全流程无人值守**。

**4 个跟踪器适配器**（issue 来源）：
- GitHub
- Gitee
- GitCode
- Linear

**6 个 issue 状态**：
- `pending` · `running` · `synced` · `completed` · `failed` · `abandoned`

**6 个杀手级特性**（可作分镜）：
1. **LiveView HTTP/SSE 仪表盘** —— 浏览器直接看 agent 在干啥（`:8080` 端口）
2. **Takeover** —— 暂停 agent 启动 REPL 人工接管，完事再切回
3. **PR 评审自动修复** —— review 评论 + CI 失败自动迭代同分支
4. **提交前测试门禁** —— pre-commit / pre-push 跑 pytest 不过不发 PR
5. **重跑标签机制** —— issue 加 `agent:retry` 标签自动重跑
6. **13 态澄清队列** —— agent 卡住不会干等，3 通道（交互 / 文件 / @提及）求解，13 种状态机走完整

**CLI 入口（4 类子命令）**：
```bash
clawcodex-dev orchestrator server {start,status,stop} --workflow <file>
clawcodex-dev orchestrator issue {list,show,tail,stop,pause,resume,takeover,clarify,inject,workspace,retry}
clawcodex-dev orchestrator dashboard [--port 8080]
```

**真实日志样本**（README 的 Demo 段，可作 step 1 的屏幕内容）：
```
14:02:11  ◐ Read src/services/lock.py · 132 lines
14:02:13  ◐ Grep "asyncio.Lock" · 3 hits
14:02:18  ◐ Edit src/services/lock.py · +18 -4
14:02:24  ◐ Bash pytest tests/test_lock.py · 4 passed
14:02:24  ✓ Verification gate OK (pytest -x)
14:02:25  ◐ Git commit -m "fix: per-key lock granularity in flush_batch"
14:02:26  ◐ Git push origin clawcodex/AGENTSDK-15
14:02:31  ✓ PR opened · auto-review-loop subscribed
```

### 1.2 SOP 编译器（SOP Compiler）—— 把工程流程编译成多 agent 团队

**一句话**：把你写的 `workflow.md` 流程规范，编译成一组可协同的 agent：每个角色一个 agent 定义 + 一个入口 skill + 一张编排图。

**3 个核心模块**：
- `sdk_parser.py` —— 解析 workflow.md
- `skill_grouper.py` —— 技能分组
- `agent_builder.py` —— 构造 agent 定义
- `templates.py` —— Jinja 模板

**输出**：
- agent 定义（每个角色一个）
- 入口 skill
- 编排图（可读、可执行、可观测）

**协同方式**：
- Worker 间通过 task-notification XML 路由互相通信
- 轻量级协调器工具集：Read / WebSearch / WebFetch + Agent / SendMessage / TaskStop

**示例命令**：
```bash
clawcodex-dev sop convert examples/sop/order_processing.md --out ./.clawcodex
```

---

## 2. 四个辅助能力

### 2.1 自动化工程闭环（PR Review Auto-Fix + 验证门禁）

- **PR Review Auto-Fix**：reviewer 提评论、CI 报错，agent 自动读反馈、迭代修复、加测试、重跑门禁，反复直到过线
- **Verification Gate**：`pre-commit` / `pre-push` / `post-sync` 跑 `pytest`，失败 block push
- Markdown + JSON 报告自动插入 PR body

### 2.2 LiteLLM 100+ LLM 后端

- 一行切到任何模型：`--provider litellm`
- 覆盖：Bedrock · Vertex · Azure · OpenAI · Together · Anyscale · ...
- 跨 provider 块转换（Anthropic image/document → OpenAI-compat）

### 2.3 分布式 Cron + IM 网关

- **Cron**：文件锁 + 抖动调度防重跑；5 字段 cron 表达式 + `@daily/@hourly/@reboot` 别名；NDJSON 任务历史
- **IM 网关**：统一接 WeChat / 飞书 / Slack / Discord；REPL 和 Orchestrator 都能挂上去；`/pause AGENTSDK-15` 这样的控制命令能从手机发

### 2.4 运行时切换模型（/provider /model runtime）

- REPL / TUI 内 `/provider litellm` · `/model gpt-4o` 即时切
- ModelRegistry 热替换，不停会话

---

## 3. 一键安装

**3 个平台并列**（按用户操作系统选）：

| 平台 | 命令 |
|---|---|
| macOS · Linux · WSL | `curl -fsSL https://raw.githubusercontent.com/peroxider/clawcodex/main/install.sh \| bash` |
| PowerShell | `powershell -NoProfile -ExecutionPolicy Bypass -Command "iwr https://raw.githubusercontent.com/peroxider/clawcodex/main/install.ps1 -UseBasicParsing -OutFile $env:TEMP\cc.ps1; & $env:TEMP\cc.ps1"` |
| 源码 | `git clone https://gitcode.com/chadwweng/clawcodex.git && cd clawcodex && uv venv && uv pip install -e ".[all]"` |

**辅助命令**：
- `bash install.sh doctor` —— 预检环境
- `bash install.sh --dry-run` —— 模拟安装
- `clawcodex-dev --version` —— 验证

**预置要求**（极简）：
- Python 3.10+（uv 自动装）
- Git 2.x
- 500 MB 磁盘
- 全用户本地安装，无需 sudo

---

## 4. Hero Metrics（landing.html 同款 3 数）

| 数字 | 含义 |
|---|---|
| **4** | 支持的 issue 跟踪器（GitHub · Gitee · GitCode · Linear） |
| **100+** | LLM 后端（LiteLLM 路由） |
| **3 行** | 启动一个自主工程流水线（`start · list · tail`） |

---

## 5. 5 个次要卖点（landing.html 6-card 实际是 5 张）

- 🤖 自动化工程闭环
- 🌐 LiteLLM · 100+ LLM 后端
- ⏰ 分布式 Cron + IM 网关
- 🔁 运行时切换模型
- 💬 13 态澄清队列

---

## 6. 项目元信息

- **Repo**：https://gitcode.com/chadwweng/clawcodex
- **Mirror**：https://github.com/peroxider/clawcodex（仅一键安装脚本）
- **License**：MIT
- **状态**：活跃开发
- **测试覆盖**：270+ orchestration tests passing
- **开源替代**：7/10 完成，减 4,530 LOC

---

## 7. 视觉与配图建议

**可用素材**：
- `assets/orchestrator/article/index.html` —— 编排器深度文章（已带 SVG / CSS 视觉）
- `assets/orchestrator/demo.html` —— 16:9 完整 demo 屏幕（适合截关键帧）
- `assets/orchestrator/viz/*.html` —— 7 个独立可视化
  - `arch-overview.html` —— 三层架构图
  - `pipeline-flow.html` —— 13 阶段流水线
  - `verification-gate.html` —— 三道验证门控
  - `followup-loop.html` —— 反馈闭环
  - `intent-decision-tree.html` —— 意图决策树
  - `tracker-matrix.html` —— 4 跟踪器矩阵
  - `perf-comparison.html` —— 性能对比

**视觉风格已统一**（同 landing.html）：冷蓝黑 `#0a0e14` + 青绿 `#00d4aa` + JetBrains Mono + 极简留白

---

## 8. 不要写 F-N 编号

用户面一律用友好名：
- "PR 评审自动修复" 而不是 "F-37"
- "提交前测试门禁" 而不是 "F-38"
- "重跑标签机制" 而不是 "F-39"
- "LiteLLM 后端" 而不是 "F-72"
- "13 态澄清队列" 而不是 "F-43"
- ...
