# F-10: ExecuteExtraTool 延迟工具系统

> 状态: 📋 规划中
> 章节: docs/feature_plan/07-other/f-10-extratool.md
> 最后更新: 2026-06-24

## §1 设计规划

### 1.1 目标

按需加载延迟工具，支持语义搜索和子代理执行。

### 1.2 功能说明

完整的延迟工具按需加载系统，支持子代理（Async Agent）执行：

| 组件 | 功能 |
|------|------|
| SearchExtraToolsTool | TF-IDF 工具索引语义搜索 |
| ExecuteExtraTool | 通过名称和参数执行延迟工具 |
| validateInput 校验 | 调用前校验防止崩溃 |
| ASYNC_AGENT_ALLOWED_TOOLS | 子代理可执行延迟工具 |

### 1.3 核心机制

| 机制 | 说明 |
|------|------|
| 工具延迟加载 | 工具按名称和参数动态执行，非预加载 |
| 语义搜索 | TF-IDF 索引支持自然语言工具搜索 |
| 子代理执行 | Async Agent 可调用延迟工具 |
| 输入校验 | execute 前 validateInput 防止无效调用 |

### 1.4 实现文件（参考上游 TS 实现）

| 文件 | 位置 | 状态 |
|------|------|:----:|
| ExecuteExtraTool | `packages/builtin-tools/src/tools/ExecuteTool/ExecuteTool.ts` | 待实现 |
| SearchExtraToolsTool | `packages/builtin-tools/src/tools/SearchExtraToolsTool/` | 待实现 |
| ASYNC_AGENT_ALLOWED_TOOLS | `constants/tools.ts` | 待配置 |
| 延迟工具提示 | `constants/prompts.ts` | 待配置 |

### 1.5 当前状态

当前无实现代码。状态从 🔄 降级为 📋（PROGRESS.md v3.18 确认）。

## §2 进度跟踪

尚未开始。

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-06-24 | 补全功能说明+实现文件表 | 对齐 FEATURE_PLAN.legacy.md |
