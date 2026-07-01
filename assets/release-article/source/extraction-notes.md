# Extraction Notes · Phase 1 抽取决策记录

## 双源概览

| 源文件 | 语言 | 行数 | 性质 |
|---|---|---|---|
| `assets/video-b/article.md` | 中文 | 195 | 视频口播稿底料,叙事完整、面向用户 |
| `CHANGELOG.md.raw` | 英文 | 135 | v0.1.0 MVP 技术 changelog,含代码结构 / 依赖 / 已知限制 |

## 整合策略

### 目标语言

- 用户**未指定**目标语言(项目历史交互为中文;`CLAUDE.md` 明确"始终使用中文与用户交互")
- 与源材料主语言(中文)一致 → **不翻译 `article.md`,但** `CHANGELOG.md.raw` 内容**需译为中文**
- 最终文章语言 = 中文

### `article.md` 内容处理

| 段 | 处理 |
|---|---|
| §0 一句话定位 | 完整保留(已含友好名,直接落地) |
| §1.1 编排器 | 完整保留(已含 6 杀手级特性 + 真实日志样本) |
| §1.2 SOP 编译器 | 完整保留 |
| §2 四个辅助能力 | 完整保留 |
| §3 一键安装 | 完整保留(命令原文不变) |
| §4 Hero Metrics | 完整保留(3 数) |
| §5 5 个次要卖点 | 完整保留(emoji 一并保留) |
| §6 项目元信息 | 完整保留 |
| §7 视觉与配图建议 | 降级:由"事实"转为"供 Phase 2 决策参考"——这一段本是对视频 agent 的提示,不应作为最终文章的硬性约束 |
| §8 "不要写 F-N 编号" | **删除**(这是写作约束,不是素材;已通过 CLAUDE.md 在 Phase 2+ 隐式生效) |

### `CHANGELOG.md.raw` 内容处理

| 段 | 处理 |
|---|---|
| Keep a Changelog / SemVer 头 | 省略(可在文章文末"格式声明"中提一句,不照搬) |
| `[0.1.0] - 2026-04-19` 头部 | 保留版本号 + 日期(用于项目元信息) |
| Added · Core Features | 译为中文,融入"技术细节 / MVP 已交付"段 |
| Added · CLI Commands | 与 `article.md` 已覆盖的命令合并到一处(避免重复) |
| Added · Provider Implementations | 译为中文;与 LiteLLM 段并存(原生 3 家 + 路由 100+) |
| Added · REPL Features | 译为中文,作为 MVP 已交付的一部分 |
| Added · Configuration System | 译为中文 |
| Added · Session Management | 译为中文 |
| Added · Code Quality | 译为中文 |
| Added · Testing | 译为中文;数字"270+ orchestration tests passing"保留 |
| Technical Details · Architecture | **重写**为中文友好的架构骨架(基于当前真实 `src/` 目录结构而非旧版 5 模块);遵循 CLAUDE.md "Layout" 段 |
| Technical Details · Dependencies | **删除**(不暴露技术栈底牌——这是发布文章,不是技术白皮书) |
| Technical Details · File Structure | 与 Architecture 段合并,统一为"架构骨架" |
| Known Limitations | 完整保留,作为"诚实声明"段(这正是 AI 工程师看重的) |
| Migration Notes | **删除**(初版无迁移;对发布文章无价值) |
| Future Roadmap | **删除**(面向内部的路线图不应在对外发布文章中承诺;若用户后续想加可单独成段) |
| Release Notes · v0.1.0 段 | 与 source.md 开头"一句话定位"已覆盖,不重复 |
| Special Thanks | **删除**(致敬 Claude Code 不必出现在对外发布文) |

### 新增段落(从 CLAUDE.md 提取)

- **"三层解耦架构"** 段 —— `CLAUDE.md` 详细描述了 src/clawcodex_ext/extensions 三层分工,这是下游 fork 的**唯一差异化卖点**之一;原 `article.md` 没有展开,需要补
- **"黄金法则"** 简述 —— 同上
- **已知限制**翻译自 CHANGELOG,中文友好化

## 信息保留比例

按 Phase 2 待选文章类型预估:

- **`longform · ~100%`**:技术细节完整保留(含依赖、文件结构)→ 文章会偏技术报告,失去发布说明气质
- **`full-report · ~80%`**:去掉依赖列表 + Migration Notes + Future Roadmap(已完成)→ 适合
- **`tutorial · ~90%`**:聚焦"怎么装 + 怎么用",适合发布说明 → 适合
- **`essay · ~70%`**:突出"我们做这个的判断 + 为什么这样",适合发布说明 → 适合

**当前 source.md 实际保留比例约 80-85%**(CHANGELOG 段删除一些面向内部的细节 + 视觉建议段降级)。Phase 2 Checkpoint 1 由用户选择文章类型。

## 决策汇总(自检)

1. ✅ **主 Agent 内联 5 条 checklist 自查**(无需 SubAgent)
   - 源语言识别正确(中文为主)
   - 双源都读到位
   - 翻译去翻译腔(英文 CHANGELOG 段用"已暴露 streaming 接口"而非"providers expose streaming interfaces")
   - 数字 / 命令 / 路径 / 术语保留原文
   - 结构与信息保留比例符合"事实底座"定位(不替 Phase 2 决策)
2. ✅ **未开 SubAgent**(per skill 硬性约束:`Phase 1 Source`默认主 Agent 内联)
3. ✅ **未写 `review/source-review.md`**(本抽取置信度高,无需 diff)
4. ✅ **未静默翻译** —— 用户未指定语言,与源一致 → 不翻译;CHANGELOG 英文翻译在"整合策略"段明示
5. ✅ **`source.md` 与 `extraction-notes.md` 同地落盘**

## 给 Phase 2 的备忘

- 推荐文章类型候选:`full-report` (80%) / `essay` (70%) —— 由用户在 Checkpoint 1 选
- 推荐主题:tufte(技术优先)或 press(叙事优先)—— 由用户在 Checkpoint 1 选
- 配图模式:已有 7 个 `assets/orchestrator/viz/*.html` 可作为候选(`user-assets`),或 `none`(纯文本 + 代码块)
- 封面:3:4 书封式,可作"封面"——开 / 关由用户在 Checkpoint 1 选
- 信息密度:源约 400 行 markdown,3-5 个章节比较合适(避免过密)