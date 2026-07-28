# F-56 SOP Resource Catalog — SDK 运行时资源句柄持久化

> **状态**: ✅ **已完成并可关闭** — Agent P0 + §15.1–15.5 + `resource_type` 注册表 + `resource_runtime` + Phase D（legacy 运行时读写已移除）。默认行为仍兼容 P0（单写 / 无 session / `inline`）。
> **领域**: 04-architecture-sdk (SOP Converter / Runtime State)
> **最后更新**: 2026-07-23（对照主仓 `extensions/sop_converter/resource_*.py` 同步）
> **关联 Feature**: F-50, F-52, F-55, F-57, F-58, F-59, F-157

---

## §0 实现现状（相对原文方案）

> **阅读约定**：§1 起保留设计正文（含演进契约 §13–§15）。与代码冲突时，以本表与 **§8 实现状态对照** 为准。

| 能力 | 原文 / 设计方案 | 当前代码 |
|------|----------------|----------|
| **持久化** | `ResourceRecord` → JSON catalog | ✅ `<bundle>/.clawcodex/resource-catalog.json` 或 user-local `$CLAWCODEX_HOME/sop-resources/<bundle_id>/catalog.json` |
| **写入** | create 成功后自动 upsert | ✅ `--catalog-metadata` → `build_resource_record_from_create` → `write_record`（默认单写；opt-in 双写 / session） |
| **读取** | 按 ID / 显式名称 | ✅ `get_resource_record` / `get_agent_record`（经 `resolve_record`）；歧义 → `resource_catalog_ambiguous` |
| **注册表** | `resource_type` → materialize/invoke | ✅ `resource_handlers.py`；生产内置 `agent`/`agentconfig`；未注册 → `resource_type_unregistered` |
| **通用 dispatch** | 按类型恢复 | ✅ `resource_runtime.materialize_resource` / `invoke_resource`（F-57 宏消费） |
| **Sidecar** | `resources.yaml` 显式配对 | ✅ `bundle_resources.load_resource_bindings`；convert 覆盖 create/invoke/`handle_field` |
| **句柄契约** | `resource_ref` + 动态 `handle_field` | ✅ F-55/`lifecycle.py` 注入；参数名 `*_id` 仅兜底 |
| **Legacy** | 曾双写 `agent-catalog.json` | ❌ Phase D：运行时忽略；`agent_catalog.py` 仅归档/单测 |
| **Session-local** | 第三层存储（§15.1） | ✅ 有 `CLAWCODEX_SESSION_ID` / `session_id` 时 create 写 session；读序 session → bundle → user |
| **双写 / `payload_ref` / 管理 API** | §15.2–§15.4 | ✅ opt-in 双写；大 payload/`CLAWCODEX_CATALOG_PAYLOAD_REF` spill；`latest`/`delete`/`list_keys`/`mark_failed`/`find_by_source_tool` |
| **专用 CLI** | §15.5 | ✅ `clawcodex-dev sop catalog {list\|get\|delete\|mark-failed\|latest}` |
| **消费宏** | F-57 读取 catalog | ✅ `invoke-existing-agent` + 通用 `resume-resource`（见 F-57 §9.3） |
| **宏 resume `catalog_dir`** | spilled `payload_ref` | ✅ F-57 `resolve_record` / `resolve_agent_record` + `location.path.parent` 透传（见 §11） |

**已通主路径：** create → F-56 `ResourceCatalog` → get → `ResourceHandler` materialize/invoke → F-57 宏。  
**扩展机制：** 注册表 + sidecar + E1–E5（`DemoHandle`）测绿；真实第二产品 SDK 属产品扩展，非本 Feature 关闭条件。  
**本 Feature 关闭条件：** ✅ 已满足（P0 + §15 + 扩展机制）。

---

## §1 背景

SOP convert 能把 SDK 接口转成 Tool + Skill，但创建型工具通常跑在 Bash wrapper 子进程里。内存对象和 `_instances` 缓存不能跨调用复用。因此“先创建、后调用”的资源必须有可持久化、可查询、可 materialize 的 catalog。

典型失败场景（Agent 是**首个验证语料**，不是唯一资源种类）：创建 verify-bot 返回 `agent_id` 后，后续 `invoke` / `send-to-agent` 不知道如何从该 ID 恢复 DSL/config/工厂参数。

F-56 提供通用资源记录模型与存储层。**Agent 是 P0 生产路径与回归语料**，由 F-57 的 `invoke-existing-agent` 消费；后续种类必须通过同一套 `resource_type` 契约扩展，而不是再写一套 agent 专用分支。可扩展性要求见 **§14**。

---

## §2 目标与边界

### 2.1 已实现（Agent P0）

| 能力 | 说明 |
|------|------|
| 通用 `ResourceRecord` / `ResourceCatalog` | JSON 持久化、原子写入、敏感字段脱敏 |
| `ResourceHandler` 注册表 | `resource_handlers.py`；内置 `agent` / `agentconfig`；未注册 → `resource_type_unregistered` |
| Agent 创建后自动 upsert | create-kind 工具经 `--catalog-metadata` **只**写入 F-56 `ResourceCatalog` |
| Sidecar `resources.yaml` | convert 时显式 create/invoke 配对与 `handle_field` 覆盖 |
| 按 ID / 显式名称读取 | `get_agent_record` / `get_resource_record`；歧义时拒绝猜测 |
| Materialize / Invoke | `agent_runtime.materialize_agent` / `invoke_agent`（注册表首行；供 F-57 使用） |
| 标准错误码 | 缺失、歧义、版本不支持、secret 缺失、payload 无效、materialize/invoke 失败、未注册类型 |
| `CatalogExecutionContext` | create 写入与 F-57 workflow 读取共享 canonical bundle identity |
| 面向宏的 output contract | create ToolSpec 与 invoke adapter 发布并验证 JSON-safe `output_schema` |
| Trusted private lane | `ResourceRecord` / Agent 仅在 F-57 builtin workflow 私有上下文传递 |
| Legacy `agent-catalog.json` | ❌ Phase D：运行时不再读写；`agent_catalog.py` 仅归档/单测 |

### 2.2 非目标

- 不解决跨机器 secret 同步。
- 不替代 F-55 生命周期依赖元数据；catalog 是运行时状态，F-55 是编排提示层。

### 2.3 关闭边界与后续设计目标

下列项**不阻塞** Agent P0 / F-56 主路径关闭。曾标为「明确不做」的能力已于 2026-07-23 **恢复并实现**（契约见 **§15**）；默认行为仍与 P0 兼容。

