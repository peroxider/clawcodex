# F-123: Intent Forecast 空闲意图预测

> 状态: 📋 规划中  
> 章节: `docs/feature_plan/03-agent-core/f-123-intent-forecast.md`  
> 最后更新: 2026-07-01  
> 关联能力: Away Summary, Dreaming, SessionStorage, TUI/REPL, CLI subcommands

---

## §1 设计规划

### 1.1 背景与目标

当用户打开 ClawCodex 的 REPL/TUI 后，如果短时间内没有输入，系统可以根据历史会话、项目记忆文件和当前工作区状态，预测用户可能想继续做的下一步，并以低打扰方式给出可采纳的任务选项。

该能力不是让 agent 主动开始执行工作，而是提供一个可确认的“下一步建议”。用户采纳后，建议会被转换成普通 prompt 进入既有任务执行路径。

核心目标:

1. **2 分钟空闲后预测下一步**: 用户打开 REPL/TUI 后，若 2 分钟内没有任何输入操作、agent 不忙、输入框为空，则触发 intent forecast。
2. **低打扰展示**: 预测结果使用与 Away Summary 一致的浅色系统提示风格，避免强制弹窗打断用户。
3. **显式采纳才执行**: 用户选择某个建议后，才把对应 prompt 提交给 agent。
4. **用户输入优先**: 预测过程中一旦用户输入或提交任何指令，当前预测任务立即作废。
5. **逐步学习偏好**: 用户采纳/忽略/拒绝的行为写入 feedback，用于后续排序和提示词强化。
6. **Slash 与 CLI 同名**: 对外统一命名为 `forecast`，提供 `/forecast` 与 `clawcodex forecast`。
7. **会话摘要异步维护**: `summary.json` 作为 session intelligence sidecar，不阻塞 REPL/TUI 退出。

### 1.2 命名

用户可见命名统一为 **forecast**:

| Surface | 命名 | 说明 |
|------|------|------|
| Slash command | `/forecast` | 交互式预测、采纳、状态查看 |
| CLI | `clawcodex forecast` | 非交互预测、JSON 输出、补摘要、统计 |
| 配置键 | `intent_forecast` | 语义清晰，避免与普通 forecast 混淆 |
| 内部模块 | `clawcodex_ext/intent_forecast/` | 表达该能力是“用户意图预测” |

推荐命令:

```text
/forecast
/forecast run
/forecast accept 1
/forecast dismiss
/forecast status
/forecast on
/forecast off

clawcodex forecast
clawcodex forecast run
clawcodex forecast --json
clawcodex forecast status
clawcodex forecast accept <id>
clawcodex forecast summarize --session <session_id>
clawcodex forecast stats
```

### 1.3 触发规则

Intent Forecast 的自动触发条件:

| 条件 | 要求 |
|------|------|
| 空闲时间 | 默认 `120s`，即 2 分钟 |
| agent 状态 | 当前没有运行中的 agent turn |
| 输入框状态 | draft 为空 |
| 会话状态 | 当前 REPL/TUI 已完成 mount |
| 去重 | 同一 workspace + conversation fingerprint 不重复提示 |
| 配置 | `settings.intent_forecast.enabled != false` |

取消条件:

| 用户行为 | 处理 |
|------|------|
| PromptInput draft 从空变非空 | 取消当前 timer 或废弃运行中的预测结果 |
| 提交普通 prompt | 取消预测，并按用户真实输入执行 |
| 执行 slash command | 取消预测 |
| 执行 `!command` | 取消预测 |
| ESC / Ctrl+C 等明确交互 | 取消预测 |
| agent run start | 取消预测 |

设计原则: **真实用户输入永远优先于系统猜测**。如果 provider 调用无法底层中断，也必须在返回后通过 generation token 丢弃过期结果。

### 1.4 总体架构

```text
REPL/TUI
  ├─ IntentForecastController
  │    ├─ on_user_interaction()
  │    ├─ on_run_start()
  │    ├─ on_run_finish()
  │    └─ idle timer: 120s
  │
  ├─ IntentForecastService
  │    ├─ collect context
  │    ├─ call provider
  │    └─ parse/rank suggestions
  │
  ├─ Forecast display
  │    ├─ light system message
  │    ├─ selectable options
  │    └─ accept -> submit_to_agent(prompt)
  │
  └─ Learning feedback
       ├─ accepted
       ├─ dismissed
       └─ stale/cancelled
```

建议模块:

