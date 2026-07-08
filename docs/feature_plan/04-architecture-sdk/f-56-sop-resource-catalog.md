# F-56 SOP Resource Catalog — SDK 运行时资源句柄持久化

> **状态**: 📋 规划中  
> **领域**: 04-architecture-sdk (SOP Converter / Runtime State)  
> **最后更新**: 2026-07-08  
> **关联 Feature**: F-50 (SOP Converter), F-52 (SDK→Tool 注册), F-55 (Tool Lifecycle Dependencies)

---

## §1 背景

SOP convert 当前已能把 SDK 接口转成 Tool + Skill + domain agent，但创建型工具的产物仍多是普通字符串或 dict。例如 `agentbuilder-build-agent` 返回 `agent_id` 后，后续 `run-agent` / `invoke-agent` 并不知道如何从该 ID 恢复 DSL/config/实例。

由于 SOP SDK 工具通常通过 bash wrapper 在独立 Python 子进程执行，内存对象和 `_instances` 缓存不能跨工具调用复用。因此任何需要“先创建、后调用”的资源，都必须有一个可持久化、可查询、可恢复的 catalog。

---

## §2 目标

建立 SOP Resource Catalog，统一持久化由 SDK 工具创建的运行时资源句柄，使后续工具能从 ID 恢复到可执行配置。

### 2.1 P0 范围

| 能力 | 说明 |
|------|------|
| Agent catalog | 持久化 `agent_id → DSL/config/model/provider/source_tool` |
| 通用 resource record | 定义 `resource_type`、`resource_id`、`bundle_id`、`schema_version`、`payload_ref` |
| 创建工具写入 | 创建型工具成功后自动 upsert catalog |
| 调用工具读取 | `invoke-existing-agent` / `run-agent` fallback 可按 ID 读取 catalog |
| 错误标准化 | catalog 缺失、版本不兼容、payload 无法 materialize 时返回标准错误 |

### 2.2 非目标

- 不解决跨机器 secret 同步。
- 不要求所有 SDK 类型一次性适配。
- 不替代 F-55 的生命周期依赖元数据；catalog 是运行时状态层，F-55 是编排提示/依赖层。

---

## §3 数据模型

### 3.1 ResourceRecord

```json
{
  "schema_version": 1,
  "resource_type": "agent",
  "resource_id": "0f40ed92-2b9d-4136-a635-616577714c7d",
  "bundle_id": "core_merged",
  "source_tool": "agentbuilder-build-agent",
  "created_at": "2026-07-08T00:00:00Z",
  "updated_at": "2026-07-08T00:00:00Z",
  "sdk": {
    "name": "openjiuwen",
    "version": null,
    "source_dir": "C:/path/to/sdk"
  },
  "materializer": {
    "kind": "python_function",
    "module": "core.agent_factory",
    "name": "create_llm_agent"
  },
  "invoker": {
    "kind": "python_method",
    "method": "invoke",
    "input_param": "query"
  },
  "payload": {
    "kind": "inline",
    "dsl": {},
    "model": "deepseek-v4-flash"
  },
  "secrets": {
    "policy": "env_refs_only",
    "env_refs": ["DEEPSEEK_API_KEY", "DEEPSEEK_MODEL_NAME"]
  },
  "status": "active"
}
```

### 3.2 存储位置

按优先级查找：

| 层级 | 路径 | 用途 |
|------|------|------|
| Bundle-local | `<bundle>/.clawcodex/resource-catalog.json` | bundle 内可复现资源 |
| User-local | `$CLAWCODEX_HOME/sop-resources/<bundle_id>/catalog.json` | 跨会话复用 |
| Session-local | `$CLAWCODEX_HOME/sessions/<session_id>/sop-resources.json` | 短生命周期资源 |

P0 推荐写 user-local + session-local；bundle-local 仅在 bundle 目录可写且资源不含敏感 payload 时写入。

---

## §4 API 设计

### 4.1 Python 模块

新增：

```text
extensions/sop_converter/resource_catalog.py
```

