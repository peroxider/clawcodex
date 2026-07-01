# F-93: TeamMem 共享记忆

> 状态: 📋 规划中(已有 `clawcodex_ext/memdir/team_mem_paths.py` 与 team prompt 基础;目标模块 `extensions/agents/team_memory.py` 待建)
> 章节: `docs/feature_plan/06-ccb-benchmark/f-93-team-memory.md`
> 最后更新: 2026-07-01
> 缺口来源: gap-analysis-2026q2.md §3.3(`#### F-93: TeamMem 团队共享记忆`,已分解到本文档 §0)

## §0 缺口摘要

> 本节为 gap-analysis-2026q2.md §3.3 F-93 派工条目的分解版本;详细设计与基线请阅读 §1。

### 0.1 缺口描述

部分基础设施已具备,但**没有面向 team 的共享记忆服务层**:

- 已有 `clawcodex_ext/memdir/team_mem_paths.py`(三层 path-traversal 防御:`_sanitize_path_key` → `os.path.abspath` containment → `_realpath_deepest_existing` symlink 解析);
- 已有 `clawcodex_ext/memdir/team_mem_prompts.py`(combined memory prompt 形态);
- 已有 `clawcodex_ext/services/swarm/team_file.py:TeamFile`(`.clawcodex/team.json` 读写 + `add_member` / `remove_member`);
- 已有 `tool_system/tools/send_message.py`(mailbox / in-process / broadcast);

完全缺失:

- append-only JSONL store 与 atomic write;
- tag / source / scope 过滤 + score 排序 retrieval;
- scope 权限校验(`team` / `lead_only` / `agent_pair`);
- 谁在何时写了什么的 audit;
- TopK budget-aware prompt 注入;
- TeamDelete / Compact 后的归档机制;
- prompt 中 stale caveat 显式提示。

### 0.2 对标

- CCB `TeamMem` 持久化 + 可检索 + 可审计 + 按团队隔离;
- CCB `scope=team / lead_only / agent_pair` 多层权限(lead_only 需 lead approval);
- CCB `topK` budget-aware prompt 注入与"trust files over memory"stale caveat;
- CCB source weight 排序(manual / task_result / review / send_message / system);
- CCB TeamDelete 默认归档而非删除共享记忆。

### 0.3 解耦落地路径(避免污染 `src/`,放 `extensions/agents/`)

- `extensions/agents/team_memory.py`(独立子系统):
  - `service.py:TeamMemoryService` — facade;
  - `store.py:TeamMemoryStore` — append-only JSONL + atomic write + index 缓存;
  - `index.py:TeamMemoryIndex` — 关键词 / 标签 / source / agent 过滤 + score;
  - `policy.py:TeamMemoryPolicy` — permission + scope 校验;
  - `audit.py:TeamMemoryAuditLog` — 谁在何时写了什么;
- `extensions/agents/team_memory_integration.py` — TeamCreate / TeamDelete / SendMessage 摘要钩子;
- `clawcodex_ext/tool_system/tools/team_memory.py` — `TeamMemoryTool`;
- `clawcodex_ext/command_system/team_memory_commands.py` — `/team memory` debug 命令族;
- `extensions/capabilities/team_memory_protocol.py` — `TeamMemoryService` Protocol 给三方扩展;
- 完全复用 `team_mem_paths.py` 的三层防御,fail closed 路径。

### 0.4 依赖

- 现有 `clawcodex_ext/memdir/team_mem_paths.py` + `team_mem_prompts.py`;
- 现有 `clawcodex_ext/services/swarm/team_file.py`;
- 现有 `SendMessage` mailbox 路由;
- F-92 Skill Search(可复用 tokenizer / TF-IDF index);
- F-94 BG_SESSIONS(后台 agent 恢复时读取 TeamMem,避免丢失团队上下文);
- F-100 Dreaming(可把长期 team 经验抽取为 compact summary)。

### 0.5 估算工时

2 周(单人)。

---

## §1 设计规划

### 1.1 目标

对标 CCB `TEAMMEM` 能力,为 ClawCodex 的 Team / Coordinator / Agent 协作模式提供团队级共享记忆层。多个 agent 在同一 team workspace 内工作时,可以把跨 agent 有用的信息写入共享记忆,并在后续子任务、恢复会话、跨 teammate 通信时自动注入相关摘要,避免每个 agent 只能依赖私有上下文或重复询问 team lead。

F-93 的目标不是重做个人 memory,也不是替代 `SendMessage` 即时通信;它提供的是**可持久化、可检索、可审计、按团队隔离**的长期协作知识库。

