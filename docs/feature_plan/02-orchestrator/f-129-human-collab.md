# F-129: 编排器人机协同闭环 — issue 子命令注入、接管与恢复

> 状态: ✅ 已完成（五条命令全部实现并端到端验证通过）
> 章节: docs/feature_plan/02-orchestrator/f-129-human-collab.md
> 最后更新: 2026-07-27
> 关联能力: F-49（会话统一存储 + ControlSocket Phase 1）、F-39（Issue 重跑）、F-54（可观测性）

---

## §0 当前实现

### 0.1 已有基础设施

F-49 Phase 1 已交付 ControlSocket（Unix domain socket）和基础 CLI 命令族。F-129 Phase 1-4 已实现 socket 跨 turn 存活、socket 命令补全（inject/stop 生效）、mid-turn drain、real-time inject via pending_messages。`attach` 命令已废弃删除。**handback 机制已完全移除**（takeover 重新设计为纯只读快照查看器，inject 重新设计为 pause→写 transcript→auto-resume）。现有基础设施盘点：

| 组件 | 状态 | 关键位置 |
|------|------|---------|
| **ControlSocket** | ✅ 通道完备，7 命令定义（pause/resume/inject/stop/detach/takeover/flush_transcript），多客户端并发，事件广播，跨 turn 存活 | `extensions/orchestrator/control_socket.py` |
| **send_cmd 客户端工具** | ✅ 从已删除的 attach.py 提取到 control_socket.py，供 takeover 等 CLI 复用 | `extensions/orchestrator/control_socket.py:send_cmd` |
| **session_id == run_id** | ✅ 编排器 run_id 就是 clawcodex session_id，可直接 `--resume` | `takeover.py`, `agent_runner.py` |
| **SessionStorage + transcript.jsonl** | ✅ JSONL transcript 读取，`Session.load()` 三分支加载（enhanced transcript / session.json / metadata+transcript） | `clawcodex_ext/agent/session.py:load()`, `clawcodex_ext/services/session_storage.py` |
| **`--resume` CLI** | ✅ 历史恢复、session fork、resume-at-index | `clawcodex_ext/cli/{parser,dispatch}.py` |
| **`issue pause`/`resume`/`stop`** | ✅ socket 优先（即时生效），控制文件 fallback；stop 设 status=failed + break stream loop | `extensions/orchestrator/cli/issue.py:_write_control` |
| **`issue takeover`** | ✅ **纯只读快照查看器**：通过 `flush_transcript` 命令让 agent flush 缓冲区到磁盘，然后 spawn `--resume` REPL 显示对话历史。**不暂停 agent、不做 handback** | `extensions/orchestrator/cli/takeover.py` |
| **`issue inject`** | ✅ **pause → 写 UserMessage 到 transcript → auto-resume** 三步流程。消息以独立 user message（`origin="inject"`）写入 transcript.jsonl，takeover REPL 可见。socket 不可用时退回 `.operator_hints.md` 文件路径 | `extensions/orchestrator/cli/issue.py:_run_inject` |
| **socket `inject`** | ✅ 写 UserMessage 到 transcript + `queue_pending_message()` 排入内存 Conversation + 立即发射 `InjectDelivered`（不等 ToolResult 边界） | `agent_runner.py:_drain_control_commands` |
| **socket `flush_transcript`** | ✅ flush SessionStorage 缓冲区到 transcript.jsonl（不暂停 agent），供 takeover REPL 读取实时对话历史 | `agent_runner.py:_drain_control_commands` |
| **socket `stop`** | ✅ 设 `status=failed` + break stream loop | `agent_runner.py:_drain_control_commands` |
| **mid-turn drain** | ✅ ToolResult 边界 drain（`pending_tool_results <= 0` 时触发） | `agent_runner.py:_make_control_drain_fn` |
| **`pending_messages` drain** | ✅ 编排器 agent 已接入（`LocalAgentTaskState(agent_id=run_id)`） | `agent_runner.py`, `clawcodex_ext/query/query.py` |
| ~~`issue attach` TUI~~ | 🗑️ 已废弃删除（需求变更：attach 冗余，五条命令已覆盖全部协同场景） | — |
| ~~handback~~ | 🗑️ **已完全移除**（takeover 重新设计为纯只读快照，inject 重新设计为 pause→transcript→resume，无需 handback 恢复机制） | — |

