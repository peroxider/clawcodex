# F-168: 被动累积模式 — 增量思考 + 统一输出

> 状态: 📋 规划中
> 章节: `docs/feature_plan/03-agent-core/f-168-passive-accumulation-mode.md`
> 最后更新: 2026-07-23
> 设计来源: 用户需求讨论 — 让 Agent 从"有问必答"模式切换到"只听不说 + 静默思考 + 统一输出"模式

## §0 元信息

| 字段 | 值 |
|------|---|
| 文档性质 | Wave 2 P1 工具化组（中等门槛，~1-2 月可落地） |
| 前置依赖 | F-102 Hook 扩展点、ToolContext 状态字段 |
| 协同 | F-166 记忆分层（思考日志可写入 Episodic Memory）、F-158 Working Memory（增量思考结果可用 VERIFIED 标记）、F-157 ToolSearch（思考过程中动态检索工具） |
| 解耦原则 | ✅ 全部新增代码落在 `clawcodex_ext/accumulator/` + `clawcodex_ext/tool_system/tools/`，零 `src/` 侵入 |
| 落地形态 | 被动累积模式 = 累积层 + 思考层 + 输出层，支持斜杠命令 / 工具 / 自动检测三种触发方式 |

---

## §1 设计规划

### 1.1 背景

当前 Agent 的行为模式是**"有问必答"**——用户输入任何内容，Agent 都会产生文本输出。这在以下场景中存在问题：

| 场景 | 用户想要 | 当前行为 |
|------|---------|---------|
| **粘贴大段文档** | "先收着，别分析" | Agent 立即分析并输出长篇回复 |
| **分段输入多文件** | "全部贴完后再统一处理" | Agent 每收到一段就输出一次，打断用户节奏 |
| **批量数据录入** | "只管记录，不要注释" | Agent 对每条数据都做评论 |
| **被动观察** | "你看着就行，别说话" | Agent 无法保持沉默 |

**F-168 的定位**：提供一个通用「被动累积模式」，将 Agent 的"接收 → 思考 → 输出"行为拆解为三个独立阶段，允许用户控制何时输出。

### 1.2 目标

- 让 Agent 可在「接收模式」下只累积内容，不输出文本
- 让 Agent 在累积过程中可进行**增量思考**（内部调用工具做分析）
- 让所有增量思考的结果在**退出模式时统一输出**
- 支持三种触发方式：斜杠命令 / 工具调用 / 自动检测
- 支持多种数据目标：内存 / 文件 / 分块存储
- 与现有 `plan_mode` 正交兼容（可同时处于 plan + accumulate 模式）

### 1.3 非目标 (Out of Scope)

- 不替代 F-166 记忆分层（F-166 是跨会话持久化，F-168 是会话内行为模式切换）
- 不替代 F-158 Working Memory（F-168 的思考日志可消费 F-158 的 VERIFIED 标记，但不替代）
- 不替代 F-159 JIT 上下文合成（F-168 是"当次累积"而非"跨会话复用"）
- 不自动晋升思考日志到 Episodic Memory（留 Wave 3 或 F-166 集成）
- 不提供跨会话的"累积档案"——仅限单次会话内的累积生命周期

### 1.4 子特性分解

| 编号 | 子特性 | 覆盖范围 | 状态 | 工时 |
|:----:|--------|:---------:|:----:|:----:|
| P168-A | 累积层核心（AccumulatorSink Protocol + 三种 Sink 实现） | 核心基础设施 | 📋 | 1-2d |
| P168-B | Accumulate 工具（append / flush 双动作） | 核心工具 | 📋 | 1-2d |
| P168-C | Think 工具（增量思考记录 + 类型化 + 关联片段索引） | 思考层核心 | 📋 | 1-2d |
| P168-D | Note 工具（对累积片段做注释 + 标签） | 思考层辅助 | 📋 | 1d |
| P168-E | 被动模式系统提示词动态切换（进入/退出时注入/移除） | 行为控制 | 📋 | 1d |
| P168-F | 斜杠命令 `/accumulate`（start / flush / cancel + 参数） | 触发方式 1 | 📋 | 1d |
| P168-G | 自动检测触发（NLP 关键词 + 边界检测） | 触发方式 2 | 📋 | 1-2d |
| P168-H | 静默 Subagent（子代理在累积模式下的思考隔离） | 思考层扩展 | 📋 | 2-3d |
| P168-I | 自动反思触发器（按累积量阈值触发元认知反思） | 思考层自动化 | 📋 | 1-2d |
| P168-J | 退出时统一输出（思考摘要 + 累积内容路径） | 输出层 | 📋 | 1d |

