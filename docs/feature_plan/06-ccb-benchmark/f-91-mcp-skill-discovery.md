# F-91: MCP Skills 自动发现

> 状态: 📋 规划中(目标模块 `clawcodex_ext/services/mcp/skill_discovery.py` 待建;底层 MCP transport 已在 `clawcodex_ext/services/mcp/`)
> 章节: `docs/feature_plan/06-ccb-benchmark/f-91-mcp-skill-discovery.md`
> 最后更新: 2026-07-01
> 缺口来源: gap-analysis-2026q2.md §3.3(`#### F-91: MCP Skills 自动发现`,已分解到本文档 §0)

## §0 缺口摘要

> 本节为 gap-analysis-2026q2.md §3.3 F-91 派工条目的分解版本;详细设计与基线请阅读 §1。

### 0.1 缺口描述

`clawcodex_ext/services/mcp/` 已有完整 MCP transport 与连接管理(`client.py` / `connection_manager.py` / `transport.py` / `official_registry.py` 等 ~30 个模块),但**没有任何自动发现 → skill 注册**流程:

- `tools/list` / `prompts/list` / `resources/list` 枚举**未实现**;
- 增量更新通知订阅(`notifications/tools/list_changed`)**未处理**;
- TTL fallback(默认 1h)**缺失**;
- 命名空间隔离(`server.tool`)**缺失**;
- `MCP_SKILL_DISCOVERY` Feature Flag **缺失**;
- 与 `skill_registry` 注册中心**未联通**;
- mock MCP server 测试 fixture **缺失**。

### 0.2 对标

- CCB MCP server 启动后自动枚举 `tools` / `prompts` / `resources`,封装为本地 skill 描述,`source=mcp:<server>` 标记可见;
- CCB `notifications/tools/list_changed` 触发增量刷新 + 1h TTL fallback,允许 mtime-based stale;
- CCB 多个 MCP server 同名 tool 不冲突,通过 `<server>.<tool>` 命名空间隔离。

### 0.3 解耦落地路径(全部 `clawcodex_ext/services/mcp/discovery/`,不动 `src/`)

- `skill_discovery.py:McpSkillDiscovery` — `discover_all()` / `refresh(server_id)` / `handle_notification()` 三大入口;
- `skill_writer.py` — `inputSchema → JSON Schema 子集` 转写器;
- `notifier.py` — `tools/list_changed` 通知订阅 + 自动 refresh;
- `cache.py` — LRU + TTL(默认 3600s)+ stale fallback 重建;
- `namespace.py` — `<server>.<tool>` 命名空间 + 冲突检测(`detect_collision`);
- `registry_integration.py` — 挂到 `skill_registry.register()` + `source=mcp:*` 标签;
- `clawcodex_ext/feature_gate/registry.py` 注册 `MCP_SKILL_DISCOVERY` 默认 off;
- 单元测试:`tests/services/mcp/discovery/` + `mock_mcp_server.py` 模拟 server 暴露 tools。

### 0.4 依赖

- 现有 `clawcodex_ext/services/mcp/` 全部 transport 模块;
- `clawcodex_ext/skills/` 现有 skill 加载框架;
- F-68 Feature Gate(`MCP_SKILL_DISCOVERY=on`);
- F-92 Skill Search(将来 MCP skill 一并进入 TF-IDF 索引)。

### 0.5 估算工时

1 周(单人)。

---

## §1 设计规划

### 1.1 目标

对标 CCB MCP Skills 自动发现能力,使 ClawCodex 能在 MCP server 启动 / 连接时**自动枚举**其暴露的 tools / prompts / resources,将其封装为 ClawCodex 内置 skill 描述注册到 `skill_registry`,无需用户在 `~/.clawcodex/skills/` 手动编写 SKILL.md / manifest。零手动配置即可让 Agent 看到 MCP server 提供的全部能力。

### 1.2 背景

**已完成基础设施**:

- `clawcodex_ext/services/mcp/` 已有 MCP transport 抽象与连接管理(具体子模块以当前实现为准);
- `clawcodex_ext/feature_gate/registry.py`(F-68)支持 `MCP_SKILL_DISCOVERY` 等 flag;
- `clawcodex_ext/skills/` skill 加载框架已存在(描述、manifest 解析)。

**缺口**:

1. **MCP server 能力枚举**: `tools/list` / `prompts/list` / `resources/list` RPC 调用并缓存结果,**待实现**;
2. **自动 skill 注册**: 把 MCP 暴露的 tool 转写为 skill 描述(`name` / `description` / `input_schema`),注入 `skill_registry` **完全缺失**;
3. **增量更新**: MCP server 通知 `notifications/tools/list_changed` 时增量重扫,**缺失**;
4. **TTL 缓存**: 启动时一次性扫描 + 启动后增量更新 + TTL fallback(默认 1h)**缺失**;
5. **沙箱元数据透出**: AI 端通过 `SkillListTool` 看到 MCP skill,但标记 `source=mcp:<server>` **缺失**;
6. **Feature Flag**: `MCP_SKILL_DISCOVERY` 默认 off,需用户显式开启 **缺失**;
7. **多 server 命名空间**: 多个 MCP server 暴露同名 tool 时不冲突(`server.tool` 形式命名空间)**缺失**;
8. **测试**: mock MCP server + 自动发现 + 注册断言 **完全缺失**。

### 1.3 子特性分解

| 编号 | 子特性 | 预计工作量 |
|:----:|--------|:----------:|
| P91-A | `McpSkillDiscovery` 核心类(`skill_discovery.py`):RPC `list_changed` 订阅 + 缓存 + 重扫 | 2-3 天 |
| P91-B | MCP tool → skill 描述转写器(`skill_writer.py`):input_schema → JSON Schema 子集 + description 摘要 | 1-2 天 |
| P91-C | 增量通知订阅(`notifier.py`):解析 `notifications/tools/list_changed` + 自动触发重扫 | 1 天 |
| P91-D | TTL 缓存(`cache.py`):LRU + TTL 默认 1h + stale fallback 重建 | 1 天 |
| P91-E | 命名空间隔离(`namespace.py`):`server.tool` 命名 + 冲突检测 | 1 天 |
| P91-F | Skill 注册中心集成(`registry_integration.py`):挂到 `skill_registry.register()` + `source` 标签 | 1 天 |
| P91-G | Feature Gate(`MCP_SKILL_DISCOVERY`)+ 默认 off | 0.5 天 |
| P91-H | 单元 + 集成测试(mock MCP server fixture) | 2 天 |

**估算总工时**:1 周(单人)。

### 1.4 架构设计

```
┌─────────────────────────────────────────────────────────────────┐
│ MCP Server A (stdio / sse)                                       │
│   ├─ tools: list_files, read_file, write_file, ...              │
│   ├─ prompts: code-review, refactor, ...                        │
│   └─ resources: file://...                                       │
└─────────────────────────────────────────────────────────────────┘
                          │ JSON-RPC
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ clawcodex_ext/services/mcp/                                      │
│   client.py(transport + connection)                              │
│   + skill_discovery.py(McpSkillDiscovery)                        │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ Skill 转写器(skill_writer.py)                                    │
│   MCP tool{name, description, inputSchema}                       │
│   → SkillManifest{name: "A.list_files", description, params}    │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ Skill Registry(clawcodex_ext/skills/)                           │
│   skills:                                                        │
│     - A.list_files  (source=mcp:A)                              │
│     - A.read_file   (source=mcp:A)                              │
│     - B.search_web  (source=mcp:B)                              │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
              Agent via SkillListTool
```

#### 包结构(全部解耦)

```
clawcodex_ext/services/mcp/                       ← 现有 transport(扩展)
└── skill_discovery.py                            # P91-A: McpSkillDiscovery 核心

clawcodex_ext/services/mcp/discovery/              ← 新建
├── __init__.py
├── skill_writer.py                                # P91-B: MCP tool → skill 描述
├── notifier.py                                    # P91-C: list_changed 通知订阅
├── cache.py                                       # P91-D: LRU + TTL 缓存
├── namespace.py                                   # P91-E: server.tool 命名
└── registry_integration.py                        # P91-F: 注入 skill_registry

clawcodex_ext/feature_gate/registry.py             # P91-G: 注册 MCP_SKILL_DISCOVERY

tests/services/mcp/discovery/                     ← P91-H
├── test_skill_discovery.py
├── test_skill_writer.py
├── test_namespace.py
└── mock_mcp_server.py                             # 模拟 MCP server 暴露 tools
```

#### 解耦要点

| 设计点 | 解耦方式 | 理由 |
|--------|----------|------|
| MCP transport 复用 | 复用 `clawcodex_ext/services/mcp/` 现有 client | 不破坏现有 MCP 连接管理 |
| 转写器独立 | `discovery/skill_writer.py` 单文件 | 便于单元测试 |
| Skill 注册 | 走 `skill_registry.register()` + `source` 标签 | 与现有 skill 加载流程一致 |
| 命名空间 | `namespace.py` 提供 `server.tool` 拆分 + 冲突检测 | 避免多 server 同名 tool 覆盖 |
| Feature Gate | F-68 注册 `MCP_SKILL_DISCOVERY` 默认 off | 避免误启动时阻塞 |
| 不动 `src/` | 全部新模块落 `clawcodex_ext/` | 遵守 CLAUDE.md 解耦原则 |

