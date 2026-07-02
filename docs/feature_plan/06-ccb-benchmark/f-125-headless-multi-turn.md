# F-125: Headless 无头模式多轮交互支持

> **标签**: `headless`, `resume`, `entrypoint`, `multi-turn`, `ccb-gap`
>
> **状态**: 🚧 实施中（Phase 1+2 已落地，Phase 3 部分完成）
>
> **上游对标**: `claude-code-best/src/cli/print.ts`
>
> **最后更新**: 2026-07-02

---

## 1. 背景与目标

### 1.1 现状

当前 `clawcodex_ext/entrypoints/headless.py` 的 `run_headless()` 是**单次执行**模式：

- 接受一个 prompt（`-p "prompt"` 或 stdin 管道）
- 执行 agent loop（或斜杠命令）
- 输出结果
- 进程退出

上游 CCB 的 `print.ts` 也是单次执行模式，但额外支持两个扩展机制：

1. **stream-json 多消息**（SDK/CCR 传输层可以持续发送消息）
2. **`--resume` 加载历史会话**（在历史基础上继续对话）

### 1.2 目标

为 clawcodex headless 模式增加**多轮交互支持**的可行方案分析。本特性涵盖但不限于：

- `--resume` 加载历史会话 → 追加新 prompt
- `--fork-session` 加载历史会话 → 派生新会话
- stream-json 持续输入的多消息处理
- 非交互式多轮的使用体验一致性

---

## 2. 需求范围

### 2.1 P0 需求

| # | 需求 | 描述 | 上游对标 | 状态 |
|---|------|------|---------|:----:|
| R1 | `--resume <session_id>` | 加载指定会话的历史消息，在其基础上执行新 prompt | `print.ts:694-708` `loadInitialMessages()` | ✅ |
| R2 | `--continue`（`-c`） | 自动检测最近会话并 resume | `print.ts` CLI 参数 | ✅ (CLI 解析，缺 E2E 测试) |
| R3 | 会话持久化 | headless 执行结束后将会话写入 `SessionStorage`（JSONL） | `print.ts:5144` `persistSession` | ✅ |
| R4 | Session ID 统一 | resume 时复用被恢复会话的 ID，而非创建新 ID | `print.ts` 全局 session_id | ✅ |
| R5 | 文档与用户提示 | `--resume` 行为说明，输出 `session_id` 以便后续使用 | `print.ts` resume hint | ✅ |

### 2.2 P1 需求

| # | 需求 | 描述 | 上游对标 | 状态 |
|---|------|------|---------|:----:|
| R6 | `--fork-session <session_id>` | 派生新会话（加载历史但使用新 ID） | `print.ts` | ✅ |
| R7 | `--resume-session-at <index>` | 恢复到历史会话的指定消息索引处 | `print.ts` | ✅ |
| R8 | session metadata 保留 | title、tags、agent 设置等元数据随 `--resume` 恢复 | `print.ts` | 🚧 |
| R9 | 文件系统状态种子（readFileState） | 从历史消息中提取文件的读取状态，使 Edit 工具能检测外部修改 | `print.ts:1173-1176` | ✅ |

### 2.3 P2 需求

| # | 需求 | 描述 | 状态 |
|---|------|------|:----:|
| R10 | `--append-system-prompt` 兼容性检查 | resume 时检查 system prompt 变化并警告 | 🚧 |
| R11 | Provider/Model 不匹配警告 | resume 时 provider/model 与原会话不同时发出警告 | 🚧 |
| R12 | Cost tracking 累积 | 恢复时读取原会话的累计消耗，合并到当前运行 | 🚧 |

---

## 3. 实施路径

### 3.1 阶段性方案

#### Phase 1：基础设施统一（前置依赖）

将 `run_headless()` 迁移到使用 `RuntimeContext.build()`，消除 provider/registry/context/session 的双代码路径。

**改动文件**：
- `clawcodex_ext/entrypoints/headless.py` — 使用 `RuntimeContext` 替代手搓 setup
- `clawcodex_ext/runtime/context.py` — 验证 headless 路径的兼容性
- `clawcodex_ext/frontend/headless.py` — `HeadlessFrontend.run()` 透传 session

**验收**：
- [x] headless 通过 `RuntimeContext.build()` 创建 provider/tool_registry/tool_context（`HeadlessFrontend.run()` 经 `external_session` 透传）
- [x] 现有功能回归测试通过（稳定性门禁 Stage 1-6 全通过）
- [x] `run_headless()` 不再有独立的 Session.create() 作为唯一路径（三分支：external_session / resume_session_id / fresh create）