### 1.5 影响范围

| 依赖特性 | 关系 | 说明 |
|---------|------|------|
| ToolContext | **扩展** | P168-A 在 ToolContext 上新增 `_accumulator: AccumulatorState \| None` 字段 |
| ToolRegistry | **扩展** | P168-B/C/D 注册新增工具到注册表 |
| CommandRegistry | **扩展** | P168-F 注册 `/accumulate` 斜杠命令 |
| 系统提示词组装 | **扩展** | P168-E 在 `build_full_system_prompt` 中根据 `accumulator_mode` 标志注入/移除被动模式规则 |
| 查询循环 query() | **无侵入** | 不修改 `query()` 函数体；通过 `post_llm` hook 抑制文本输出（见 §4.2） |
| F-102 Hook 系统 | **消费** | 文本输出抑制通过 `post_llm` hook 实现；自动反思通过 `pre_llm` hook 实现 |
| F-166 记忆分层 | **可集成** | 退出模式时，思考日志可选择性写入 Episodic Memory（远期） |

---

## §2 架构设计

### 2.1 三层架构

```
┌─────────────────────────────────────────────────────────────────────┐
│  Layer 1: 累积层 (Accumulation Layer)                              │
│  ┌──────────────────────────────────────────────────┐              │
│  │  Accumulate 工具  │  AccumulatorSink (Protocol)  │              │
│  │  append / flush   │  MemorySink / FileSink /     │              │
│  │                   │  RotatingBatchSink           │              │
│  └────────┬─────────┴──────────┬───────────────────┘              │
│           │                    │                                    │
│           ▼                    ▼                                    │
│  ┌──────────────────────────────────────────────────┐              │
│  │  AccumulatorState（会话内状态）                    │              │
│  │  chunks: list[str]      # 原始内容片段            │              │
│  │  metadata: list[dict]   # 每段元数据              │              │
│  │  sink: AccumulatorSink  # 持久化目标              │              │
│  └──────────────────────────────────────────────────┘              │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 2: 思考层 (Thinking Layer)                                   │
│  ┌──────────────────────────────────────────────────┐              │
│  │  Think 工具  │  Note 工具  │  Subagent 思考       │              │
│  │  analysis /  │  label +    │  fork 子代理         │              │
│  │  summary /   │  annotation │  并行分析            │              │
│  │  question /  │  + 行范围   │                      │              │
│  │  plan /      │            │                      │              │
│  │  reflection  │            │                      │              │
│  └────────┬─────────┬────────┴──────────┬───────────┘              │
│           │         │                   │                            │
│           ▼         ▼                   ▼                            │
│  ┌──────────────────────────────────────────────────┐              │
│  │  AccumuatorState.thoughts  (增量思考记录列表)      │              │
│  │  + annotations  (每段注释)                        │              │
│  │  + subagent_results  (子代理结果)                  │              │
│  │  + auto_reflection  (自动反思)                     │              │
│  └──────────────────────────────────────────────────┘              │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 3: 输出层 (Output Layer)                                     │
│  ┌──────────────────────────────────────────────────┐              │
│  │  退出模式时: Accumulate(action="flush")          │              │
│  │  → 返回: 累积内容 + 思考摘要 + 注释 + 子代理结果  │              │
│  │  → 模型: 综合所有增量思考 → 输出统一报告          │              │
│  └──────────────────────────────────────────────────┘              │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 核心数据流

```
用户输入
  │
  ├─→ /accumulate start
  │      ↓
  │   进入累积模式
  │      ↓
  │   系统提示词注入: "你现在处于被动累积模式..."
  │      ↓
  │
  ├─→ 用户粘贴 chunk_1
  │      ↓
  │   模型: Accumulate(chunk="chunk_1")     → 缓冲区: [chunk_1]
  │   模型: Think(type="analysis", ...)      → 思考日志: [分析1]
  │   模型: Note(label="critical", ...)      → 注释: {chunk_0: [critical]}
  │   模型: Grep("pattern")                  → 内部搜索（不可见）
  │      ↓
  │   用户: 继续粘贴
  │
  ├─→ 用户粘贴 chunk_2
  │      ↓
  │   模型: Accumulate(chunk="chunk_2")     → 缓冲区: [chunk_1, chunk_2]
  │   模型: Think(type="summary", ...)       → 思考日志: [分析1, 总结2]
  │   模型: Agent(fork, ...)                 → 子代理后台分析
  │      ↓
  │   [自动反思触发: 累积量 > 5000 chars]
  │   模型: Think(type="reflection", ...)    → 元认知反思
  │
  ├─→ 用户输入 /accumulate flush
  │      ↓
  │   Accumulate(action="flush"):
  │     → 持久化全部内容到 sink
  │     → 构建思考摘要
  │     → 清除累积状态
  │     → 恢复普通系统提示词
  │      ↓
  │   模型收到 ToolResult:
  │     - total_chunks: 2
  │     - total_chars: 15342
  │     - total_thoughts: 3
  │     - thought_summary: "分析1: ...; 总结2: ...; 反思: ..."
  │     - content_path: /tmp/accumulate_xxx.txt
  │      ↓
  │   模型基于全部内容 + 所有增量思考 → 输出统一分析报告