核心接口：

```python
@dataclass
class ResourceRecord:
    schema_version: int
    resource_type: str
    resource_id: str
    bundle_id: str | None
    source_tool: str
    materializer: dict[str, Any]
    invoker: dict[str, Any]
    payload: dict[str, Any]
    sdk: dict[str, Any] = field(default_factory=dict)
    secrets: dict[str, Any] = field(default_factory=dict)
    status: str = "active"

class ResourceCatalog:
    def upsert(self, record: ResourceRecord) -> None: ...
    def get(self, resource_type: str, resource_id: str) -> ResourceRecord | None: ...
    def find_by_source_tool(self, source_tool: str) -> list[ResourceRecord]: ...
    def mark_failed(self, resource_type: str, resource_id: str, reason: str) -> None: ...
```

### 4.2 Tool 注入点

| 注入点 | 行为 |
|--------|------|
| `tool_registry_bridge.py` wrapper 生成 | 对识别出的 create/build 工具追加 catalog upsert |
| composite macro 工具 | 直接调用 `ResourceCatalog.get()` |
| call handler fallback | `agent not exist` / `resource not found` 时尝试 catalog 恢复 |

---

## §5 创建工具识别

### 5.1 启发式

| 模式 | 资源类型 |
|------|----------|
| 函数名 `build_agent` / `create_agent` | `agent` |
| 返回字段含 `agent_id` + `dsl` / `config` | `agent` |
| 函数名 `create_session` / 返回 `session_id` | `session` |
| 函数名 `create_team` / 返回 `team_id` | `team` |

### 5.2 显式 override

允许在 bundle sidecar 中声明：

```yaml
resources:
  - create_tool: agentbuilder-build-agent
    resource_type: agent
    id_field: agent_id
    payload_fields: [dsl, config, model]
    materializer:
      module: core.agent_factory
      name: create_llm_agent
    invoker:
      method: invoke
      input_param: query
```

---

## §6 错误模型

所有 catalog 相关错误必须可机器识别：

| code | 场景 | 建议给 Agent 的动作 |
|------|------|---------------------|
| `resource_catalog_missing` | 找不到 catalog 文件或记录 | 报告缺少可恢复记录，不要改搜其他 invoke 工具 |
| `resource_payload_invalid` | payload 缺字段或无法解析 | 报告创建记录损坏 |
| `resource_materialize_failed` | materializer 报错 | 汇报具体错误，允许有限源码诊断 |
| `resource_version_unsupported` | schema/sdk 版本不兼容 | 提示重新创建或升级 catalog |
| `resource_secret_missing` | 环境变量/secret 缺失 | 提示缺少哪个 env ref |

---

## §7 验收标准

| # | 验收项 | 方法 |
|---|--------|------|
| 1 | 创建 verify-bot 后写入 agent record | 检查 catalog 中有 `resource_type=agent` 且 ID 匹配 |
| 2 | 创建工具子进程退出后仍可读取 | 新进程调用 `ResourceCatalog.get("agent", id)` |
| 3 | catalog 不保存明文 secret | payload 中无 API key；只出现 env ref |
| 4 | 重复 upsert 幂等 | 同 ID 重复写入不破坏原 payload |
| 5 | 缺失记录返回标准错误 | 返回 `resource_catalog_missing` |

---

## §8 测试计划

新增：

```text
tests/misc/test_sop_resource_catalog.py
```

覆盖：

- JSON 文件读写与 schema migration。
- bundle_id/session_id/user-local 查找优先级。
- create-agent fake wrapper 写入后，独立进程读取。
- secret 字段脱敏。
- 标准错误码。

---

## §9 与其他 Feature 的关系

| Feature | 关系 |
|---------|------|
| F-55 | F-56 提供 F-55 P0 的状态基础 |
| F-57 | F-57 的 workflow runtime 通过 catalog 传递资源 |
| F-58 | F-58 的返回值语义 schema 用于自动生成 ResourceRecord |
| F-59 | F-59 的 fallback guard 依赖 catalog 错误码 |