```text
clawcodex_ext/intent_forecast/
  __init__.py
  config.py              # enabled, idle_seconds=120, max_sessions, token limits
  context.py             # 收集 sessions / memory files / workspace signals
  prompt.py              # 构造 forecast prompt
  service.py             # provider 调用、JSON 解析、fallback
  controller.py          # idle timer、generation token、取消逻辑
  messages.py            # 显示文本、系统消息、候选序列化
  learning.py            # feedback.jsonl 写入与排序偏好
  command.py             # /forecast
  cli.py                 # clawcodex forecast

clawcodex_ext/session_intelligence/
  summary_schema.py      # summary.json schema
  summarizer.py          # 异步/懒生成 summary
  queue.py               # enqueue + pending/status 文件
  index.py               # metadata/summary 快速检索
```

### 1.5 输入信号

Forecast 上下文按优先级收集:

| 层级 | 来源 | 说明 |
|------|------|------|
| 当前会话 | conversation 最近消息、last_user_input、queued prompts | 识别当前正在进行的工作 |
| 历史会话 | `~/.clawcodex/sessions/*/{metadata.json,summary.json,transcript.jsonl}` | 优先同 cwd、最近更新、标题/输入相似 |
| 记忆文件 | `CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.md`, `CLUDE.md`, `.clawcodex/*` | `CLUDE.md` 作为用户拼写/其他 agent 记忆文件兼容项 |
| 工作区 | `git status --short`, `git diff --stat`, 最近修改文件、README/pyproject/package | 判断未完成实现、测试、文档变更 |
| 学习反馈 | `~/.clawcodex/intent_forecast/feedback.jsonl` | 强化被采纳的意图模式，降低被忽略模式 |

必须限制 I/O 成本:

- session 召回先读 metadata/index，不全量扫描 transcript。
- 最多选取最近/最相关 N 个 session。
- transcript 只读头尾和最近 user turns；长会话优先依赖 `summary.json`。
- 缺失或损坏的历史数据跳过，不影响预测。

### 1.6 输出格式

LLM 输出应使用严格 JSON，便于 TUI/CLI 共享:

```json
{
  "suggestions": [
    {
      "id": "forecast-...",
      "title": "完善 Intent Forecast 设计文档",
      "prompt": "请基于当前仓库结构，为 Intent Forecast 功能补充设计文档并列出实现步骤。",
      "reason": "近期会话多次讨论 TUI idle、Away Summary 和 session storage。",
      "confidence": 0.74,
      "source_refs": ["session:<id>", "file:CLAUDE.md", "git:modified-files"]
    }
  ]
}
```

显示文案示例:

```text
Forecast

1. 完善 Intent Forecast 设计文档
   近期会话和当前工作区都指向这条功能规划。

2. 实现 /forecast 与 CLI 接口
   命名已收敛，可以先落地命令入口。

Enter 采纳 · ↑/↓ 选择 · Esc 忽略
```

### 1.7 用户输入期间丢弃预测

预测任务必须携带 generation token:

```text
idle timer fires
  -> generation_id = 42
  -> start forecast worker

user types/submits/cancels
  -> generation_id += 1
  -> cancel timer
  -> mark running worker stale

forecast returns
  -> if generation_id != 42: discard silently
  -> else display suggestions
```

这条规则是硬约束。即使实际 provider request 无法取消，也必须在 UI 层丢弃结果，避免“用户已经说话，系统还弹出旧猜测”的打扰。

### 1.8 Session Summary Sidecar

`summary.json` 是独立于 `metadata.json` 的 session intelligence sidecar，不建议把大块 summary 写入 metadata。

原因:

- `metadata.json` 当前用于 session list 快速展示，应该保持轻量。
- `summary.json` 可能包含 goals、open_threads、commands、preferences 等结构化内容，体积和更新频率不同。
- sidecar 可以懒生成、重试、损坏隔离，不影响 `/resume` 和基础持久化。

推荐路径:

```text
~/.clawcodex/sessions/<session_id>/
  metadata.json
  transcript.jsonl
  summary.json
  summary.status.json
```

`summary.json` 示例:

```json
{
  "schema_version": 1,
  "session_id": "...",
  "cwd": "C:/WorkSpace/clawcodex",
  "updated_at": 1782890000,
  "transcript_mtime": 1782890000,
  "title": "TUI idle intent forecast design",
  "goals": ["设计 idle 后的下一步建议功能"],
  "completed": ["调研 Away Summary 和 SessionStorage"],
  "open_threads": ["实现 /forecast command", "异步生成 summary.json"],
  "files_touched": ["clawcodex_ext/tui/app.py", "clawcodex_ext/away_summary/controller.py"],
  "commands_seen": ["rg", "pytest tests/away_summary"],
  "user_preferences": ["命令与 CLI 同名", "预测时用户输入即作废"],
  "next_action_candidates": ["实现 IntentForecastController"]
}
```

`summary.status.json` 示例:

```json
{
  "state": "pending",
  "transcript_mtime": 1782890000,
  "attempts": 0,
  "last_error": "",
  "updated_at": 1782890000
}
```

### 1.9 Summary 写入时机

`summary.json` 生成不能阻塞 REPL/TUI 退出。退出路径只允许做轻量 enqueue。

推荐写入策略:

| 时机 | 行为 | 是否阻塞用户 |
|------|------|:----:|
| agent turn finish | 若会话发生明显变化，后台低优先级刷新 summary | 否 |
| Away Summary 成功生成 | 将 recap 作为输入，异步更新结构化 summary | 否 |
| REPL/TUI exit/save | 只写 pending/status 或 queue 记录，立即退出 | 否 |
| 下次启动 | 扫描 pending queue，补生成缺失/过期 summary | 否 |
| `/forecast` 需要时 | 缺失则 fallback；高相关会话可顺手 enqueue lazy summarize | 否 |
| `clawcodex forecast summarize --session` | 手动同步或后台生成 | CLI 可控 |

退出时推荐流程:

```text
TUI/REPL exit
  -> flush metadata/transcript
  -> enqueue summary job
  -> optionally spawn background worker
  -> return to shell immediately
```

队列路径可选:

```text
~/.clawcodex/session_summaries/queue.jsonl
```

或每个 session 写:

```text
~/.clawcodex/sessions/<session_id>/summary.status.json
```

生成成功时必须原子替换:

```text
summary.json.tmp -> summary.json
```

### 1.10 summary.json 缺失时的 forecast 策略

Forecast 不得依赖 `summary.json` 必然存在。

fallback 分层:

```text
summary.json 存在且 schema_version 合法
  -> 直接使用

summary.json 不存在，但 metadata.json 存在
  -> 用 metadata 快速召回，再读取 transcript 尾部 N 条

metadata/transcript 异常
  -> 忽略该 session

session 高相关但无 summary
  -> enqueue lazy summarize，供下次使用
```

当前预测不等待所有 summary 补齐。缺失 summary 是性能退化，不是功能失败。

### 1.11 学习与强化

用户行为写入:

```text
~/.clawcodex/intent_forecast/feedback.jsonl
```

事件示例:

```json
{
  "event": "accepted",
  "suggestion_id": "forecast-...",
  "cwd": "C:/WorkSpace/clawcodex",
  "title": "实现 /forecast command",
  "prompt": "请实现 /forecast slash command 与 clawcodex forecast CLI。",
  "confidence": 0.76,
  "features": {
    "matched_recent_session": true,
    "matched_memory_file": true,
    "dirty_worktree": true
  },
  "created_at": 1782890000
}
```

学习方式:

- accepted: 相似 cwd、文件、标题、会话主题加权。
- dismissed: 同 fingerprint 短期内降权，避免重复打扰。
- stale/cancelled: 不视为负反馈，仅记录系统预测被真实输入替代。
- rejected: 明确拒绝时降低相似模式权重。

---

## §2 子特性拆分

| 编号 | 子特性 | 状态 | 优先级 | 依赖 |
|:----:|------|:----:|:------:|------|
| F-123-A | `IntentForecastConfig` + settings 读取，默认 `idle_seconds=120` | 📋 | P0 | 无 |
| F-123-B | `IntentForecastController` idle timer + generation token + 取消逻辑 | 📋 | P0 | F-123-A |
| F-123-C | `IntentForecastContextBuilder` 收集 session/memory/workspace/feedback 信号 | 📋 | P0 | F-123-A |
| F-123-D | `IntentForecastService` provider 调用 + JSON 解析 + fallback | 📋 | P0 | F-123-C |
| F-123-E | TUI/REPL 显示与采纳交互，浅色系统提示 | 📋 | P0 | F-123-B/D |
| F-123-F | `/forecast` slash command | 📋 | P0 | F-123-D/E |
| F-123-G | `clawcodex forecast` CLI，同名语义 | 📋 | P0 | F-123-D |
| F-123-H | `feedback.jsonl` 学习记录与排序加权 | 📋 | P1 | F-123-D/F |
| F-123-I | `summary.json` schema + async queue + lazy summarize | 📋 | P1 | SessionStorage |
| F-123-J | Away Summary -> structured summary 异步更新桥接 | 📋 | P2 | F-123-I |
| F-123-K | 测试与稳定性门禁 | 📋 | P0 | 全部 P0 |

---

## §3 实施细节

### 3.1 新建文件

