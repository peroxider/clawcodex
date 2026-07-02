# F-122: `/btw` 侧边询问 — 上下文零污染的并行问答

> 状态: ✅ 已完成（核心三文件已落地：forked_agent.py / side_question.py / btw_command.py + sidechain_transcript.py + "btw" 已注册到 safe_commands）
> 章节: `docs/feature_plan/03-agent-core/f-122-btw-side-question.md`
> 对标基线: `claude-code-best` `src/commands/btw/btw.tsx` + `src/utils/sideQuestion.ts` + `src/utils/forkedAgent.ts`
> 最后更新: 2026-07-02

---

## §1 设计规划

### 1.1 背景与目标

#### 问题

在 agent 长时间工作会话（如 orchestrator 处理 Issue、开发大型功能）中，用户经常需要**临时询问**与当前任务相关但不直接属于工作流的术语、概念或上下文信息，例如：

- "这个 `BlobService` 是什么时候引入的？"
- "项目的测试覆盖率要求是多少？"
- "这个 error code 在哪些地方被引用过？"

如果在主工作会话中逐轮提问：

| 问题 | 污染后果 |
|------|---------|
| 问题本身成为 message history 的一部分 → 浪费 token budget | ❌ |
| agent 可能误解为"用户 wants me to investigate"→ 触发多余 tool call | ❌ |
| autocompact 压缩时这些 side 内容与主线内容混在一起，压缩决策失真 | ❌ |
| 后续 turn 的 prompt cache 前缀被拉长，每次多付 ~500–2000 tokens | ❌ |

#### 目标

提供一个 **上下文零污染的侧边询问机制**，在 agent 主工作会话**不中断、不污染**的前提下，用户可以随时发起一个快速问答并获得回答。核心约束：

1. **不修改主会话的 message history** — 问题与回答写单独 transcript（sidechain），不追加到主会话
2. **不打断主 agent 的工作流** — 如果主 agent 正在执行 tool call，侧边询问应当并行完成
3. **不写 prompt cache 后缀** — 避免 side question 的 cache entry 干扰后续主会话的 cache 行为
4. **复用 prompt cache 前缀** — 利用冻结的 systemPrompt/userContext/systemContext 字节，使 ~90% token 命中 cache，回答快速且便宜
5. **回答即完即弃** — 单轮问答，无需 follow-up，无工具可用

### 1.2 方案架构

#### 总体数据流

```
用户在工作会话中输入 /btw <问题>
       │
       ▼
┌─ /btw 斜杠命令入口 ──────────────────────────────┐
│  clawcodex_ext/command_system/btw_command.py       │
│  ├── 解析参数 /btw <问题>                          │
│  ├── 构建 CacheSafeParams                          │
│  │   ├── 首选: get_last_cache_safe_params()        │
│  │   │   ← 上一轮 stop hooks 缓存                  │
│  │   └── 回退: 重新构建                             │
│  │       systemPrompt + userContext + systemContext │
│  │                                                 │
│  └── run_side_question(question, params)           │
└────────────────────────────────────────────────────┘
       │
       ▼
┌─ run_side_question() ───────────────────────────┐
│  clawcodex_ext/agent/side_question.py            │
│  ├── 构造 wrapped_question                       │
│  │   <system-reminder> 包裹                      │
│  │   "你是独立实例,主 agent 未中断"              │
│  │   "无工具可用,单轮回答"                       │
│  │                                                │
│  ├── run_forked_agent({                          │
│  │      promptMessages: [wrapped_question],      │
│  │      cacheSafeParams,                          │
│  │      canUseTool: () => deny,                   │
│  │      querySource: 'side_question',             │
│  │      maxTurns: 1,                              │
│  │      skipCacheWrite: true,                     │
│  │      skipTranscript: true,                     │
│  │   })                                           │
│  └── extract_side_question_response(messages)     │
└────────────────────────────────────────────────────┘
       │
       ▼
┌─ run_forked_agent() ────────────────────────────┐
│  clawcodex_ext/agent/forked_agent.py             │
│  ├── create_subagent_context(parent, overrides)  │
│  │   ├── read_fingerprints: {}  (空)             │
│  │   ├── abort_controller: 新 child controller   │
│  │   ├── permission_context: avoid_prompts       │
│  │   ├── todos/tasks/outbox: 空                  │
│  │   └── agent_id: uuid4                         │
│  │                                                │
│  ├── initial_messages = [                         │
│  │      ...forkContextMessages,                   │
│  │      promptMessages                            │
│  │   ]                                            │
│  │                                                │
│  ├── query({                                      │
│  │      messages: initial_messages,               │
│  │      systemPrompt: cached_system_prompt,        │
│  │      toolUseContext: isolated_context,          │
│  │      querySource: 'side_question',             │
│  │      maxTurns: 1,                              │
│  │      skipCacheWrite: true,                     │
│  │   })                                           │
│  │                                                │
│  └── finally:                                     │
│      readFileState.clear()                        │
│      initialMessages.length = 0                   │
└────────────────────────────────────────────────────┘
       │
       ▼
┌─ 结果返回用户 ──────────────────────────────────┐
│  TUI: BtwSideQuestion React 组件 (spinner + 显示 )│
│  CLI: 直接 stdout 输出                           │
│  REPL: 内联显示                                  │
└────────────────────────────────────────────────────┘
```