#### Phase 2：Session 加载与持久化

| 子特性 | 改动 | 风险 |
|--------|------|:----:|
| `HeadlessOptions` 增加 `resume_session_id` 字段 | `headless.py:128-150` | 低 |
| `HeadlessFrontend.run()` 传递 resume 参数 | `frontend/headless.py:27-49` | 低 |
| resume 时复用 session_id | `headless.py:226-238` → `Session.resume()` | 中 |
| 对话结束后持久化到 `SessionStorage` | `headless.py:799-818` finally 块 | 中 |
| `persist_on_exit` 默认 True | `headless.py:145-150` | 低 |

**验收**：
- [x] `clawcodex -p "hello" --resume abc123` 加载历史并输出回复
- [x] 第二次 `-p "继续" --resume abc123` 能看到第一次的回复（`test_resume_accumulates_history_across_two_runs`）
- [x] 输出格式 `text` / `json` / `stream-json` 均有 `session_id`

#### Phase 3：边角修复

- ✅ `--allowed-tools` 与 resume 的历史工具兼容性（C5 警告）
- ✅ telemetry session_id 统一（C4 已在 Phase 2 一并解决）
- ✅ `--fork-session` 支持（R6）
- ✅ `--resume-session-at` 支持（R7）
- ✅ readFileState 种子（C9 / R9）
- ✅ R3 跨轮累积 E2E 验证
- 🚧 `--continue` 验证路径对齐（端到端测试待补）
- 🚧 session metadata 保留（R8）
- 🚧 `append_system_prompt` 时序警告（C8 / R10）
- 🚧 Provider/Model 不匹配警告（C11 / R11）
- 🚧 Cost tracking 累积（C10 / R12）
- 🚧 JSONL 并发写入文件锁（C13）
- 🚧 TailFollower 泄漏修复（C14）

---

## 4. `--resume` 冲突全景分析

### 4.1 结构级冲突

#### C1：双代码路径漂移

`RuntimeContext.build()`（`runtime/context.py:151-156`）已实现 resume 逻辑，但 `run_headless()` 完全不使用 `RuntimeContext`，从零搭建 provider/registry/context/session。

```python
# runtime/context.py — 已有 resume 支持
if options.resume_session_id:
    session, _tail = resume_session_with_tail(options.resume_session_id)

# headless.py — 完全绕过，永远创建新 session
session = Session.create(provider_name, model)
```

**修复**：`HeadlessFrontend.run()`（`clawcodex_ext/frontend/headless.py`）通过 `external_session=ctx.session` 把 RuntimeContext 产出的 session 透传给 `run_headless`。当 dispatch.py 通过 RuntimeContext.build() 走时，headless 路径接收已构造好的 session（含 resume/fork/create 结果），消除双代码路径。

#### C2：Session ID 双重性

`run_headless()` 第187行 `Session.create()` 永远生成新 session_id。如果 `--resume abc123`，新对话的 session_id 是 def456 而非 abc123。

```
Session 层面:  abc123（--resume 指定的）
    ↓ 加载历史消息作为 initial_messages
Conversation:  Session.create() 的新 session_id = def456
    ↓ 新对话被写入 def456
后续 --resume abc123 → 看不到 def456 的内容
后续 --resume def456 → 看不到 abc123 的历史
```

**修复**：resume 时通过 `Session.resume()` 复用被恢复会话的 session_id，`_persist` 回调和持久化路径都写入原始 ID。仅在 `--fork-session` 时创建新 ID。

#### C3：`_persist` 回调归属

`run_headless()` 的 `_persist` 回调将消息写入当前 `session.conversation`（内存）。如果历史来自 session A、但当前 session 是 B，写入的是 B 而非 A。LLM 调用时上下文正确（因为 initial_messages 包含 A 的历史），但持久化时路径错误。

**修复**：C2 修复后 resume 路径复用原始 session，`_persist` 自然写入正确的 session。

#### C4：Telemetry session_id 不一致

```python
record_session_start(
    session_id=session.session_id,  # 新 ID，而非被恢复的 ID
    ...
)
```

聚合分析无法将 headless 恢复的轮次与原始会话关联。

**修复**：`run_headless()` 中 session 装配后统一用 `session.session_id` 调用 `record_session_start`。resume 时 session_id 为原始 ID，telemetry 与持久化路径一致。

#### C5：`--allowed-tools` 静默过滤历史工具