### 0.2 已修复的 P0/P1 Bug

| Bug | 文件 | 修复内容 | 状态 |
|-----|------|---------|------|
| attach CSS 文件缺失 | `attach.py` | 删除 `CSS_PATH = "attach.tcss"` | ✅ (attach 已删除) |
| takeover `--workspace` 非法参数 | `takeover.py` | 删除 subprocess 的 `--workspace` 参数，workspace 通过 `cwd` 传递 | ✅ |
| socket `stop` 只设元数据 | `agent_runner.py` | stop 设 status=failed + break stream loop | ✅ |
| socket `inject` 是 no-op | `agent_runner.py` | inject 写 transcript + queue_pending_message + 立即发射 InjectDelivered | ✅ |
| resume 走控制文件 30s 延迟 | `issue.py` | `_write_control` 优先走 socket | ✅ |
| inject 消息不出现在 transcript | `agent_runner.py` | inject handler 写 UserMessage 到 transcript + flush | ✅ |
| takeover REPL 看不到对话历史 | `takeover.py`, `session.py` | `flush_transcript` 命令 + `Session.load()` 空消息 fall through + `_ensure_session_stub` 不遮蔽 transcript | ✅ |
| inject 与 socket inject 不汇聚 | `issue.py`, `agent_runner.py` | 统一为 pause→inject→resume 三步流程 | ✅ |
| inject 非幂等 | `issue.py` | `_inject_hint` 增加去重检查 | ✅ |

### 0.3 Bug 清单（最终状态）

| # | 严重度 | 命令 | Bug | 状态 |
|---|--------|------|-----|------|
| 3 | P1 | ~~attach~~ | socket 每 turn 断连 | 🗑️ attach 已删除，socket 跨 turn 存活已实现 |
| 4 | P1 | ~~attach~~ | 无历史回放 | 🗑️ attach 已删除 |
| 5 | P1 | ~~attach~~ | socket `stop` 只设元数据 | ✅ 已修复 |
| 6 | P1 | resume | 走控制文件 30s 延迟 | ✅ 已修复 |
| 7 | P1 | inject | socket inject 是 no-op | ✅ 已修复 |
| 8 | P2 | takeover | ~~无 handback~~ → 重新设计为纯只读快照，不需要 handback | ✅ 设计变更 |
| 9 | P2 | takeover | ~~transcript 分叉~~ → takeover 不修改 transcript，无分叉问题 | ✅ 设计变更 |
| 10 | P2 | inject | 描述不准 | ✅ 已修复 |
| 11 | P2 | inject | 与 socket inject 不汇聚 | ✅ 已修复 |
| 12 | P2 | inject | 非幂等 | ✅ 已修复 |
| 13 | P3 | pause/resume/stop | 控制文件 30s 延迟 | ✅ 已修复 |
| 14 | P3 | resume-session | 非交互 | 🗑️ `--interactive` flag 已删除 |

---

## §1 设计规划

### 1.1 背景与目标

#### 问题陈述

编排器处理 Issue 时拉起一个 clawcodex session（`run_id == session_id`）执行方案设计和代码修改。用户需要通过 `clawcodex-dev orchestrator issue` 的子命令族实现人机协同：注入提示纠偏、查看对话历史、暂停/恢复/停止。

#### 目标

以 `issue *` 子命令为出发点，维持五个人机协同控制命令的完整闭环：

