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

## §8 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-07-01 | 初始规划；确定 `/forecast` 与 `clawcodex forecast` 同名；默认 idle 触发时间为 2 分钟；明确用户输入即废弃预测；明确 `summary.json` 异步生成，不阻塞退出 | 用户提出 Intent Forecast 功能需求 |