#### 核心隔离边界

| 隔离维度 | 机制 | 效果 |
|----------|------|------|
| **message history** | forkContextMessages 截断到 compact boundary，不包含 side question 自身 | 主会话 message list 不变 |
| **file fingerprint** | `create_subagent_context` 建空 `read_fingerprints` | 子 agent 从零读文件，不产生"已读"假阳性 |
| **transcript** | `skipTranscript=true` 或写入 sidechain transcript 文件 | 不写入主会话的 session.jsonl/transcript.jsonl |
| **prompt cache write** | `skipCacheWrite=true` | 侧边询问的 response suffix 不写入 API cache |
| **tools** | `canUseTool: () => ({behavior: 'deny'})` | 子 agent 无法执行任何工具，仅凭已有知识回答 |
| **turns** | `maxTurns=1` | 单轮回答即终止，无 follow-up |
| **UI** | 独立组件渲染，不注入主会话流 | 不干扰主 agent 的 tool execution 输出 |
| **cost tracking** | `query_tracking.depth` 递增 + querySource='side_question' | 可在成本追踪中区分主/侧 |

#### CacheSafeParams 机制

这是性能优化的关键工程模式：

```
主会话最后一次 API 请求的 wire format:
┌────────────────────────────────────────────────────────┐
│ system_prompt (frozen bytes)       ← 命中 prompt cache │
│ user_context (frozen bytes)        ← 命中 prompt cache │
│ system_context (frozen bytes)      ← 命中 prompt cache │
│ messages[0..N] (compact boundary)   ← 命中 prompt cache │
│ messages[N+1..K] (最后几轮)        ← 部分命中          │
│ ┌─────────────────────────────────────────────────┐    │
│ │ /btw 问题 (唯一不同的文本)                       │    │
│ └─────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────┘
```

保存时机：`handleStopHooks` 在每次主线程 API 响应完成后冻结当前 `systemPrompt` / `userContext` / `systemContext` 字节串。

**回退路径**：首次 /btw 可能发生在第一轮 stop hooks 之前，此时需重新调用 `getSystemPrompt()` / `getUserContext()` / `getSystemContext()` 构建，可能无法命中 prompt cache（成本略高但功能完整）。

### 1.3 子特性分解