1. **暂停-恢复**：`pause` → `resume`，命令即时生效（socket 优先，不走 30s 控制文件）
2. **只读快照**：`takeover` → `--resume` REPL 查看对话历史，**不暂停 agent、不做 handback**，退出后不影响编排器
3. **停止任务**：`stop` → `transcript` → `retry`
4. **消息注入**：`inject` → pause → 写 UserMessage 到 transcript → auto-resume，消息以独立 user message 出现在对话历史中
5. **回答提问**：`clarify`（当前可用，不在本特性范围）

**核心目标：让用户通过 `issue pause/resume/stop/inject/takeover` 命令族随时纠偏或查看状态，实现编排器→agent↔用户的人机协同闭环。**

#### 非目标

- ❌ 不修改 `clawcodex --resume` 的 CLI 行为（`--resume` 是 takeover 内部的实现细节）
- ❌ 不新增 server-side 长进程会话管理（那是 F-94 BG_SESSIONS 的范畴）
- ❌ 不实现 `cc://` URL scheme 直连（那是 F-99 DIRECT_CONNECT 的范畴）
- ❌ 不实现 handback 机制（takeover 是纯只读快照，inject 是 pause→写→resume，无需 handback）

### 1.2 协同命令分类

| 角色 | 命令 | 作用 | 当前状态 |
|------|------|------|---------|
| 观察 | `tail` | 文件 tail 实时观察（只读） | ✅ |
| 观察 | `transcript` | 完整历史读取（只读） | ✅ |
| 观察 | `resume-session` | 加载历史 + 预览 summary（只读） | ✅ |
| 观察 | `takeover` | flush transcript → `--resume` REPL 查看对话历史（只读，不暂停 agent） | ✅ |
| 控制 | `pause` | 暂停 agent（socket 优先，即时生效） | ✅ |
| 控制 | `resume` | 恢复 agent（socket 优先，即时生效） | ✅ |
| 控制 | `stop` | 停止 agent（socket 优先，ToolResult 边界生效） | ✅ |
| 注入 | `inject` | pause → 写 UserMessage 到 transcript → auto-resume | ✅ |
| 交互 | `clarify` | 回答澄清请求 | ✅ |

---

## §2 架构分析

### 2.1 双控制通道

存在两套控制通道，pause/resume/stop 优先走 socket（即时生效），控制文件作为 fallback：

| 通道 | 路径 | 延迟 | 使用者 |
|------|------|------|--------|
| **Unix socket**（优先） | `{workspace}/.run_control/{run_id}.sock` → `agent_runner.py` 在 event 边界 drain 命令队列 | **~60ms** | `pause` / `resume` / `stop` / `inject` / `flush_transcript` |
| **控制文件**（fallback） | `{workspace}/.orchestrator_control/{cmd}_{id}.control` → 编排器 `_poll_and_dispatch` 每 poll cycle 读一次 | **最高 30s** | `pause` / `resume` / `stop`（socket 不可用时） |

### 2.2 Socket 命令清单

| 命令 | agent 端处理 | 说明 |
|------|------------|------|
| `pause` | `_apply_pause_session`：设 `session.paused = True` + `_pause_gate.clear()` | 进入 `_pause_wait` drain-and-wait 循环 |
| `resume` | `_apply_resume_session`：设 `session.paused = False` + `_pause_gate.set()` | 退出 drain 循环，恢复运行 |
| `stop` | 设 `session.status = "failed"` + `pause_resume_event.set()` | stream 循环退出，agent 终止 |
| `inject` | 写 UserMessage 到 transcript + `queue_pending_message` + 立即发射 `InjectDelivered` | 消息以独立 user message 出现在对话历史 |
| `flush_transcript` | `session._transcript_storage.flush()` | flush 缓冲区到 transcript.jsonl，供 takeover REPL 读取 |
| `takeover` | 设 `session.status = "failed"` | control socket 协议层命令（IM gateway 使用，与 CLI `issue takeover` 不同） |
| `detach` | 日志记录 | 基本版本 |

### 2.3 Socket 生命周期

socket 跨 turn 存活——不在 PhaseComplete 时 stop，只在 terminal SessionComplete 和 max_turns exit 时 stop。

### 2.4 Mid-turn drain