```

### 2.3 状态机

```
                    ┌──────────────┐
                    │  正常模式    │
                    └──────┬───────┘
                           │
              ┌────────────┴────────────┐
              │ 触发方式:               │
              │  /accumulate start      │
              │  EnterAccumulateMode 工具│
              │  自动检测触发词          │
              └────────────┬────────────┘
                           │
                           ▼
                    ┌──────────────┐
              ┌─────┤ 累积模式激活 ├─────┐
              │     │              │     │
              │     │ 状态:         │     │
              │     │ 缓冲区有内容   │     │
              │     │ 思考日志有记录 │     │
              │     │ 文本输出被抑制 │     │
              │     └──────────────┘     │
              │                         │
              ▼                         ▼
      ┌──────────────┐         ┌──────────────┐
      │ 继续接收内容   │         │ 退出累积模式   │
      │ 增量思考      │         │ flush → 统一  │
      │ 自动反思      │         │ 输出结果      │
      └──────────────┘         └──────┬───────┘
                                      │
                                      ▼
                               ┌──────────────┐
                               │  正常模式    │
                               │ (恢复文本输出) │
                               └──────────────┘
```

---

## §3 接口定义

### 3.1 AccumulatorSink Protocol

```python
# clawcodex_ext/accumulator/interface.py

class AccumulatorSink(Protocol):
    """任何可以接收累积数据的 sink。
    
    实现此 Protocol 的类可作为累积模式的持久化目标。
    """
    def write(self, chunk: str, metadata: dict[str, Any] | None = None) -> None:
        """写入一个内容片段。"""
        ...
    
    def flush(self) -> str:
        """返回全部累积内容并清空缓冲区。
        
        Returns:
            累积内容的完整字符串（或文件路径，取决于实现）。
        """
        ...
    
    def reset(self) -> None:
        """清空缓冲区，丢弃所有内容。"""
        ...
```

### 3.2 AccumulatorConfig

```python
# clawcodex_ext/accumulator/interface.py

