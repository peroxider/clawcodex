# Plan · ClawCodex DevMind 发布说明长文

## Checkpoint 1 决策记录(2026-07-01)

| # | 决策项 | 用户确认 |
|---|---|---|
| 1 | 文章类型 | `full-report · ~80%` |
| 2 | 主题 | `tufte · Data-Ink` |
| 3 | 版式宽度 | `regular` |
| 4 | 配图模式 | `none`(Raw 始终存在) |
| 5 | 封面 | `开`(模板 C · 上下分屏 + 三层架构 SVG) |

**偏离**:无(全部走推荐值)。

**2026-07-01 实现偏离澄清**:封面实际采用**模板 C(上下分屏)**而非 Brief 段写下的"模板 D · 几何拼贴"。模板选择从 D 改回 C 的理由:Tufte 主题 profile 推荐"极细线网格 + 低饱和数据点",气质更贴合"克制分屏"而非"满屏拼贴"。视觉内容(细线网格 + 三层堆叠 + 编排器环)与原决策一致,只是模板分类标签从 D 纠正为 C。此项决策记录与最初 Brief 段描述不符,在此纠正。

**语言 / TOC / 编辑权限**默认跟随(语言 = 跟随源 = 中文;TOC = 开;允许编辑删减重组)。

---

## Brief

- **目标读者**:正在评估 ClawCodex DevMind 是否值得在自家工程链上试用的 AI 工程师 / 技术负责人;次级读者是想了解 Python agent 工具链现状的旁观工程师。
- **目标语言**:跟随源(中文)。源 `assets/video-b/article.md` 是中文;`CHANGELOG.md.raw` 已在 `source/extraction-notes.md` 中说明 → 已译为地道中文并入 `source/source.md`。
- **文章类型**:`full-report · ~80%`(推荐)。理由:技术叙事为主,有 CLI / 架构 / 安装 / 限制多块并列证据,适合完整报告型;`longform 100%` 会过于技术白皮书化,`essay 70%` 会损失关键事实;`tutorial 90%` 会过度强调安装教程,弱化架构差异。
- **信息保留比例**:**80%**(type-标准)。已删:CHANGELOG 的 Dependencies 列表、Migration Notes、Future Roadmap、Special Thanks 段、§7 视觉配图建议(降级为内部备忘)、§8 "不要写 F-N" 约束(已在 CLAUDE.md 隐式生效)。
- **必须保留**:
  - 一句话定位 + 项目元信息(repo · license · python 版本 · 测试覆盖数字)
  - 编排器 4 跟踪器 + 6 状态 + 6 杀手级特性 + 真实日志样本(8 行)
  - SOP 编译器 4 模块 + 输出 + 协同方式 + 示例命令
  - 4 个辅助能力(PR auto-fix / LiteLLM / Cron+IM / 运行时切模型)
  - **三层解耦架构**(差异化核心卖点) + 黄金法则简述
  - 一键安装 3 平台命令原文 + 辅助命令 + 预置要求
  - Hero Metrics 3 数(4 / 100+ / 3 行)
  - 5 个次要卖点(emoji 保留)
  - v0.1.0 MVP 已交付清单(核心 6 项)
  - 已知限制 4 条(诚实声明)
- **可删减**:
  - CHANGELOG Dependencies 列表 → 不在发布文披露技术栈底牌
  - CHANGELOG Migration Notes → 初版无迁移
  - CHANGELOG Future Roadmap → 内部路线图,不在对外承诺
  - CHANGELOG Special Thanks → 致敬无需出现在正式发布
  - 真实日志样本中 "AGENTSDK-15" 任务 ID → 保留或泛化(`AGENTSDK-NN`)
- **语气**:克制分析 + 出版叙事。Tufte 主题的衬线字体支持"分析报告"气质;但叙述保留"可值守工程团队"、"全流程无人值守"这类出版感短语,避免变成纯规格表。
- **主要观点**(读者读完应记住):
  1. ClawCodex DevMind = Claude Code Python 重构版 + 编排器 + SOP 编译器;其**唯一差异化**是长跑守护进程把单 agent 升级为值守团队
  2. 三层解耦架构(`src` / `clawcodex_ext` / `extensions`)是 fork 长期可维护性的根本保障
  3. 安装摩擦极低(一行命令),运行摩擦也低(`/provider litellm` · `/model gpt-4o` 即时切)
- **阅读目标**:读者读完能(a) 决定是否尝试;(b) 知道在哪一行命令安装;(c) 理解其与 Claude Code 上游的根本差异(编排器 + SOP + 三层解耦)。
- **版式宽度**:`regular`(默认)。理由:正文含代码块 + 表格 + 短引用,`narrow` 会让代码块换行频繁,`wide` 会让行过长降低阅读节奏。
- **TOC**:**开**(默认)。
- **配图策略**:`none`。理由:Beautiful Article 是单文件 HTML 文章,不适合嵌入 `assets/orchestrator/viz/*.html` 这种交互式 SVG(它们自身已是完整 HTML 页面);发布文章应靠正文 + Raw + 表格承载视觉密度,而非外部图片。Raw 块(`--ra-*` token)可承担架构示意图职责(类似 `orchestrator/article/index.html` 已实现的 SVG 风格)。
- **封面**:**开**(默认)。构图想法:Tufte 主题下,封面选 **模板 C · 上下分屏**(细线网格 + 等宽字号 + 三层架构示意作为主视觉),主视觉用 SVG 画"src / clawcodex_ext / extensions 三层堆叠 + 编排器圆环"——同时承担主题(克制 + 数据墨水)与内容(差异化卖点)双重职责;标题"ClawCodex DevMind · 发布说明",副标题"把单个 agent 升级为可值守工程团队"。

