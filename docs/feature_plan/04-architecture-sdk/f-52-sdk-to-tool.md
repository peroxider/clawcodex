# F-52: Python SDK 方法注册为 Tool

> 状态: ✅ 已完成
> 章节: docs/feature_plan/04-architecture-sdk/f-52-sdk-to-tool.md
> 最后更新: 2026-07-21

## §1 设计规划

### 1.1 目标

将 SOP 转换解析出的 `SourceOperation`（如 `detect_modality`、`load_dataset`）注册为 clawcodex 可调用的 `Tool` 对象。

### 1.2 实现计划

实际实现与最初规划有偏差：能力已合入 `tool_registry_bridge.py`，并在 `sop convert` CLI 中按需调用，而不是通过独立的 `tool_registry.py` / `agent_loader_hook.py`。具体如下：

| 组件 | 实际文件 | 说明 |
|------|----------|------|
| `operation_to_spec` | `extensions/sop_converter/tool_registry_bridge.py` | 将单个 `SourceOperation` 转换为 `AgentToolSpec`（含 kebab-case 名称、JSON Schema、bash wrapper 脚本路径） |
| `register_component_tools` | `extensions/sop_converter/tool_registry_bridge.py` | 批量注册某组件的所有 operations，返回原始名到 kebab-case 名的映射 |
| CLI 接线 | `clawcodex_ext/cli/sop_cmd/commands.py` | `sop convert --register-tools` 时调用 `register_component_tools`，生成并持久化 tool spec + wrapper 脚本 |
| 弃用/未落地 | `tool_registry.py`、`agent_loader_hook.py`、`agent_builder.py` 自动注册 | 早期规划文件；功能由 `tool_registry_bridge.py` + CLI 统一覆盖 |

### 1.3 验收标准

1. `operation_to_spec(operation).name == "detect-modality"`（原始 snake_case / dotted name 规范化为 kebab-case） ✅
2. 调用 `register_component_tools(components, source_dir)` 后，可持久化 `AgentToolSpec` 与 bash wrapper 脚本；映射到注册表后可通过 kebab-case 名调用 ✅
3. 空 operations 列表或组件无 Python 源文件时返回空 name_map，不抛异常 ✅
4. 类方法、独立函数、CLI handler 均能生成合法 wrapper 脚本 ✅

### 1.4 依赖

F-50（SourceCodeParser 已输出 SourceOperation）

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-07-21 | 状态更新为 ✅ 已完成；实现路径对齐 `tool_registry_bridge.py` | `operation_to_spec` + `register_component_tools` 已落地并通过 `test_sop_converter_tool_registry_bridge.py`；CLI `sop convert --register-tools` 已接线 |
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
