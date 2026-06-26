# F-54: 运行期可观测性

> 状态: 🔄 进行中
> 章节: docs/feature_plan/02-orchestrator/f-54-observability.md
> 最后更新: 2026-06-24

## §1 设计规划

### 1.1 背景与目标

**场景**: headless agent 在 issue 开发中途陷入迷茫 / operator 想人工介入。

**触发条件（任一）**:
1. orchestrator 检测到 agent 连续多轮无进展（F-51 空转检测）
2. operator 通过 dashboard 看到 agent stuck
3. operator 通过 F-49 Phase 1 的 socket 手动触发 pause

**Operator 执行流程**:
```
$ clawcodex --resume <run_id>

内部流程:
  → Session.resume(run_id) 读取 metadata.json + transcript.jsonl
  → 重建完整的 Conversation（UserMessage / AssistantMessage 交替列表）
  → 恢复到前台 REPL，LLM context 与 agent 中断时一致
```

**恢复后的对话完整性保证**:
```
Session.resume() 恢复的 transcript 内容:
┌─ turn 0 ──────────────────────────────────┐
│ UserMessage:    初始 prompt                │
│ AssistantMessage: 思考 + tool_use Read     │
│ UserMessage:    tool_result (文件内容)      │
├─ turn N ──────────────────────────────────┤
│ UserMessage:    "这个 Read 结果不对..."    │ ← operator 介入写入
│ AssistantMessage: 新的 LLM 响应             │ ← 新写入
└───────────────────────────────────────────┘
```

**--resume 并发安全**:

| 场景 | 行为 |
|------|------|
| agent 已结束 | ✅ 正常恢复，进入交互 REPL |
| agent 正在运行中 | ✅ 恢复后获得历史快照（readonly），agent 继续运行 |
| agent 正在运行 + operator 想接管 | socket 发送 pause → agent 挂起 → --resume 进入可写 REPL |
| 两个 operator 同时 --resume | 各自获得独立历史快照，最后写入者胜 |

### 1.2 当前文件结构（F-49 统一后）

```
# 主转录（Message 级别，可 resume）
~/.clawcodex/sessions/{run_id}.json        ← Session 快照（含 cost 计数）
~/.clawcodex/sessions/{run_id}/
  ├── metadata.json                         ← 元数据
  ├── transcript.jsonl                      ← Message 对话转录
  └── content/                              ← 大内容文件引用

# 辅助日志（非 Message 级别，不可用于 resume）
~/.clawcodex/tool-events/{run_id}/events.ndjson
  └── 每行 8 字段：ts / tool / params / approved / deny_reason / ...
      （F-45 审计旁路，50MB rotate）

{workspace}/.orchestrator_control/runs/{run_id}/debug.ndjson
  └── 每行 {ts, stage, ...fields}
```

### 1.3 事件流数据流向图

```
AgentRunner.run()
  ├── run() 开始
  │     ├── SessionStorage(session_id=run_id)
  │     ├── .init_metadata(model, cwd, title)
  │     └── .write_raw(user_prompt_msg_dict)
  │
  ├── 循环 per turn:
  │     ├── 累积 TextDelta → text_buf list
  │     ├── 累积 ToolCallEvent → tool_use_buf list
  │     ├── 累积 ToolResultEvent → tool_result_buf dict[tool_use_id]
  │     ├── TurnComplete:
  │     │     ├── 组装 AssistantMessage(text_buf + tool_use_buf)
  │     │     ├── .write_raw(assistant_msg_dict)
  │     │     ├── 组装 UserMessage(tool_result_buf.values())
  │     │     └── .write_raw(user_msg_dict)
  │     └── F-45 逻辑独立并行：_append_tool_event_log(event)
  │
  ├── SessionComplete: .flush()
  └── 异常退出：.flush()  ← 确保已累积消息不丢失
```

### 1.4 Unix Socket 控制通道（Phase 1）

| 新增文件 | 说明 |
|----------|------|
| `extensions/orchestrator/control_socket.py` | ControlSocket 类：Unix domain socket 监听 |
| ControlCommand dataclass | cmd: pause/resume/inject/stop/detach/takeover + payload |

```python
@dataclass
class ControlCommand:
    cmd: Literal["pause", "resume", "inject", "stop", "detach", "takeover"]
    payload: str = ""

class ControlSocket:
    """Bidirectional control via Unix domain socket."""
```

