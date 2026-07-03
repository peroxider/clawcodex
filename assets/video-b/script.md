# ClawCodex DevMind · 项目展示视频 · 口播稿

> **总时长**：约 2 分 20 秒（口播 ~ 650 字 ÷ 4.5 字/秒）
> **章节**：4 章 / 40 步
> **风格**：B 站科技类 · 短句节奏 · 演示驱动 · 反差钩子开场
>
> **约定**：行内代码（如 `curl ... | bash`）是**屏幕显示**的口播搭档，**不念出口**。
> 念的只是代码外的口语。chapter agent 用行内代码做终端视觉。

---

## 第一章 · coldopen（3 步 / ~9s）

你睡了，agent 在干活。
---
早上醒来，PR 自己开了。
---
这就是 ClawCodex DevMind。

---

## 第二章 · orchestrator · 自主流水线（16 步 / ~52s）

它有个 Orchestrator，编排器。
---
一条常驻流水线，盯 4 个 issue 平台——GitHub、Gitee、GitCode、Linear。
---
哪个 issue 冒头，worktree 拉出来，agent 进场。
---
真实跑起来长这样——
---
Read，132 行代码。
---
Grep 关键字，3 个匹配。
---
Edit，加 18 行删 4 行。
---
Bash 跑 pytest，4 个 test 全过。
---
Verification gate OK。
---
Commit。Push。
---
PR opened。
---
reviewer 评论落地？
---
它接住，自己改，再 commit，同分支。
---
CI 报错？再读再改再跑。
---
你也能随时插一脚。`clawcodex-dev orchestrator issue takeover`，REPL 接管，完事切回。
---
13 种状态机管全程。

---

## 第三章 · sop-compiler · 多 agent 团队（8 步 / ~30s）

第二个看家本领：SOP 编译器。
---
你写个 workflow.md，描述流程。
---
它编译成一组多 agent 团队——
---
每个角色一个 agent，一个入口 skill，一张编排图。
---
agent 间 SendMessage 互相通信。
---
崩了能恢复。
---
一行命令搞定——`clawcodex-dev sop convert your_workflow.md --out ./.clawcodex`。

---

## 第四章 · install + 完整面貌（13 步 / ~48s）

装它只要 3 行。
---
macOS、Linux、WSL——`curl -fsSL https://raw.githubusercontent.com/peroxider/clawcodex/main/install.sh | bash`，复制粘贴回车。
---
PowerShell 也一行。
---
`iwr ... | iex`，搞定。
---
想改源码——3 步。
---
`git clone`，`uv venv`，`uv pip install -e ".[all]"`，三步走。
---
装好以后——`clawcodex-dev --version` 验一下。
---
想要点安全感？`--dry-run` 先模拟一遍。
---
环境不太确定？`doctor` 预检一下。
---
4 个 issue 平台。
---
100 多个 LLM 后端。
---
3 行起跑。
---
现在去装一个。链接在简介。