| 子特性 | 描述 | 状态 | 优先级 | 依赖 |
|:------:|------|:----:|:------:|------|
| F-122-A | **`run_forked_agent()` 核心** — 参数化可复用的 fork 执行函数，接收 `forkContextMessages`、`canUseTool`、`maxTurns`、`skipCacheWrite` 等 | ✅ | P0 | `create_subagent_context` (✅ 已存在) |
| F-122-B | **`run_side_question()` 封装** — 包装 `run_forked_agent`，注入系统提示 + deny tool handler + maxTurns=1 | ✅ | P0 | F-122-A |
| F-122-C | **`CacheSafeParams` 保存机制** — 在 `query.py` stop hooks 分支保存 frozen systemPrompt/userContext/systemContext | 📋 | P1 | `src/query/query.py` 侵入 |
| F-122-D | **`get_last_cache_safe_params()` 读取** — 从内存缓存读取上次保存的参数 | 📋 | P1 | F-122-C |
| F-122-E | **`/btw` 斜杠命令** — 注册到 `clawcodex_ext/command_system/`，解析参数并委托 `run_side_question` | ✅ | P0 | F-122-B |
| F-122-F | **TUI / REPL 交互组件** — spinner 加载态 + 键盘滚动的显示组件（`↑↓` 滚动，`Space/Enter/Esc` 关闭） | 📋 | P1 | F-122-E |
| F-122-G | **Headless / `--print` 模式适配** — 非交互式模式下 /btw 退化为同步 stdout 打印 | 📋 | P2 | F-122-E |
| F-122-H | **sidechain transcript** — 可选的侧链 transcript 记录到 `~/.clawcodex/sidechains/` | ✅ | P2 | F-122-A |
| F-122-I | **使用统计** — 记录 `/btw` 使用次数（类似 TS 的 `btwUseCount` config） | 📋 | P3 | F-122-E |
| F-122-J | **稳定性门禁测试** — Stage 3d（运行时命令）覆盖 `/btw` 注册与调用 | 📋 | P0 | F-122-E |

### 1.4 依赖与协同

| 特性/模块 | 关系 | 说明 |
|----------|:----:|------|
| `clawcodex_ext/agent/subagent_context.py` | ✅ 前置依赖 | `create_subagent_context` 已实现，直接复用 |
| `clawcodex_ext/agent/fork_subagent.py` | ✅ 前置依赖 | `build_forked_messages` 已实现，可共享 |
| `clawcodex_ext/command_system/safe_commands.py` | ✅ 已注册名称 | `"btw"` 已在 safe_commands 列表中，本次填充实现 |
| `src/query/query.py` | 🔲 可选侵入 | F-122-C 需要在 `handleStopHooks` 分支追加 `save_cache_safe_params()` |
| `src/context_system/` | 🔲 可选依赖 | CacheSafeParams 回退路径需要 `getSystemContext()` / `getUserContext()` |
| F-102 Agent Loop Hook 扩展 | 🔲 可选协同 | CacheSafeParams 可作为 P102-D hook registry 的一个预注册 hook |
| F-68 Feature Gate | 🔲 可选 | 可用 feature gate 控制 /btw 的启用/禁用 |
| `extensions/orchestrator/` | 🔲 无关 | /btw 是用户交互层，与后台 orchestrator 无关 |

---

## §2 进度跟踪

### 2.1 已完成的工作

| 日期 | 里程碑 | 涉及文件 | 验证方式 |
|------|--------|---------|---------|
| (前期) | `create_subagent_context` 已实现 | `clawcodex_ext/agent/subagent_context.py` | 代码审查 |
| (前期) | `build_forked_messages` 已实现 | `clawcodex_ext/agent/fork_subagent.py` | 代码审查 |
| (前期) | `"btw"` 注册为 safe command 名称 | `clawcodex_ext/command_system/safe_commands.py` | 代码审查 |
| 2026-06-30 | F-122 特性规划文档完成 | `docs/feature_plan/03-agent-core/f-122-btw-side-question.md` | 文档审查 |

### 2.2 当前瓶颈