### 1.5 核心数据模型

```python
# clawcodex_ext/services/mcp/discovery/skill_writer.py

@dataclass(frozen=True)
class McpSkillDescriptor:
    """从 MCP tool 转写而来的 skill 描述。"""
    name: str                              # "A.list_files" (server.tool 命名)
    display_name: str                      # "List Files (MCP server A)"
    description: str                       # 来自 MCP tool.description
    source: Literal["mcp"] = "mcp"
    server_id: str                         # MCP server 标识
    tool_name: str                         # 原始 MCP tool name
    input_schema: dict[str, Any]           # JSON Schema 子集(inputSchema → 简化)
    version: str | None = None             # MCP server 报告的版本
    discovered_at: str                     # ISO 8601
    ttl_seconds: int = 3600

    def to_skill_manifest(self) -> dict:
        """输出与现有 skill manifest 兼容的 dict,便于直接注册。"""


# clawcodex_ext/services/mcp/discovery/namespace.py

@dataclass(frozen=True)
class NameSpacedTool:
    server_id: str
    tool_name: str
    @property
    def qualified(self) -> str:            # "A.list_files"
        return f"{self.server_id}.{self.tool_name}"

def detect_collision(server_id: str, tool_name: str, registry: SkillRegistry) -> bool: ...
```

### 1.6 核心接口

```python
# clawcodex_ext/services/mcp/skill_discovery.py

class McpSkillDiscovery:
    """MCP server 启动后自动发现其 tools,转写为 skill 注册到 skill_registry。"""

    def __init__(
        self,
        *,
        mcp_client: "McpClient",                 # 复用现有 transport
        skill_registry: SkillRegistry,
        ttl_seconds: int = 3600,
        feature_gate: FeatureGate | None = None,
    ) -> None: ...

    async def discover_all(self) -> list[McpSkillDescriptor]:
        """启动时一次性扫描所有已连接 MCP server,注册 skill。"""

    async def refresh(self, server_id: str) -> list[McpSkillDescriptor]:
        """重扫单个 server(用于 list_changed 通知或 TTL 过期)。"""

    async def handle_notification(self, server_id: str, method: str, payload: dict) -> None:
        """处理 MCP notification(如 notifications/tools/list_changed)。"""

    def get_skill(self, qualified_name: str) -> McpSkillDescriptor | None: ...

    def list_skills(self, *, source: str = "all") -> list[McpSkillDescriptor]: ...
```

### 1.7 失败模式

| 错误类型 | 触发场景 | 处理 |
|----------|----------|------|
| `McpConnectionError` | MCP server 不可达 | 跳过该 server,启动时不阻塞 |
| `McpListTimeoutError` | `tools/list` 30s 超时 | 重试一次,二次失败用上次缓存 |
| `SkillRegistrationError` | 注册到 skill_registry 失败(名称冲突) | 用 `server.tool` 命名空间隔离 |
| `InvalidInputSchemaError` | MCP tool input_schema 不符合 JSON Schema | 记录 WARNING + 跳过该 tool |
| `NotificationLostError` | `list_changed` 通知丢失 | TTL 兜底,定期全量 refresh |

### 1.8 测试策略

| 层级 | 框架 | 范围 |
|------|------|------|
| 单元 | pytest | `skill_writer` 转写正确性 + `namespace` 冲突检测 |
| 单元 | pytest | `cache` LRU + TTL 过期逻辑 |
| 集成 | pytest + mock MCP server | `discover_all` → 注册断言 + `handle_notification` → 重扫 |
| E2E | pytest + 真实 MCP server | 启动 `mcp-server-filesystem`,断言 `SkillListTool` 列出 `filesystem.*` skill |

### 1.9 排序与索引策略

针对 Agent / SkillListTool 经常会高频查询列出 skills 的场景,引入 LRU + 标签倒排索引,避免每次 cold scan:

| 维度 | 实现 |
|------|------|
| 命中顺序 | 最近调用 → 优先级 source 顺序:`mcp:*` < `user:` < `project:` < `managed:` |
| 索引键 | `(server_id, tool_name)` → `qualified_name`(复合索引);`tag` → `qualified_name`(倒排表) |
| 失效 | 通知 `list_changed` 命中 server_id → 局部索引失效;TTL 兜底全局索引失效 |
| 退路 | 索引损坏时 fallback 到全量 `discover_all()` 并写 audit |