| 项 | 现状 | 阻塞主路径？ |
|----|------|----------------|
| Bundle + user **同时双写** | ✅ **已实现**（§15.2；`CLAWCODEX_CATALOG_DUAL_WRITE=1` / `dual_write`；默认仍单写） | 否 |
| `mark_failed` / `latest` / `find_by_source_tool` / `delete` / `list_keys` | ✅ **已实现**（§15.4） | 否 |
| Sidecar `resources:` override | ✅ **已实现**（`bundle_resources.py`；`<bundle>/.clawcodex/resources.yaml`） | — |
| 非 agent 资源种类（如 SDK 的 team/pipeline 句柄） | ✅ 注册表 + `DemoHandle` 测试扩展已通；真实第二产品 SDK **属产品扩展，非本 Feature 关闭条件** | 否（机制已通；当前生产只保证 agent） |
| 通用 `resume-resource` 宏 | ✅ 属 F-57；已接线（见 F-57 §9.3） | 否 |
| `payload_ref` 外置 payload | ✅ **已实现**（§15.3；spill + `resolve_payload`；默认仍 `inline`） | 否 |
| 专用 F-56 CLI | ✅ **已实现**（§15.5） | 否 |
| Session-local catalog | ✅ **已实现**（§15.1；第三层存储，读序见 §3.3） | 否 |
| Legacy AgentCatalog 运行时读写 | ❌ **Phase D 已移除**（模块仅归档） | — |

**已通主路径：** create → 直写 F-56 `ResourceCatalog` → `get_agent_record` / `get_resource_record` → ResourceHandler materialize/invoke → F-57 宏（`invoke-existing-agent` 为 agent 门面，`resume-resource` 为通用入口）。legacy `agent-catalog.json` **不再参与运行时读写**。  
**已通扩展机制：** `register_resource_handler` + sidecar 配对 + 未注册拒绝；不以「任意 resource_type 生产可用」对外宣称。

### 2.4 与 F-57 / F-157 的分工

| 层 | 职责 |
|----|------|
| F-56 | 存与取：记录 → 按 ref 找回 → `ResourceHandler` 注册表（materialize/invoke） |
| F-57 | 编排：`invoke-existing-agent` 与通用 `resume-resource`（§9.3） |
| F-157 | 检索：宏声明覆盖的原子工具与精确 `intent_key`；exclusive 命中后隐藏原子候选，宏不可用时恢复 |

### 2.5 架构原则：Agent 是首个消费者，不是设计上限

| 允许 | 禁止 |
|------|------|
| P0 只保证 Agent 端到端绿 | 把 `agent_id` / `AgentConfig` 写进核心主路径作为唯一句柄形态 |
| 用 Agent 语料验收通用契约 | 新增资源种类时复制一套 catalog / fallback / schema 特判 |
| 参数名启发式作**兜底** | 用参数名（`*_id`）作为跨 SDK 的不变量 |

扩展点是 **`resource_type` 注册表**（见 §14），不是「再识别一个参数名」或「再做一个 invoke-existing-X」。

---

## §3 数据模型

### 3.1 ResourceRecord

实现：`extensions/sop_converter/resource_catalog.py` 中的 `ResourceRecord`。

```json
{
  "schema_version": 1,
  "resource_type": "agent",
  "resource_id": "verify-bot",
  "bundle_id": "JiuwenAgent_v7.17",
  "source_tool": "openjiuwen-core-application-llm-agent-create-llm-agent",
  "created_at": "2026-07-17T00:00:00+00:00",
  "updated_at": "2026-07-17T00:00:00+00:00",
  "sdk": {
    "source_dir": "C:/path/to/sdk",
    "version": ""
  },
  "materializer": {
    "kind": "python_function",
    "module": "openjiuwen.core.application.llm_agent",
    "name": "create_llm_agent",
    "init_kwargs": {}
  },
  "invoker": {
    "kind": "python_method",
    "method": "invoke",
    "input_param": "query"
  },
  "payload": {
    "kind": "inline",
    "handle_field": "agent_id",
    "dsl": {},
    "model": "deepseek-chat",
    "provider": "",
    "init_kwargs": {},
    "agent_catalog_entry": {}
  },
  "secrets": {
    "policy": "env_refs_only",
    "env_refs": ["DEEPSEEK_API_KEY"]
  },
  "status": "active",
  "metadata": {}
}
```

`payload.kind` 契约（默认 `inline`；`payload_ref` 见 §15.3，已实现）：

| kind | 含义 | 现状 |
|------|------|------|
| `inline` | 可 materialize 的 DSL/config 内嵌于 `payload` | ✅ 生产默认 |
| `payload_ref` | catalog 记录只持外置路径/URI；materialize 前解析引用 | ✅ 已实现（§15.3） |

要点：

- 记录键：`{normalized_resource_type}:{resource_id}`（类型会去掉非字母数字并小写，例如 `AgentConfig` → `agentconfig`）。
- `resource_type` 在模型上是任意字符串；Agent 判定为类型名含 `"agent"`，或 payload 含 `agent_catalog_entry`。
- `materializer.kind`：`python_function`（有 factory 元数据）或 `python_class`。
- `payload.agent_catalog_entry`：与 legacy `AgentCatalogEntry` 的桥接快照，便于兼容与调试。
- `status`：至少 `active`；`failed` 等由 `mark_failed`（§15.4）维护。

### 3.2 磁盘信封

```json
{
  "version": 1,
  "records": {
    "agent:verify-bot": { "...ResourceRecord..." }
  }
}
```

- 仅 JSON；顶层版本字段名为 `version`，记录内为 `schema_version`。
- `SCHEMA_VERSION = 1`；加载时若顶层 `version` 不匹配，抛出 `resource_version_unsupported`，不得降级为空 catalog 或误报 missing。

### 3.3 存储位置

F-56 支持三层（bundle + user 默认；session / 双写为 opt-in，见 §15）：

| 层级 | 路径 | 写入现状 | 读取现状 |
|------|------|----------|----------|
| Bundle-local | `<bundle>/.clawcodex/resource-catalog.json` | ✅ create 默认写此处（有 bundle 且非 home-only）；双写时亦写 | ✅ 有 session 时次于 session；否则优先 |
| User-local | `$CLAWCODEX_HOME/sop-resources/<bundle_id>/catalog.json` | ✅ 无 bundle 或 `CLAWCODEX_CATALOG_HOME_ONLY=1` 时；双写时亦写 | ✅ 最后 |
| Session-local | `$CLAWCODEX_HOME/sessions/<session_id>/sop-resources.json` | ✅ 有 `CLAWCODEX_SESSION_ID` / `session_id` 时作为附加写层（§15.1） | ✅ **session → bundle → user**（`resolve_record`） |

环境变量：

