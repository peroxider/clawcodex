# F-52: Python SDK 方法注册为 Tool

> 状态: 📋 规划中
> 章节: docs/feature_plan/04-architecture-sdk/f-52-sdk-to-tool.md
> 最后更新: 2026-06-24

## §1 设计规划

### 1.1 目标

将 SOP 转换解析出的 `SourceOperation`（如 `detect_modality`、`load_dataset`）注册为 clawcodex 可调用的 `Tool` 对象。

### 1.2 实现计划

| 组件 | 文件 | 说明 |
|------|------|------|
| `ToolWrapper` | `extensions/pos_converter/tool_registry.py` | 将 SourceOperation 包装为 Tool 对象 |
| `register_source_operations` | `extensions/pos_converter/tool_registry.py` | 批量注册某 agent 的所有 operations |
| `AgentBuilder` 增量 | `extensions/pos_converter/agent_builder.py` | build() 自动注册 tool |
| `agent_loader_hook.py` | `extensions/pos_converter/agent_loader_hook.py` | 加载 agent markdown 时自动注册 |

### 1.3 验收标准

1. `ToolWrapper(operation).to_tool().name == "detect_modality"`
2. 注册后 `registry.get_tool("detect_modality")` 返回有效 `Tool`
3. 无 Python 源文件时优雅降级

### 1.4 依赖

F-50（SourceCodeParser 已输出 SourceOperation）

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