### 1.5 观测点计划

| 层级 | 观测点 | 记录内容 |
|------|--------|----------|
| QueryRunner.stream() start | headless session 启动 | workspace, provider, model, permission_mode, max_turns, prompt length, run_id |
| QueryRunner.on_event | headless bridge 收到事件 | kind, tool_name, tool_use_id, event_count, seconds_since_start |
| QueryRunner.stream() heartbeat | future pending 期间周期性输出 | future done/pending, seconds_since_last_event, event counts |
| AgentRunner.run() turn start/end | 每轮 turn 生命周期 | issue_id, run_id, turn, has_tool_calls, workspace dirty |
| AgentRunner.run() event receive | 每个 QueryEvent 被消费 | event type, tool name, text length, session_complete reason |
| Orchestrator._run_issue() timeout | watchdog 触发 | session status, turn_count, tool_count, last_event_type |

### 1.6 持久化格式

```
{workspace}/.orchestrator_control/runs/{run_id}/debug.ndjson
```

示例行:
```json
{"ts": "2026-06-04T20:01:26Z", "stage": "agent_runner.start", "issue_id": "F-40-progress-sink"}
{"ts": "2026-06-04T20:01:27Z", "stage": "query_runner.start", "provider": "minimax", "prompt_len": 18420}
{"ts": "2026-06-04T20:03:27Z", "stage": "query_runner.heartbeat", "future_done": false, "seconds_since_last_event": 120}
{"ts": "2026-06-04T20:29:57Z", "stage": "orchestrator.timeout", "turn_count": 0, "tool_count": 0}
```

### 1.7 Registry / CLI 摘要字段

| 字段 | 含义 |
|------|------|
| run_id | 当前或最后一次 agent run id |
| last_agent_event_at | AgentRunner 最近收到 QueryEvent 的时间 |
| last_agent_event | 最近事件类型 |
| turn_count | 当前 session 已完成 turn 数 |
| tool_count | 当前 session 已消费 tool event 数 |
| debug_log_path | debug.ndjson 路径 |

### 1.8 实施阶段

| 阶段 | 任务 | 状态 |
|------|------|:----:|
| 1 | 新增 debug writer debug.ndjson | 📋 |
| 2 | QueryRunner.stream() start/event/heartbeat 观测点 | 📋 |
| 3 | AgentRunner.run() turn/event counters | 📋 |
| 4 | watchdog timeout diagnostic snapshot → registry | 📋 |
| 5 | CLI issue status 增加 debug 摘要 | 📋 |

### 1.9 已落地基础设施

- `extensions/orchestrator/debug_log.py`（29 行）：`append_debug_event`
- `ObservabilityConfig`：schema 配置
- `agent_runner.py:751`：已写 `debug.ndjson`

### 1.10 验收标准

1. headless future pending 无 tool event 时 `debug.ndjson` 周期性出现 heartbeat
2. watchdog timeout 后 registry 包含 run_id, turn_count, tool_count, last event
3. debug 文件不在 git sync 中被提交
4. F-49 落地后可迁移到 SessionStorage

### 1.11 依赖与协同

- **F-40**: progress event 扇出与 session 结束落点
- **F-45**: tool-events.ndjson（已通过的 tool approval）
- **F-49**: 后续统一 SessionStorage
- **Watchdog**: fail-closed + retry，F-54 解释原因

## §2 进度跟踪

### 2.1 已完成里程碑

| 日期 | 里程碑 | 涉及文件 | 验证方式 |
|------|--------|---------|---------|
| 2026-06 | 基础 debug_log 落地 | debug_log.py, agent_runner.py | debug.ndjson 可写入 |
| 2026-06 | 可观测性 schema 定义 | ObservabilityConfig | schema 验证 |

### 2.2 当前瓶颈

- 仪表盘/query-runner heartbeat 未接入
- CLI 诊断字段未补齐

### 2.3 下一步计划

1. QueryRunner.stream() heartbeat 接入
2. AgentRunner turn/event counters
3. watchdog diagnostic snapshot
4. CLI issue status 扩展

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-06-24 | 补全详细设计（resume 流程+文件结构+事件流+观测点） | 对齐 FEATURE_PLAN.legacy.md |