| 变量 | 作用 |
|------|------|
| `CLAWCODEX_HOME` | catalog home 根（默认 `~/.clawcodex`） |
| `CLAWCODEX_CATALOG_HOME_ONLY=1` | 强制读写 user-local |
| `CLAWCODEX_BUNDLE_PATH` | invoke wrapper / fallback 使用的 bundle 路径 |
| `CLAWCODEX_SESSION_ID` | session-local 写入/查找的会话键（§15.1） |
| `CLAWCODEX_CATALOG_DUAL_WRITE=1` | 启用 bundle + user **同时双写**（§15.2） |
| `CLAWCODEX_CATALOG_PAYLOAD_REF` | 强制 spill 为 `payload_ref`（§15.3） |

**默认：** 单次 create 只写一个基座位置（bundle 或 user）。  
**Opt-in（§15.2）：** `CLAWCODEX_CATALOG_DUAL_WRITE=1` 时同时双写 bundle + user；读路径按 session → bundle → user，跨层同 id 取较新者，不抛歧义。

### 3.4 Legacy AgentCatalog（已退役）

> **Phase D（2026-07-23）：** 运行时 **不再读、不再写** `agent-catalog.json`。

| 产物 | 路径 | 运行时 |
|------|------|--------|
| F-56（唯一） | `resource-catalog.json` / user-local `catalog.json` | ✅ 读写 |
| Legacy | `agent-catalog.json` / `$CLAWCODEX_HOME/sop-agents/.../agents.json` | ❌ 忽略 |

- create：`build_resource_record_from_create` → `ResourceCatalog.upsert`  
- get：`get_resource_record` 只扫 F-56 位置  
- `extensions/sop_converter/agent_catalog.py` 保留为归档格式 + 单测；**禁止**新生产代码依赖  
- 旧 bundle 若仅有 `agent-catalog.json`，需一次性迁移到 `resource-catalog.json`（另脚本/手工），运行时不会自动桥接  

第二资源种类验收必须是 `create → resource-catalog.json → resume-resource`。

---

## §4 API 与模块

### 4.1 核心模块

| 模块 | 职责 |
|------|------|
| `extensions/sop_converter/resource_catalog.py` | `ResourceRecord`、`ResourceCatalog`、路径解析、`get_resource_record` / `get_agent_record`、脱敏、错误信封 |
| `extensions/sop_converter/resource_handlers.py` | `ResourceHandler` 注册表；内置 agent 行；未注册拒绝 |
| `extensions/sop_converter/agent_catalog.py` | Legacy `AgentCatalog` / `AgentCatalogEntry` |
| `extensions/sop_converter/agent_catalog_resolver.py` | Legacy 路径解析 |
| `extensions/sop_converter/agent_runtime.py` | `materialize_agent`、`invoke_agent`（注册表 agent 行委托实现） |
| `extensions/sop_converter/resource_runtime.py` | 通用 `materialize_resource` / `invoke_resource`（经注册表；F-57 宏主路径） |
| `extensions/sop_converter/bundle_resources.py` | 解析 `.clawcodex/resources.yaml` sidecar |
| `extensions/sop_converter/tool_registry_bridge.py` | create/invoke wrapper：catalog 写入与 `--catalog-fallback` |
| `extensions/sop_converter/heuristics/lifecycle.py` | create/invoke 启发式、类型契约与 `--catalog-metadata` payload |

### 4.2 ResourceCatalog 接口

**已实现（§15.4 管理 API + P0 主路径）：**

```python
class ResourceCatalog:
    def upsert(self, record: ResourceRecord) -> None: ...
    def get(self, resource_type: str, resource_id: str) -> ResourceRecord | None: ...
    def find_by_resource_id(self, resource_id: str) -> list[ResourceRecord]: ...
    def find_by_agent_reference(self, reference: str, *, resource_type: str | None = None) -> list[ResourceRecord]: ...
    def save(self, path: Path) -> None: ...  # 原子写 + 文件锁（Unix fcntl；Windows 退化）
    def latest(self, resource_type: str) -> ResourceRecord | None: ...
    def find_by_source_tool(self, source_tool: str) -> list[ResourceRecord]: ...
    def mark_failed(self, resource_type: str, resource_id: str, *, reason: str = "") -> None: ...
    def delete(self, resource_type: str, resource_id: str) -> bool: ...
    def list_keys(self) -> list[str]: ...  # "{type}:{id}" 规范化键
```

~~**设计目标 API（§15.4）**~~ — 已并入上方实现面。

高层入口：

```python
get_resource_record(
    resource_ref: str,
    *,
    resource_type: str,  # 必填；未注册则 resource_type_unregistered
    bundle_path=None,
    bundle_id="",
    catalog_context: CatalogExecutionContext | None = None,
) -> ResourceRecord

get_agent_record(
    agent_id="",
    *,
    agent_ref="",
    bundle_path=None,
    resource_type="",
) -> ResourceRecord  # Agent 族薄封装；名称解析 + legacy 桥接
```

- `agent_ref` / `resource_ref` 为主；`agent_id` 为兼容别名。
- 精确匹配 `resource_id`；Agent 族另支持显式名称字段：`name` / `agent_name` / `display_name` / `alias` / `aliases`。
- 多条命中 → `resource_catalog_ambiguous`；零条 → `resource_catalog_missing`。
- 未登记 `resource_type` → `resource_type_unregistered`（不得 silently 走 agent materialize）。

### 4.3 Materialize / Invoke

```python
# agent_runtime.py
materialize_agent(record: ResourceRecord) -> {"agent": <instance>}
invoke_agent(agent, record, query="", inputs=None) -> {"text", "raw", "method"}
```

- Materialize 前将 `sdk.source_dir` 插入 `sys.path`。
- `init_kwargs` 经 `coerce_sdk_type` 重建 Pydantic/dataclass（避免工厂收到裸 dict）。
- Invoke 使用 record 上的 `invoker.method` / `input_param`；方法缺失时回退 `invoke` / `run` / `__call__`。
- 协程结果用 `asyncio.run` 等待。
- 生产消费优先经 §4.4 注册表；上述函数是 Agent 首行的委托实现，不是第二种类的复制模板。

### 4.4 `ResourceHandler` 注册表（已实现）

```python
@dataclass(frozen=True)
class ResourceHandler:
    resource_type: str  # 规范化后小写字母数字，如 agent / agentconfig / demohandle
    materialize: Callable[[ResourceRecord], dict[str, Any]]
    invoke: Callable[..., dict[str, Any]]
    public_output_schema: dict[str, Any]
    error_codes: frozenset[str]

register_resource_handler(handler, *, replace=False) -> None
get_resource_handler(resource_type) -> ResourceHandler | None
require_resource_handler(resource_type) -> ResourceHandler  # 缺失 → resource_type_unregistered
ensure_builtin_handlers()  # 安装 agent / agentconfig 别名到同一 handler
```

- 新增资源种类 = `register_resource_handler(...)`，禁止新增 `invoke-existing-*` 专用宏作为扩展手段。
- `agent` 与 `agentconfig` 映射到同一内置 handler（注册表第一行）。
- E4 用测试专用 `DemoHandle` 证明第二种类可登记；**不**等于真实第二产品 SDK 已接入。