```python
if options.allowed_tools:
    _filter_registry(tool_registry, keep=lambda n: n.lower() in allow)
```

如果原始会话使用了 tool X（已记录在历史消息的 tool_use/tool_result 中），但恢复运行时 `--allowed-tools` 未包含 X，X 被移除。LLM 在上下文中看到工具调用记录但无法调用——导致幻觉、重试循环、报错。

**修复**：`_warn_history_tool_conflicts()`（`headless.py:1183-1255`）在 registry 过滤后扫描历史消息的 tool_use 名称，若被移除则 stderr 打印警告。`test_allowed_tools_conflict_warns_when_history_tool_filtered_out` 覆盖此场景。

### 4.2 语义级冲突

#### C6："恢复" vs "快照重启"认知陷阱

用户预期的 `--resume`：

```
run 1: -p "写个测试"           → session A 创建
run 2: -p "再优化" --resume A → 继续 A，内容追加到 A
run 3: -p "加日志" --resume A → 看到 run 1+2+3 的所有内容
```

没有持久化时的实际行为：

```
run 2: -p "再优化" --resume A → 加载 A 的消息，但新内容无法存回 A
run 3: -p "加日志" --resume A → 还是只看到 A 的原始历史
```

**用户以为在"继续"，实际是"基于快照重启"。**

**修复**：`persist_on_exit=True` 为 `HeadlessOptions` 默认值，`run_headless()` finally 块调用 `session.save()` 将累积的 transcript 写入磁盘。后续 `--resume <sid>` 加载包含新消息的完整历史。`test_resume_accumulates_history_across_two_runs` 端到端验证此行为。

#### C7：`--continue` 语义侵蚀

dispatch.py 将 `--continue` 解析为 `--resume <last_session>`。持久化落地后，`--continue` 行为与用户预期的"继续上一个会话"一致。

**修复**：C6 持久化 + C2 session_id 复用的组合使 `--continue` 正确追加内容到最近会话。

#### C8：`append_system_prompt` 时序混淆

原始会话使用系统提示 P_old，恢复运行时使用 P_new。LLM 看到的历史消息是在 P_old 指导下生成的，但当前系统提示是 P_new。模型不知道该用哪个策略来回应。

**当前状态**：🚧 待修复。计划在 resume 时检测新旧 system prompt 差异并在 stderr 发出警告。

### 4.3 状态级冲突

#### C9：文件系统状态漂移

原始运行中 LLM 读取了 `src/main.py`（内容 V1）。恢复运行时该文件已被修改为 V2。LLM 上下文中看到 V1 的内容但磁盘上是 V2。如果 LLM 接着编辑该文件——上游的 `readFileState` 种子机制会检测差异并重新读取，但 clawcodex headless 没有此机制。

上游 `print.ts:1173-1176`：

```typescript
let readFileState = extractReadFilesFromMessages(
    initialMessages,  // 从恢复的历史消息中提取文件状态
)
```

**没有这个种子，Edit 工具的"检测外部修改"功能在恢复后会失效。**

**修复**：新建 `clawcodex_ext/agent/read_file_seed.py`，实现 `seed_read_file_state_from_history()`，从历史消息的 `tool_use` 块中提取 `Read` 调用的 `file_path`，调用 `context.mark_file_read()` 植入 `read_file_fingerprints`。在 `run_headless()` tool_context 构建后接入（`headless.py:434-458`）。支持 partial read 标记（offset/limit），缺失文件静默跳过。

#### C10：Cost tracking 归零

每次 `run_headless()` 创建新的 `CostTracker`。即使 `--resume` 恢复了对话上下文，原始会话的花费丢失了。

**当前状态**：🚧 待修复（P2）。计划在 `Session.resume()` 时读取累积消耗，合并到当前 `CostTracker`。

#### C11：MCP 服务器状态不同步

如果原始会话连接了 MCP 服务器 S，对话历史中包含对 S 的工具调用。恢复运行时 S 没启动——LLM 在上下文中看到 S 的工具记录但 registry 中没有对应工具。

**当前状态**：🚧 待修复（P2）。属于 MCP 框架层问题，非 headless 独有。C5 `--allowed-tools` 警告机制可间接缓解（工具不存在时会警告）。

#### C12：Hook side effects 丢失

原始会话中 post_sampling_hooks 或 session_hooks 修改了请求/响应。恢复运行时这些 hook 不会重播，但历史消息中已经包含了 hook 处理后的结果。