| 文件 | 子特性 | 说明 |
|------|:------:|------|
| `clawcodex_ext/intent_forecast/config.py` | F-123-A | 配置读取 |
| `clawcodex_ext/intent_forecast/controller.py` | F-123-B | idle timer 与取消 |
| `clawcodex_ext/intent_forecast/context.py` | F-123-C | 输入信号收集 |
| `clawcodex_ext/intent_forecast/prompt.py` | F-123-D | prompt 构造 |
| `clawcodex_ext/intent_forecast/service.py` | F-123-D | LLM 调用和解析 |
| `clawcodex_ext/intent_forecast/messages.py` | F-123-E | 展示格式和候选模型 |
| `clawcodex_ext/intent_forecast/learning.py` | F-123-H | feedback 写入/读取 |
| `clawcodex_ext/intent_forecast/command.py` | F-123-F | `/forecast` |
| `clawcodex_ext/intent_forecast/cli.py` | F-123-G | `clawcodex forecast` |
| `clawcodex_ext/session_intelligence/summary_schema.py` | F-123-I | `summary.json` schema |
| `clawcodex_ext/session_intelligence/summarizer.py` | F-123-I | 摘要生成 |
| `clawcodex_ext/session_intelligence/queue.py` | F-123-I | pending queue |
| `clawcodex_ext/session_intelligence/index.py` | F-123-I | summary/metadata 检索 |

### 3.2 修改文件

| 文件 | 子特性 | 改动 |
|------|:------:|------|
| `clawcodex_ext/tui/app.py` | F-123-B/E | 安装 controller；submit/cancel/run start/run finish 时通知 |
| `clawcodex_ext/tui/screens/repl.py` | F-123-E | PromptInput 交互时取消预测；采纳选项提交到 agent |
| `clawcodex_ext/repl/core.py` 或 `clawcodex_ext/repl/app.py` | F-123-B/E | legacy REPL 接入 |
| `clawcodex_ext/command_system/builtins.py` | F-123-F | 注册 `/forecast` |
| `clawcodex_ext/tui/commands.py` | F-123-F | TUI private registry 注册 |
| `clawcodex_ext/cli/subcommand_registry.py` | F-123-G | 注册 `forecast` 子命令 |
| `clawcodex_ext/away_summary/service.py` | F-123-J | Away Summary 成功后 enqueue structured summary |
| `clawcodex_ext/services/session_persistence.py` | F-123-I | flush/exit 时 enqueue summary job，不阻塞 |

### 3.3 配置

建议 settings:

```json
{
  "intent_forecast": {
    "enabled": true,
    "idle_seconds": 120,
    "max_sessions": 12,
    "max_transcript_tail_messages": 12,
    "max_input_tokens": 16000,
    "max_output_tokens": 800,
    "min_confidence": 0.45,
    "auto_display": true,
    "feedback_enabled": true,
    "summary_lazy_generate": true
  }
}
```

### 3.4 Controller 接口草案

```python
@dataclass
class IntentForecastController:
    provider_getter: Callable[[], Any]
    model_getter: Callable[[], str | None]
    session_getter: Callable[[], Any | None]
    workspace_root: Path
    display: Callable[[ForecastResult], None]
    submit: Callable[[str], None]
    config_loader: Callable[[], IntentForecastConfig]

    def on_user_interaction(self, reason: str = "user") -> None: ...
    def on_prompt_draft_changed(self, text: str) -> None: ...
    def on_run_start(self) -> None: ...
    def on_run_finish(self) -> None: ...
    def on_mount(self) -> None: ...
    def close(self) -> None: ...
```

### 3.5 Service 接口草案

```python
@dataclass(frozen=True)
class ForecastSuggestion:
    id: str
    title: str
    prompt: str
    reason: str
    confidence: float
    source_refs: list[str]

@dataclass(frozen=True)
class ForecastResult:
    generated: bool
    suggestions: list[ForecastSuggestion]
    reason: str = ""
    fingerprint: str = ""

class IntentForecastService:
    def generate(self, *, trigger: str, force: bool = False) -> ForecastResult:
        ...
```

---

## §4 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 预测打扰用户 | UX 下降 | 2 分钟只在完全空闲触发；用户输入即废弃 |
| 退出变慢 | 用户误以为卡死 | 退出只 enqueue summary job，不做 LLM 调用 |
| 历史会话过多 | I/O 慢、token 高 | metadata/index 先召回，限制 N，summary 缺失 fallback |
| 预测不准 | 用户不信任 | 采纳/忽略 feedback 加权；低 confidence 不展示 |
| summary 写入竞态 | 文件损坏 | status lock + tmp 原子替换 |
| 隐私担忧 | 历史会话被自动读取 | 默认只读本地；配置可关闭；CLI/status 明示使用来源 |
| 与 Away Summary 重复 | 功能边界混乱 | Away Summary 面向“回顾”；Forecast 面向“下一步候选”；summary.json 为机器可读 sidecar |

---

## §5 验收标准