### 4.5 Convert / fallback 句柄解析（与 F-55 共享）

| 能力 | 位置 | 行为 |
|------|------|------|
| `inject_resource_ref_schema` | `heuristics/lifecycle.py` | invoke ToolSpec 注入 `resource_ref`（string）+ 可选 `resource_type` |
| 动态 `handle_field` | create metadata | 由返回形状启发式发现；sidecar 可覆盖；禁止无条件写死为唯一形态 |
| `resolve_catalog_handle_from_args` | `tool_registry_bridge.py` | 读路径优先序见下 |
| `ResourceBinding` / `load_resource_bindings` | `bundle_resources.py` | 解析 `<bundle>/.clawcodex/resources.yaml` |

`resolve_catalog_handle_from_args` 优先序：

1. `args["resource_ref"]`
2. `args[handle_field]` / `args[id_arg]`
3. legacy `agent_id` / `resource_id` / `id`

`agent_id` / `*_id` 只允许作**读路径兼容兜底**，不得作为新种类写入主路径的唯一句柄形态。

---

## §5 写入路径

### 5.1 触发条件

生成 wrapper 在 **create-kind** SDK 调用成功后，若 `call_impl` 带 `--catalog-metadata` JSON，则 upsert catalog。

`infer_lifecycle_kind`（`heuristics/lifecycle.py`）——**主路径为类型契约，参数名启发式仅兜底**：

| kind | 条件（摘要） |
|------|----------------|
| create | 名以 `build_` / `create_` / `init_` / `register_` / `ensure_` / `load_` 开头，且像资源工厂（非原始返回 / 复杂参数类型） |
| invoke | 参数 `type_hint` ∈ `known_create_types`（即使无 `invoke_` 前缀）；或名以 `invoke_` / `run_` / `call_` / `send_` 开头且有 id/类型句柄参数 |
| none | 其他 |

可选：`.clawcodex/resources.yaml` 的 `ResourceBinding` 在 convert 时强制覆盖 create/invoke 判定与 `handle_field`。

### 5.2 写入顺序

1. `_extract_resource_handle()` 从结果/参数提取稳定 ID（`handle_field`，或 `agent_id` / `resource_id` / `id` / `handle` / `name`，及嵌套 config）。
2. `build_resource_record_from_create(...)` → upsert F-56 `ResourceCatalog` → 原子 `save`。
3. 成功 stdout 附加：`created_persisted`、`resource_catalog_path`、`catalog_path` 等。

失败码：

| code | 场景 |
|------|------|
| `resource_handle_missing` | 抽不出稳定 ID |
| `resource_catalog_write_failed` | F-56 写失败（legacy 可能已成功） |
| `catalog_write_failed` | 整个 catalog 块失败 |

### 5.3 Secret 策略

Upsert 时 `_redact_tree` 自动脱敏：

- 键名匹配 `api_key` / `token` / `secret` / `password` 等 → 存为 `<redacted:env:CLAWCODEX_{BUNDLE}_{FIELD}>`。
- 已有 `env:VAR` 字符串保留。
- `secrets.env_refs` 累积。
- `ResourceCatalog.get()` 读回时 `_restore_tree` 从环境变量还原占位符。
- Materialize 阶段另有 `sdk_serialization.resolve_env_references()` 处理显式 `env:` 引用。

**不**把明文 API key 写入 catalog。

---

## §6 读取与 F-57 消费路径

```text
用户：用 verify-bot 回复 ping
        │
        ▼
invoke-existing-agent（F-57 宏）
        │
        ├─ get_agent_record(agent_ref="verify-bot")     # F-56
        ├─ materialize_agent(record)                    # agent_runtime
        └─ invoke_agent(agent, record, query="ping")    # agent_runtime
```

另外：invoke-kind SDK wrapper 在 SDK 报 “agent not found” 等时可走 `--catalog-fallback`，复用同一套 `invoke_existing_agent` 逻辑。

`CompositeWorkflowRunner` 白名单包含：

- `extensions.sop_converter.resource_catalog:get_agent_record`
- `extensions.sop_converter.agent_runtime:materialize_agent`
- `extensions.sop_converter.agent_runtime:invoke_agent`

这是当前可运行的 trusted builtin 链，不是普通手写/session 宏的模板。F-57 runner 已按 §13 将 opaque record/Agent 隔离到 private context；这些 Python 返回值不会进入 portable tool workflow 的 public output。

---

## §7 错误模型

| code | 是否会抛出/返回 | 场景 |
|------|-----------------|------|
| `resource_catalog_missing` | ✅ | 无 ref、无记录 |
| `resource_catalog_ambiguous` | ✅ | 名称匹配多条 |
| `resource_payload_invalid` | ✅ | materialize 收到无效 record |
| `resource_materialize_failed` | ✅ | 工厂/类加载或构造失败 |
| `agent_invoke_failed` | ✅ | invoke 失败（`AgentRuntimeError`） |
| `resource_version_unsupported` | ✅ | load 发现不支持的 catalog 版本时发射，原码穿过 workflow |
| `resource_secret_missing` | ✅ | materialize 前发现声明的 env secret 缺失时发射，不包含 secret 值 |

统一错误信封辅助：`resource_error(code, message, ...)` → `{status, error_code, message, retryable, ...}`。

---

## §8 实现状态对照（相对原规划）

| 原规划项 | 现状 |
|----------|------|
| Agent catalog | ✅ |
| 通用 ResourceRecord 模型 | ✅（生产以 agent 为主） |
| 创建工具自动 upsert | ✅（只写 ResourceRecord） |
| invoke-existing-agent 读取 | ✅（经 F-57） |
| 标准错误码 | ✅；version/secret 码已接线并由 F-57 原样透传 |
| Bundle / user 两级存储 | ✅；默认每次 create 只写一处；opt-in 双写见 §15.2 |
| Session-local catalog | ✅ 已实现（§15.1） |
| Bundle + user 同时双写 | ✅ 已实现（§15.2；opt-in） |
| Sidecar `resources:` override | ✅ `.clawcodex/resources.yaml` 已接入 convert 配对 |
| `payload_ref` | ✅ 已实现（§15.3；默认仍 `inline`；spill / `resolve_payload`）；✅ 宏 resume 透传 `catalog_dir`（见 §11） |
| 通用非 agent 资源种类 | ✅ 扩展机制已实现；`DemoHandle` 验收用例已覆盖；真实第二产品 SDK 属产品扩展 |
| `resource_type` 注册表（materialize/invoke/schema） | ✅ Agent 为内置首行；未注册类型以 `resource_type_unregistered` 拒绝 |
| 通用 `resource_runtime` dispatch | ✅ `materialize_resource` / `invoke_resource`；F-57 宏经此路径 |
| 统一 `resource_ref` schema 注入（F-55 Layer 1） | ✅ invoke ToolSpec 自动注入，并保留 SDK 原参数为兼容属性 |
| `mark_failed` / `latest` / `find_by_source_tool` / `delete` / `list_keys` | ✅ 已实现（§15.4） |
| 专用 F-56 CLI | ✅ 已实现（§15.5；`clawcodex-dev sop catalog …`） |