@dataclass
class AccumulatorConfig:
    """被动累积模式的配置。
    
    在进入累积模式时构造，挂载到 ToolContext._accumulator 上。
    """
    # --- 累积层 ---
    sink: AccumulatorSink                    # 数据写到哪里
    buffer_behavior: str = "append"          # append / replace / batch
    max_chunks: int | None = None            # 最大片段数（None=不限）
    
    # --- 输出控制 ---
    suppress_text_output: bool = True        # 是否抑制模型的文本输出
    ack_message: str = "✓ 已接收。"           # 每次接收后的确认消息
    ack_detail: str = "brief"                # none / brief / verbose
    
    # --- 思考层 ---
    enable_thinking: bool = True             # 是否启用 Think 工具
    enable_notes: bool = True                # 是否启用 Note 工具
    enable_auto_reflection: bool = True      # 是否启用自动反思
    reflection_interval_chars: int = 5000    # 每累积多少字符触发一次反思
    thought_log_path: str | None = None      # 可选：持久化思考日志到文件
```

### 3.3 AccumulatorState

```python
# clawcodex_ext/accumulator/state.py

@dataclass
class ThoughtRecord:
    """一次增量思考的记录。"""
    type: Literal["analysis", "summary", "question", "plan", "reflection"]
    thought: str                     # 思考内容
    chunk_index: int | None = None   # 关联到哪个片段（None=全局）
    timestamp: float = 0.0
    depth: int = 0                   # 0=主循环, 1=子代理


@dataclass
class Annotation:
    """对累积片段的一条注释。"""
    label: str                       # critical / question / summary / todo / idea
    annotation: str                  # 注释内容
    line_range: tuple[int, int] | None = None  # 行范围
    chunk_index: int = 0             # 关联到哪个片段
    timestamp: float = 0.0


@dataclass
class SubagentResult:
    """子代理在累积模式下的思考结果。"""
    agent_id: str
    agent_type: str
    directive: str                   # 分派给子代理的任务
    result_summary: str              # 子代理返回的摘要
    total_thoughts: int = 0
    completed_at: float = 0.0


@dataclass
class AccumulatorState:
    """累积模式的完整运行时状态。
    
    挂载在 ToolContext._accumulator 上，进入模式时创建，退出时销毁。
    """
    config: AccumulatorConfig
    
    # --- 累积层 ---
    chunks: list[str] = field(default_factory=list)
    metadata: list[dict] = field(default_factory=list)
    
    # --- 思考层 ---
    thoughts: list[ThoughtRecord] = field(default_factory=list)
    annotations: list[list[Annotation]] = field(default_factory=list)
    subagent_results: list[SubagentResult] = field(default_factory=list)
    last_reflection_at: int = 0      # 上次反思时的累积字符数
    
    # --- 元数据 ---
    entered_at: float = 0.0
    total_chars_received: int = 0
    flush_called: bool = False
```

### 3.4 工具接口

#### Accumulate 工具

```python
Accumulate(input_schema={
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["append", "flush"],
            "description": "append=追加内容片段, flush=完成累积并退出模式",
        },
        "chunk": {
            "type": "string",
            "description": "内容片段（action=append 时必填）",
        },
        "metadata": {
            "type": "object",
            "description": "可选元数据：{source, mime_type, language, ...}",
        },
    },
    "required": ["action"],
})
```

#### Think 工具

```python
Think(input_schema={
    "type": "object",
    "properties": {
        "thought": {
            "type": "string",
            "description": "推理内容",
        },
        "type": {
            "type": "string",
            "enum": ["analysis", "summary", "question", "plan", "reflection"],
            "description": "思考类型",
        },
        "chunk_index": {
            "type": "integer",
            "description": "关联到第几个内容片段（从0开始）",
        },
    },
    "required": ["thought"],
})
```

#### Note 工具

```python
Note(input_schema={
    "type": "object",
    "properties": {
        "annotation": {
            "type": "string",
            "description": "注释内容",
        },
        "label": {
            "type": "string",
            "enum": ["critical", "question", "summary", "todo", "idea"],
            "description": "注释标签",
        },
        "chunk_index": {
            "type": "integer",
            "description": "关联到第几个内容片段",
        },
        "line_start": {
            "type": "integer",
            "description": "起始行号（可选）",
        },
        "line_end": {
            "type": "integer",
            "description": "结束行号（可选）",
        },
    },
    "required": ["annotation"],
})
```

### 3.5 触发接口

#### 斜杠命令

```
/accumulate start [--sink memory|file|batch] [--path <path>]
                  [--no-think] [--no-reflect] [--ack none|brief|verbose]