`_make_control_drain_fn` 返回一个闭包，被 `QueryRunner.stream()` 的 polling loop 每 ~60ms 调用。同时 `_pause_wait` 的 drain-and-wait 循环在 agent paused 时也每 60ms 调用 `_drain_control_commands`，确保 inject/resume/stop 在 pause 状态下也能被处理。

### 2.5 Inject 投递机制

inject 采用 **pause → 写 transcript → auto-resume** 三步流程：

```
CLI                         Agent Runner (_pause_wait drain loop)
 │                              │
 ├─ send "pause" ──────────────►├─ _apply_pause_session → enters drain loop
 │◄── "Paused" event ───────────┤
 │                              │
 ├─ send "inject" ─────────────►├─ write UserMessage(origin="inject") to transcript + flush()
 │                              ├─ queue_pending_message() → 加入内存 Conversation
 │                              ├─ emit "InjectDelivered" (立即，不等 ToolResult)
 │◄── "InjectDelivered" ────────┤
 │                              │
 ├─ send "resume" ─────────────►├─ _apply_resume_session → exits drain loop
 │◄── "Resumed" event ──────────┤
 │                              │
 └─ print "Message injected     │  agent continues, sees injected message
     and agent resumed"          │  at next tool-round boundary
```

关键点：
- **transcript 写入**：`create_user_message(content=[TextBlock(text=cmd.payload)], origin="inject")` + `session._transcript_storage.flush()` 立即落盘
- **内存 Conversation**：`queue_pending_message()` 将消息排入 pending 队列，在下一个 ToolResult 边界由 `_drain_pending_user_messages` 注入 LLM context
- **`InjectDelivered` 立即发射**：不设置 `_inject_pending_snippet`（避免 ToolResult 边界重复发射）
- **文件 fallback**：socket 不可用时（agent 未运行）退回 `.operator_hints.md`，由 `_get_operator_hints` 嵌入下一 turn prompt

### 2.6 Takeover 快照机制

takeover 是纯只读快照查看器，通过 `flush_transcript` 命令确保对话历史落盘：

```
takeover --id 24
  ├─ _resolve_target() → (run_id, workspace_path)
  ├─ _send_flush_transcript(sock_path)     → 让 agent flush 缓冲区到 transcript.jsonl
  ├─ asyncio.sleep(1.0)                     → 等 agent 处理 flush 命令
  ├─ _wait_for_transcript(run_id, timeout=5.0)  → 等 transcript.jsonl 落盘
  ├─ _ensure_session_stub(run_id)           → 仅在 transcript 不存在时写 stub（不遮蔽真实数据）
  └─ _spawn_resume_repl(run_id, workspace_path)
       → python3 -m src.cli --resume <run_id>
```

关键修复（对话历史可见性）：
1. **`_ensure_session_stub` 不遮蔽 transcript**：transcript.jsonl 已存在时跳过 stub 写入
2. **`Session.load()` 空消息 fall through**：session.json 的 `messages` 为空时，fall through 到 Branch 3 读 transcript
3. **`flush_transcript` 命令**：让 agent 主动 flush 内存缓冲区到磁盘（agent 在第一个 turn 内时，消息缓冲在内存中未落盘）

### 2.7 SessionStorage 缓冲机制

- `write_message()` / `write_raw()` 将消息加入内存 `_write_buffer`
- 缓冲达 `MAX_FLUSH_BATCH=50` 条时自动 flush
- `_flush_turn_transcript()` 在 turn 结束时调用 `flush()`
- `init_metadata()` 只写 `metadata.json`，不创建 `transcript.jsonl`
- `_save_json_snapshot()` 在 agent 运行结束时调用（`finally` 块），写 `session.json`

### 2.8 Session.load() 三分支加载

