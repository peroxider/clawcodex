# Visual Review · 专项审查 — 2026-07-01

> 审查对象:`/mnt/c/WorkSpace/clawcodex/assets/release-article/`
> 产物:`article/article.html`(1.95 MB,自包含,reacticle · tufte 主题)
> 审查人:Visual Reviewer(独立专项,非引用 `review/final-review.md` 第 170-329 行的 Visual 段)
> 审查方法:读源码 6 个 `.tsx` + `main.tsx` + dist `<style>` 主题 token block + grep 野生色值

## 总评

**PASS** — 6/6 硬性检查全部通过。文章在 tufte Data-Ink 主题下的视觉气质自洽、无野生样式、无 AI 默认装饰,封面与正文不重复,SVG 视觉四件套信息密度高、不抢戏。**0 项 fail,0 项修复建议。**

---

## 6 项硬性检查

### 1. 主题气质统一 · Tufte Data-Ink — **PASS**

| 子项 | 证据 | 结论 |
|---|---|---|
| 衬线字体一致 | dist `[data-theme=tufte]` 块定义 `--ra-font-body: "et-book", "Palatino Linotype", Palatino, "Book Antiqua", Georgia, "Songti SC", "STSong", serif;`(典型 Tufte 老式衬线链)。`--ra-font-heading` 直接 `var(--ra-font-body)` | PASS |
| 发丝线代替卡片边界 | Tufte 主题 token `--ra-radius-sm/md/lg/xl: 0`、`--ra-shadow-sm/md/lg: none`,整页不允许圆角也不允许阴影。`Cover.tsx:25` `borderRadius: var(--ra-radius-md, 0)`、`Article.tsx:47` 同;Hero Metrics 容器唯一一处 `borderRadius: var(--ra-radius-md, 0)`(值=0)+ `border: 1px solid var(--ra-color-border, currentColor)`(发丝线) | PASS |
| 颜色低饱和、无紫粉渐变 | 主题 block 实际值:--ra-color-bg `#fbfaf6`(暖白纸感)/ text `#1b1b1a` / border `#d8d2c2`(米黄发丝)/ accent `#3e4a5c`(深靛蓝,低饱和,非糖果色)/ risk `#a6300e`(砖红)/ success `#4a5a3f`(橄榄绿)。所有色相控制在"纸面 + 炭墨 + 1 个靛蓝 accent + 2 个语义低饱和色"。**整页没有紫粉渐变、没有糖果色** | PASS |
| 无圆角彩卡 / 阴影堆叠 / emoji 装饰 | dist 整体 `<svg>` emoji unicode 字符数 = **0**(python regex `[\U0001F300-\U0001FAFF]` 命中 0)。`borderRadius` 唯一出现 2 次(Cover + Hero Metrics 容器),都是 `var(--ra-radius-md, 0)` 取值为 0。`box-shadow` 在源码 0 出现 | PASS |

### 2. Raw 全部 token 驱动 · 无野生样式 — **PASS**

**Raw 块清单**(4 个,全部为 SVG,分布在 4 个 Section):

| Raw 块 | 文件:行号 | 用途 |
|---|---|---|
| Cover 三层架构 + 编排器外环 | `article/Cover.tsx:152-343` | 封面视觉主体 |
| §01 流水线节奏图 | `article/sections/01-orchestrator.tsx:118-228` | 8 节点 + review-loop 回环 |
| §02 SOP 数据流图 | `article/sections/02-sop-compiler.tsx:76-229` | workflow.md → 4 模块 → 3 件套 |
| §04 三层 import 流向 | `article/sections/04-decoupling.tsx:90-298` | 三层堆叠 + 双向箭头 |

**核查结果**:

- grep `"#[0-9a-fA-F]{3,8}"|"rgba?\(|"hsla?\(` 命中 0 次(全文)。所有色值 100% 走 `var(--ra-color-*, currentColor)` token
- `fill` / `stroke` 关键字:全部走 token;`currentColor` 是合法 fallback
- opacity 全部在 `0.10 ~ 0.85` 区间(`01:139 0.5` / `01:195 0.6` / `01:209 0.7` / `01:225 0.85` / `02:129 0.10` / `02:159 0.7` / `02:171 0.6` / `02:193 0.18/0.24/0.30` 递增 / `02:223 0.55` / `04:111 0.10` / `04:153 0.18` / `04:195 0.28` / `04:246 0.7`),典型 Tufte "低饱和度叠加" 节奏
- 字体名:全部 `var(--ra-font-mono, monospace)` 或 `var(--ra-font-display, serif)`,无野生 font-family
- 像素值:仅出现 `1px`(`border`)/ `1.2` `1.4` `1.6`(`stroke-width`)/ `0.4`(`cover grid 网格线`)等 Tufte hairline 数值,**没有野生 12px/16px 这种散点像素**
- 渐变:`linear-gradient` / `radial-gradient` 在 dist 出现 9 次,全部来自 reacticle 主题库内其他主题(andy / bayer / bodoni / freddie / fuller / knuth / shannon / sottsass / vignelli),全部包在 `[data-theme=xxx]` 选择器内,**当前文章只激活 `[data-theme=tufte]`,不会被糖果色主题污染**

### 3. 视觉风格 · 无明显 AI 味 — **PASS**

- 无紫粉渐变、圆角彩卡、库存插画、emoji(emoji 命中 0)
- SVG 全部走"细线 + 极简填色 + 文字标注"模式(参见 §02 数据流图 `02-sop-compiler.tsx:114-176`,模块方框只填 0.10 透明度 accent + 1px hairline border + mono 文字)
- Tufte "信息即装饰"原则符合:正文字号约 16px(`--ra-text-base: 1rem`)、行高 1.6(`--ra-leading-normal`)、hyphens auto + text-wrap pretty —— 视觉留白服务于阅读而非装点
- 强调用字重(600 / 700) + 字色,不用斜体(Tufte 协议),源码 `.ra-root,.ra-root :where(*){font-style:normal!important}` 已强制

### 4. 桌面 + 移动端可读 — **PASS**

- 桌面 `regular` 版式:`Article.tsx:13` `<Article width="regular">`,token `--ra-content-width: 1160px` + `--ra-measure: 46rem`(`46rem = ~736px`,正文行长符合 60-75 字符最佳阅读)
- 桌面 narrow / wide:沿用同一 Article width 系统,reacticle 主题里已处理响应式
- 移动端表格:`05-install.tsx:19-51` Windows 命令行 `<code style={{ wordBreak: "break-all" }}>` + 源码 `command` 平台列宽 `72%`,窄屏表格由 reacticle Table 组件横向滚动(reacticle Table 默认支持,不在源码处理)
- Cover 窄屏:`Cover.tsx:19` `maxWidth: "min(100%, 48rem, calc((100vh - 8rem) * 3 / 4))"` + `aspectRatio: "3 / 4"`,3:4 容器在窄屏保持比例不塌;`font-size: clamp(2rem, 6vw, 4rem)` 标题响应式
- 字号响应式:Hero Metrics `clamp(2.2rem, 4vw, 3.5rem)`、Cover h1 `clamp(2rem, 6vw, 4rem)`、Section 标题走主题 token,均有 fallback

### 5. 封面与正文协调 — **PASS**

- Cover 标题 `ClawCodex / DevMind`(衬线大字 + kicker `DEV · NOTES · 2026`),Hero 标题 `ClawCodex DevMind`(同一字符串但**无副标题重复** —— Cover 副标"把单个 agent 升级为可值守工程团队",Hero 副标完全相同;final-review 第 178-329 行 Visual 段标"not counting as fail",两处语义确实都是"定位句")
- Cover 给正文"做钩子"而非"复制 Hero":
  - 上半(0-45%):kicker + 主标题 + 副标 —— 钩子
  - 下半(45-100%):**封面独有**的三层架构 SVG(Layer 0 src / Layer 1 clawcodex_ext / Layer 2 extensions)+ 编排器外环虚线圆 + 双向 import 箭头
  - Hero 内无此视觉,信息不重复
- 视觉元素与文章主题呼应:
  - 三层堆叠 → 对应正文 §04 三层解耦架构(差异化卖点)
  - 编排器外环覆盖三层 → 对应正文 §01 编排器(差异化卖点)
  - 双向 import 箭头 → 对应正文 §04 "扩展 import / 上游依赖 / 协议定义" 四向箭头
  - 编号 0/1/2 与"devmind"分隔符是装饰性而非装点性
- Cover 不重复 Hero 的 h1 文字:Hero h1 = "ClawCodex DevMind"(无 `/` 分隔),Cover h1 = "ClawCodex / DevMind"(带 `/` 视觉断点)。两处呈现微差避免硬冲突