/accumulate flush

/accumulate cancel

/accumulate status
```

#### 工具触发

```python
EnterAccumulateMode(input_schema={
    "type": "object",
    "properties": {
        "sink": {"type": "string", "enum": ["memory", "file", "batch"]},
        "path": {"type": "string"},
        "suppress_text": {"type": "boolean"},
        "enable_thinking": {"type": "boolean"},
    },
})

ExitAccumulateMode(input_schema={
    "type": "object",
    "properties": {
        "discard": {"type": "boolean", "description": "true=丢弃已累积内容"},
    },
})
```

---

## §4 实现细节

### 4.1 文件结构

```
clawcodex_ext/
  accumulator/
    __init__.py               # 导出公共 API
    interface.py              # AccumulatorSink Protocol, AccumulatorConfig
    state.py                  # AccumulatorState, ThoughtRecord, Annotation
    sinks.py                  # MemorySink, FileSink, RotatingBatchSink
    reflection.py             # 自动反思触发器
    prompt.py                 # 被动模式系统提示词模板
    hooks.py                  # post_llm 文本抑制 hook + pre_llm 反思注入 hook
  tool_system/
    tools/
      accumulate.py           # Accumulate 工具
      accumulate_mode.py      # EnterAccumulateMode / ExitAccumulateMode 工具
      think.py                # Think 工具
      note.py                 # Note 工具
  command_system/
    accumulate_command.py     # /accumulate 斜杠命令
  input_processing.py         # （扩展）自动检测触发词
```

### 4.2 文本输出抑制机制

累积模式的核心挑战是阻止模型输出文本。通过两种机制协同实现：

**机制 A — 系统提示词（主要）**：
进入模式时，系统提示词注入：

```
你现在处于「被动累积模式」。

规则：
1. 对用户输入的每段内容，只能调用 Accumulate(action="append", chunk=...) 接收
2. 在接收过程中，你可以：
   - 调用 Think 工具做内部推理
   - 调用 Note 工具对内容做注释
   - 调用 Read/Grep/Search 等工具搜索相关信息
   - 调用 Agent 工具创建子代理做并行分析
3. 禁止输出任何文本、分析、注释、问题
4. 当用户说"好了"、"处理"、"flush"时，调用 Accumulate(action="flush")
```

**机制 B — post_llm hook（保障）**：
通过 F-102 Hook 系统注册 `post_llm` hook，在模型输出后、yield 给用户前拦截文本内容：

```python
# clawcodex_ext/accumulator/hooks.py

def _post_llm_text_suppression_hook(
    assistant_messages: list[AssistantMessage],
    tool_use_blocks: list[ToolUseBlock],
    state: QueryState,
    params: QueryParams,
) -> tuple[list[AssistantMessage], list[ToolUseBlock]]:
    """在累积模式下，清除 assistant message 中的文本内容。
    
    保留 tool_use_blocks 不变，让工具调用继续执行。
    """
    accumulator = getattr(params.tool_use_context, "_accumulator", None)
    if accumulator is None or not accumulator.config.suppress_text_output:
        return assistant_messages, tool_use_blocks
    
    # 清除文本内容，但保留工具调用块
    for msg in assistant_messages:
        if isinstance(msg.content, list):
            msg.content = [
                block for block in msg.content
                if not (isinstance(block, dict) and block.get("type") == "text")
            ]
        elif isinstance(msg.content, str):
            msg.content = ""
    
    return assistant_messages, tool_use_blocks
```

### 4.3 自动反思触发器

```python
# clawcodex_ext/accumulator/reflection.py

def maybe_trigger_reflection(state: AccumulatorState) -> bool:
    """检测累积量是否达到反思阈值。
    
    当累积字符数超过上次反思时的值 + reflection_interval_chars 时，
    向模型注入反思提示（通过 pre_llm hook 注入 UserMessage）。
    
    Returns:
        是否触发了反思。
    """
    if not state.config.enable_auto_reflection:
        return False
    
    current_chars = sum(len(c) for c in state.chunks)
    if current_chars - state.last_reflection_at >= state.config.reflection_interval_chars:
        state.last_reflection_at = current_chars
        return True
    return False