### 1.2 背景

现有基础设施已经具备 TeamMem 的若干底座:

1. `clawcodex_ext/memdir/team_mem_paths.py` 已实现 team memory 路径解析与三层 path traversal 防护;
2. `clawcodex_ext/memdir/team_mem_prompts.py` 已提供 combined memory prompt 形态;
3. `clawcodex_ext/services/swarm/team_file.py` 已有 `.clawcodex/team.json` team roster 读写模型;
4. `clawcodex_ext/tool_system/tools/send_message.py` 已支持 in-process agent、team mailbox 与 broadcast 通信;
5. `TeamCreate` / `TeamDelete` 与 agent name registry 已能表达 team 生命周期。

缺口在于:上述能力目前更偏路径、prompt 与消息路由原语,缺少一个面向 team 的共享记忆服务,无法统一完成写入策略、冲突合并、检索排序、权限校验、审计记录与 tool/CLI/API 接入。

### 1.3 子特性分解

| 编号 | 子特性 | 预计工作量 |
|:----:|--------|:----------:|
| P93-A | 数据模型(`TeamMemoryEntry`, `TeamMemoryQuery`, `TeamMemoryResult`) | 1 天 |
| P93-B | 存储层(`TeamMemoryStore`): JSONL + markdown entrypoint + 原子写 | 2 天 |
| P93-C | 检索层(`TeamMemoryIndex`):关键词/标签/agent/source 过滤 + recency score | 1.5 天 |
| P93-D | 权限与隔离(`TeamMemoryPolicy`):team member / lead / readonly / private scope | 1 天 |
| P93-E | Team 生命周期集成:TeamCreate 初始化、TeamDelete 可选归档、SendMessage 摘要落盘 | 1.5 天 |
| P93-F | Tool/CLI 接入:`TeamMemoryTool` + `/team memory` debug 命令 | 1 天 |
| P93-G | prompt 注入:`get_team_memory_section()` 与 budget-aware topK | 1 天 |
| P93-H | 单元 + 集成测试 | 2 天 |

**估算总工时**:2 周。

### 1.4 架构设计

```
Team runtime
  ├─ .clawcodex/team.json                 # TeamFile: lead + members
  ├─ SendMessage / mailbox JSONL          # 即时通信
  └─ Agent tasks / Coordinator mode
             │
             ▼
extensions/agents/team_memory.py
  ├─ TeamMemoryService                    # 对外 facade
  ├─ TeamMemoryStore                      # append/read/compact/archive
  ├─ TeamMemoryIndex                      # query topK
  ├─ TeamMemoryPolicy                     # permission + scope
  └─ TeamMemoryAuditLog                   # mutation audit
             │
             ▼
<auto_mem>/team/
  ├─ MEMORY.md                            # 人类可读 entrypoint
  ├─ entries.jsonl                        # 结构化 append-only entry log
  ├─ index.json                           # 可重建缓存
  ├─ audit.jsonl                          # 谁在何时写了什么
  └─ archive/*.jsonl                      # TeamDelete / compact 后归档
```

#### 包结构

```
extensions/agents/
├── team_memory.py                         # P93-A/B/C: service + models + store
├── team_memory_policy.py                  # P93-D: permission/scope rules
└── team_memory_integration.py             # P93-E/G: team lifecycle + prompt hooks

clawcodex_ext/tool_system/tools/
└── team_memory.py                         # P93-F: TeamMemoryTool

clawcodex_ext/command_system/
└── team_memory_commands.py                # P93-F: /team memory 命令族

clawcodex_ext/memdir/
├── team_mem_paths.py                      # 已有:路径与 traversal 防护
└── team_mem_prompts.py                    # 已有/扩展:prompt section 生成

tests/extensions/agents/
├── test_team_memory_store.py
├── test_team_memory_index.py
├── test_team_memory_policy.py
└── test_team_memory_integration.py
```

### 1.5 核心数据模型