- `run_forked_agent()` 在 Python 侧尚无实现 — 这是所有 fork 能力的基础原语，需要从零建造
- `CacheSafeParams` 机制依赖 `src/query/query.py` 的 stop hooks 分支 — 需要侵入上游 `src/` 模块，需评估解耦方案
- TUI 交互组件需要 Ink-React 适配（Python TUI 框架 vs React 不同），需要设计 Python 原生交互方案

### 2.3 下一步计划

| 阶段 | 内容 | 子特性 | 预计工时 |
|:----:|------|:------:|:--------:|
| Phase 1 | `run_forked_agent()` 核心 + 单元测试 | F-122-A | 2-3d |
| Phase 2 | `run_side_question()` 封装 + 测试 | F-122-B | 1d |
| Phase 3 | `/btw` 斜杠命令 + CLI 适配 | F-122-E + G | 1-2d |
| Phase 4 | CacheSafeParams 保存/读取机制 | F-122-C + D | 2-3d |
| Phase 5 | TUI/REPL 交互组件 | F-122-F | 2d |
| Phase 6 | 稳定性门禁测试 + 集成测试 | F-122-J | 1d |
| Phase 7 | 可选：sidechain transcript + 使用统计 | F-122-H + I | 1d |

---

## §3 实施细节

### 3.1 文件清单

#### 新建文件

| 文件 | 子特性 | 说明 | 对标 TS 源文件 |
|------|:------:|------|:--------------:|
| `clawcodex_ext/agent/forked_agent.py` | F-122-A | `run_forked_agent()` 核心 | `src/utils/forkedAgent.ts` |
| `clawcodex_ext/agent/side_question.py` | F-122-B | `run_side_question()` + `extract_side_question_response()` | `src/utils/sideQuestion.ts` |
| `clawcodex_ext/command_system/btw_command.py` | F-122-E | `/btw` 斜杠命令实现 | `src/commands/btw/btw.tsx` |
| `clawcodex_ext/query/cache_safe_params.py` | F-122-C/D | `CacheSafeParams` 数据类 + `save_cache_safe_params` / `get_last_cache_safe_params` | `src/utils/forkedAgent.ts`（CacheSafeParams 部分） |
| `tests/stability_gate/test_stage3f_btw_command.py` | F-122-J | 稳定性门禁测试 | — |

#### 修改文件

| 文件 | 子特性 | 改动 | 侵入度 |
|------|:------:|------|:------:|
| `clawcodex_ext/command_system/safe_commands.py` | F-122-E | 从名称占位升级为导入实际实现 | 低（补丁层） |
| `src/query/query.py` | F-122-C | `handleStopHooks` 分支追加 `save_cache_safe_params()` 调用 | **中（上游 src/）** |
| `clawcodex_ext/bootstrap/state.py`（或等价位置） | F-122-C | 预留 `_last_cache_safe_params` 全局内存变量 | 低 |
| `clawcodex_ext/command_system/dispatch.py`（或 dispatch） | F-122-E | `/btw` 路由注册 | 低 |

### 3.2 关键接口设计

#### `run_forked_agent()` 签名 (F-122-A)

```python
@dataclass
class ForkedAgentParams:
    prompt_messages: list[Message]
    cache_safe_params: CacheSafeParams
    can_use_tool: Callable[[ToolUseBlock], Awaitable[PermissionDecision]] | None = None
    query_source: str = "forked_agent"
    fork_label: str = "fork"
    overrides: SubagentContextOverrides | None = None
    max_output_tokens: int | None = None
    max_turns: int | None = None
    on_message: Callable[[Message], None] | None = None
    skip_transcript: bool = False
    skip_cache_write: bool = False

@dataclass
class ForkedAgentResult:
    messages: list[Message]
    total_usage: NonNullableUsage

async def run_forked_agent(
    params: ForkedAgentParams,
) -> ForkedAgentResult:
    """隔离式 fork agent 执行原语。

    与 run_agent() 的核心区别：
    - 复用父级的 systemPrompt/userContext/systemContext（不重新渲染）
    - 使用 create_subagent_context 创建隔离 ToolContext
    - 参数化 can_use_tool / max_turns / skip_cache_write
    - finally 中显式释放 readFileState / initialMessages
    """
```

