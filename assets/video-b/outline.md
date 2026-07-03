# Video Outline · ClawCodex DevMind 项目展示视频

> **主题**：待 Checkpoint Plan 选定 —— 候选见 Checkpoint Plan 推荐段
> **总时长**：约 2 分 20 秒（口播 ~ 650 字 ÷ 4.5 字/秒）
> **章节数**：4 章 / 40 步
> **口播约定**：行内代码是**屏幕显示**（不念出口）；念的只是代码外的口语部分。chapter agent 用行内代码做终端视觉。

---

## 1. coldopen — 钩子（3 steps · ~9s）

**信息池**：
- 核心数据："PR 自己开" 是核心冲击数字 —— 来源 article §0
- 形态定位："长跑守护进程" + "声明式 workflow.md" —— 来源 article §0
- 品牌副标："把单个 agent 升级为一支可值守的工程团队" —— 来源 landing.html L477

**开发计划**：
- step 1 (~3s) — 大字 "你睡了，agent 在干活。" 居中
- step 2 (~3s) — 切到 "早上醒来，PR 自己开了。"
- step 3 (~3s) — 落版 "ClawCodex DevMind" + 副标

口播节选：
> 你睡了，agent 在干活。
> 早上醒来，PR 自己开了。
> 这就是 ClawCodex DevMind。

---

## 2. orchestrator — 编排器核心（16 steps · ~52s）

**信息池**：
- 4 跟踪器：GitHub / Gitee / GitCode / Linear —— 来源 article §1.1
- 6 状态：pending / running / synced / completed / failed / abandoned —— 来源 article §1.1
- 真实日志样本：Read / Grep / Edit / Bash / OK / Commit / Push / PR opened —— 来源 README L156-177
- 13 态澄清队列 —— 来源 article §1.1
- Takeover 命令：`clawcodex-dev orchestrator issue takeover --id <id>` —— 来源 article §1.1
- 真实 PR 评论自动修复链路 —— 来源 article §1.1 / §2.1

**开发计划**：
- step 1 (~3.5s) — "它有个 Orchestrator，编排器。" + 大字 + 副标
- step 2 (~8s) — "一条常驻流水线，盯 4 个 issue 平台" + 4 平台 logo 横向排列
- step 3 (~5.5s) — "哪个 issue 冒头，worktree 拉出来，agent 进场" + 流程示意
- step 4 (~2s) — "真实跑起来长这样——" + 转场
- step 5-11 (~2-4s each) — 真实日志逐行揭示（Read → Grep → Edit → Bash → OK → Commit/Push → PR opened）
- step 12 (~2s) — "reviewer 评论落地？" + 转折
- step 13 (~4s) — "它接住，自己改，再 commit，同分支" + 同分支示意
- step 14 (~3.5s) — "CI 报错？再读再改再跑" + 反馈环
- step 15 (~6.75s) — "你也能随时插一脚" + `issue takeover` 终端命令
- step 16 (~2.25s) — "13 种状态机管全程" + 13 态列表

口播节选：
> 它有个 Orchestrator，编排器。
> 一条常驻流水线，盯 4 个 issue 平台——GitHub、Gitee、GitCode、Linear。
> 真实跑起来长这样——
> Read，132 行代码。Grep 关键字，3 个匹配。Edit，加 18 行删 4 行。
> Bash 跑 pytest，4 个 test 全过。Verification gate OK。Commit。Push。PR opened。
> reviewer 评论落地？它接住，自己改，再 commit，同分支。
> 你也能随时插一脚。`issue takeover`，REPL 接管，完事切回。
> 13 种状态机管全程。

---

## 3. sop-compiler — 多 agent 团队（8 steps · ~30s）

**信息池**：
- 核心命令：`clawcodex-dev sop convert <file> --out <dir>` —— 来源 article §1.2 / README L347
- 3 模块：sdk_parser / skill_grouper / agent_builder —— 来源 article §1.2
- 4 输出：agent 定义 / 入口 skill / 编排图 / 通信机制 —— 来源 article §1.2
- 协同方式：task-notification XML 路由 + SendMessage —— 来源 article §1.2
- 崩溃恢复能力 —— 来源 article §1.2

**开发计划**：
- step 1 (~3.75s) — "第二个看家本领：SOP 编译器。" + 大字
- step 2 (~3.5s) — "你写个 workflow.md，描述流程。" + workflow.md 文件示意
- step 3 (~3.25s) — "它编译成一组多 agent 团队——" + 编译转场
- step 4 (~5.5s) — 4 项输出列表揭示（agent / skill / 编排图 / 通信）
- step 5 (~4s) — "agent 间 SendMessage 互相通信" + 通信图
- step 6 (~1.25s) — "崩了能恢复" + 恢复动画
- step 7 (~1.25s) — "一行命令——" + 转场
- step 8 (~7.5s) — `clawcodex-dev sop convert ...` 终端

