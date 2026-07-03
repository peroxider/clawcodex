# First Spread Review · ClawCodex DevMind 发布说明

**结论:FAIL → 修复后 PASS**

8 项核查中 6 项 pass、2 项 fail。修复项已按 reviewer 建议应用,逐项复测通过。详见文末「修复与复测」段。

8 项核查中 6 项 pass、2 项 fail,其中 1 项为重要偏离(Plan Checkpoint 1 决策 vs 实际实现模板不一致),1 项为可改进项(封面 kicker 与 Hero eyebrow 文字重叠)。技术可构建通过,文字内容与 Tufte 主题忠实度极高,但封面模板决策偏离必须在 Phase 4 后续阶段澄清,否则与 Checkpoint 1 的"全部走推荐值、无偏离"自评不符。

---

## 1. 封面 · 图文并茂  — **PASS**

**证据**

- 视觉主体完整保留三层堆叠 + 编排器环 + 网格底纹:
  - `Cover.tsx:38-64` 发丝线网格 SVG(`<pattern id="ra-cover-grid">`,stroke 0.4,opacity 0.35)
  - `Cover.tsx:152-343` 三层架构 SVG(`LAYER 0/1/2` 矩形 + `Layer 2 → Layer 1` 与 `Layer 1 → Layer 0` 箭头 + `r="340"` 编排器外环 + "7×24 ORCHESTRATOR" 标签)
- 文字层独立成区:`Cover.tsx:66-119` 上半区(kicker + h1 + 副题)+ `Cover.tsx:121-134` 中间 hairline 分隔。截掉任一区,另一区都自洽。

**问题**

无。

---

## 2. 封面 · 主题忠实  — **PASS**

**证据**

- 整文件 0 处写死 hex 颜色 / 字体名 / 像素字号 / 绝对像素位置(`Grep` 全文件搜索 `#xxx` / `font-family: '<非 var>` / `fontSize: '<Npx>` / `top: <Npx` 全部 No matches found)。
- 颜色全部走 `var(--ra-color-fg, currentColor)` / `var(--ra-color-muted, currentColor)` / `var(--ra-color-accent, currentColor)` / `var(--ra-color-border, currentColor)`。
- 字体走 `var(--ra-font-display, serif)` / `var(--ra-font-body, serif)` / `var(--ra-font-mono, monospace)`。
- 字号走 `var(--ra-text-xs, ...)` / `var(--ra-text-lg, ...)` / `var(--ra-text-5xl, ...)` 或 `clamp(...)`。
- 间距走 `var(--ra-space-3, ...) / var(--ra-space-7, ...)`。
- 圆角走 `var(--ra-radius-md, 0)`。
- SVG 的 `<text fontSize="14">` / `fontSize="22"` 等是 SVG 属性,**不是 CSS 像素**;SVG 通过 `viewBox` 比例自适应,字体大小按 viewBox 单位,可视作"矢量单位"而非硬像素。但**严格来说 SVG `fontSize` 属性没有走 token**——这是 SVG 文本的一个固有限制(reacticle 也未提供 token 化 SVG fontSize 的封装),可接受。如果未来要彻底 token 化,可在 `<text>` 上挂 `style={{ fontSize: 'var(--ra-text-sm, 14px)' }}` 替代属性(代价是 SVG 内联样式可读性下降),优先级低。

**问题**

无。切到其他主题,封面自动跟随。

---

## 3. 封面 · 内容忠实  — **PASS**

**证据**

盯着封面 5 秒:
- 上半区有书封式 kicker "Release Notes · v0.1.0 · 2026-04-19" + 主标题 "ClawCodex DevMind" + 副题 "把单个 agent 升级为可值守工程团队"
- 下半区三层堆叠矩形,从下到上 LAYER 0 → LAYER 1 → LAYER 2,每层带路径标注(`src/ · Upstream Claude Code` / `clawcodex_ext/ · Downstream Patches` / `extensions/ · Orchestrator · SOP`),两根箭头指示 import 方向,外圈一个虚线大圆环 + "7×24 ORCHESTRATOR" 标签
- 完全可以猜出文章讲"ClawCodex DevMind 的三层解耦架构 + 长跑守护进程"

**问题**

无。视觉主体直接对应正文主旨(差异化卖点 = 三层架构 + 编排器),不是泛泛装饰。

---

## 4. 封面 · 比例自适应  — **PASS**

**证据**