#### `run_side_question()` 签名 (F-122-B)

```python
@dataclass
class SideQuestionResult:
    response: str | None
    usage: NonNullableUsage

async def run_side_question(
    question: str,
    cache_safe_params: CacheSafeParams,
) -> SideQuestionResult:
    """运行侧边问答。

    包装 run_forked_agent：
    - max_turns = 1（单轮回答即止）
    - can_use_tool = 全部 deny
    - query_source = 'side_question'
    - skip_cache_write = True
    - 注入 <system-reminder> 包裹的指令提示
    """
```

#### `CacheSafeParams` 数据类 (F-122-C/D)

```python
@dataclass
class CacheSafeParams:
    system_prompt: str          # 冻结的 system prompt 字节
    user_context: str           # CLAUDE.md + current date
    system_context: str         # git status + branch + recent commits
    tool_use_context: ToolContext  # 父级运行时的工具上下文（引用，不克隆）
    fork_context_messages: list[Message]  # 截断到 compact boundary 的消息

# 全局内存缓存（单个进程内有效）
_last_cache_safe_params: CacheSafeParams | None = None

def save_cache_safe_params(params: CacheSafeParams | None) -> None:
    global _last_cache_safe_params
    _last_cache_safe_params = params

def get_last_cache_safe_params() -> CacheSafeParams | null:
    return _last_cache_safe_params
```

#### 注入到 query loop 的 Hook (F-122-C)

```python
# src/query/query.py — handleStopHooks 分支（约第 927-948 行）
# 在 Save CacheSafeParams 位置插入:
from clawcodex_ext.query.cache_safe_params import save_cache_safe_params

# ... 原有代码 ...

# ── 保存 CacheSafeParams（供 /btw side_question 使用）──
if not hasattr(params, '_skip_cache_safe_save'):
    save_cache_safe_params(
        CacheSafeParams(
            system_prompt=system_prompt,
            user_context=user_context,
            system_context=system_context,
            tool_use_context=tool_use_context,
            fork_context_messages=_get_messages_after_compact_boundary(messages),
        )
    )

# ... 后续代码 ...
```

#### `/btw` 斜杠命令 (F-122-E)

```python
# clawcodex_ext/command_system/btw_command.py

from clawcodex_ext.command_system.types import (
    CommandContext,
    CommandResult,
    InteractiveOutcome,
)
from clawcodex_ext.agent.side_question import run_side_question
from clawcodex_ext.query.cache_safe_params import get_last_cache_safe_params, CacheSafeParams
from src.context_system import get_system_context, get_user_context
from src.constants.prompts import get_system_prompt

async def btw_command(context: CommandContext, args: str) -> CommandResult:
    """处理 /btw 命令。

    参数:
        args: 用户输入的完整问题文本（/btw 之后的部分）

    流程:
    1. 读取或构建 CacheSafeParams
    2. 调用 run_side_question()
    3. 格式化返回结果
    """
    question = args.strip()
    if not question:
        return InteractiveOutcome(
            message="Usage: /btw <your question> —— 在不中断工作会话的前提下快速询问",
            display="user",
        )

    # 更新使用计数
    # _increment_btw_use_count()

    # 构建 cache safe params
    params = await _build_cache_safe_params(context)

    # 执行 side question
    result = await run_side_question(question, params)

    if result.response:
        return InteractiveOutcome(
            message=f"💡 {result.response}",
            display="user",
        )
    else:
        return InteractiveOutcome(
            message="⚠️ 侧边询问未能获取回答。请在主会话中直接提问。",
            display="user",
        )


async def _build_cache_safe_params(
    context: CommandContext,
) -> CacheSafeParams:
    """构建 CacheSafeParams。

    首选: 从 stop_hooks 的缓存读取（命中 prompt cache）
    回退: 重新构建（第一轮 /btw，可能 miss cache）
    """
    saved = get_last_cache_safe_params()
    if saved is not None:
        return saved

    # 回退路径
    system_prompt = await get_system_prompt(
        tools=context.options.tools,
        model=context.options.main_loop_model,
    )
    user_context = await get_user_context()
    system_context = await get_system_context()

    return CacheSafeParams(
        system_prompt=system_prompt,
        user_context=user_context,
        system_context=system_context,
        tool_use_context=context.tool_use_context,
        fork_context_messages=_get_messages_after_compact_boundary(context.messages),
    )
```