def _build_reflection_prompt(state: AccumulatorState) -> str:
    """构建自动反思提示。"""
    thought_count = len(state.thoughts)
    chunk_count = len(state.chunks)
    total_chars = sum(len(c) for c in state.chunks)
    
    return (
        f"【自动反思触发】已累积 {chunk_count} 段 / {total_chars} 字符，"
        f"已有 {thought_count} 条增量思考记录。\n\n"
        "请调用 Think(type="reflection") 做阶段性元认知反思：\n"
        "1. 目前对已接收内容的理解程度如何？\n"
        "2. 是否发现了需要进一步探究的问题？\n"
        "3. 当前的心智模型是否完整？\n"
        "4. 后续内容还需要关注哪些方面？"
    )
```

### 4.4 退出时的思考摘要构建

```python
# clawcodex_ext/accumulator/state.py 或 flush 方法中

def build_thought_summary(thoughts: list[ThoughtRecord]) -> str:
    """将增量思考记录压缩为摘要，供模型在退出模式时使用。
    
    按思考类型分组，保留关键内容，剔除冗余。压缩到 2000 tokens 以内。
    """
    summary_parts = []
    
    # 按类型分组
    by_type: dict[str, list[ThoughtRecord]] = {}
    for t in thoughts:
        by_type.setdefault(t.type, []).append(t)
    
    # 输出每个类型的总结
    type_labels = {
        "analysis": "分析结论",
        "summary": "阶段性总结",
        "question": "未解问题",
        "plan": "规划",
        "reflection": "元认知反思",
    }
    
    for ttype, label in type_labels.items():
        records = by_type.get(ttype, [])
        if not records:
            continue
        summary_parts.append(f"--- {label} ({len(records)}条) ---")
        for i, r in enumerate(records[-3:], 1):  # 每种类型最多取最近3条
            chunk_ref = f" [chunk {r.chunk_index}]" if r.chunk_index is not None else ""
            summary_parts.append(f"{i}.{chunk_ref} {r.thought[:200]}")
    
    return "\n".join(summary_parts)
```

### 4.5 自动检测触发

```python
# 扩展 clawcodex_ext/command_system/input_processing.py

_ACCUMULATION_TRIGGERS = [
    "我要粘贴", "我贴一段", "以下内容", "接下来是",
    "别回答", "不要回复", "只听", "先别处理",
    "我来贴", "我分段贴",
    "I'll paste", "don't answer", "listen only", "accumulate",
    "just listen", "silent mode",
]

_ACCUMULATION_BOUNDARY_PATTERN = re.compile(
    r"(?:累积模式|accumulate|accumulation)(?:\s*[:：])?\s*"
    r"(?P<action>start|flush|cancel|status)"
    r"(?:\s+--sink\s+(?P<sink>memory|file|batch))?"
    r"(?:\s+--path\s+(?P<path>\S+))?"
)


def is_accumulation_triggered(text: str) -> bool:
    """检测用户是否在暗示要进入累积模式。"""
    return any(t in text.lower() for t in _ACCUMULATION_TRIGGERS)


def parse_accumulation_intent(text: str) -> AccumulationIntent | None:
    """解析累积模式相关的结构化意图。"""
    m = _ACCUMULATION_BOUNDARY_PATTERN.search(text)
    if m:
        return AccumulationIntent(
            action=m.group("action") or "start",
            sink=m.group("sink") or "memory",
            path=m.group("path"),
        )
    return None
```

---

## §5 使用场景

### 5.1 文档审查

```
用户: /accumulate start --sink file --path ./review_input.txt
系统: 进入累积模式。

用户: [粘贴 src/main.py 代码]
  模型: Accumulate(chunk="...") ✓ 已接收。
  模型: Think(type="analysis", thought="入口函数结构清晰，但错误处理不完整...")
  模型: Note(label="critical", annotation="第45行可能引起空指针异常", chunk_index=0, line_start=45)

用户: [粘贴 src/utils.py 代码]
  模型: Accumulate(chunk="...") ✓ 已接收。
  模型: Think(type="analysis", thought="utils 层功能单一，但缺少单元测试...")
  模型: Agent(fork, "分析 utils.py 的依赖关系")