**当前状态**：🚧 待修复（P2）。影响面有限——历史消息中的工具调用结果已保存，不重播 hook 不影响下游推理正确性，仅在严格审计场景中需要复现原始请求形变。

### 4.4 并发级冲突

#### C13：JSONL 文件并发损坏

```
终端1: clawcodex -p "任务1" --resume abc123
终端2: clawcodex -p "任务2" --resume abc123  # 同时
```

两个进程都加载同一文件，各自追加写入，文件内容交错损坏。上游通过 `resetSessionFilePointer()` 和 append-only 写入缓解，但多进程并发仍然不安全。

**当前状态**：🚧 待修复（P2）。需要文件锁（`fcntl.flock` 或 `portalocker`）保护 append 写入路径。

#### C14：TailFollower 泄漏

`resume_session_with_tail()` 返回 `TailFollower` 用于监听 session 文件变化。headless 获取后既不使用也不关闭——文件描述符泄漏。

**当前状态**：🚧 已识别（P2）。`RuntimeContext.build()` 在 resume 时通过 `resume_session_with_tail` 获取 TailFollower 但未关闭。修复方式：headless 路径调用后显式关闭 follower，或为 `RuntimeContext.build()` 新增 `close_tail_follower()` 方法。

### 4.5 冲突矩阵

| 编号 | 冲突 | 层级 | 严重度 | 修复成本 | 依赖 | 状态 |
|------|------|------|:------:|:--------:|:----:|:----:|
| C1 | 双代码路径漂移 | 结构 | 🔴 高 | 大 | Phase 1 | ✅ 已修复 |
| C2 | Session ID 双重性 | 结构 | 🔴 高 | 中 | C1 | ✅ 已修复 |
| C3 | `_persist` 归属混乱 | 结构 | 🔴 高 | 中 | C1 | ✅ 已修复 |
| C4 | Telemetry ID 不一致 | 结构 | 🟡 中 | 低 | C2 | ✅ 已修复 |
| C5 | `--allowed-tools` 静默过滤 | 结构 | 🟡 中 | 低 | — | ✅ 已修复（警告） |
| C6 | "恢复" vs "快照重启"认知 | 语义 | 🔴 高 | 大 | C2 + 持久化 | ✅ 已修复 |
| C7 | `--continue` 语义侵蚀 | 语义 | 🔴 高 | 大 | C6 | ✅ 已修复（持久化落地） |
| C8 | `append_system_prompt` 混淆 | 语义 | 🟡 中 | 低 | — | 🚧 待修复 |
| C9 | 文件系统状态漂移 | 状态 | 🟡 中 | 中 | — | ✅ 已修复（种子） |
| C10 | Cost tracking 归零 | 状态 | 🟢 低 | 低 | — | 🚧 待修复 |
| C11 | MCP 服务器不同步 | 状态 | 🟡 中 | 中 | — | 🚧 待修复 |
| C12 | Hook side effects 丢失 | 状态 | 🟢 低 | 低 | — | 🚧 待修复 |
| C13 | JSONL 并发写入损坏 | 并发 | 🔴 高 | 大 | 持久化 | 🚧 待修复 |
| C14 | TailFollower 泄漏 | 并发 | 🟢 低 | 低 | — | 🚧 待修复 |

---

## 5. 风险与约束

### 5.1 设计约束

1. **不在 `src/` 中添加新代码**：所有改动位于 `clawcodex_ext/`（补丁层）
2. **不破坏现有 headless 单次执行语义**：未使用 `--resume`/`--continue` 时行为完全不变
3. **不与斜杠命令执行冲突**：`clawcodex -p "/cost" --resume xxx` 应加载历史但不浪费 I/O（斜杠命令 `continue` 跳出后，历史加载的开销白费——当前可接受，后续可以延迟加载优化）

### 5.2 实施风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| `run_headless()` 重构为 `RuntimeContext` 的回归风险 | 高 | 充分测试覆盖（Stage 1-6 + 斜杠命令 E2E） |
| 持久化后 JSONL 文件结构变化 | 中 | 向后兼容现有 SessionStorage 格式 |
| `--continue` 与 `--resume` 路径的 dispatch 混乱 | 中 | Phase 2 验证后再启用 |

### 5.3 边界场景