注意:索引不和 skill_registry 主存储强耦合,主存储永远以 `discover_all()` 为真值源。

### 1.10 CLI / Tool 行为

#### `McpSkillDiscoveryTool`(供 Agent / 管理员调用)

| action | 输入 | 输出 |
|--------|------|------|
| `list` | `server_id?`, `tag?`, `source?` | 命中列表(带 cache 状态)|
| `refresh` | `server_id?`(空表全部) | 被刷新的 servers + 新增/移除的 skills |
| `inspect` | `qualified_name` | 输入 schema 详情 + 真实 server 上的 tool spec |
| `enable` / `disable` | - | 切换 `MCP_SKILL_DISCOVERY` 并立即生效 |

#### 命令族(`/mcp-skill`)

```
/mcp-skill list [--server A] [--tag io] [--source mcp]
/mcp-skill refresh [server-id]
/mcp-skill inspect <qualified-name>
/mcp-skill enable
/mcp-skill disable
/mcp-skill health                              # 上次成功列表时间 / 当前 cache 状态
```

注意 CLI 默认隐藏,需 `--debug-mcp` 才显示,避免打扰普通用户;Agent 默认仍可调用 Tool API。

### 1.11 验收标准

1. MCP server 启动后 5s 内,`SkillListTool` 列出该 server 的所有 tools(`source=mcp:<server>`);
2. 收到 `notifications/tools/list_changed` 后 1s 内增量更新 skill 列表;
3. TTL 过期后下一次 `SkillGet` 触发后台 refresh + 返回 stale + future refresh 后返回新数据;
4. 两个 MCP server 同名 tool 不冲突,分别用 `<server>.tool` 命名;
5. `MCP_SKILL_DISCOVERY=off` 时不调用 `tools/list`,零开销,不写索引;
6. 索引命中 `/mcp-skill list --tag io` 在 1000 条 skills 上 < 20ms;
7. `McpSkillDiscoveryTool` 各项 action 都有审计记录(server / actor / time);
8. `refresh --server A` 后对应索引局部失效,其他 server 索引保持不变;
9. mock MCP server 不可达时 `discover_all()` 跳过该 server,不会阻塞其他 server 注册;
10. 单元测试覆盖转写、命名空间、cache、notifier、tool actions、并发 refresh 场景;
11. 集成测试:启动 mock MCP server → `SkillListTool` 列表 → 修改 mock → 通知触发 → 列表更新;
12. 测试覆盖率 ≥ 80%(核心模块)。

## §2 落地步骤

| 步骤 | 内容 | 涉及子特性 | 工时 |
|:----:|------|:----------:|:----:|
| 1 | `skill_discovery.py` + `cache.py` + 集成现有 MCP client | P91-A/D | 2 天 |
| 2 | `skill_writer.py` + `namespace.py` | P91-B/E | 2 天 |
| 3 | `notifier.py` + `registry_integration.py` | P91-C/F | 1 天 |
| 4 | F-68 注册 `MCP_SKILL_DISCOVERY` | P91-G | 0.5 天 |
| 5 | 单元 + 集成 + mock fixture | P91-H | 2 天 |

**累计工时**:1 周。

## §3 风险与缓解

| 风险 | 等级 | 缓解 |
|------|:----:|------|
| MCP server 启动慢阻塞 ClawCodex | 🟠 | 异步并发扫描 + 启动超时 5s |
| `list_changed` 通知频率过高 | 🟡 | 1s 去抖窗口 |
| input_schema 不规范污染 skill 注册 | 🟠 | 严格 JSON Schema 校验 + skip + WARN |
| 多 server 同名 tool 覆盖 | 🔴 | 强制 `server.tool` 命名空间 |

## §4 与其他特性的关系

| 协同 | 说明 |
|------|------|
| **F-68 Feature Gate** | 注册 `MCP_SKILL_DISCOVERY` |
| **F-71 Tool Gap** | MCP tool 可视为内置 tool,纳入统一 registry |
| **F-92 Skill Search** | 自动发现的 skill 与手动 SKILL.md 一并索引 |
| **F-95 Templates** | 可基于 MCP skill 生成模板 |
| **F-100+** | 其他 MCP 子特性 |

## §5 后续展望

- P91-I 智能推荐:根据当前任务上下文推荐最相关的 MCP skill;
- P91-J 健康检查:MCP server 心跳 + stale 检测 + 自动重连;
- P91-K 元 prompt 转写:把 MCP `prompts/list` 转为 slash 命令族。

---

**关联文档**: [README.md 缺口矩阵](./README.md#a-全特性对照矩阵)