```python
@dataclass(frozen=True)
class TeamMemoryEntry:
    id: str                                # stable hash(team_id + created_at + author + content)
    team_id: str
    content: str
    summary: str
    author_agent_id: str
    author_name: str | None = None
    source: Literal["manual", "send_message", "task_result", "review", "system"] = "manual"
    scope: Literal["team", "lead_only", "agent_pair"] = "team"
    tags: tuple[str, ...] = ()
    related_agents: tuple[str, ...] = ()
    created_at: str                        # ISO 8601 UTC
    updated_at: str | None = None
    expires_at: str | None = None
    confidence: float = 1.0


@dataclass(frozen=True)
class TeamMemoryQuery:
    team_id: str
    query: str
    requester_agent_id: str
    top_k: int = 8
    tags: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    include_expired: bool = False


@dataclass(frozen=True)
class TeamMemoryResult:
    entry: TeamMemoryEntry
    score: float
    matched_terms: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class TeamMemoryConfig:
    enabled: bool = False
    max_entries: int = 2000
    max_entry_bytes: int = 16_384
    prompt_top_k: int = 8
    query_top_k: int = 20
    index_path: Path | None = None
    allow_agent_writes: bool = True
    require_lead_approval_for_lead_only: bool = True
```

### 1.6 核心接口

```python
class TeamMemoryStore:
    """Team 共享记忆的 append-only 持久化层。"""

    def __init__(self, *, team_id: str, root: Path, config: TeamMemoryConfig) -> None: ...

    def append(self, entry: TeamMemoryEntry) -> TeamMemoryEntry: ...

    def list_entries(self, *, include_expired: bool = False) -> list[TeamMemoryEntry]: ...

    def get(self, entry_id: str) -> TeamMemoryEntry | None: ...

    def delete(self, entry_id: str, *, actor: str, reason: str) -> bool: ...

    def compact(self, *, actor: str) -> TeamMemoryEntry: ...

    def archive(self, *, reason: str) -> Path: ...


class TeamMemoryService:
    """面向 Team/Agent/Tool 的高层 API。"""

    def __init__(
        self,
        *,
        workspace_root: Path,
        team_file: TeamFile,
        config: TeamMemoryConfig,
    ) -> None: ...

    def remember(
        self,
        content: str,
        *,
        author_agent_id: str,
        tags: Iterable[str] = (),
        source: str = "manual",
        scope: str = "team",
    ) -> TeamMemoryEntry: ...

    def recall(self, query: TeamMemoryQuery) -> list[TeamMemoryResult]: ...

    def build_prompt_section(self, *, requester_agent_id: str, task: str) -> str: ...

    def record_message_summary(
        self,
        *,
        sender: str,
        recipients: Iterable[str],
        summary: str,
        message: str,
    ) -> TeamMemoryEntry | None: ...
```

### 1.7 权限与隔离规则

| 场景 | 规则 |
|------|------|
| 非 team workspace | TeamMemoryService 不启动,返回 disabled |
| requester 不在 `.clawcodex/team.json` | 拒绝 recall/write |
| `scope=team` | 所有 team member 可读,成员可写 |
| `scope=lead_only` | team lead 可读写;普通成员写入需要 lead approval 或降级为 team scope |
| `scope=agent_pair` | author 与 `related_agents` 可读;lead 可审计 |
| TeamDelete | 默认归档 `<auto_mem>/team/archive/`,不自动删除 |
| 路径输入 | 必须通过 `validate_team_mem_key()` / `validate_team_mem_write_path()` |

### 1.8 Prompt 注入策略

TeamMem 不应把整个共享记忆注入每个 agent。Prompt section 只注入与当前任务相关的 topK 条目:

```
<team_memory>
You are working in team "triage-bot". Relevant shared memories:
1. [build/test] Use `python3 -m pytest tests/stability_gate/ -q --tb=short -x` before committing.
2. [ownership] agent "reviewer" owns PR comment analysis; agent "fixer" owns code edits.

Only rely on team memory when it matches the current repo state. If memory conflicts with observed files, trust the files.
</team_memory>
```

排序建议:

```
score(entry, query) = lexical_score * tag_boost * source_weight * recency_decay * confidence

source_weight:
  manual       = 1.2
  task_result  = 1.1
  review       = 1.1
  send_message = 0.9
  system       = 0.8
```

当 F-92 Skill Search 落地后,TeamMem 可复用 tokenizer / TF-IDF index,避免重复实现复杂检索。

### 1.9 Tool / CLI 行为

#### TeamMemoryTool

| action | 输入 | 输出 |
|--------|------|------|
| `remember` | `content`, `tags`, `scope`, `source` | 新 entry id + prompt-safe summary |
| `recall` | `query`, `top_k`, `tags` | ranked entries |
| `list` | `limit`, `tags`, `source` | 最近 entries |
| `delete` | `entry_id`, `reason` | 删除/墓碑结果 |
| `compact` | `reason` | compact summary entry |

#### `/team memory` 命令族

```
/team memory status
/team memory recall "deployment checklist"
/team memory remember --tag build "Run stability gate before commit."
/team memory list --tag review
/team memory compact
```