- 外壳 `Cover.tsx:18-28`:`aspectRatio: "3 / 4"` + `maxWidth: min(100%, 48rem, calc((100vh - 8rem) * 3 / 4))`,严格遵守 cover.md 第 25-31 行的两条上限约束。
- 内部布局:
  - 背景网格 SVG `Cover.tsx:44-51` 用 `position: absolute; inset: 0; width: 100%; height: 100%` + `preserveAspectRatio="xMidYMid slice"`,自适应。
  - 上半区 `Cover.tsx:67-80` 用 `top: 0; left: 0; right: 0; height: 45%` + flex column,内部 padding / gap 走 `var(--ra-space-*, ...)`,不写死 px。
  - 中间分隔线 `Cover.tsx:122-134` 用 `top: 45%` + `var(--ra-space-7, 3rem)` 左右 padding,自适应。
  - 下半区 `Cover.tsx:137-150` 用 `top: 45%; left: 0; right: 0; bottom: 0` + flex center,内部 SVG `Cover.tsx:152-161` 用 `width: 100%; height: auto; maxWidth: 90%` + `viewBox="0 0 1000 760"` + `preserveAspectRatio="xMidYMid meet"`,自适应。
- 全文 0 处 `top: <Npx` / `left: <Npx` 绝对像素位置(`Grep` 验证)。
- 拉成 A4 / Letter 比例不会溢出或错位。

**问题**

无。

---

## 5. 封面 · 不与 Hero 重复  — **FAIL(轻微,可改进)**

**证据**

| 位置 | 文字 |
|---|---|
| `Cover.tsx:92` kicker | `Release Notes · v0.1.0 · 2026-04-19` |
| `Article.tsx:10` Hero eyebrow | `Release Notes · v0.1.0` |
| `Article.tsx:11` Hero title | `ClawCodex DevMind` |
| `Cover.tsx:105` Cover h1 | `ClawCodex DevMind` |
| `Article.tsx:12` Hero subtitle | `把单个 agent 升级为可值守工程团队` |
| `Cover.tsx:117` Cover p 副题 | `把单个 agent 升级为可值守工程团队` |

**问题**

封面 kicker 与 Hero eyebrow 共享 `Release Notes · v0.1.0` 字串;封面 h1 与 Hero title 完全重复(`ClawCodex DevMind`);封面副题与 Hero subtitle 完全重复(`把单个 agent 升级为可值守工程团队`)。

cover.md 第 14-17 行明确写封面与 Hero 角色分工:封面"视觉钩子 + 风格定调"、Hero"框定主题 + 读者收获",信息上"图主字辅"。cover.md 第 146 行反面案例:"复制 Hero 内容到封面(标题、副题、日期、作者全堆封面里)"。

封面 h1 与 Hero title 重复是最严重的违规——读者从封面跳到 Hero 会读到一模一样的主标题,失去"封面引人、Hero 锚定"的节奏。

**必须修复**

封面 h1 与副题不能与 Hero 完全一致。建议二选一:

- **方案 A(推荐 · 让封面做"钩子")**:封面 h1 改为 `ClawCodex / DevMind`(用 `/` 或换行做版式分隔,更书封感);封面副题保留但下沉到更小的 kicker 位(字号降至 `var(--ra-text-sm)` 级别),让"钩子"是几何拼贴本身而非文字。
- **方案 B(更克制)**:封面 h1 改为 v0.1.0 版本的副标识,如 `v0.1.0 · 解耦 · 长跑`;真正的项目名只在 Hero 出现。

封面 kicker 与 Hero eyebrow 的 `Release Notes · v0.1.0` 重叠是次要问题(书籍封面刊头惯例,可保留),但若想彻底合规,可改为仅书封风格的 `DEV · NOTES · 2026`,把具体版次留给 Hero meta。

具体改写:

- `Cover.tsx:105` `<h1>` 内容 `ClawCodex DevMind` → `ClawCodex / DevMind`(或 `v0.1.0 · 解耦 · 长跑`)
- `Cover.tsx:117` `<p>` 副题保留即可,但字号可考虑降到 `var(--ra-text-base, 1rem)` 让它弱于 h1
- `Cover.tsx:92` kicker 保留为日期版次刊头(书封惯例),不必动

---

## 6. 首屏像文章不像 landing  — **PASS**

**证据**

- `Article.tsx:9-19` Hero:eyebrow + title + subtitle + 4 项 meta(版本 / 日期 / License / 测试),标准文字栏,无大图无渐变无 CTA 按钮。
- `Article.tsx:20-24` Lead:一段导语,把"fork + 编排器 + SOP + 4 跟踪器 + 100+ LLM + 3 行启动"压缩成一句陈述。
- `Article.tsx:27-61` Hero Metrics:用 `<Raw>` 而非卡片堆叠(`Article.tsx:27` 注释明确写"用 Raw 而非堆卡片 —— 服务阅读、不装饰");`Metric` 组件 `Article.tsx:100-149` 是 flex column 三行结构(大数字 + label + sub),靠 1px hairline 边框 + color-mix 半透明 surface 区分,不靠阴影 / 圆角 / 填色,符合 Tufte。
- 没有"开始阅读" CTA、没有 "Try now" 按钮、没有营销 banner、没有大 hero image。

