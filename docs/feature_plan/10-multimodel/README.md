# 10 — 多模型并行调度（Multi-Model Parallel Dispatch）

## 目录

| 文件 | 内容 |
|------|------|
| `README.md` | 本文件 — 总览、背景、设计目标 |
| `f-157-multimodel-router.md` | 核心调度器设计（MultiModelRouter + 策略） |
| `f-157-multimodel-display.md` | TUI/REPL/Headless 展示方案 |
| `f-157-multimodel-aggregator.md` | 投票集成与聚合器设计 |
| `f-157-multimodel-cli.md` | CLI 命令与运行时配置 |

## 状态

| 项目 | 状态 |
|------|------|
| 设计文档 | 草稿 |
| 优先级 | P1（待定） |
| F 编号 | 待分配 |

## 背景

当前 clawcodex 每个会话（Session）绑定一个 `provider` + `model`，`QueryEngine` 和 `query()` 循环全程使用同一个 provider。无法在同一个会话中同时调用多个模型服务。

## 使用场景

| 场景 | 说明 | 示例 |
|------|------|------|
| **并行对比** | 同一问题发给多个模型，用户对比选择 | 对比 claude-sonnet-4-6 / gpt-4o / deepseek-v4-flash 的代码生成质量 |
| **投票集成** | 多模型输出后聚合，选择最佳结果 | 代码审查：3 个模型各自审查，投票决定是否通过 |
| **路由分发** | 不同子任务分配给不同模型 | 复杂任务：opus 规划大纲 → gpt-4o 撰写 → deepseek 生成代码 |
| **故障转移** | 主模型超时/限流时自动切换到备选模型 | 生产环境高可用保障 |

## 设计目标

1. **零侵入核心**：`MultiModelRouter` 实现 `BaseProvider` 接口，对 `query()` / `_call_model_sync` 透明，不修改 `src/` 下的任何文件
2. **可插拔策略**：策略可配置、可组合，不启用时不增加任何开销
3. **统一交互**：TUI 中用 `← → ↑ ↓ Enter` 完成所有操作，零学习成本，零键位冲突
4. **成本可见**：每次多模型调用都记录各模型的 token 消耗和耗时