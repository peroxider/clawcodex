# F-89: @agent-name 多入口统一支持

> 状态: 🔄 进行中（基础支持存在，多入口统一未完成）
> 章节: docs/feature_plan/07-other/f-89-agent-name.md
> 最后更新: 2026-06-24

## §1 设计规划

### 1.1 目标

确保所有入口（CLI、REPL、TUI、headless、orchestrator）都支持 `@agent-name` 语法，且行为一致。

### 1.2 当前基线

| 入口 | 支持 @agent-name | 备注 |
|------|:----------------:|------|
| CLI | ✅ | `agent_cmd/` 存在 |
| REPL | 🔄 | 部分支持 |
| TUI | 🔄 | 部分支持 |
| headless | 🔄 | 部分支持 |
| orchestrator | 📋 | 待确认 |

### 1.3 子特性

| 子特性 | 描述 | 状态 |
|--------|------|:----:|
| F-89-A | CLI @agent-name 解析 | ✅ |
| F-89-B | REPL @agent-name 完整支持 | 📋 |
| F-89-C | TUI @agent-name 完整支持 | 📋 |
| F-89-D | headless @agent-name 完整支持 | 📋 |
| F-89-E | orchestrator @agent-name 支持 | 📋 |

### 1.4 实现要求

- 所有入口对 `@agent-name` 的解析行为保持一致
- 支持子命令 / 参数传递
- 未知 agent 名称时给出友好错误提示

## §2 进度跟踪

### 2.1 已实现

`agent_cmd/` 目录存在，代码中有 @agent-name 引用。

### 2.2 当前瓶颈

多入口统一未完成。CLI 优先，REPL/TUI/headless/orchestrator 待统一。

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
