# F-71: 内置工具补齐

> 状态: ✅ 全部完成（15 工具已落地，ALL_STATIC_TOOLS 共 45 工具）
> 章节: docs/feature_plan/06-ccb-benchmark/f-71-tool-gap.md
> 最后更新: 2026-07-02

## §1 设计规划

### 1.1 目标

对标 CCB 内置工具集，批量实现 clawcodex 缺失的工具，覆盖 agent 生成、浏览器控制、消息发送、任务停止、团队管理、摘要简报、计划模式、代码分析、定时任务、远程触发等能力。

### 1.2 子特性分解

| 编号 | 子特性 | Python 依赖 | 状态 | 预计工时 |
|:----:|--------|:-----------:|:----:|:--------:|
| P71-A | AgentTool 子 Agent 生成 | 无 | ✅ | 5-7d |
| P71-B | WebBrowserTool 浏览器控制 | `playwright`（可选） | ✅ | 5-7d |
| P71-C | SendMessageTool Agent 消息发送 | 无 | ✅ | 2-3d |
| P71-D | TaskStopTool 任务停止 | 无 | ✅ | 2-3d |
| P71-E | TeamCreateTool 团队创建 | 无 | ✅ | 2-3d |
| P71-F | TeamDeleteTool 团队删除 | 无 | ✅ | 2-3d |
| P71-G | BriefTool 摘要简报 | 无 | ✅ | 2-3d |
| P71-H | ExitPlanModeTool 退出计划模式 | 无 | ✅ | 1-2d |
| P71-I | EnterPlanModeTool 进入计划模式 | 无 | ✅ | 1-2d |
| P71-J | LSPTool LSP 代码分析 | 无 | ✅ | 3-5d |
| P71-K | ExecuteTool 代理工具执行 | 无 | ✅ | 3-5d |
| P71-L | CronCreate/Delete/ListTool 定时任务 | 无 | ✅ | 5-7d |
| P71-M | RemoteTriggerTool 远程触发 | `httpx`（可选） | ✅ | 3-5d |
| P71-N | WebBrowserTool 浏览器控制 | `playwright`（可选） | ✅ | 5-7d |
| P71-O | **SnipTool** 历史消息截取 | 无 | ✅ **已完成** | 2-3d |

### 1.3 已落地

`clawcodex_ext/tool_system/tools/snip.py`（282 行），支持按索引范围/角色/关键词过滤 conversation history，三种输出格式（text/json/summary），只读且并发安全。注册于 `ALL_STATIC_TOOLS`，别名 `context_snip` / `history_snip`。

#### 1.3.1 WebBrowserTool（2026-07-02）

`clawcodex_ext/tool_system/tools/web_browser.py`（235 行）。轻量 HTTP 页面抓取，`navigate`/`screenshot` 两个 action。参考 `claude-code-best` 的 `WebBrowserTool.ts`，但用标准库 `urllib` 替代 `playwright`（F-71 将 `playwright` 标为可选依赖，参考实现本身也只是 HTTP fetch + HTML 文本剥离，非真浏览器）。复用 `web_fetch.py` 的 SSRF 私网守卫（`_validate_url` + `_is_private_host`）保持一致。只读、非并发安全、`should_defer=True`。别名 `browser` / `web_page`，`max_result_size_chars=100_000`，内容截断上限 50_000 字符。

#### 1.3.2 ExecuteTool（2026-07-02）

`clawcodex_ext/tool_system/tools/execute.py`（219 行）。代理执行其它工具的调度器，参考 `ExecuteTool.ts`。查找顺序：`context.tool_registry.get()` → `context.options.tools`（`find_tool_by_name`）。中心化 schema 校验（`coerce_tool_input` + `validate_json_schema`）+ 目标工具 `validate_input` + `check_permissions`，再委托目标工具 `call`。权限决策委托给目标工具自身，使 ask/deny UI 行为与直接调用一致。未找到 / 已禁用 / 校验失败 / 权限拒绝均返回结构化结果 + `new_messages` 用户消息而非抛异常。非并发安全、非只读。

#### 1.3.3 RemoteTriggerTool（2026-07-02）

`clawcodex_ext/tool_system/tools/remote_trigger.py`（259 行）。远程 triggers REST API 客户端（list/get/create/update/run），参考 `RemoteTriggerTool.ts`。用 `urllib` 替代 `httpx`（可选依赖）。clawcodex 不携带 claude.ai OAuth 栈，改用环境变量配置端点和 token：`CLAWCODEX_TRIGGERS_API_URL` / `CLAWCODEX_TRIGGERS_TOKEN` / `CLAWCODEX_TRIGGERS_ORG`（可选），未配置时 `is_enabled=False`。带内存审计日志（上限 500 条，返回 `audit_id`）。`list`/`get` 只读，`run` 标记 destructive，并发安全，`should_defer=True`。

#### 1.3.4 注册总览

3 工具均注册于 `ALL_STATIC_TOOLS`，工具数从 42 → 45。稳定性门禁 345/345 全绿，ruff lint 全部通过。

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

已完成的工具通过 `ALL_STATIC_TOOLS` 或 `EXTENSION_TOOLS` 注册。所有 15 个子特性工具均使用相同注册机制，落地点见 §1.3。

## §2 进度跟踪

### 2.1 已完成

| 日期 | 里程碑 | 涉及文件 |
|------|--------|---------|
| 2026-06-22 | SnipTool 实现 | snip.py (282 行) |
| 2026-06 | AgentTool / SendMessage / TaskStop / TeamCreate / TeamDelete | 多文件 |
| 2026-06 | BriefTool / ExitPlanMode / EnterPlanMode / LSPTool | 多文件 |
| 2026-06 | CronCreate/Delete/ListTool | 多文件 |
| 2026-07-02 | WebBrowserTool / ExecuteTool / RemoteTriggerTool（补齐最后 3 工具） | web_browser.py / execute.py / remote_trigger.py |

### 2.2 下一步计划

✅ 全部完成。F-71 内置工具补齐工作收尾，后续维护点：
- WebBrowserTool 若需 JavaScript 渲染能力，可后续接入 `playwright` 作为可选后端
- RemoteTriggerTool 若对接具体 claude.ai 兼容端点，可补 OAuth token 自动刷新逻辑

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-06-24 | 补全详细设计（完整子特性表+实现模式） | 对齐 FEATURE_PLAN.legacy.md |
| 2026-07-02 | 实现 WebBrowserTool / ExecuteTool / RemoteTriggerTool，F-71 收尾 | 补齐最后 3 个待实现工具，参考 claude-code-best TS 实现 |