| 分支 | 条件 | 读取源 |
|------|------|--------|
| 1. Enhanced transcript | transcript.jsonl 首行是 `session_init` | `_load_from_enhanced_transcript()` |
| 2. Legacy session.json | session.json 存在且 **messages 非空** | `session.json` → `Conversation.from_dict()` |
| 3. Metadata + transcript | session.json 不存在或 **messages 为空** | `metadata.json` + `SessionStorage.read_transcript()` |

> **关键修复**：Branch 2 原来信任 session.json 即使 messages 为空（直接返回空对话，短路 Branch 3）。现在 messages 为空时 fall through 到 Branch 3 读 transcript。

### 2.9 关键约束

1. `ControlSocket` 无 per-turn 状态——跨 turn 存活是安全的
2. drain 是非阻塞的（`get_nowait()`），与事件流解耦
3. `session_id == run_id`——`--resume <run_id>` 能加载同一 transcript
4. `_pause_wait` drain-and-wait 循环确保 inject/resume/stop 在 pause 状态下也能被处理

---

## §3 开发计划（已完成）

### Phase 1: Socket 跨 turn 存活 ✅

**目标**：socket 不在 turn 间隙断连。

**改动**：删除 PhaseComplete 路径的 socket stop + `= None`。保留 terminal SessionComplete 和 max_turns exit 的 stop。

**状态**：✅ 已完成

### Phase 2: Socket 命令补全 + 控制命令统一 ✅

**目标**：inject/stop/detach 生效；`issue pause/resume/stop` 优先走 socket。

**改动**：提取 `_drain_control_commands` 方法；ToolResult 边界 mid-turn drain；`_write_control` 优先走 socket。

**状态**：✅ 已完成

### Phase 3: ~~Takeover handback~~ → 重新设计为只读快照 ✅

**原始目标**：takeover REPL 退出后自动 handback，agent 重启读 transcript。

**实际实现**：takeover 重新设计为**纯只读快照查看器**。不暂停 agent、不做 handback。通过 `flush_transcript` 命令让 agent flush 缓冲区到磁盘，REPL 读取 transcript 显示对话历史。

**移除的代码**：
- `cli/takeover.py`：`_send_pause_and_takeover`、`_write_handback_control`、`_wait_for_quiet_period`、`bootstrap_session_id` 字段
- `cli/issue.py`：`--no-handback` 参数
- `orchestrator.py`：`resume_run_id` 读取/清除死分支
- `agent_runner.py`：`resume_from_run_id` 字段、`bootstrap_session_id` 字段及捕获块、handback run_id 复用、`_handback_notice` 系统提示注入
- `issue_registry.py`：`resume_run_id` 字段

**状态**：✅ 已完成（设计变更：handback 移除，takeover 改为只读快照）

### Phase 4: Real-time inject via pending_messages ✅

**原始目标**：inject 在下一个 ToolResult 边界生效。

**实际实现**：inject 重新设计为 **pause → 写 UserMessage 到 transcript → auto-resume** 三步流程。消息以独立 user message（`origin="inject"`）写入 transcript.jsonl，takeover REPL 可见。同时通过 `queue_pending_message` 排入内存 Conversation，LLM 在下一个 ToolResult 边界看到。

**改动**：
- `agent_runner.py` inject handler：新增 transcript 写入 + flush；`InjectDelivered` 立即发射；不设置 `_inject_pending_snippet`
- `cli/issue.py` `_run_inject`：改为 `_send_and_wait("pause")` → `_send_and_wait("inject")` → `_send_and_wait("resume")` 三步

**状态**：✅ 已完成

### Phase 5: 打磨 ✅

**目标**：描述准确、行为符合预期。

**状态**：✅ 已完成

---

## §4 关键设计决策