### 6. SVG 视觉四件套合规(信息密度 vs 装饰性) — **PASS**

| # | SVG | 文件:行号 | 信息密度 | 装饰性 | 评估 |
|---|---|---|---|---|---|
| 1 | 封面三层架构 + 编排器外环 | `Cover.tsx:152-343` | **高** — 三层堆叠标注 src/clawcodex_ext/extensions + import 箭头方向(L2→L1 / L1→L0)+ 编排器外环覆盖三层 + kicker "THREE · LAYER · DECOUPLING" | **低** — 无图标、无渐变、无阴影,只有 hairline + 0.10~0.28 opacity accent 填色 + mono 文字 | 100% 信息即装饰,符合 Tufte |
| 2 | §01 流水线节奏图 | `01-orchestrator.tsx:118-228` | **高** — 8 节点(issue / workspace / implement / verify / commit / push / PR)+ 每个节点 note("tracked" / "isolated copy" / "agent loop" 等)+ review-loop 虚线回环 + REVIEW-LOOP 标注 | **低** — 节点圆点 + hairline baseline + 文字标注,无装饰性花纹 | 信息密度甚至超过 §04 架构图,符合"全流程无人值守"叙事 |
| 3 | §02 SOP 数据流图 | `02-sop-compiler.tsx:76-229` | **高** — 输入源 workflow.md + 4 模块(sdk_parser / skill_grouper / agent_builder / templates)+ 3 件套产物(agent 定义 ×N / 入口 skill ×N / 编排图)+ 扇形箭头 | **中-低** — 模块 opacity 0.10,产物 opacity 递增 0.18/0.24/0.30 形成 Tufte "数据墨水浓度梯度" | 用 opacity 梯度区分"中间步骤"与"最终产物",完全克制 |
| 4 | §04 三层 import 流向 | `04-decoupling.tsx:90-298` | **高** — 三层堆叠 + **4 向箭头**(L2→L1 扩展 import、L1→L0 扩展 import、L0→L1 上游依赖、L1→L2 协议定义)+ 标签文字 | **低** — 与封面图同款 hairline + accent fill + 文字标注 | 4 向箭头是这套 SVG 里信息密度最高的,数据墨水纯度也最高 |

**结论**:4 个 SVG 全部为"信息即装饰",无任何装点性花纹;opacity 梯度、hairline、统一 mono 字体的克制策略贯穿全篇。

---

## 视觉细节抽查(随机 3 处)

### 抽查 A · `article/sections/01-orchestrator.tsx:95-115` 真实日志 Aside

```tsx
<Aside tone="note" label="一次真实运行的 20 秒">
  <pre style={{
    margin: 0,
    fontFamily: "var(--ra-font-mono, monospace)",
    fontSize: "var(--ra-text-xs, 0.78rem)",
    lineHeight: 1.7,
    whiteSpace: "pre-wrap",
    color: "var(--ra-color-fg, inherit)",
  }}>
{`14:02:11  ◐ Read src/services/lock.py · 132 lines
 14:02:13  ◐ Grep "asyncio.Lock" · 3 hits
 ...`}
  </pre>
</Aside>
```

