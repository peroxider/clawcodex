# F-71: 内置工具补齐

> 状态: 🔄 进行中（SnipTool 已完成，3 工具待实现）
> 章节: docs/feature_plan/06-ccb-benchmark/f-71-tool-gap.md
> 最后更新: 2026-06-24

## §1 设计规划

### 1.1 目标

对标 CCB 内置工具集，批量实现 clawcodex 缺失的工具，覆盖 agent 生成、浏览器控制、消息发送、任务停止、团队管理、摘要简报、计划模式、代码分析、定时任务、远程触发等能力。

### 1.2 子特性分解

| 编号 | 子特性 | Python 依赖 | 状态 | 预计工时 |
|:----:|--------|:-----------:|:----:|:--------:|
| P71-A | AgentTool 子 Agent 生成 | 无 | ✅ | 5-7d |
| P71-B | WebBrowserTool 浏览器控制 | `playwright` | 📋 | 5-7d |
| P71-C | SendMessageTool Agent 消息发送 | 无 | ✅ | 2-3d |
| P71-D | TaskStopTool 任务停止 | 无 | ✅ | 2-3d |
| P71-E | TeamCreateTool 团队创建 | 无 | ✅ | 2-3d |
| P71-F | TeamDeleteTool 团队删除 | 无 | ✅ | 2-3d |
| P71-G | BriefTool 摘要简报 | 无 | ✅ | 2-3d |
| P71-H | ExitPlanModeTool 退出计划模式 | 无 | ✅ | 1-2d |
| P71-I | EnterPlanModeTool 进入计划模式 | 无 | ✅ | 1-2d |
| P71-J | LSPTool LSP 代码分析 | 无 | ✅ | 3-5d |
| P71-K | ExecuteTool 代理工具执行 | 无 | 📋 | 3-5d |
| P71-L | CronCreate/Delete/ListTool 定时任务 | 无 | ✅ | 5-7d |
| P71-M | RemoteTriggerTool 远程触发 | `httpx` | 📋 | 3-5d |
| P71-N | WebBrowserTool 浏览器控制 | `playwright` | 📋 | 5-7d |
| P71-O | **SnipTool** 历史消息截取 | 无 | ✅ **已完成** | 2-3d |

### 1.3 已落地

`clawcodex_ext/tool_system/tools/snip.py`（282 行），支持按索引范围/角色/关键词过滤 conversation history，三种输出格式（text/json/summary），只读且并发安全。注册于 `ALL_STATIC_TOOLS`（共 42 工具），别名 `context_snip` / `history_snip`。稳定性门禁 245/245 全绿。

### 1.4 实现模式

参考 `src/tool_system/build_tool.py`，每个工具使用 `build_tool()` 工厂函数创建：

```python
from src.tool_system.build_tool import build_tool

my_tool = build_tool(
    name="my_tool",
    description="Tool description",
    input_schema={
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "..."},
        },
        "required": ["param1"],
    },
    call=my_handler,
)
```

### 1.5 工具注册

已完成的工具通过 `ALL_STATIC_TOOLS` 或 `EXTENSION_TOOLS` 注册。待实现的 3 个工具（WebBrowserTool、ExecuteTool、RemoteTriggerTool）使用相同注册机制。

## §2 进度跟踪

### 2.1 已完成

| 日期 | 里程碑 | 涉及文件 |
|------|--------|---------|
| 2026-06-22 | SnipTool 实现 | snip.py (282 行) |
| 2026-06 | AgentTool / SendMessage / TaskStop / TeamCreate / TeamDelete | 多文件 |
| 2026-06 | BriefTool / ExitPlanMode / EnterPlanMode / LSPTool | 多文件 |
| 2026-06 | CronCreate/Delete/ListTool | 多文件 |

### 2.2 下一步计划

实现剩余 3 个工具:
1. WebBrowserTool（`playwright` 依赖）
2. ExecuteTool（代理工具执行）
3. RemoteTriggerTool（`httpx` 依赖）

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-06-24 | 补全详细设计（完整子特性表+实现模式） | 对齐 FEATURE_PLAN.legacy.md |