1. REPL/TUI 打开后，用户 2 分钟无输入且 agent idle，会自动生成 forecast。
2. 用户在预测运行中输入任何内容，预测结果不会展示。
3. `/forecast` 与 `clawcodex forecast` 命名一致，子命令语义一致。
4. 采纳建议后，候选 prompt 进入现有 `submit_to_agent()` 路径。
5. 采纳/忽略/过期事件写入 `feedback.jsonl`。
6. 退出 REPL/TUI 不等待 `summary.json` 生成。
7. `summary.json` 缺失时 forecast 仍可用，并采用 metadata + transcript tail fallback。
8. `summary.json` 写入使用 tmp 原子替换，失败只记录 status，不影响会话。
9. 浅色显示风格与 Away Summary 保持一致。

---

## §6 测试计划

| 测试文件 | 覆盖 |
|------|------|
| `tests/intent_forecast/test_config.py` | 默认 120s、settings 覆盖、禁用 |
| `tests/intent_forecast/test_controller.py` | idle arm、user interaction cancel、generation token stale discard |
| `tests/intent_forecast/test_context.py` | session 召回、memory file 读取、workspace signal |
| `tests/intent_forecast/test_service.py` | JSON 解析、fallback、低 confidence 过滤 |
| `tests/intent_forecast/test_learning.py` | feedback 写入和排序加权 |
| `tests/intent_forecast/test_command.py` | `/forecast run/status/accept/dismiss/on/off` |
| `tests/intent_forecast/test_cli.py` | `clawcodex forecast` 子命令 |
| `tests/session_intelligence/test_summary_queue.py` | enqueue、status、原子写、失败重试 |
| `tests/tui/test_intent_forecast_frontend_wiring.py` | TUI idle 显示、采纳提交、输入取消 |

---

## §7 进度跟踪

### 7.1 当前瓶颈

- 尚未实现 `clawcodex_ext/intent_forecast/` 模块。
- TUI PromptInput 需要暴露 draft changed 或 key interaction 事件，供 controller 取消预测。
- Session summary 异步队列需要与现有 SessionStorage 保存路径保持解耦。

### 7.2 下一步计划

| Phase | 内容 | 子特性 | 预计工时 |
|:----:|------|:------:|:--------:|
| Phase 1 | config + controller + stale discard 单测 | F-123-A/B/K | 1-2d |
| Phase 2 | context builder + service + prompt | F-123-C/D/K | 2-3d |
| Phase 3 | TUI/REPL display + accept flow | F-123-E/K | 2d |
| Phase 4 | `/forecast` + `clawcodex forecast` | F-123-F/G/K | 1-2d |
| Phase 5 | feedback learning | F-123-H/K | 1d |
| Phase 6 | session summary sidecar + async queue | F-123-I/K | 2-3d |
| Phase 7 | Away Summary bridge + polish | F-123-J/K | 1d |

---

## §8 意图预测准确率增强规划

本节是在基础 Intent Forecast 能力之上的增强规划，目标是让系统不只是“根据上下文猜一句 prompt”，而是能理解当前任务状态、用户偏好、真实执行进展和历史反馈，从而预测更贴近用户下一步需求的动作。增强项按推荐落地优先级排列。

### 8.1 任务状态模型

**目标**: 将上下文从原始片段升级为结构化任务状态，减少仅靠最近消息和历史摘要推断带来的漂移。

**新增状态字段**:

| 字段 | 含义 | 主要来源 |
|------|------|------|
| `active_goal` | 当前最可能正在推进的目标 | 最近用户消息、session summary、goal controller、工作区 diff |
| `last_completed_step` | agent 或用户最近已经完成的步骤 | 最近 assistant 消息、tool result、测试输出 |
| `next_unfinished_step` | 当前目标下尚未完成的下一步 | session summary、diff、失败命令、TODO |
| `blocked_reason` | 当前是否被错误、权限、缺少信息、测试失败阻塞 | tool result、terminal/test output、permission event |
| `pending_tests` | 修改后尚未运行或失败的测试集合 | changed_files、pytest output、测试文件映射 |
| `open_questions` | 仍需向用户确认的问题 | 最近 ask-user、assistant 提问、未回答问题 |
| `recent_decisions` | 用户最近明确表达的偏好或决策 | user turns、memory files、feedback |

**实现入口**:

- 在 `IntentForecastContextBuilder.build()` 中新增 `task_state` 字段。
- 新增 `clawcodex_ext/intent_forecast/task_state.py`，负责从 conversation、workspace、session summary、tool result 中提取状态。
- `ForecastContext.to_prompt_dict()` 将 `task_state` 放在 `current_messages` 之后，提示词中明确要求优先依据 `task_state`。