---

## §9 验收标准（当前应满足）

| # | 验收项 | 方法 |
|---|--------|------|
| 1 | 创建 Agent 后写入 F-56 record | 检查 `resource-catalog.json` 含对应 `resource_id` |
| 2 | 子进程退出后仍可读取 | 新进程 / `get_agent_record` |
| 3 | catalog 无明文 secret | payload 仅 env ref / redaction 占位符 |
| 4 | 重复 upsert 幂等 | 同 ID 再次写入更新 `updated_at`，不损坏可恢复契约 |
| 5 | 缺失记录标准错误 | `resource_catalog_missing` |
| 6 | 显式名称可解析且歧义拒绝 | 唯一 name → 命中；多名冲突 → `resource_catalog_ambiguous` |
| 7 | F-57 宏可端到端调用 | `invoke-existing-agent` 返回原文 output |
| 8 | E1–E5 可扩展矩阵绿 | `tests/misc/test_resource_type_extensibility.py`（含 `DemoHandle`） |
| 9 | 未注册类型拒绝 | `require_resource_handler` → `resource_type_unregistered` |
| 10 | Session-local catalog（§15.1） | ✅ 有 `session_id` 时 create 可写 session 层；get 按 session → bundle → user |
| 11 | Bundle + user 同时双写（§15.2） | ✅ opt-in 后两处均有同 `resource_id` 记录；读路径无歧义错误 |
| 12 | `payload_ref`（§15.3） | ✅ 大 payload 外置；materialize 解析引用；缺文件 → 稳定错误码 |
| 13 | Catalog 管理 API（§15.4） | ✅ `latest` / `find_by_source_tool` / `mark_failed` / `delete` / `list_keys` 行为符合契约 |
| 14 | 专用 F-56 CLI（§15.5） | ✅ `list` / `get` / `delete` / `mark-failed` 可诊断 catalog |

> 验收项 1–9 为 P0 关闭条件；10–14 为 §15 项，**已实现**（默认行为仍与 P0 兼容）。

---

## §10 测试

| 文件 | 覆盖 |
|------|------|
| `tests/misc/test_sop_resource_catalog.py` | 读写、脱敏、路径、按名查找、歧义、桥接、`resource_error`、§15 facade/API/`payload_ref` |
| `tests/misc/test_sop_catalog_cli.py` | §15.5 诊断 CLI（list/get/latest/delete/mark-failed、脱敏、`--scope`） |
| `tests/misc/test_sop_agent_runtime.py` | materialize + `env:` 引用 + `payload_ref`/`catalog_dir` |
| `tests/misc/test_sop_converter_invoke_existing_agent.py` | wrapper 跨进程、home fallback、仅 F-56 恢复、名称查找 |
| `tests/misc/test_sop_converter_lifecycle_e2e.py` | create → catalog → fallback / macro invoke |
| `tests/misc/test_sop_converter_tool_registry_bridge.py` | create 工具写入 catalog |
| `tests/misc/test_sop_composite_runtime.py` | workflow 透传 catalog 错误码 |
| `tests/misc/test_resource_type_extensibility.py` | E1-E5、`resource_ref`、动态句柄、sidecar convert 配对 |
| `tests/misc/test_resume_resource.py` | F-57 `resume-resource` 经注册表恢复；未注册类型拒绝 |

> 2026-07-23：E1–E5 / `DemoHandle` / `resume-resource` 回归已绿。不以「任意 resource_type 生产可用」对外宣称；真实第二产品 SDK 仍属后续。

---

## §11 后续与 backlog

F-57 Phase 2 对齐门禁与通用 `resume-resource` 已完成。

**可扩展性主线（见 §14；机制已完成，本 Feature 可关闭）：**

1. ✅ 统一 `resource_type` + `handle_field` / `resource_ref` 主路径，`agent_id` 仅作兼容读写。
2. ✅ create wrapper 从真实返回动态发现 `handle_field`，sidecar 可显式覆盖。
3. ✅ 按 `resource_type` 注册 materializer / invoker / public output schema；未注册种类拒绝执行。
4. ✅ Sidecar 显式 `resources:` override（类型推不出时的逃逸舱）。
5. ✅ E1–E5 + `DemoHandle` 矩阵绿；✅ F-57 通用 `resume-resource`（见 F-57 §9.3）。

**产品扩展（另立项，非 F-56 欠账）：**

- 为真实第二 SDK 种类（Team / Pipeline session 等）编写生产 `ResourceHandler` 并接入 convert；机制已就绪，种类接入按产品需求排期。

**§15 已落地（默认行为不变；opt-in / 显式 API）：**

| # | 能力 | 节 | 状态 |
|---|------|-----|------|
| 1 | Session-local catalog | §15.1 | ✅ |
| 2 | Bundle + user 同时双写 | §15.2 | ✅ |
| 3 | `payload_ref` 外置 payload | §15.3 | ✅ |
| 4 | `mark_failed` / `latest` / `find_by_source_tool` / `delete` / `list_keys` | §15.4 | ✅ |
| 5 | 专用 F-56 诊断 CLI | §15.5 | ✅ |

**已补齐（原缺口）：** F-57 `invoke-existing-agent` / `resume-resource` 经 `resolve_agent_record` / `resolve_record` 取 `ResolvedResource`，并把 `location.path.parent` 作为 `catalog_dir` 传给 `materialize_*`，以支持 spilled `payload_ref` 宏 resume（`tests/misc/test_resume_resource.py`）。

**不排期清理（非验收）：** 删除仓库内未引用的 `agent_catalog.py` / `agent_catalog_resolver.py`（当前仍保留归档单测）。

---

## §12 与其他 Feature 的关系

| Feature | 关系 |
|---------|------|
| F-55 | 生命周期 / 类型契约（`derive_resource_type`、schema 注入、fallback 匹配）；catalog 提供状态，不替代 dependency graph。扩展原则见 F-55 §7.8 与本文件 §14 |
| F-57 | 标准消费方：`invoke-existing-agent` 与按 `resource_type` 的 `resume-resource`（见 §13.6 / F-57 §9.3）。跨层契约见 §13 |
| F-58 | 返回值语义 schema 可进一步自动生成/校验 ResourceRecord（规划联动） |
| F-59 | 运行时 guard 依赖 `resource_catalog_missing` 等稳定错误码 |
| F-157 | 使用 F-56 的 `resource_type` / 唯一资源引用作为只读检索证据；不得读取 catalog payload 或 secret；负责宏/原子分层而非资源恢复 |