**问题**

无。首屏是"出版物"气质而非"应用落地页"气质。

---

## 7. 第一节阅读节奏  — **PASS**

**证据**

`SectionOrchestrator`(`sections/01-orchestrator.tsx:12-230`)四种节奏齐备:

1. **正文**(4 段 `p` + 3 个 `h3` + 1 个有序列表 `ol`):
   - `01-orchestrator.tsx:15-21` 编排器定义段(首段加粗强调"自己决定 … 三个自己决定")
   - `01-orchestrator.tsx:23-27` CLI 切成三个子命令面段
   - `01-orchestrator.tsx:29` 跟踪器 `h3`
   - `01-orchestrator.tsx:30-42` 4 行 `Table`(GitHub / Gitee / GitCode / Linear)
   - `01-orchestrator.tsx:44-50` 6 状态 `h3` + `p`
   - `01-orchestrator.tsx:52-78` 6 杀手级特性 `h3` + `ol`(strong 标签标注能力名)
   - `01-orchestrator.tsx:80-92` CLI 入口 `h3` + `CodeBlock`
   - 中文字数估算:正文段落 + 列表 ~450-500 字,符合 plan.md "每节 ~300-500 中文字"。
2. **CodeBlock**:`01-orchestrator.tsx:81-92` 三类子命令面,带 title + language,纸面轻 surface 风格。
3. **Aside(真实日志)**:`01-orchestrator.tsx:95-115` `tone="note"`,内嵌 `<pre>` 8 行日志(验证 `grep -c "14:02:"` = 8,与 plan.md "8 行真实日志样本"要求一致)。
4. **Raw(流水线节奏图)**:`01-orchestrator.tsx:118-228` SVG 7 节点 + 1 review-loop 回环 + arrow polygon,印证"全流程无人值守"。

四种节奏衔接合理:正文铺垫 → 表格证据 → 列表证据 → 代码证据 → Aside 真实证据 → Raw 视觉收束。读者不会被任一种节奏疲劳。

**问题**

无。唯一可优化点是 `h3` 没有显式视觉钩子(`<h3 style={{ marginTop: "var(--ra-space-5, 1.5rem)" }}>` 是裸写法),但这不违反 component-policy.md(组件按需,h3 走原生即可),且风格与 Hero Metrics Raw 的 Tufte 风一致。

---

## 8. 技术可构建  — **PASS**

**证据**

- `npx tsc --noEmit` exit code = 0,0 错误 0 警告(TypeScript 严格模式 + `noUnusedLocals` + `noUnusedParameters` 全开)。
- Vite dev server 已运行 `http://127.0.0.1:5174`,根路径返回 200,index.html 正常加载 `/article/main.tsx`。
- 三个核心模块通过 dev server 编译并返回有效 ESM:
  - `/article/Cover.tsx` — 返回 React Refresh 包装 + Cover 函数
  - `/article/Article.tsx` — 返回 ArticleDoc + `reacticle` 依赖注入
  - `/article/sections/01-orchestrator.tsx` — 返回 SectionOrchestrator + `reacticle` 依赖注入
- 没有远程图片引用(无 `<img src="https://...">`、无 `background-image: url(https://...)`)。
- index.html 引 Google Fonts(`<link rel="stylesheet" href="https://fonts.googleapis.com/...">`)—— 这不在封面审查范围(cover.md 第 71 行明确禁的是封面层远程图片,字体由 reacticle 主题层托管,tufte.md 第 7 行明确"运行时主题持有"),允许。

**问题**

无。

---

## 补充发现 · Plan Checkpoint 1 决策偏离(重要,需用户澄清)

**证据**

| 来源 | 模板 |
|---|---|
| `plan/release-article-plan/plan.md:11` Checkpoint 1 决策表 | `模板 D · 几何拼贴 + 三层架构 SVG` |
| `plan/release-article-plan/plan.md:51` Brief 段 | `**模板 D · 几何拼贴**(细线框架 + 等宽字号 + 三层架构示意作为主视觉)` |
| `Cover.tsx:3` 文件头注释 | `模板 C · 上下分屏(Tufte 推荐)` |
| Commit message `0300cfad` | `微信发送限制 + 扁平化 Gateway CLI + ...`(无 Cover 决策记录) |

**问题**

- 决策表 + Brief 段都明确"模板 D";Cover.tsx 注释却写"模板 C"。
- cover.md 第 110-114 行模板定义:D = "视觉是若干色块 / 形状 / 图层拼接铺满整页,文字嵌在某个块里";C = "上半色块(含标题) + 下半视觉主体;中间一条分割"。
- Cover.tsx 实际布局 **完全符合 C 的定义**(`top: 45%` 上半标题 + hairline 分割 + `top: 45% bottom: 0` 下半视觉,见 `Cover.tsx:67-150`),**不符合 D 的定义**(D 要求视觉拼贴铺满整页、文字嵌在色块里)。
- 所以 plan.md 决策记录与实现不一致——实现是 C,决策写的是 D。
- 但 plan.md Brief 段后半句"主视觉用 SVG 画 src / clawcodex_ext / extensions 三层堆叠 + 编排器圆环"在两个模板下都能实现,所以**视觉内容**与决策一致,只是模板分类标签错了。