| # | 决策点 | 选择 | 理由 |
|---|--------|------|------|
| 1 | Phase 2 vs Phase 4 的 inject 策略 | **两个都做** | Phase 2 低风险（先让 inject 不再 no-op），Phase 4 高收益（让 inject 实时生效） |
| 2 | ~~Handback 默认行为~~ → **handback 移除** | **takeover 改为纯只读快照** | takeover 只查看不修改，不需要 handback 恢复机制。inject 改为 pause→写→resume，消息直接写入 transcript，不需要 handback 重启 agent |
| 3 | `_write_control` 改为优先 socket | **接受** | socket 不存在时仍走文件，保证向后兼容 |
| 4 | inject 消息写入 transcript | **pause → 写 → resume** | 确保 inject 消息作为独立 user message 出现在对话历史中（takeover 可见）。pause 确保在 clean boundary 写入，resume 让 agent 立即处理 |
| 5 | takeover 对话历史可见性 | **`flush_transcript` 命令** | agent 在第一个 turn 内时消息缓冲在内存中未落盘。通过 control socket 发送 flush 命令让 agent 主动 flush，不暂停 agent |
| 6 | `Session.load()` 空消息处理 | **fall through 到 transcript** | session.json 的 messages 为空时（`_save_json_snapshot` 的 `load_messages()` bug 导致），fall through 到 Branch 3 读 transcript |

---

## §5 协同流程设计

### 5.1 场景一：查看对话历史 + 轻量纠偏（最常用）

```
issue list                          # 发现 running 的 issue
      │
      ▼
issue takeover --id <id>            # flush transcript → --resume REPL 查看对话历史
      │                              # agent 不暂停，继续运行
      │
      ├─ 在 REPL 中查看对话历史
      │  （用户提示词 + assistant 工具调用及结果）
      │
      ├─ 发现 agent 方向偏了
      │
      ├─ 退出 REPL（/exit）
      │
      ├─ issue inject --id <id> "请先跑 pytest"
      │  │   # pause → 写 UserMessage 到 transcript → auto-resume
      │  │   # 消息以独立 user message 出现在对话历史
      │  └─ agent resume 后在下一个 ToolResult 边界看到消息
      │
      └─ issue takeover --id <id>    # 再次查看，确认 inject 消息出现
```

### 5.2 场景二：暂停-恢复

```
issue pause --id <id>               # 优先走 socket，即时生效
      │
      ▼
agent 在下一个 ToolResult 边界暂停
      │
      ├─ 用户做自己的事（跑 CI、review 代码）
      │
      ▼
issue resume --id <id>              # 优先走 socket，即时生效
      │
      ▼
agent 恢复运行
```

### 5.3 场景三：停止任务

```
issue stop --id <id>                # 优先走 socket，即时停止
      │
      ▼
issue transcript --id <id>          # 完整历史
      │
      ▼
issue retry --id <id>               # 重新拉起（会读 previous_run_ids 的 transcript）
```

---

## §6 里程碑

| 里程碑 | 包含 Phase | 交付能力 | 状态 |
|--------|-----------|---------|------|
| **M1: socket 跨 turn 存活** | Phase 1 | socket 不在 turn 间隙断连 | ✅ 已完成 |
| **M2: inject + 控制可用** | Phase 2 | socket inject/stop/detach 生效 + pause/resume/stop 即时 | ✅ 已完成 |
| **M3: takeover 只读快照** | Phase 3（重新设计） | takeover → flush_transcript → --resume REPL 查看对话历史 | ✅ 已完成 |
| **M4: inject 消息注入** | Phase 4（重新设计） | inject → pause → 写 transcript → auto-resume | ✅ 已完成 |
| **M5: 打磨** | Phase 5 | 描述准确 + 幂等 | ✅ 已完成 |

---

## §7 关键文件索引