| 场景 | 行为 |
|------|------|
| `--resume` 指向不存在的 session_id | 报错退出，不清除用户输入 |
| `--resume` + `--fork-session` 同时使用 | `--resume` 优先，`--fork-session` 被忽略 |
| `--resume` + 斜杠命令（如 `/cost`） | 加载历史（可能需要），执行斜杠命令，跳过 agent loop |
| `--resume` + stream-json 多消息 | 加载历史作为初始上下文，后续每条 stdin 消息追加到同一会话 |
| session 文件被损坏/截断 | graceful 降级：加载可读部分，日志记录错误，继续执行 |

---

## 6. 依赖与协同

| 特性 | 关系 | 说明 |
|------|------|------|
| F-49 Session 管理统一 | 🔗 前置 | session 的 CRUD + 持久化 API 需先到位 |
| F-97 Telemetry 追踪 | 🤝 协同 | telemetry session_start/end 需与 session_id 对齐 |
| F-89 Agent Name 展开 | 🤝 协同 | `@agent-name` 展开在 resume 场景中需正确处理历史消息 |
| F-108 Freeze Detection | 🤝 协同 | headless future 超时与 resume 后的持久化互不干扰 |
| F-122 BTW Side Question | 🤝 协同 | Headless 模式 `/btw` 退化为 stdout 打印的规则同样适用 |
| 斜杠命令（刚实现） | 🤝 协同 | resume 后斜杠命令支持自然继承 |

---

## 7. 验收标准

### 7.1 Phase 1 验收

- [x] 稳定性门禁全量通过（Stage 1-6 共 268 passed）
- [x] 存在斜杠命令的测试场景
- [x] text 输出格式末尾打印 `session_id` resume hint

### 7.2 Phase 2 验收

- [x] `clawcodex -p "hello" --resume <sid>` 输出回复并显示 session_id
- [x] `clawcodex -p "继续" --resume <sid>` 看到上一轮的回复（`test_resume_accumulates_history_across_two_runs`）
- [ ] `clawcodex -p "hello" --continue` 自动检测最近会话（端到端测试待补）
- [x] json 输出中 `session_id` 字段正确
- [x] stream-json 输出中 `init` 事件的 `session_id` 正确

### 7.3 Phase 3 验收

- [x] `--fork-session <sid>` 创建新会话但保留历史
- [x] `--resume-session-at N` 正确截断到指定消息
- [x] `--allowed-tools` 与历史工具冲突时发出警告
- [ ] session metadata（title/tags/agent）随 resume 恢复（R8 待补）
- [ ] 多进程并发 resume 不会产生损坏文件（文件锁保护，C13 待补）
- [x] readFileState 种子从历史消息恢复文件读取状态（C9 / R9）

---

## 8. 参考

- 上游实现：`/mnt/c/WorkSpace/claude-code-best/src/cli/print.ts`（5843 行）
- 上游 `loadInitialMessages()`：`print.ts:5141-5424`
- 上游 `StructuredIO` 多消息支持：`print.ts:3011-4345`（`for await` stdin 循环）
- 当前实现：`clawcodex_ext/entrypoints/headless.py`（1101 行）
- RuntimeContext 统一上下文：`clawcodex_ext/runtime/context.py`（277 行）
- 斜杠命令实现：`clawcodex_ext/entrypoints/headless.py:353-438`
- 会话持久化：`src/services/session_storage.py` / `clawcodex_ext/services/session_storage.py`
- readFileState 种子：`clawcodex_ext/agent/read_file_seed.py`
- 测试覆盖：`tests/cli/test_headless_resume.py`

---

## 9. 实施进度（Implementation Log）

### Phase 1 — 基础设施统一 ✅ 已完成

- `HeadlessOptions` 新增 `resume_session_id` / `fork_session_id` / `resume_session_at` / `external_session` / `persist_on_exit` 字段（`headless.py:128-150`）
- `RuntimeContext.build()` 已支持 resume / fork / resume_at 三分支 session 装配（`runtime/context.py:149-180`）
- `HeadlessFrontend.run()` 通过 `external_session=ctx.session` 把 RuntimeContext 产出的 session 透传给 `run_headless`，消除双代码路径（C1）
- `dispatch.py` 解析 `--resume` / `--continue` / `--fork-session` / `--resume-session-at` 并注入 `RuntimeOptions`（`dispatch.py:493-516`）
- `parser.py` 注册全部 CLI 参数（`parser.py:113-141`）
- `_parse_resume_at` 解析函数（`dispatch.py:823-836`）

### Phase 2 — Session 加载与持久化 ✅ 已完成