## Outline

- **Hero**:大字"ClawCodex DevMind" + 副标题"把单个 agent 升级为可值守工程团队" + meta(版本 `v0.1.0` · 发布日期 `2026-04-19` · License MIT · 270+ tests)
- **Lead**:一句话导语 + 三个 Hero Metrics 横排(`4` 跟踪器 · `100+` LLM · `3 行` 启动流水线)
- **Summary**:不放(避免重复 Lead);若用户后续要求 TL;DR 再补

### Sections

1. **01 · 编排器 · 长跑守护进程**
   - 保留信息:source.md"编排器"段全段(4 跟踪器 / 6 状态 / 6 杀手级特性 / CLI 三类子命令 / 8 行真实日志样本)
   - 需要的组件:Section 正文 + CodeBlock(CLI 三类子命令) + Aside(8 行真实日志作为终端展示)
   - 是否需要 Raw:**是**。Raw 用途:用 SVG 画"issue → workspace → commit → PR → review-loop"流水线节奏图(细线 + 节点),印证"全流程无人值守"
2. **02 · SOP 编译器 · workflow.md → 多 agent 团队**
   - 保留信息:source.md"SOP 编译器"段全段(4 模块名 / 输出三件套 / 协同方式 / 示例命令)
   - 需要的组件:Section 正文 + CodeBlock(sop convert 命令)+ Aside(模块名列表)
   - 是否需要 Raw:**是**。Raw 用途:用 SVG 画"workflow.md → sdk_parser → skill_grouper → agent_builder → {agent 定义 · 入口 skill · 编排图}"数据流
3. **03 · 四个辅助能力**
   - 保留信息:source.md"四个辅助能力"段全段(PR auto-fix / LiteLLM / Cron+IM / 运行时切模型)
   - 需要的组件:Section 正文 + 4 张小卡(每张 1 能力)或 4 段并列小节
   - 是否需要 Raw:**否**(这是清单式,正文 + 列表足够;Raw 留给 §1 §2 那种"流程/机制"型内容)
4. **04 · 三层解耦架构**
   - 保留信息:source.md"三层解耦架构"段全段(三个 layer 简述 + 黄金法则 4 条)
   - 需要的组件:Section 正文 + Raw(架构骨架代码块)+ Aside(黄金法则引用)
   - 是否需要 Raw:**是**(架构骨架本身就是代码块式的目录树,但 Raw 块可增强:用 SVG 画 3 层叠加 + 箭头表示 import 关系)。这里把代码树放进普通 CodeBlock(不是 Raw),用 Raw 单独承担"层间 import 流向"示意图
5. **05 · 一键安装**
   - 保留信息:source.md"一键安装"段全段(3 平台表格 + 辅助命令 3 条 + 预置要求 4 条)
   - 需要的组件:Section 正文 + Table(3 平台)+ CodeBlock(辅助命令)+ 列表(预置要求)
   - 是否需要 Raw:**否**(纯表格 + 代码 + 列表,无需图解)
6. **06 · 已知限制 + 项目元信息**
   - 保留信息:source.md"已知限制"4 条 + "项目元信息" + "v0.1.0 MVP 已交付"6 项(可选)
   - 需要的组件:Section 正文 + 列表(限制 4 条)+ 列表(交付 6 项) + Aside(gitcode 仓库链接 + 镜像链接)
   - 是否需要 Raw:**否**

- **结尾方式**:**行动项收束**。不放总结性抒情,放"复制这行命令,装一个 → gitcode.com/chadwweng/clawcodex"。

## Theme

- **选定主题**:`tufte`(Edward Tufte Data-Ink)
- **理由**:
  - 读者是 AI 工程师,要凑近去读代码、架构、命令;Tufte 的"低装饰 + 发丝级参考线 + 衬线老式字"恰好是这一阅读场景的最佳承载
  - 内容以"论点 + 证据(代码 / 表格 / 列表)"为主,而不是"叙事 + 视觉冲击";Tufte 的克制气质让证据说话
  - 不与视频(终端绿 CRT)和 landing(冷蓝黑青绿)争视觉风格——三者分工清晰(landing = 决策点 / video = 演示 / article = 深入阅读)
- **与源材料的冲突**:**无**。源材料的"工程叙事" + "代码 + 表格 + 列表"格式与 Tufte 完全契合。
- **当前信息密度(80%)下的表现建议**:
  - 正文为主(每节 ~300-500 中文字)
  - Raw 仅用于 §1(流水线节奏图)、§2(数据流图)、§4(层间 import 流向图)3 处;其余节一律正文 + 组件承载
  - 代码块用纸面轻 surface + 发丝线,不用深色编辑器壳
  - 表格用 hairline(发丝线),不用填色斑马纹
  - 引用 / 强调用字重 / 字色,不靠斜体(Tufte 协议禁用)
  - 字号保持偏小(~16px),行距 1.6——读者凑近读

## Assets

- **策略**:`none`
- **一句话说明**:本文章不使用外部 Image;架构 / 流程 / 机制图用 Raw 块(SVG / CSS,主题 token `--ra-*`)表达;数据 / 命令 / 列表用组件(Table / CodeBlock / List)承载。Raw 始终存在,与配图策略正交。

### 逐图计划

- 不适用(`none` 模式不写逐图计划)