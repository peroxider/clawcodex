# ClawCodex 内置记忆服务

本目录是 ClawCodex 内置的 Mem0 兼容长期记忆后端。服务通过 FastAPI 提供
REST 接口，通过 `mcp_server.py` 提供 stdio MCP 适配层；被动记忆模块只依赖
既有 MCP 工具协议，不直接依赖后端实现。

## 运行结构

```text
ClawCodex 被动记忆 / Agent MCP tool
  -> clawcodex-dev memory mcp
  -> http://127.0.0.1:8888
  -> MemoryService
  -> mem0ai
  -> embedded Qdrant (~/.clawcodex/memory/qdrant)
```

默认只有一个 REST 守护进程打开嵌入式 Qdrant。所有 MCP client 均通过 HTTP
访问它，避免多个进程同时锁定同一个本地向量库。

## 安装与启动

开发环境安装可选依赖：

```powershell
uv sync --extra dev --extra memory
```

配置默认 OpenAI LLM 与 embedder 时，需要设置 `OPENAI_API_KEY`。也可以通过
`MEM0_CONFIG_PATH` 使用现有 YAML，或把 `LLM_PROVIDER`、`EMBEDDER_PROVIDER`
配置为 Ollama。

```powershell
clawcodex-dev memory enable
clawcodex-dev memory status
clawcodex-dev memory logs --lines 100
clawcodex-dev memory disable
```

前台调试：

```powershell
clawcodex-dev memory serve
```

`memory serve` 启动时会临时启用当前项目的被动记忆；服务正常退出或按
`Ctrl+C` 关闭后，会自动删除当前项目 `.mcp.json` 中受管的 `latent-memory`
配置，并把 `.env` 中的 `CLAWCODEX_PASSIVE_MEMORY` 设回 `0`，避免后续新会话
继续加载已经停止的服务。

默认会自动加载 `~/.clawcodex/memory/memory.env`。配置模板和完整说明见：

- `memory.env.example`
- `环境配置使用说明.md`

也可以显式指定其他环境文件：

```powershell
clawcodex-dev memory enable --env-file .\memory.env
```

环境配置优先级为当前进程、`--env-file`、`CLAWCODEX_MEMORY_ENV_FILE`、默认
`memory.env`、当前目录 `.env`、内置默认值。

## 启用被动记忆与主动工具

执行 `clawcodex-dev memory enable` 会同时完成三件事：后台启动 REST 服务、在
当前项目生成被 Git 忽略的 `.mcp.json`/`latent-memory` 配置，以及把当前项目
`.env` 中的 `CLAWCODEX_PASSIVE_MEMORY` 设为 `1`。随后重新启动
`clawcodex-dev`，Agent 即可使用主动记忆工具，并在 query 生命周期中执行被动召回
与写入。`memory disable` 会停止服务、删除该 MCP 项并把项目开关设回 `0`，不会
删除已有记忆数据或其他 MCP 配置。

MCP server 默认名为 `latent-memory`。

如果项目开关仍为 `1`，但 MCP 或 REST 服务已经不可访问，被动记忆会在连续故障
期间只输出一次警告，并对当前请求降级为无记忆模式，不会把连接异常堆栈暴露给
用户或阻断正常对话。

## 存储模式

优先级如下：

1. `MEM0_CONFIG_PATH` 中显式声明的 `vector_store`；
2. `QDRANT_URL` 或 `QDRANT_HOST` 指向的外部 Qdrant；
3. `CLAWCODEX_MEMORY_STATE_DIR/qdrant` 下的嵌入式 Qdrant。

默认状态目录为 `CLAWCODEX_CONFIG_DIR/memory`，未设置
`CLAWCODEX_CONFIG_DIR` 时为 `~/.clawcodex/memory`。其中包含：

| 路径 | 用途 |
| --- | --- |
| `server.pid` | 后台服务 PID |
| `server.log` | Uvicorn 和记忆后端日志 |
| `memory.env` | 私有运行配置，默认自动加载且不应提交 Git |
| `qdrant/` | 嵌入式向量数据 |
| `history.db` | Mem0 历史记录 |
| `crystallize_state.json` | 结晶器状态 |
| `crystallize_audit.jsonl` | 结晶审计记录 |
| `solidification.db` | 固化层账本 |
| `crystal_docs/` | 固化文档投影 |

首个集成版本不会自动把旧独立 Qdrant 数据迁移到嵌入式目录。需要继续访问旧
数据时，设置原有 `QDRANT_HOST`、`QDRANT_PORT` 和 `COLLECTION_NAME`。

## 主要配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `CLAWCODEX_MEMORY_STATE_DIR` | `~/.clawcodex/memory` | 状态和数据目录 |
| `MEMORY_SERVER_HOST` | `127.0.0.1` | REST 监听地址 |
| `MEMORY_SERVER_PORT` | `8888` | REST 监听端口 |
| `MEM0_CONFIG_PATH` | 空 | 可选 Mem0 YAML 配置 |
| `LLM_PROVIDER` | `openai` | Mem0 抽取模型 provider |
| `LLM_MODEL` | `gpt-4o-mini` | Mem0 抽取模型 |
| `EMBEDDER_PROVIDER` | `openai` | embedding provider |
| `EMBEDDER_MODEL` | `text-embedding-3-small` | embedding 模型 |
| `QDRANT_HOST` | 空 | 外部 Qdrant 主机；设置后关闭嵌入式模式 |
| `QDRANT_PORT` | `6333` | 外部 Qdrant 端口 |
| `QDRANT_URL` | 空 | Qdrant URL，云端通常同时配置 API key |
| `QDRANT_API_KEY` | 空 | Qdrant API key |
| `SALIENCE_GATE_ENABLED` | `true` | 显著性门控总开关 |
| `SALIENCE_GATE_OLLAMA_MODEL` | `none` | Tier 2 模型；默认只运行规则层 |
| `CRYSTALLIZE_ENABLED` | `false` | 语义结晶开关 |
| `SOLIDIFY_ENABLED` | `false` | 持久固化开关 |

高级结晶和固化环境变量保持与原服务兼容。

## 日志与排错

```powershell
clawcodex-dev memory status
clawcodex-dev memory logs -f
$env:CLAWCODEX_MEMORY_LOG_LEVEL="debug"
clawcodex-dev memory restart
```

被动记忆链路使用独立日志配置：

```powershell
$env:CLAWCODEX_PASSIVE_MEMORY_LOG_LEVEL="DEBUG"
$env:CLAWCODEX_PASSIVE_MEMORY_LOG_FILE=".clawcodex/passive-memory.log"
```

MCP 工具调用提示 REST 服务未连接时，先执行
`clawcodex-dev memory enable`。启动失败时查看
`~/.clawcodex/memory/server.log`。

## 测试

```powershell
python -m pytest tests/memory/server -q
python -m pytest tests/memory/test_passive_memory.py tests/memory/test_passive_memory_regression.py -q
python -m ruff check clawcodex_ext/latent_memory/server clawcodex_ext/cli/memory_cmd tests/memory/server
```