| 文件 | 作用 |
|------|------|
| `extensions/orchestrator/agent_runner.py` | `_drain_control_commands`（pause/resume/stop/inject/flush_transcript/detach/takeover 命令处理）；`_pause_wait` drain-and-wait 循环；`_apply_pause_session`/`_apply_resume_session`；`_flush_turn_transcript`；`_save_json_snapshot` |
| `extensions/orchestrator/control_socket.py` | `ControlSocket` 实现；`send_cmd` 客户端工具 |
| `extensions/orchestrator/cli/takeover.py` | `_resolve_target`、`_run_takeover_async`、`_spawn_resume_repl`、`_wait_for_transcript`、`_ensure_session_stub`、`_send_flush_transcript` |
| `extensions/orchestrator/cli/issue.py` | `_write_control`（socket 优先）；`_run_inject`（pause→inject→resume 三步）；`_send_and_wait`；`_inject_hint`（文件 fallback） |
| `extensions/orchestrator/orchestrator.py` | `_apply_control_command`（控制文件 fallback）；`_on_pause_change` 回调 |
| `extensions/orchestrator/issue_registry.py` | `IssueStatus.PAUSED`；`mark_paused`/`mark_resumed`；`IssueRecord.pause_reason` |
| `extensions/orchestrator/prompt_builder.py` | `_get_operator_hints`（one-shot 读取 `.operator_hints.md`，仅文件 fallback 时使用） |
| `extensions/api/query.py` | `QueryConfig.resume_session_id`（共享基础设施）；`agent_id`/`runtime_tasks` 字段 |
| `clawcodex_ext/agent/session.py` | `Session.load()` 三分支加载（enhanced transcript / session.json / metadata+transcript） |
| `clawcodex_ext/services/session_storage.py` | `SessionStorage`（write_message / flush / read_transcript / init_metadata） |
| `clawcodex_ext/query/query.py` | `_drain_pending_user_messages`（ToolResult 边界 drain pending_messages） |
| `src/tasks/local_agent.py` | `queue_pending_message` / `drain_pending_messages` |

---

## §8 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-07-21 | 初始创建，包含 Phase 1-5 规划 + P0 Bug 修复记录 | F-129 立项 |
| 2026-07-24 | `attach` 命令废弃删除；`_send_cmd` 提取到 `control_socket.py` | 需求变更：attach TUI 冗余 |
| 2026-07-24 | 更新文档状态：Phase 1-4 已实现 | 代码审计确认实现进度 |
| 2026-07-27 | **handback 完全移除**：takeover 重新设计为纯只读快照查看器；移除 `_send_pause_and_takeover`、`_write_handback_control`、`bootstrap_session_id`、`resume_from_run_id`、`resume_run_id` 等死代码 | 需求变更：takeover 只查看不修改，不需要 handback |
| 2026-07-27 | **takeover 对话历史可见性修复**：新增 `flush_transcript` control socket 命令；`Session.load()` 空消息 fall through 到 transcript；`_ensure_session_stub` 不遮蔽已存在的 transcript | 修复 takeover REPL 看不到对话历史的问题 |
| 2026-07-27 | **inject 重新设计**：改为 pause → 写 UserMessage 到 transcript → auto-resume 三步流程；`InjectDelivered` 立即发射（不等 ToolResult 边界） | 修复 inject 消息不出现在对话历史中的问题 |
| 2026-07-27 | 文档全面更新，标记为 ✅ 已完成 | 五条命令全部实现并端到端验证通过 |

---

## §9 已知限制

### 9.1 inject 的 pause 可能超时

agent 在长 LLM 调用中时，pause 可能在 30s 内不生效。CLI 打印 warning 后继续 inject（inject 仍会在下一个 event boundary 被处理）。

### 9.2 inject 的 `--no-wait` 模式不 pause/resume

fire-and-forget 模式只发 inject 命令，不执行 pause→inject→resume 三步流程。消息仍会写入 transcript（inject handler 处理），但 agent 不暂停。

### 9.3 takeover 的 flush 有 1 秒延迟

`_send_flush_transcript` 后 `asyncio.sleep(1.0)` 等 agent 处理命令。如果 agent 在超长 LLM 调用中，flush 可能不在 1 秒内完成，takeover 会读到上一次 turn 的 transcript。

### 9.4 `_inject_pending_snippet` 残留

`agent_runner.py` 中 `session._inject_pending_snippet` 字段和 line ~2127 的 ToolResult 边界 `InjectDelivered` 发射代码仍存在但已不再触发（inject handler 不再设置此字段）。这是死代码，可在后续清理中移除。