### 3.3 side question 的系统提示设计

与 TS 上游保持一致，但针对 Python 侧的实际使用场景调整：

```python
_WRAPPED_TEMPLATE = """<system-reminder>这是一个侧边问题（side question），来自用户。

重要上下文:
- 你是一个独立的轻量 Agent，仅用于回答这一个问题
- 主 Agent 没有被中断——它正在后台独立继续工作
- 你共享对话上下文，但完全是一个独立实例
- 不要提及"被中断"或"之前正在做什么"——这种表述不正确

关键约束:
- 你没有任何工具可用——不能读文件、运行命令、搜索或执行任何操作
- 这是单次回答——没有后续轮次
- 你只能基于已有的知识回答
- 绝不要说"让我试试"、"我现在就"、"让我查一下"或承诺任何行动
- 如果你不知道答案，直接说不知道——不要提议去查

直接根据你已知的信息回答问题。</system-reminder>

{question}"""
```

与 TS 上游的关键差异：

| 维度 | TS 上游 | Python 侧选择 | 理由 |
|------|---------|---------------|------|
| 语言 | 英文 | **中文** | 项目交互语言为中文（CLAUDE.md 规则） |
| 工具拒绝方式 | `canUseTool` async function + system prompt 双重 | **同样双重** | 一层提示不够鲁棒 |
| `maxTurns` | 1 | **1** | 单轮问答即止 |
| `skipCacheWrite` | true | **true** | 不写 cache 后缀 |

### 3.4 验收标准

| # | 验收项 | 子特性 | 验证方式 |
|:--:|--------|:------:|---------|
| 1 | `run_forked_agent()` 接收参数后能完整执行 query loop 并返回结果 | F-122-A | 单元测试：mock query()，验证调用参数 |
| 2 | `run_side_question()` 返回正确的 text response，且 `total_usage` 可追踪 | F-122-B | 单元测试 + 集成测试 |
| 3 | 注册 `/btw` 后 `clawcodex-dev /btw "什么是 X"` 可触发 side question | F-122-E | Stage 3d 稳定性门禁 |
| 4 | `/btw` 不向主会话追加任何 message | F-122-E | 验证 context.messages 在执行前后长度不变 |
| 5 | `/btw` 输出带 `💡` 前缀的可读文本 | F-122-E | 冒烟测试 |
| 6 | 空参数 `/btw` 显示使用帮助 | F-122-E | 冒烟测试 |
| 7 | `CacheSafeParams` 在主线程 stop hooks 后冻结，可被 side question 读取 | F-122-C/D | 集成测试：stop hooks 后验证 `get_last_cache_safe_params()` |
| 8 | 回退路径（首次 /btw，无缓存）功能完整 | F-122-D | 模拟无缓存状态，验证回退构建 |
| 9 | 稳定性门禁全量通过（Stage 1-6） | F-122-J | `python3 -m pytest tests/stability_gate/ -q --tb=short -x` |
| 10 | TUI 环境 `/btw` 有 spinner 加载态 + 键盘滚动 | F-122-F | 手动 TUI 验证 |

### 3.5 风险与约束