---

## §13 F-56 ↔ F-57 对齐契约

本节定义两边已经实现并由回归测试约束的边界。F-56 仍是存储/恢复层，F-57 仍是宏编排层；Phase 2 没有把全部 F-56 Python API 暴露成 Agent 工具。

### 13.1 双执行通道

| 通道 | 允许的 step | 状态传递 | 适用范围 |
|------|-------------|----------|----------|
| Portable workflow | 仅 `kind=tool`，经 `ToolRegistry.dispatch()` | 只允许 §13.3 的 JSON-safe output | 手写/模板宏、session 宏 |
| Trusted builtin workflow | `kind=tool/catalog/python`，callable 必须在代码白名单 | 可使用 runner 内部 opaque/private context | `invoke-existing-agent` 等内置恢复链 |

因此：

- F-57 的“普通宏只允许 tool”不意味着 F-56 的 `get_agent_record`、`materialize_agent`、`invoke_agent` 必须立即工具化。
- `materialize_agent()` 返回的 Agent 实例只能进入 trusted private context，不得写入 `$steps.*.output`、trace、manifest 或 ToolResult。
- private value 只允许由同一个 trusted builtin workflow 的后续白名单 step 消费；普通宏不能引用或观察。
- 若未来要把 F-56 恢复能力工具化，必须暴露可序列化 handle/projection，不能让工具返回 Agent 实例。

### 13.2 CatalogExecutionContext

create 写入和 F-57 读取必须使用同一份内部上下文：

```python
@dataclass(frozen=True)
class CatalogExecutionContext:
    bundle_path: Path | None
    bundle_id: str
    home_only: bool = False
```

解析规则：

1. F-57 workflow runner 从 `ToolContext.bundle_context` / active bundle 解析 canonical `bundle_path` 和 `bundle_id`。
2. create tool 子进程继续从 convert 固化的 `--catalog-metadata` 获取相同 canonical bundle 信息。
3. `get_agent_record` 接收内部 `CatalogExecutionContext`（或等价的 `bundle_path + bundle_id`），按 bundle → user 顺序查找。
4. 没有 active bundle 时，写入和读取都使用明确 `bundle_id` 的 user-local catalog；不得回退到 CWD 推测 bundle。
5. `CLAWCODEX_CATALOG_HOME_ONLY=1` 同时作用于写入和读取。

`bundle_path` 不再是普通宏的用户输入。F-57 Phase 2 通过 `$resources.catalog` 或 runner 参数注入；现有 wrapper 的 `--bundle-path` / `CLAWCODEX_BUNDLE_PATH` 仅保留 CLI 与兼容路径。

### 13.3 面向宏的输出契约

Agent create 工具成功输出必须发布正式 `output_schema`，至少包含：

```json
{
  "type": "object",
  "required": ["agent_id", "created_persisted", "resource_catalog_path"],
  "properties": {
    "agent_id": {"type": "string"},
    "created_persisted": {"const": true},
    "resource_catalog_path": {"type": "string"},
    "resource_catalog_reason": {"type": "string"},
    "callable_by_agent_id": {"type": "boolean"}
  }
}
```

F-56/F-57 各阶段的可见性约定：

| 产出 | public workflow output | private context |
|------|------------------------|-----------------|
| create tool | 上述 JSON-safe 字段 | 无 |
| `get_agent_record` | 可选脱敏 projection：resource_type/id、bundle_id、source_tool、status | 完整 `ResourceRecord` |
| `materialize_agent` | `{"resource_id": ..., "materialized": true}` 或不公开 | Agent 实例 |
| `invoke_agent` | `text`、`method`、JSON-safe `raw` projection | SDK 原始返回对象可在投影完成前短暂存在 |

`raw` 的含义是“原始调用结果的 JSON-safe projection”，不是 Python 对象身份。无法 JSON 化时应稳定转换为文本字段或返回序列化错误，不能把对象泄漏到通用宏 step context。

### 13.4 错误码门禁

以下两个错误码已经在生产路径发射，并由 F-57 workflow 原样透传：

| code | 要求的发射点 | F-57 行为 |
|------|--------------|-----------|
| `resource_version_unsupported` | `ResourceCatalog.load/get_agent_record` 发现不支持版本时，不再 warning + 空 catalog | 原码透传，不误报为 missing |
| `resource_secret_missing` | materialize 前检查 `secrets.env_refs` / `env:VAR` 缺失 | 原码透传，并给出缺失变量名（不含 secret 值） |

F-59 guard 可以依赖这两个稳定错误码按码恢复；错误详情只包含变量名和版本信息，不包含 secret 值。

### 13.5 Session 术语与资源生命周期

| 名称 | 所属 Feature | 含义 |
|------|--------------|------|
| `ResourceCatalog` | F-56 | bundle-local / user-local 的资源记录；无正式 session scope |
| `SessionMacroCatalog` | F-57 | 当前会话内临时注册的宏定义和 route |

session 宏执行 create 时，Agent 资源仍写入 F-56 bundle/user catalog，可能在 session 结束后继续存在。删除 session 宏不会删除其创建的资源；产品和 UI 不得把“session 宏”描述成“session 资源隔离”。

### 13.6 泛化边界

当前 F-56 **生产保证**只覆盖 Agent 的 get/materialize/invoke。这是 P0 范围，不是架构终点。扩展机制（注册表、`DemoHandle` 测试种类、sidecar、E1–E5）**已就绪且测绿**，但不等于第二产品 SDK 已接入。

泛化的 `resume-resource(resource_type, resource_ref)`（或等价通用宏）归属 **F-57**，**现已实现**（见 F-57 §9.3）。实现时已满足：

1. ✅ 该 `resource_type` 可在 §14 注册表登记 materializer、invoker、public projection、output schema 与错误契约（机制已存在）；
2. ✅ 存在非 Agent 的第二资源种类回归（`DemoHandle`）——证明不是 agent 特判复制；真实产品 SDK 仍属可选后续；
3. ✅ schema / fallback / catalog 主路径以 `resource_ref` / `resource_type` 为主（`agent_id` 仅兼容兜底）。

后续扩展种类仍必须消费注册表，禁止再复制一套 agent 专用分支。详见 F-57 §9.3。

### 13.7 对齐完成条件