用户: [粘贴 tests/test_main.py]
  模型: Accumulate(chunk="...") ✓ 已接收。
  模型: Think(type="summary", thought="测试覆盖了主流程，但边界用例不足...")

用户: /accumulate flush
  模型: 输出统一代码审查报告：
        ## 代码审查报告
        ### 严重问题（3个）
        - main.py:45 空指针风险
        - ...
        ### 改进建议（5条）
        - utils.py 缺少单元测试
        - ...
```

### 5.2 批量翻译

```
用户: 累积模式 start --sink batch --path ./translations
系统: 进入累积模式。
用户: [粘贴 20 条待翻译句子]
  模型: Accumulate(chunk="句子1\n句子2\n...") ✓ 已接收。
  模型: Think(type="plan", thought="领域术语较多，需要先建立术语表...")
  模型: Think(type="question", thought="'context window' 在本场景中应译为什么？")
用户: "技术文档"
  模型: Note(label="idea", annotation="术语表建议：context window→上下文窗口")
用户: /accumulate flush
  模型: 输出完整翻译 + 术语表
```

### 5.3 日志分析

```
用户: /accumulate start --sink batch --path ./logs
用户: [粘贴 1000 行日志]
  模型: Accumulate(chunk="...") ✓ 已接收。
  模型: Think(type="analysis", thought="大量 500 错误集中在 /api/order 端点...")
  模型: Grep("ERROR") → 内部搜索
  模型: Think(type="reflection", thought="错误模式似乎与数据库连接池相关...")
用户: [粘贴更多日志]
  模型: Accumulate(chunk="...") ✓ 已接收。
  模型: Think(type="summary", thought="确认错误与连接池耗尽相关，共 47 次...")
用户: /accumulate flush
  模型: 输出错误分析报告 + 修复建议
```

---

## §6 与现有模式的关系

### 6.1 与 plan_mode 的关系

| 模式 | 行为 | 累积模式叠加后 |
|------|------|--------------|
| **正常模式** | 回答所有问题 | 累积模式切换为"只听不说" |
| **plan_mode** | 禁止写操作，只读 | 可同时累积 + 只读浏览 |
| **auto_mode** | 自动执行工具 | 累积模式下自动执行但静默 |

**兼容性矩阵**：

```
                    plan_mode=False    plan_mode=True
                    ─────────────────────────────────
accumulate=False    │ 正常回答         │ 规划模式
                    │ 文本输出可见      │ 文本输出可见
                    │ 所有工具可用      │ 只读工具
                    ─────────────────────────────────
accumulate=True     │ 静默累积         │ 静默规划
                    │ 文本输出抑制      │ 文本输出抑制
                    │ 所有工具可用      │ 只读工具
                    │ 增量思考可见      │ 增量思考可见
```

### 6.2 与 F-166 记忆分层的集成（远期）

退出累积模式时，可以将思考日志选择性写入 Episodic Memory：

```python
# 退出时可选集成
if integration_with_f166:
    for thought in state.thoughts:
        f166_episodic_memory.write(
            content=thought.thought,
            metadata={
                "type": f"accumulate_thought_{thought.type}",
                "chunk_count": len(state.chunks),
                "total_chars": state.total_chars_received,
            }
        )