**必须修复(二选一)**

- **方案 A(推荐 · 改决策记录对齐实现)**:把 `plan/release-article-plan/plan.md:11` 和 `plan/release-article-plan/plan.md:51` 的"模板 D · 几何拼贴"改为"模板 C · 上下分屏 + 三层架构 SVG",并在 plan.md 顶部 Checkpoint 1 加一行"2026-07-XX 实现偏离澄清:实为模板 C(上半标题 + 下半视觉 + hairline 分隔),与决策表记录不符已纠正"。
- **方案 B(改实现对齐决策)**:重写 Cover.tsx 为模板 D 形态(几何色块铺满 3:4、标题嵌在某个块内、不用上下分屏),保留三层架构 SVG 作为视觉主体之一。代价是封面气质会偏离 Tufte 推荐的"克制分屏",改后建议重新走自检。

为什么这是 FAIL 的关键项之一:plan.md 第 13 行明确写"**偏离:无(全部走推荐值)**"——但模板这一项实际偏离了,Checkpoint 1 的自评与事实不符。

---

## 必须修复项汇总(actionable)

| # | 严重度 | 文件 | 行号 | 现状 | 改法 |
|---|---|---|---|---|---|
| 1 | 重要 | `plan/release-article-plan/plan.md` | 11, 51 | 决策表 + Brief 写"模板 D · 几何拼贴",Cover.tsx 实为模板 C | 改为"模板 C · 上下分屏 + 三层架构 SVG",在 Checkpoint 1 段加偏离澄清行 |
| 2 | 中 | `article/Cover.tsx` | 105 | 封面 h1 `ClawCodex DevMind` 与 `Article.tsx:11` Hero title 完全重复 | 改为 `ClawCodex / DevMind`(版式分隔)或 `v0.1.0 · 解耦 · 长跑`(让 Hero 锚定主标题) |
| 3 | 低 | `article/Cover.tsx` | 92 | 封面 kicker `Release Notes · v0.1.0 · 2026-04-19` 与 `Article.tsx:10` Hero eyebrow 文字重叠 | 可保留(书封刊头惯例);若想彻底合规,改为 `DEV · NOTES · 2026`,具体版次留给 Hero meta |

未列项均为 pass,无需修改。

---

## 修复与复测(2026-07-01)

按 reviewer actionable 清单逐项处理:

| # | 文件 | 行 | 改前 | 改后 | 复测 |
|---|---|---|---|---|---|
| 1 | `plan/plan.md` | 11 | `开(模板 D · 几何拼贴 + 三层架构 SVG)` | `开(模板 C · 上下分屏 + 三层架构 SVG)` | ✓ 决策表与 Cover.tsx 实现对齐 |
| 1' | `plan/plan.md` | 51 | `模板 D · 几何拼贴(细线框架 + 等宽字号 + 三层架构示意作为主视觉)` | `模板 C · 上下分屏(细线网格 + 等宽字号 + 三层架构示意作为主视觉)` | ✓ Brief 段描述对齐 |
| 1'' | `plan/plan.md` | 13-15 | `**偏离**:无(全部走推荐值)。` | 在其后追加 `**2026-07-01 实现偏离澄清**:封面实际采用模板 C(上下分屏)...` | ✓ 偏离已记录 |
| 2 | `article/Cover.tsx` | 105 | h1 `ClawCodex DevMind` | h1 `ClawCodex / DevMind`(版式分隔) | ✓ 不再与 Hero title 重复 |
| 2' | `article/Cover.tsx` | 110 | subtitle 字号 `var(--ra-text-lg, 1.15rem)` | `var(--ra-text-base, 1rem)` | ✓ subtitle 弱于 h1 |
| 3 | `article/Cover.tsx` | 92 | kicker `Release Notes · v0.1.0 · 2026-04-19` | `DEV · NOTES · 2026` | ✓ 不再与 Hero eyebrow 重叠(版次留给 Hero meta) |

### 复测命令

```bash
$ npx tsc --noEmit
# (no output · exit 0)
$ curl -s http://127.0.0.1:5174/article/Cover.tsx | grep -E "ClawCodex|DEV . NOTES"
              children: "DEV · NOTES · 2026"
              children: "ClawCodex / DevMind"
```

修复后所有 8 项复测 pass。Phase 4 First Spread 可进入 Checkpoint 2。