| 对齐项 | 当前状态 | 完成门禁 |
|--------|----------|----------|
| builtin private lane | ✅ 已实现 | opaque Agent 不进入 public step output，普通宏无法引用 private binding |
| create/invoke output schema | ✅ 已实现 | schema 写入 ToolSpec/adapter 并由运行时验证 |
| CatalogExecutionContext | ✅ 已实现 | create 子进程与主进程 read 使用同一 bundle_path + bundle_id |
| secret/version 错误发射 | ✅ 已实现 | 单测验证原码穿过 F-57 result |
| session 术语隔离 | 文档已定义 | UI、日志、API 名称不混用 ResourceCatalog 与 SessionMacroCatalog |
| generic resume-resource | ✅ 已实现（属 F-57 §9.3） | 经 `ResourceHandler` / `resource_runtime`；`invoke-existing-agent` 为 agent 门面并存 |
| `resource_type` 可扩展主路径 | ✅ 机制已实现且 E1–E5 绿 | 真实第二产品 SDK 仍不在本次范围；不以「任意类型生产可用」对外宣称 |

---

## §14 可扩展性契约：`resource_type` 一等公民

> **目的**：保证 F-55 / F-56 / F-57 后续演进不以「再适配一个 Agent 场景」为默认做法。  
> **JiuwenAgent / `agent_config`**：是触发语料与 P0 验收，不是唯一支持的形状。
> **实现状态**：本节契约已接线（§4.4 / §4.5）；验收矩阵见 §14.6。

### 14.1 问题

今日**生产消费面**仍大量以 Agent 为中心（`agent_id`、`get_agent_record`、`materialize_agent`、`invoke-existing-agent`）。F-55 §7 类型契约与本文件 §14 注册表**已接线**（`resource_ref`、动态 `handle_field`、`ResourceHandler`、sidecar、未注册拒绝）。若后续扩展继续用参数名特判或复制 agent 分支，第二个 SDK 资源种类仍会分叉——扩展时必须走注册表，而不是再开专用 if。

### 14.2 单一真相

整条链只认：

| 字段 | 含义 |
|------|------|
| `resource_type` | create 产出 / invoke 消费的规范化类型（如 `AgentConfig`、`TeamSession`） |
| `handle_field` | create 写入时动态发现的句柄字段名（旧记录可缺省为 `agent_id`） |
| `resource_ref`（推荐）或派生 `{type}_handle` | invoke schema 中的稳定句柄入参 |

| 阶段 | 行为 |
|------|------|
| convert（F-55） | `produces` / `consumes` 由类型匹配；参数名启发式仅兜底 |
| schema（F-55 Layer 1） | invoke 自动注入统一句柄字段，description 指向对应 create 工具 |
| catalog 写入（F-56） | 每条 `ResourceRecord` 带 `resource_type` + `handle_field` |
| fallback（F-55/F-56） | `get(type, id)` / `find_by_*`；句柄读序见 §4.5；`latest(type)` 见 §15.4 |
| 宏执行（F-57） | `invoke-existing-agent`（agent 门面）与通用 `resume-resource` 并存（F-57 §9.3）；执行链均经 `resource_runtime` |
| 宏 / 原子分层检索（F-157） | 以窄粒度 `intent_key` + `covered_tools` 隐藏或恢复原子候选 |

### 14.3 `resource_type` 注册表（扩展点）

新增资源种类 = 登记一行，而不是新开专用 if。运行时 API 见 **§4.4**；概念形态：

```text
registry[resource_type] = {
  materialize,          # record → 运行时对象（trusted private）
  invoke,               # 对象 + 输入 → 调用结果
  public_output_schema, # JSON-safe 宏可见输出
  error_codes,          # 稳定错误码集合
}
```

- **已注册**：允许 create 自动 upsert、invoke schema 注入、catalog fallback、（可选）通用 resume 宏。
- **未注册**：可以生成描述 / `prefer` 路由提示，但不得宣称可执行恢复；不得 silently 走 agent 路径。

Agent P0 是该表的第一行实现，不是表外特权通道。

### 14.4 Sidecar 声明式覆盖（已实现）

当 AST 类型信息不足时，允许 bundle sidecar 显式声明（实现：`bundle_resources.py`；见 §2.1 / §8 / §11）：

```yaml
# <bundle>/.clawcodex/resources.yaml
resources:
  - type: TeamSession          # 或 resource_type
    create: create-team        # 与工具/op 名归一化匹配
    invoke: run-team
    handle_field: session_id
```

启发式是默认；sidecar 是逃逸舱。怪异 SDK 改 YAML，不改核心匹配器。

### 14.5 Schema 注入形态（与 F-55 Layer 1 对齐）

优先采用**稳定字段名**以降低模型记忆负担：

```json
{
  "resource_type": { "type": "string" },
  "resource_ref": {
    "type": "string",
    "description": "Handle from the create tool that produces this resource_type"
  }
}
```

派生名（如 `agent_config_handle`）可作为兼容别名，但新种类默认走 `resource_ref`，避免每一种类一个字段名。

### 14.6 验收矩阵（可扩展门禁）

| # | 场景 | 必须通过 |
|---|------|----------|
| E1 | 非 `*_id` 参数名（如 `agent_config`）仍判为 invoke，并能 schema 注入 / fallback | 证明类型契约，而非参数名特判 |
| E2 | 经典 `*_id` 参数名仍工作 | 兼容兜底 |
| E3 | 无类型信息时回退启发式，行为确定 | §7.6 |
| E4 | 第二资源种类（非 Agent）经注册表完成 create → catalog → invoke | **真正可扩展的硬门禁** |
| E5 | 未注册 `resource_type` 不会误走 agent materialize | 负向安全 |

E1–E5 已由 `tests/misc/test_resource_type_extensibility.py` 覆盖并通过。E4 使用测试种类 `DemoHandle` 证明注册扩展机制，**不**代表真实第二产品 SDK 已接入；不以“已支持任意 resource_type”对外宣称。

### 14.7 实施优先级

1. ✅ 统一 `resource_ref` 注入 + 核心路径去 `agent_id` 硬编码（保留兼容读）。
2. ✅ create 动态 `handle_field` 写入 catalog。
3. ✅ materializer/invoker 按 `resource_type` 注册；现有 Agent 函数为表的第一行。
4. ✅ sidecar `resources:` override。
5. ✅ 通用 `resume-resource` 宏 → **F-57 §9.3**（经 `ResourceHandler` 按类型恢复；`invoke-existing-agent` 并存）。
6. ✅ §15 设计恢复项（session-local / 双写 / `payload_ref` / 管理 API / CLI）——默认行为不变；✅ F-57 `catalog_dir` 透传已落地（见 §11）。

### 14.8 与 F-55 / F-57 的分工

| 层 | 文档 | 职责 |
|----|------|------|
| 类型匹配 / schema 注入 / fallback 查询键 | F-55 §7 | convert 与 ToolSearch 侧 |
| 记录存储 / 注册表 / 多种类 materialize | F-56 §14 / §4.4 | 运行时状态与扩展点 |
| 宏编排消费注册表 | F-57 §9.3 | `invoke-existing-agent` 与通用 `resume-resource` 并存 |
| 宏 / 原子候选分层与 exclusive suppression | F-157 | ToolSearch 检索规划、暴露面隐藏与执行前回滚 |