**验收标准**:

1. 当最近一轮已完成实现但未运行测试时，forecast 优先建议运行相关测试。
2. 当最近一轮测试失败时，forecast 优先建议修复失败点，而不是继续新增功能。
3. 当 assistant 刚提出澄清问题且用户未回答时，forecast 不建议擅自继续实现。

### 8.2 用户当前意图阶段分类

**目标**: 在生成候选建议前先判断用户处于哪种工作阶段，避免历史会话或工作区信号把预测带偏。

**意图阶段枚举**:

| 阶段 | 典型下一步 |
|------|------|
| `explore` | 继续阅读代码、总结架构、定位入口 |
| `plan` | 细化方案、拆分任务、确认风险 |
| `implement` | 修改代码、补功能、接线 |
| `test` | 运行 focused tests、修复失败测试 |
| `debug` | 根据错误栈定位原因、验证假设 |
| `review` | 做代码审查、找风险、补测试 |
| `document` | 更新文档、写使用说明、补计划 |
| `commit` | 查看 diff、整理提交、生成 PR 信息 |
| `pause` | 不主动建议动作或仅提供低打扰恢复入口 |

**实现入口**:

- 新增 `intent_stage` 到 `ForecastContext`。
- 在 provider prompt 前增加轻量规则分类；必要时允许 LLM 同时返回 `stage` 与 suggestions。
- `fallback_suggestions()` 根据 `intent_stage` 选择不同策略库，而不是只按最近用户消息和 dirty worktree 兜底。

**验收标准**:

1. 用户明确要求“查看/分析/评估”时，不预测成“直接实现”。
2. 工作区有代码变更但最近用户要求“写文档”时，优先文档建议。
3. 测试失败后进入 `debug` 或 `test` 阶段，建议围绕失败点。

### 8.3 反馈学习特征化

**目标**: 将 feedback 从标题级加权升级为特征级学习，使系统学到用户在不同场景下更愿意采纳哪类建议。

**新增反馈特征**:

| 特征 | 示例 |
|------|------|
| `stage` | `implement`、`test`、`review` |
| `focus_ids` | `intent_forecast`、`tui`、`tests` |
| `changed_file_globs` | `clawcodex_ext/intent_forecast/*.py` |
| `suggestion_kind` | `run_tests`、`fix_failure`、`continue_impl`、`write_docs` |
| `has_dirty_worktree` | `true`/`false` |
| `had_recent_failure` | `true`/`false` |
| `language` | `Chinese`、`English` |
| `trigger` | `auto`、`slash`、`cli` |

**实现入口**:

- `record_feedback()` 写入 `features` 时由 service/controller 填充。
- `feedback_weight()` 增加基于特征相似度的权重，而不是只匹配 title。
- 对同一 fingerprint 的 dismiss 继续短期降权，对跨 fingerprint 的 accepted 做弱正向迁移。

**验收标准**:

1. 用户多次采纳“修改测试后运行 focused tests”后，相似场景中测试建议排序提升。
2. 用户多次忽略“泛泛 review 当前 changes”后，相似泛化建议排序下降。
3. 不同 cwd 的反馈默认不互相强影响，只在同类项目特征高度相似时弱迁移。

### 8.4 采纳后的结果闭环

**目标**: 单纯 `accepted` 不等于预测正确。需要追踪采纳后的执行结果，判断建议是否真正帮用户达成目标。

**新增事件**:

| 事件 | 含义 |
|------|------|
| `accepted_started` | 用户采纳建议并提交给 agent |
| `accepted_completed` | 采纳后的 agent turn 正常完成，且未被用户立即纠正 |
| `accepted_aborted` | 采纳后用户取消或中断 |
| `accepted_corrected` | 用户采纳后马上表达“不是这个/方向不对/改成...” |
| `accepted_followup` | 采纳后用户继续沿该方向追问或要求扩展 |

**实现入口**:

- `IntentForecastController.accept()` 记录 `accepted_started`。
- 在 run finish、cancel、用户下一条输入处，根据时间窗口和文本信号补写结果事件。
- 反馈权重优先使用完成类事件，弱化只点击但没有完成的事件。

**验收标准**:

1. 被采纳但马上取消的建议不会长期加权。
2. 被采纳并顺利完成的建议获得更高正向权重。
3. 用户采纳后立刻纠正方向时，同类建议后续降权。

### 8.5 历史 session 相关性召回

**目标**: 历史会话不应只按最近 N 个进入上下文，而应先按当前任务相关性排序，避免近期但无关的 session 污染预测。

**相关性信号**:

| 信号 | 权重建议 |
|------|:------:|
| `cwd` 完全一致 | 高 |
| `files_touched` 与 `changed_files` 重叠 | 高 |
| session title/summary 与 recent user text 相似 | 中高 |
| `next_action_candidates` 与当前 focus 匹配 | 中高 |
| 最近更新时间 | 中 |
| tags/model 等弱上下文 | 低 |

**实现入口**:

- 新增 `session_retrieval.py`，封装 session 打分和裁剪。
- `IntentForecastContextBuilder._sessions()` 先读取轻量 metadata/index，再只对 top K 读取 summary/tail。
- `summary.json` schema 中优先使用 `files_touched`、`commands_seen`、`next_action_candidates`。

**验收标准**:

1. 当前修改 `intent_forecast` 文件时，历史 orchestrator 会话不会排在相关 intent forecast 会话前。
2. 相同 cwd 但主题完全不同的 session 不应进入 top 3。
3. 没有 summary 时仍可使用 metadata + transcript tail fallback。

### 8.6 Workspace 信号增强

**目标**: 让 forecast 更准确理解当前代码状态，而不是只知道“有文件变更”。

**新增信号**:

| 信号 | 用途 |
|------|------|
| `git_branch` | 判断是否处于 feature/fix/release 分支 |
| `git_diff_names` | 比 diff stat 更稳定地获得文件列表 |
| `diff_hunks_summary` | 提取每个文件改动主题，控制长度 |
| `last_command` / `last_command_exit` | 判断用户刚运行过什么、是否失败 |
| `last_test_failures` | 预测修复失败测试或重跑测试 |
| `changed_test_mapping` | 源文件变更对应测试文件 |
| `untracked_files` | 新增文件是否还未接线或测试 |

**实现入口**:

- `_workspace_signals()` 扩展为可组合 collector，避免单函数膨胀。
- 终端/工具执行层可写入最近命令 sidecar，forecast 只读轻量摘要。
- 对 diff 内容只保留短摘要，不把大 diff 直接塞进 prompt。

**验收标准**:

1. 最近 pytest 失败时，forecast 建议包含失败测试名或失败文件。
2. 新增模块但未新增测试时，forecast 能建议补测试或接线验证。
3. 已经刚运行过同一测试且通过时，不重复建议立即运行同一测试。

### 8.7 通用 fallback 策略库

**目标**: 将当前偏硬编码的 fallback 扩展为面向多种项目状态的策略库，提升 provider 不可用或低置信度时的质量。

**策略示例**:

| 条件 | 建议类型 |
|------|------|
| dirty worktree + source files changed | review current changes / identify unfinished work |
| tests changed or source maps to tests | run focused tests |
| recent test failure | fix failing test |
| docs changed | preview/check docs consistency |
| command/CLI files changed | run command wiring tests |
| frontend files changed | run frontend wiring or browser smoke test |
| no strong signal | return no confident suggestion |

**实现入口**:

- 新增 `fallback.py`，将规则拆成独立 `FallbackRule`。
- 每条规则返回 `ForecastSuggestion`、confidence、source_refs 和 `suggestion_kind`。
- 规则按 `task_state`、`intent_stage`、`workspace_focus` 共同排序。

**验收标准**:

1. fallback 不再只对单一功能有特殊优待。
2. provider 关闭时仍能给出与当前文件和阶段一致的建议。
3. 没有足够信号时返回 `generated=false`，避免无意义打扰。

### 8.8 Alias 与 workspace focus 误判治理

**目标**: 降低宽泛关键词导致的误判，例如普通 `forecast` 文本被误认为 Intent Forecast 功能。

**增强方式**:

- 将 alias 分为 `strong_path_aliases`、`module_aliases`、`weak_text_aliases`。
- 弱文本 alias 必须与路径、最近用户消息或 summary evidence 共同出现才计入焦点。
- 对多 focus 场景输出置信度和证据，供调试和测试断言。
- 对“通用词”如 `summary`、`forecast`、`commands` 设置更低权重。

**实现入口**:

- 重构 `_focus_definitions()` 与 `_workspace_focuses()`。
- `ForecastContext.workspace` 增加 `focuses` 调试字段，便于 CLI/status 检查。
- 测试覆盖宽泛词误判、跨模块变更、多焦点并存。

**验收标准**:

1. 仅 README 中出现 `forecast` 不会强判为 `intent_forecast`。
2. 路径 `clawcodex_ext/intent_forecast/service.py` 仍强判为 `intent_forecast`。
3. 同时修改 TUI 和 intent_forecast 时，两者都能进入 focus，但无关 orchestrator 建议被过滤。

### 8.9 允许“不建议行动”

**目标**: 提升用户信任度。没有足够证据时宁可不展示，也不要为了展示而生成泛泛建议。

**触发 no-suggestion 的条件**:

- 当前没有最近用户目标、没有 dirty worktree、没有相关 session next action。
- 最近用户表达暂停、等待、稍后再说。
- assistant 刚完成任务且没有未运行测试、未提交变更或失败信号。
- 所有候选建议 confidence 都低于动态阈值。

**实现入口**:

- `IntentForecastService.generate()` 在 fallback 前后加入 no-suggestion gate。
- `min_confidence` 支持动态调整，例如自动触发比手动 `/forecast run` 更严格。
- CLI/status 显示 no-suggestion reason，自动触发时静默。

**验收标准**:

1. 空仓库或无上下文时自动 forecast 不打扰用户。
2. 手动 `/forecast run` 可以显示“暂无可靠建议”的原因。
3. no-suggestion 事件写入 history 以便后续评估触发质量。

### 8.10 离线评估集与质量指标

**目标**: 为 prompt、规则和学习策略建立可回归的质量评估，避免凭感觉优化。

**评估数据构造**:

- 从真实 session 中截取某个时刻的 context snapshot。
- 将用户下一条真实输入或后续 agent turn 目标作为标签。
- 对敏感内容做本地脱敏或仅保留结构化特征。
- 保留正例、负例、无建议例、多语言例和跨模块例。

**核心指标**:

| 指标 | 含义 |
|------|------|
| `top1_match` | 第一条建议是否匹配真实下一步 |
| `top3_match` | 三条建议中是否包含真实下一步 |
| `off_topic_rate` | 建议是否跑到无关模块/历史任务 |
| `interrupt_risk` | 是否在应静默时展示建议 |
| `language_accuracy` | 建议语言是否符合用户上下文 |
| `actionability` | prompt 是否可直接提交给 agent |

**实现入口**:

- 新增 `eval/intent_forecast/`，包含 dataset schema、runner 和报告生成。
- 支持 provider mock 与真实 provider 两种模式。
- 每次调整 prompt、focus、fallback、learning 时运行小型回归集。

**验收标准**:

1. 至少包含 30 个本地样例，覆盖实现、测试、文档、review、无建议场景。
2. 报告输出每类场景的 top1/top3/off-topic/no-suggestion 指标。
3. CI 或本地命令能快速运行无 provider 的规则回归。

### 8.11 增强实施顺序

| Phase | 内容 | 覆盖增强项 | 建议优先级 |
|:----:|------|------|:------:|
| Phase 8 | 任务状态模型 + intent stage | 8.1、8.2 | P0 |
| Phase 9 | session 相关性召回 + workspace 信号增强 | 8.5、8.6 | P0 |
| Phase 10 | feedback 特征化 + 采纳后闭环 | 8.3、8.4 | P1 |
| Phase 11 | 通用 fallback + no-suggestion gate | 8.7、8.9 | P1 |
| Phase 12 | alias 误判治理 + focus 调试字段 | 8.8 | P1 |
| Phase 13 | 离线评估集与质量报告 | 8.10 | P1 |

### 8.12 新增测试计划

| 测试文件 | 覆盖 |
|------|------|
| `tests/intent_forecast/test_task_state.py` | active_goal、last_completed_step、blocked_reason、pending_tests 提取 |
| `tests/intent_forecast/test_intent_stage.py` | explore/implement/test/debug/review/document/commit 阶段分类 |
| `tests/intent_forecast/test_session_retrieval.py` | cwd、changed_files、summary 相似度排序 |
| `tests/intent_forecast/test_workspace_signals.py` | branch、last command、test failures、diff names 收集 |
| `tests/intent_forecast/test_feedback_features.py` | 特征化 feedback 写入与相似度加权 |
| `tests/intent_forecast/test_acceptance_outcomes.py` | accepted_completed、accepted_aborted、accepted_corrected 事件 |
| `tests/intent_forecast/test_fallback_rules.py` | 通用 fallback 策略与 no-suggestion gate |
| `tests/intent_forecast/test_focus_aliases.py` | strong/module/weak alias 权重与误判防护 |
| `eval/intent_forecast/test_eval_runner.py` | 离线样例指标计算 |

---

## §9 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-07-01 | 初始规划；确定 `/forecast` 与 `clawcodex forecast` 同名；默认 idle 触发时间为 2 分钟；明确用户输入即废弃预测；明确 `summary.json` 异步生成，不阻塞退出 | 用户提出 Intent Forecast 功能需求 |
| 2026-07-02 | 增补 Intent Forecast 准确率增强规划：任务状态模型、意图阶段分类、反馈特征化、采纳后闭环、相关 session 召回、workspace 信号、fallback 策略、focus 误判治理、no-suggestion gate 和离线评估集 | 提升下一步意图预测准确率，使建议更贴近用户真实目标和执行步骤 |