- `run_headless()` session 装配三分支：`external_session` → `resume_session_id` → fresh `Session.create()`（`headless.py:211-240`），解决 C1/C2/C3
- `resume_session_id` 路径复用原 session_id（`Session.resume()`），解决 C2 session-id 双重性
- `fork_session_id` 路径加载历史但 mint 新 session_id（`headless.py:249-265`）
- `resume_session_at` 截断到指定消息索引（`headless.py:267-283`）
- `persist_on_exit=True` 默认 + finally 块 `session.save()`（`headless.py:799-818`），解决 C6 认知陷阱
- Telemetry 使用 `session.session_id`（resume 时为原 ID），解决 C4
- `print_resume_hint` 在 text 输出末尾打印 resume 提示（R5）

### Phase 3 — 边角修复 🚧 部分完成

#### 已完成（2026-07-02）

- **C9 / R9 readFileState 种子**：新建 `clawcodex_ext/agent/read_file_seed.py`（209 行），从历史消息提取 `Read` tool_use 块的 `file_path`，调用 `context.mark_file_read()` 植入 `read_file_fingerprints`。在 `run_headless()` tool_context 构建后接入（`headless.py:434-458`）。支持 partial read 标记（offset/limit），缺失文件静默跳过。Edit/Write/NotebookEdit 的 `was_file_read_and_unchanged` staleness 检查在 resume 后可正常工作。
- **C5 `--allowed-tools` 冲突警告**：`_warn_history_tool_conflicts()`（`headless.py:1183-1255`）在 registry 过滤后扫描历史消息的 tool_use 名称，若被移除则 stderr 打印警告。避免 LLM 看到工具调用记录但无法调用的幻觉/重试循环。
- **R3 跨轮累积 E2E 测试**：`test_resume_accumulates_history_across_two_runs` 验证 run 1 持久化后，run 2 `--resume` 能在加载的历史中看到 run 1 的 assistant 回复。

#### 测试覆盖（`tests/cli/test_headless_resume.py`，14 passed）

| 测试 | 覆盖项 |
|------|--------|
| `test_headless_external_session_keeps_session_id` | C2 — external_session 复用 ID |
| `test_headless_persists_new_messages_into_resumed_session` | C6 — persist_on_exit |
| `test_headless_direct_resume_session_id_creates_loads_and_keeps_id` | C2 — direct resume 路径 |
| `test_headless_resume_unknown_session_id_exits_2` | 边界 — 不存在的 session_id |
| `test_headless_fork_session_copies_history_and_uses_new_id` | R6 — fork 派生新 ID |
| `test_headless_resume_session_at_truncates` | R7 — 索引截断 |
| `test_headless_resume_session_at_out_of_range_exits_2` | 边界 — 索引越界 |
| `test_read_file_seed_marks_files_from_history` | C9/R9 — 种子植入 |
| `test_read_file_seed_skips_missing_files` | C9 — 缺失文件静默跳过 |
| `test_read_file_seed_marks_partial_reads` | C9 — partial 标记 |
| `test_allowed_tools_conflict_warns_when_history_tool_filtered_out` | C5 — 冲突警告 |
| `test_allowed_tools_no_warning_when_history_tool_present` | C5 — 无冲突时静默 |
| `test_allowed_tools_no_warning_on_fresh_session` | C5 — 新会话不警告 |
| `test_resume_accumulates_history_across_two_runs` | R3 — 跨轮累积 E2E |

#### 未完成（后续迭代）

| 项 | 优先级 | 说明 |
|----|--------|------|
| R8 session metadata 保留 | P1 | title/tags/agent 随 resume 恢复 |
| C8 `append_system_prompt` 时序警告 | P2 | R10 — system prompt 变化警告 |
| C11 Provider/Model 不匹配警告 | P2 | R11 — resume 时 provider/model 差异警告 |
| C10 Cost tracking 累积 | P2 | R12 — 恢复原会话累计消耗 |
| C13 JSONL 并发写入文件锁 | P2 | 多进程并发 resume 保护 |
| C14 TailFollower 泄漏修复 | P2 | resume_session_with_tail 返回的 follower 需关闭 |
| `--continue` 端到端测试 | P1 | R2 — 自动检测最近会话 E2E |

### 验收状态

- ✅ Phase 1 验收：稳定性门禁 Stage 1-6 全通过（262+6 passed），ruff lint 通过
- ✅ Phase 2 验收：`--resume` 复用 session_id、跨轮累积、json/text 输出含 session_id、persist_on_exit
- 🚧 Phase 3 验收：C9 种子 + C5 警告 + R3 E2E 已完成；fork/at/metadata 待补