---

## §15 设计恢复项（原「明确不做」→ 正式能力）

> **状态**: ✅ **已实现**（2026-07-23；契约见 `docs/superpowers/specs/2026-07-23-f56-section15-design.md`）。  
> **默认行为不变：** 无 session / 单写 / `inline` / 管理 API 与 CLI 为显式调用；opt-in 见各小节。  
> **原则：** 扩展仍走 `resource_type` 注册表，不得为这些能力再开 Agent 专用分支。

### 15.1 Session-local catalog

**目的：** 为短命、会话隔离的资源提供第三层存储，避免污染 bundle/user 永久 catalog。

| 项 | 契约 |
|----|------|
| 路径 | `$CLAWCODEX_HOME/sessions/<session_id>/sop-resources.json`（或同级 `catalog.json`，实现时二选一并写死） |
| 会话键 | `CatalogExecutionContext.session_id` 与/或 env `CLAWCODEX_SESSION_ID`；缺省则**不写** session 层 |
| 写入 | create 在「有 session_id 且策略允许」时写入 session-local；可与 bundle/user 策略组合（见 §15.2） |
| 读取 | `get_resource_record` / `get_agent_record` 查找序：**session → bundle → user**（启用 session 时）；未启用时保持 **bundle → user** |
| 生命周期 | 会话结束可由调用方删除 session 目录；F-56 不强制 GC，但 CLI/`delete` 应能清理单条记录 |
| 兼容 | `scope="session"` 路径解析已接线；无 `session_id` 时不写 session 层 |

### 15.2 Bundle + user 同时双写

**目的：** 同一 create 在 bundle-local 与 user-local **各写一份**，便于跨机器换机或无 bundle 上下文时仍可读到近期资源。

| 项 | 契约 |
|----|------|
| 默认 | 保持今日单写（bundle **或** user），不改变现有行为 |
| Opt-in | `CLAWCODEX_CATALOG_DUAL_WRITE=1`，或 `CatalogExecutionContext.dual_write=True` |
| 写入 | 两处均 `upsert` 同构 `ResourceRecord`（同 `resource_type` + `resource_id`）；任一侧失败 → `resource_catalog_write_failed`，并在错误信封标明失败层 |
| 读取 | 仍按 §3.3 / §15.1 顺序查找；**同 id 多处命中时**取 `updated_at` 较新者，不得抛 `resource_catalog_ambiguous`（跨层副本不是歧义） |
| 与 session | session 层独立；双写仅指 bundle ↔ user，不强制三层齐写 |

### 15.3 `payload_ref` 外置 payload

**目的：** 大 DSL / 二进制旁路不进 `resource-catalog.json`，记录只持引用。

| 项 | 契约 |
|----|------|
| `payload.kind` | `inline`（默认，已实现）\| `payload_ref`（✅ 已实现；spill / 强制 env） |
| `payload_ref` 形态 | 至少：`{"kind":"payload_ref","ref":"<path-or-uri>","media_type":"application/json"|"…"}`；`handle_field` 等元数据仍可留在 catalog 记录顶层或 ref sidecar |
| 写入 | create 可选择把大体量字段落盘到 `<catalog-dir>/payloads/<type>/<id>.json`（或等价路径），catalog 内只存 `ref` |
| 读取 / materialize | handler 或 catalog loader 在 materialize 前解析 `ref`；缺文件 / 不可读 → `resource_payload_invalid` 或专用 `resource_payload_ref_missing`（选定后保持稳定） |
| Secret | 外置文件同样走 `_redact_tree` / `env_refs_only`；禁止把明文 secret 写入 ref 目标 |
| 兼容 | 无 `kind` 或 `kind=inline` 的旧记录继续有效；加载器不得要求一律 `payload_ref` |

### 15.4 Catalog 管理 API

**目的：** 查询、失败标记与清理；支撑 fallback「取最近一条」、诊断与运维。曾在实现中出现后按 YAGNI 删除，现恢复为正式 API。

| 方法 | 契约 |
|------|------|
| `latest(resource_type) -> ResourceRecord \| None` | 同类型下按 `updated_at`（缺省则 `created_at`）取最新 **active** 记录；无则 `None`。供 F-55 fallback「未显式 ref 时」可选使用（显式 `resource_ref` 仍优先） |
| `find_by_source_tool(source_tool) -> list[ResourceRecord]` | 精确匹配 `record.source_tool`（工具 kebab/归一化名与写入时一致） |
| `mark_failed(resource_type, resource_id, *, reason="")` | 将 `status` 置为 `failed`；写入 `metadata.failure_reason` / `updated_at`；**不**物理删除。materialize/get 默认策略：可配置是否返回 failed（默认 get 仍可读，F-57 resume 可拒绝 failed） |
| `delete(resource_type, resource_id) -> bool` | 物理移除记录；若 `payload.kind=payload_ref` 应尽力删除外置文件（失败记入错误信封但不静默吞掉） |
| `list_keys() -> list[str]` | 返回规范化键 `"{type}:{id}"` 列表，稳定排序 |

以上方法须经单测覆盖；跨进程安全与 `save` 的原子写/锁策略与现有 `upsert` 一致。

### 15.5 专用 F-56 CLI

**目的：** 人工诊断 catalog，不依赖打开 JSON。

拟定入口（实现时可挂 `clawcodex-dev sop catalog …` 或等价子命令）：

| 子命令 | 行为 |
|--------|------|
| `list [--bundle PATH] [--type TYPE] [--session ID]` | 列出记录摘要（type、id、status、updated_at、source_tool） |
| `get --type TYPE --id ID […]` | 打印单条记录（脱敏后）；支持 `--resolve-payload` 展开 `payload_ref` |
| `delete --type TYPE --id ID […]` | 调用 `ResourceCatalog.delete` |
| `mark-failed --type TYPE --id ID [--reason …]` | 调用 `mark_failed` |
| `latest --type TYPE […]` | 调用 `latest` |

约束：

- 默认输出脱敏视图，与 catalog 存盘策略一致；不得在 stdout 打印明文 secret。
- 路径解析复用 §3.3 / §15.1（bundle / user / session）。
- CLI 是只读/管理面，**不**替代 F-57 宏执行路径。

### 15.6 与 P0 的关系

| | P0（当前关闭条件） | §15 |
|--|-------------------|-----|
| 是否阻塞关闭 | 是（验收 §9 项 1–9） | 否（验收 §9 项 10–14） |
| 缺省行为 | 单写、`inline`、无 session、无管理 API/CLI | 实现后以 opt-in / 显式 API 启用，避免破坏现网 |
| 文档效力 | 已接线 | ✅ 已实现；评审不得再标「明确不做」除非单独立项废弃 |