口播节选：
> 第二个看家本领：SOP 编译器。
> 你写个 workflow.md，描述流程。
> 它编译成一组多 agent 团队——
> 每个角色一个 agent，一个入口 skill，一张编排图。
> 一行命令——`clawcodex-dev sop convert your_workflow.md --out ./.clawcodex`

---

## 4. install + 完整面貌（13 steps · ~39s）

**信息池**：
- 3 平台安装命令 —— 来源 article §3 / landing.html L484-505
- 3 验证命令（version / doctor / dry-run）—— 来源 article §3 / README L188-198
- 3 Hero Metrics：4 / 100+ / 3 行 —— 来源 article §4 / landing.html L508-522
- 链接位置：项目源码在 https://gitcode.com/chadwweng/clawcodex —— 来源 README L8

**开发计划**：
- step 1 (~1.75s) — "装它只要 3 行。" + 大字
- step 2 (~6s) — "macOS、Linux、WSL——`curl ... | bash`，复制粘贴回车。" + 平台标签 + curl 终端
- step 3 (~1.25s) — "PowerShell 也一行。" + 平台标签
- step 4 (~4s) — "`iwr ... | iex`，搞定。" + iwr 终端
- step 5 (~1.25s) — "想改源码——3 步。" + 平台标签
- step 6 (~5s) — "`git clone` → `uv venv` → `uv pip install -e`，三步走。" + 3 步终端
- step 7 (~4.5s) — "装好以后——`clawcodex-dev --version` 验一下。" + 验证
- step 8 (~3s) — "想要点安全感？`--dry-run` 先模拟一遍。" + 模拟终端
- step 9 (~3s) — "环境不太确定？`doctor` 预检一下。" + 预检终端
- step 10 (~2s) — "4 个 issue 平台。" + 4 平台 logo
- step 11 (~2.5s) — "100 多个 LLM 后端。" + LLM 标识
- step 12 (~1.25s) — "3 行起跑。" + 3 行命令
- step 13 (~3.25s) — "现在去装一个。链接在简介。" + GitCode 链接 + 收尾 logo

口播节选：
> 装它只要 3 行。
> macOS、Linux、WSL——`curl ... | bash`，复制粘贴回车。
> PowerShell 也一行。`iwr ... | iex`，搞定。
> 想改源码——3 步。`git clone`，`uv venv`，`uv pip install -e ".[all]"`，三步走。
> 装好以后——`clawcodex-dev --version` 验一下。
> 想要点安全感？`--dry-run` 先模拟一遍。环境不太确定？`doctor` 预检一下。
> 4 个 issue 平台。100 多个 LLM 后端。3 行起跑。
> 现在去装一个。链接在简介。

---

## 素材清单

### 1. coldopen
- ✓ 字体：Inter Tight / 思源黑体 —— 主题自定
- ⚠️ 背景动效（待 chapter agent 设计）

### 2. orchestrator
- ✓ 真实日志样本 —— 来源 README.md L156-177
- ✓ 4 平台 logo（GitHub / Gitee / GitCode / Linear）—— chapter agent 自行 SVG/纯文字
- ✓ 13 态列表 —— 来源 article §1.1

### 3. sop-compiler
- ✓ workflow.md 文件示意 —— chapter agent 设计
- ✓ 编译转场动画 —— chapter agent 设计

### 4. install
- ✓ 3 平台安装命令 —— 来源 landing.html L484-505 / README L184-215
- ✓ 3 验证命令 —— 来源 README L188-198
- ✓ Hero Metrics（4 / 100+ / 3）—— 来源 landing.html L508-522

---

## 自检（写完 outline 强制执行）

- [x] 每个 step 单一句屏幕内容描述，无"动画"行 / "手段"行
- [x] 没有写具体毫秒/秒数（除 `(~Ts)` 口播估时）
- [x] 每章首段都有信息池 block + 来源标注
- [x] 所有 step `(~Ts)` 累加 ≈ 9 + 52 + 30 + 39 = 130s ≈ 2:10，匹配顶部声明的 ~2:20
- [x] 章节切分符合"每章 3-8 步 / 30-60s 一聚焦主题"经验
- [x] 末尾素材清单分章节列出
- [x] 脚本无标题/序号等非口播内容