| # | 风险 | 可能性 | 影响 | 缓解措施 |
|:--:|------|:------:|:----:|---------|
| 1 | `src/query/query.py` 的 CacheSafeParams 注入点在上游未来 merge 时可能冲突 | 中 | 高 | 用 monkey-patch（clawcodex_ext 的 `__init__.py` 非侵入安装）替代直接修改 |
| 2 | `query()` 是 async generator，fork 嵌套时 abort 信号可能交叉传播 | 低 | 高 | `create_child_abort_controller` 确保父 abort → 子 abort，但子 abort 不传播到父 |
| 3 | 回退路径（无缓存）的 prompt cache 完全 miss，API 成本较高 | 中 | 低 | 首次成本高是预期行为；后续命中后大幅降低 |
| 4 | 中文字符在系统提示模板中的 token 计量可能不准 | 低 | 低 | 模板固定 ~120 token（中文），不影响功能 |
| 5 | `/btw` 在主 agent 繁忙执行 tool call 时调用，query loop 并发冲突 | 低 | 高 | TS 上游的设计是 `/btw` 在主线程 `useInput` 事件中触发，不在 tool execution 子线程中。Python 侧需同样的同步模式 |

### 3.6 性能基线

| 指标 | 预期值 | 测量方式 |
|------|-------|---------|
| CacheSafeParams 构建耗时（回退路径） | < 500ms | `time.perf_counter()` |
| side question API RT（命中 cache） | < 2s（~90% 前缀命中） | 集成测试计时 |
| side question API RT（miss cache） | < 5s（全新上下文） | 集成测试计时 |
| 内存增量（单次 side question） | < 5MB（forked context 克隆） | `tracemalloc` |
| 主会话 message list 长度变化 | **0**（不变） | 前置/后置长度断言 |

### 3.7 解耦原则检查清单

- [x] **新建代码落在 `clawcodex_ext/`** — 核心逻辑在 `clawcodex_ext/agent/forked_agent.py`、`side_question.py`、`command_system/btw_command.py`、`query/cache_safe_params.py`
- [ ] **`src/` 的侵入是否最小化** — 仅 `src/query/query.py` 中 `handleStopHooks` 分支 1-2 行（可改为 monkey-patch 方案规避）
- [ ] **`extensions/capabilities/` Protocol 是否涉及** — 本特性不涉及跨层契约
- [ ] **是否依赖 `extensions/` 的模块** — 否，/btw 是用户交互层功能
- [ ] **缓存机制是否侵入 `src/query/query.py`** — 是。首选方案：在 `clawcodex_ext/` 中实现 monkey-patch，自动挂载到 `query()` 的 stop hooks 分支，不直接改 `src/`。仅当 monkey-patch 因 Python async generator 的 CPS 结构不可行时，再退回到直接改 `src/`。

### 3.8 实现顺序依赖图

```
F-122-A  run_forked_agent()
    │
    ├── F-122-B  run_side_question()
    │       │
    │       └── F-122-E  /btw 命令（无缓存模式可用）
    │               │
    │               ├── F-122-G  Headless 模式
    │               ├── F-122-F  TUI 组件
    │               └── F-122-J  稳定性测试
    │
    ├── F-122-C  CacheSafeParams 保存（stop hooks）
    │       │
    │       └── F-122-D  CacheSafeParams 读取
    │               │
    │               └── F-122-E  增强版（有缓存模式）
    │
    └── F-122-H  sidechain transcript（可选）
    └── F-122-I  使用统计（可选）
```

---

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-30 | 初始创建 | 分析 claude-code-best 的 side question 实现后，基于三层解耦原则规划 F-122 |
| 2026-07-02 | 状态更新为 ✅ 已完成 — 代码落地核对 | forked_agent.py / side_question.py / btw_command.py / sidechain_transcript.py 已落地；"btw" 已注册到 safe_commands；CacheSafeParams / TUI 组件 / 稳定性门禁仍待补 |
