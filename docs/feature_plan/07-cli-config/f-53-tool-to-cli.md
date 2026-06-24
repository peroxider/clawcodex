# F-53: Tool 自动暴露为 CLI 斜杠命令

> 状态: 📋 规划中
> 章节: docs/feature_plan/07-other/f-53-tool-to-cli.md
> 最后更新: 2026-06-24

## §1 设计规划

### 1.1 目标

将注册到 `ToolRegistry` 的工具自动暴露为 REPL/TUI 中的 `/tool-name` 斜杠命令，使 SOP 生成的子 Agent 方法（如 `detect_modality`）同时可在 CLI 中作为常规命令直接调用。

### 1.2 背景

当前 clawcodex 的 `/` 斜杠命令系统只内置少量固定命令（`/goal`、`/permission`、`/provider`、`/model` 等）。SOP 生成的工具在注册为 `Tool` 后（F-52），sub-agent 可通过 tool call 间接使用，但人类用户在 REPL/TUI 中没有直接入口。

### 1.3 设计目标

1. 已注册的 `Tool` 自动映射为 `/tool-name` 斜杠命令，无手动配置
2. 命令参数从 Tool 的 param schema 自动推导，支持 `--param value` 风格
3. 命令执行结果直接输出到当前对话上下文
4. 保持 `src/*` 零改动——所有新增代码落入 `clawcodex_ext/cli/`

### 1.4 架构

```
ToolRegistry ──> DynamicCommandDiscovery ──> subcommand_registry 注册 /tool-name
                     │
                     ▼
   REPL: /detect_modality --path /data/raw ──> Tool.execute({path: "/data/raw"})
                     │
                     ▼
             结果输出到对话上下文
```

### 1.5 命令行格式

```
/<tool-name> [--param1 value1] [--param2 value2] [--flag]
```

示例：
```
/detect_modality --path /data/sample.mp4
/load_dataset --source s3://bucket/data --modality video
/quality_check --report-format json
```

**参数映射规则**:

| Tool ParamSpec | CLI arg | 说明 |
|----------------|---------|------|
| `name="path", required=True, type="str"` | `--path STR` (required) | 必填字串参数 |
| `name="format", required=False, default="json"` | `--format {json,html}` (可选) | 可选参数，限制为枚举值 |
| `name="verbose", type="bool"` | `--verbose` (flag) | bool 类型映射为 flag |
| `name="*args", type="list"` | 位置参数 `ARGS [ARGS ...]` | 变长参数 |

### 1.6 实现切片

| 组件 | 路径 | 说明 |
|------|------|------|
| `DynamicCommandDiscovery` | `clawcodex_ext/cli/tool_cmd/discovery.py` | 扫描 ToolRegistry 中非核心工具集合，自动生成命令定义 |
| `DynamicToolCommand` | `clawcodex_ext/cli/tool_cmd/command.py` | 单个 tool→command 适配器，从 Tool 参数 schema 推导 argparse 参数 |
| 注册钩子 | `clawcodex_ext/cli/tool_cmd/hooks.py` | 在 subcommand_registry 加载时调用 DynamicCommandDiscovery |

### 1.7 验收标准

1. 核心工具（Read/Write/Bash 等）不产生 `/read` 等命令
2. `/detect_modality --path /data/sample.mp4` 等价于 `Tool("detect_modality").execute({"path": "/data/sample.mp4"})`
3. 缺少必填参数时显示友好的 usage 提示
4. 工具执行报错时输出错误信息而非崩溃
5. TUI 斜杠自动补全包含已注册工具
6. 现有 CLI/REPL/TUI 测试继续通过

### 1.8 风险与约束

- **命令名冲突**: `/read` 已存在，不能重复注册
- **大量工具注册**: 如果注册 100+ 工具，CLI 帮助输出会过长
- **LLM 绕过风险**: 直接通过 CLI 调用工具绕过了 LLM 决策，但 audit 路径（F-45）应能记录

### 1.9 依赖

- **依赖**: F-52（Tool 注册机制是前置条件），F-18（CreateAgentTool 注册的 tool 也可被 F-53 发现）
- **协同**: F-43（CLI 命令注册模式可复用 subcommand_registry），F-45（手动工具调用应走 audit 旁路）

## §2 进度跟踪

尚未开始。

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-06-24 | 补全详细设计（架构+参数映射+实现切片+风险） | 对齐 FEATURE_PLAN.legacy.md |