```

---

## §7 风险与约束

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| **模型不遵守"不输出文本"规则** | 偶尔仍会输出文本 | post_llm hook 作为保障机制（§4.2 机制 B） |
| **Think 工具被滥用** | 模型过度调用 Think 而非 Accumulate | 设置 Think 调用频率限制 + 系统提示词强调优先级 |
| **累积内容过大** | 内存 / 上下文溢出 | sink 支持文件持久化 + max_chunks 限制 |
| **子代理思考结果丢失** | 子代理返回时主循环已退出 | 子代理结果写入 AccumulatorState 而非直接返回 |
| **与 plan_mode 语义冲突** | 用户不清楚两模式叠加效果 | 清晰的兼容性矩阵 + 状态提示 |
| **自动反思注入时机不当** | 打断用户输入节奏 | 在用户输入之间而非之中触发 |

---

## §8 验收标准

| 编号 | 验收条件 | 验证方式 |
|:----:|---------|---------|
| AC-01 | 用户输入 `/accumulate start` 后进入累积模式，模型不再输出文本 | 手动测试 |
| AC-02 | 累积模式下，模型可调用 `Accumulate` 工具接收内容 | 手动测试 |
| AC-03 | 累积模式下，模型可调用 `Think` 工具记录增量思考 | 手动测试 |
| AC-04 | 累积模式下，模型可调用 `Note` 工具对片段做注释 | 手动测试 |
| AC-05 | 累积模式下，模型仍可调用其他工具（Read/Grep/Search/Agent） | 手动测试 |
| AC-06 | 用户输入 `/accumulate flush` 后，模型输出统一分析报告 | 手动测试 |
| AC-07 | 用户输入 `/accumulate cancel` 后，丢弃已累积内容，退出模式 | 手动测试 |
| AC-08 | 累积量达到 5000 字符时触发自动反思 | 集成测试 |
| AC-09 | 退出模式时，思考摘要包含所有增量思考的压缩信息 | 单元测试 |
| AC-10 | 累积模式与 plan_mode 正交兼容（可同时激活） | 集成测试 |
| AC-11 | 自动检测触发：用户输入"别回答，我贴一段代码"后自动进入模式 | 手动测试 |
| AC-12 | 三种 Sink 实现均正常工作：MemorySink / FileSink / RotatingBatchSink | 单元测试 |
| AC-13 | 斜杠命令 `/accumulate status` 显示当前累积状态（段数、字符数、思考数） | 手动测试 |

---

## §9 实施计划

| 阶段 | 子特性 | 预估工时 | 依赖 |
|:----:|--------|:--------:|:----:|
| **Phase 1: 核心基础设施** | P168-A + P168-E | 2-3d | ToolContext |
| **Phase 2: 核心工具** | P168-B + P168-C + P168-D | 2-3d | Phase 1 |
| **Phase 3: 触发方式** | P168-F + P168-G | 1-2d | Phase 2 |
| **Phase 4: 思考增强** | P168-H + P168-I | 2-3d | Phase 2 |
| **Phase 5: 输出 & 集成** | P168-J + 测试 | 1-2d | Phase 4 |

**总计**: ~8-13 个工作日

---

## §10 附录

### 10.1 系统提示词模板（完整版）

```markdown
## 被动累积模式

你现在处于「被动累积模式」。

### 你的任务
接收用户粘贴的内容，**不做任何文本回复**。你只能通过工具来响应。

### 可用工具（按优先级排序）

1. **Accumulate** — 接收内容片段（必选）
   - 用户每粘贴一段内容，调用 `Accumulate(action="append", chunk=...)`
   - 用户说"好了"、"处理"、"flush"时，调用 `Accumulate(action="flush")`

2. **Think** — 内部推理（可选但推荐）
   - 每次收到新内容后，调用 `Think(type="analysis", thought=...)` 做分析
   - 阶段性总结用 `type="summary"`
   - 有疑问用 `type="question"`
   - 规划下一步用 `type="plan"`

3. **Note** — 对特定内容做注释（可选）
   - critical: 关键问题
   - question: 有待确认
   - summary: 片段摘要
   - todo: 需要处理
   - idea: 想法

4. **其他工具** — 正常使用（Read/Grep/Search/Agent 等）

### 禁止行为
- ❌ 禁止输出任何文本、分析、注释、问题
- ❌ 禁止对用户输入做任何文本性回复
- ❌ 禁止在接收到新内容时询问用户"是否继续"

### 自动反思
当累积量达到阈值时，系统会提示你做阶段性反思。
调用 `Think(type="reflection")` 记录你的元认知思考。

### 退出模式
当用户说"处理"、"好了"、"flush"或调用 `Accumulate(action="flush")` 时：
1. 先调用 `Accumulate(action="flush")` 完成累积
2. 然后基于全部累积内容 + 所有增量思考记录，输出统一的分析报告
```