CLI 主要用于 debug 与人工维护,agent 默认使用 Tool API。

### 1.10 失败模式

| 错误 | 场景 | 处理 |
|------|------|------|
| `TeamMemoryDisabledError` | flag off 或 auto-memory off | 返回空 section,不写文件 |
| `TeamNotFoundError` | `.clawcodex/team.json` 不存在 | fallback 到个人 memory |
| `TeamMemoryPermissionError` | 非成员读写 / scope 越权 | 拒绝并写 audit |
| `TeamMemoryCorruptError` | `entries.jsonl` 单行损坏 | 跳过坏行 + WARN + 保留原文件 |
| `TeamMemoryIndexStaleError` | `index.json` 过期 | 后台重建或同步重建 |
| `PathTraversalError` | key/path 逃逸 | fail closed,不创建任何文件 |
| `TeamMemoryTooLargeError` | 单 entry 超过限制 | 拒绝写入,提示 compact/摘要 |

### 1.11 验收标准

1. `TEAMMEM=off` 时不读写 `<auto_mem>/team/`,prompt section 为空;
2. TeamCreate 后启用 TeamMem 时自动初始化 `MEMORY.md` / `entries.jsonl` 所需目录;
3. team member 写入后,其他 member 能通过 `recall()` 查询到相关 entry;
4. 非 team member 无法读写共享记忆;
5. `scope=lead_only` 不会注入普通 member prompt;
6. 损坏 JSONL 单行不会导致整个 team memory 加载失败;
7. path traversal / symlink escape 用例全部 fail closed;
8. 1000 条 entry recall top8 < 50ms;
9. TeamDelete 默认归档而非删除共享记忆;
10. 单元测试覆盖 store/index/policy/integration 关键路径。

## §2 落地步骤

| 步骤 | 内容 | 涉及子特性 | 工时 |
|:----:|------|:----------:|:----:|
| 1 | 梳理现有 `team_mem_paths` / `team_mem_prompts` / `team_file` API,定义模型 | P93-A | 1 天 |
| 2 | 实现 `TeamMemoryStore` append-only JSONL + atomic write + audit | P93-B | 2 天 |
| 3 | 实现 `TeamMemoryPolicy` 与 team roster 校验 | P93-D | 1 天 |
| 4 | 实现 `TeamMemoryIndex` 与 recall 排序 | P93-C | 1.5 天 |
| 5 | 接入 TeamCreate / TeamDelete / SendMessage 摘要钩子 | P93-E | 1.5 天 |
| 6 | 增加 `TeamMemoryTool` 与 `/team memory` debug 命令 | P93-F | 1 天 |
| 7 | 增加 prompt section 与 budget-aware topK 注入 | P93-G | 1 天 |
| 8 | 补齐单元/集成/安全测试 | P93-H | 2 天 |

## §3 风险与缓解

| 风险 | 等级 | 缓解 |
|------|:----:|------|
| 共享记忆污染 prompt | 🟠 | topK 检索 + source/confidence + 显式 stale caveat |
| agent 写入噪声过多 | 🟡 | 写入限流 + max entry bytes + compact |
| team scope 泄漏 lead/private 信息 | 🔴 | `TeamMemoryPolicy` 统一 authorize + 测试覆盖 scope |
| JSONL 并发写冲突 | 🟠 | 文件锁 + tmp + atomic replace / append lock |
| 路径逃逸安全风险 | 🔴 | 复用 `team_mem_paths.py` 三层防护,fail closed |
| 与个人 memory 语义混淆 | 🟡 | prompt 中明确 team memory 来源与 stale caveat |

## §4 与其他特性的关系

| 协同 | 说明 |
|------|------|
| **TeamCreate / TeamDelete** | Team 生命周期决定共享记忆初始化、成员权限与归档 |
| **SendMessage** | 可把广播或关键协作消息摘要沉淀为 TeamMem entry |
| **F-92 Skill Search** | 可复用 tokenizer / TF-IDF index 做 TeamMem 检索 |
| **F-89 Proactive** | 空闲 tick 可触发 compact / stale scan,但必须 feature-gated |
| **F-94 BG_SESSIONS** | 后台 agent 恢复时读取 TeamMem,避免丢失团队上下文 |
| **F-100 Dreaming** | 可把长期 team 经验抽取为 compact summary,但需避免重复保存 |

---

**关联文档**: [README.md 缺口矩阵](./README.md#a-全特性对照矩阵), [F-92 Skill Search](./f-92-skill-search.md)