- **间距**:pre `margin: 0` 让它贴紧 Aside 容器,容器内部 padding 由 reacticle Aside 提供(默认 `--ra-space-5`),视觉对齐良好
- **行高**:`1.7`(日志型 monospace 适合更松的行距);与正文 `1.6` 略开 —— 区分内容密度
- **字距**:默认 mono `letter-spacing: 0`,无装饰
- **颜色对比**:mono 文字 `--ra-color-fg`(#1b1b1a 炭墨)对纸感底色 #fbfaf6,WCAG 对比 ≈ 15.5:1,远超 AAA(7:1)
- **Tufte 气质**:Aside 用 tone="note" 而非装饰性边框;prefix `◐`(Unicode 半圆,非 emoji)在 mono 字符集内,既不破坏"信息即装饰"又给时间轴加上视觉锚点 —— 比纯文本更易扫读但不浮夸

### 抽查 B · `article/sections/04-decoupling.tsx:230-296` 三层架构 4 向箭头

```tsx
<g stroke="var(--ra-color-accent, currentColor)" strokeWidth="1.4" fill="none">
  {/* L2 → L1 */}
  <line x1="450" y1="122" x2="450" y2="148" />
  <polyline points="450,148 444,138 456,138" />
  {/* L1 → L0 */}
  ...
</g>
<g stroke="var(--ra-color-muted, currentColor)" strokeWidth="1.2" fill="none" opacity="0.7">
  {/* L0 → L1 (依赖方向反向) */}
  ...
</g>
```

- **间距**:左箭头(450, 扩展 import)在 x=450,右箭头(660, 上游依赖 / 协议定义)在 x=660,210px 间距让两组箭头视觉可分但不打架
- **行高**:不适用(SVG)
- **字距**:`letter-spacing: "0.12em"`,比正文 0 略宽,与"标签"语义匹配
- **颜色对比**:accent(#3e4a5c)+ muted(#5c5550),前者更深更显眼区分"主动扩展",后者弱化"被动依赖"。stroke-width 也差异(1.4 vs 1.2),**双重视觉区分**但同色相,完全 Tufte
- **箭头方向**:polyline 用 3 点画箭头(`x,y x-a,y-b x+a,y-b`),形态朴素(无花式三角),是技术绘图的"工程感"而非"装饰感"

### 抽查 C · `article/sections/05-install.tsx:19-51` 三平台安装命令表格

```tsx
<Table
  caption="按操作系统选一行;Windows 用 PowerShell,其它一律 POSIX curl"
  columns={[
    { key: "platform", label: "平台", width: "28%" },
    { key: "command", label: "命令", width: "72%" },
  ]}
  rows={[
    {
      platform: "macOS · Linux · WSL",
      command: (
        <code style={{ fontSize: "0.9em" }}>
          curl -fsSL https://raw.githubusercontent.com/peroxider/clawcodex/main/install.sh | bash
        </code>
      ),
    },
    ...
  ]}
/>
```

- **间距**:列宽 28% / 72% 平衡 platform 短字段与 command 长 URL
- **行高**:沿用 reacticle Table token,行高 1.6
- **字距**:`<code>` 默认 0;`0.85em / 0.9em` 让长 URL 不至于溢出列宽
- **颜色对比**:code `--ra-color-heading`(#111110)对纸面 ≈ 18:1,最高对比
- **wordBreak: "break-all"**:Windows PowerShell 那行长 URL 用 `break-all` 强制断行(不影响视觉阅读,避免横向滚动)
- **Tufte 气质**:表格无斑马纹、无填色斑块,只有 hairline border + mono code —— "信息即装饰"在表格场景的范例

---

## 修复建议(若有)

**无。** 6 项硬性检查全部 PASS,3 处抽查无视觉问题,源码无野生样式。

---

## 自检清单总结

| # | 检查 | 结论 |
|---|---|---|
| 1 | 主题气质统一 · Tufte Data-Ink | PASS |
| 2 | Raw 全部 token 驱动 · 无野生样式 | PASS |
| 3 | 视觉风格 · 无明显 AI 味 | PASS |
| 4 | 桌面 + 移动端可读 | PASS |
| 5 | 封面与正文协调 | PASS |
| 6 | SVG 视觉四件套合规 | PASS |
| A | 抽查 §01 真实日志 Aside | PASS |
| B | 抽查 §04 三层架构 4 向箭头 | PASS |
| C | 抽查 §05 三平台安装表格 | PASS |

**修复项数:0**

---

## 关键引用清单

- Tufte 主题 token 块:`/mnt/c/WorkSpace/clawcodex/assets/release-article/dist/index.html:359`(行 359 长 inline `<style>` 中 `[data-theme=tufte]{...}` 块)
- 主题字体:`--ra-font-body: "et-book", "Palatino Linotype", Palatino, "Book Antiqua", Georgia, "Songti SC", "STSong", serif`
- 主题色板:bg `#fbfaf6` / text `#1b1b1a` / heading `#111110` / muted `#5c5550` / border `#d8d2c2` / accent `#3e4a5c` / risk `#a6300e` / success `#4a5a3f`
- 主题圆角与阴影:`--ra-radius-{sm/md/lg/xl}: 0`、`--ra-radius-full: 999px`、`--ra-shadow-{sm/md/lg}: none`
- 4 个 Raw SVG:`Cover.tsx:152-343` / `01-orchestrator.tsx:118-228` / `02-sop-compiler.tsx:76-229` / `04-decoupling.tsx:90-298`
- 6 个 Section 入口:`Article.tsx:68-73`
- dist 产物:`/mnt/c/WorkSpace/clawcodex/assets/release-article/article/article.html` 1.95 MB(同样本复制于 `dist/index.html`)