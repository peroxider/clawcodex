# F-125: Headless 无头模式多轮交互支持

> **标签**: `headless`, `resume`, `entrypoint`, `multi-turn`, `ccb-gap`
>
> **状态**: 📋 规划中
>
> **上游对标**: `claude-code-best/src/cli/print.ts`
>
> **最后更新**: 2026-06-30

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

| # | 需求 | 描述 | 上游对标 |
|---|------|------|---------|
| R1 | `--resume <session_id>` | 加载指定会话的历史消息，在其基础上执行新 prompt | `print.ts:694-708` `loadInitialMessages()` |
| R2 | `--continue`（`-c`） | 自动检测最近会话并 resume | `print.ts` CLI 参数 |
| R3 | 会话持久化 | headless 执行结束后将会话写入 `SessionStorage`（JSONL） | `print.ts:5144` `persistSession` |
| R4 | Session ID 统一 | resume 时复用被恢复会话的 ID，而非创建新 ID | `print.ts` 全局 session_id |
| R5 | 文档与用户提示 | `--resume` 行为说明，输出 `session_id` 以便后续使用 | `print.ts` resume hint |

### 2.2 P1 需求

| # | 需求 | 描述 | 上游对标 |
|---|------|------|---------|
| R6 | `--fork-session <session_id>` | 派生新会话（加载历史但使用新 ID） | `print.ts` |
| R7 | `--resume-session-at <index>` | 恢复到历史会话的指定消息索引处 | `print.ts` |
| R8 | session metadata 保留 | title、tags、agent 设置等元数据随 `--resume` 恢复 | `print.ts` |
| R9 | 文件系统状态种子（readFileState） | 从历史消息中提取文件的读取状态，使 Edit 工具能检测外部修改 | `print.ts:1173-1176` |

### 2.3 P2 需求

| # | 需求 | 描述 |
|---|------|------|
| R10 | `--append-system-prompt` 兼容性检查 | resume 时检查 system prompt 变化并警告 |
| R11 | Provider/Model 不匹配警告 | resume 时 provider/model 与原会话不同时发出警告 |
| R12 | Cost tracking 累积 | 恢复时读取原会话的累计消耗，合并到当前运行 |

---

## 3. 实施路径

### 3.1 阶段性方案

#### Phase 1：基础设施统一（前置依赖）

将 `run_headless()` 迁移到使用 `RuntimeContext.build()`，消除 provider/registry/context/session 的双代码路径。

**改动文件**：
- `clawcodex_ext/entrypoints/headless.py` — 使用 `RuntimeContext` 替代手搓 setup
- `clawcodex_ext/runtime/context.py` — 验证 headless 路径的兼容性
- `clawcodex_ext/cli/runners.py` — `run_print_mode()` 传输 resume 参数

**验收**：
- [ ] headless 通过 `RuntimeContext.build()` 创建 provider/tool_registry/tool_context
- [ ] 现有功能回归测试通过（稳定性门禁 332 passed）
- [ ] `run_headless()` 不再有独立的 Session.create()

#### Phase 2：Session 加载与持久化

| 子特性 | 改动 | 风险 |
|--------|------|:----:|
| `HeadlessOptions` 增加 `resume_session_id` 字段 | `headless.py:79-126` | 低 |
| `run_print_mode()` 传递 `args.resume` | `runners.py:106-120` | 低 |
| resume 时复用 session_id | `headless.py:187` → 调用 `SessionStorage.session_dir()` | 中 |
| 对话结束后持久化到 `SessionStorage` | `headless.py` finally 块新增 | 中 |
| 文件指针管理（reset + append） | 对齐 `SessionStorage` API | 中 |

**验收**：
- [ ] `clawcodex -p "hello" --resume abc123` 加载历史并输出回复
- [ ] 第二次 `-p "继续" --resume abc123` 能看到第一次的回复
- [ ] 输出格式 `text` / `json` / `stream-json` 均有 `session_id`

#### Phase 3：边角修复

- `--continue` 验证路径对齐
- `--allowed-tools` 与 resume 的历史工具兼容性
- telemetry session_id 统一
- `--fork-session` 支持
- `--resume-session-at` 支持

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

**修复**：Phase 1 强制 headless 使用 `RuntimeContext`。

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

**修复**：resume 时复用被恢复会话的 session_id，仅在 `--fork-session` 时创建新 ID。

#### C3：`_persist` 回调归属

`run_headless()` 第492行的 `_persist` 回调将消息写入当前 `session.conversation`（内存）。如果历史来自 session A、但当前 session 是 B，写入的是 B 而非 A。LLM 调用时上下文正确（因为 initial_messages 包含 A 的历史），但持久化时路径错误。

#### C4：Telemetry session_id 不一致

```python
record_session_start(
    session_id=session.session_id,  # 新 ID，而非被恢复的 ID
    ...
)
```

聚合分析无法将 headless 恢复的轮次与原始会话关联。

#### C5：`--allowed-tools` 静默过滤历史工具

```python
if options.allowed_tools:
    _filter_registry(tool_registry, keep=lambda n: n.lower() in allow)
```

如果原始会话使用了 tool X（已记录在历史消息的 tool_use/tool_result 中），但恢复运行时 `--allowed-tools` 未包含 X，X 被移除。LLM 在上下文中看到工具调用记录但无法调用——导致幻觉、重试循环、报错。

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

#### C7：`--continue` 语义侵蚀

dispatch.py 第387行将 `--continue` 解析为 `--resume <last_session>`。如果 headless 的 `--resume` 不持久化，`--continue` 就变成了"用上次的上下文重跑一次"——完全不同的语义。

#### C8：`append_system_prompt` 时序混淆

原始会话使用系统提示 P_old，恢复运行时使用 P_new。LLM 看到的历史消息是在 P_old 指导下生成的，但当前系统提示是 P_new。模型不知道该用哪个策略来回应。

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

#### C10：Cost tracking 归零

每次 `run_headless()` 创建新的 `CostTracker`。即使 `--resume` 恢复了对话上下文，原始会话的花费丢失了。

#### C11：MCP 服务器状态不同步

如果原始会话连接了 MCP 服务器 S，对话历史中包含对 S 的工具调用。恢复运行时 S 没启动——LLM 在上下文中看到 S 的工具记录但 registry 中没有对应工具。

#### C12：Hook side effects 丢失

原始会话中 post_sampling_hooks 或 session_hooks 修改了请求/响应。恢复运行时这些 hook 不会重播，但历史消息中已经包含了 hook 处理后的结果。

### 4.4 并发级冲突

#### C13：JSONL 文件并发损坏

```
终端1: clawcodex -p "任务1" --resume abc123
终端2: clawcodex -p "任务2" --resume abc123  # 同时
```

两个进程都加载同一文件，各自追加写入，文件内容交错损坏。上游通过 `resetSessionFilePointer()` 和 append-only 写入缓解，但多进程并发仍然不安全。

#### C14：TailFollower 泄漏

`resume_session_with_tail()` 返回 `TailFollower` 用于监听 session 文件变化。headless 获取后既不使用也不关闭——文件描述符泄漏。

### 4.5 冲突矩阵

| 编号 | 冲突 | 层级 | 严重度 | 修复成本 | 依赖 |
|------|------|------|:------:|:--------:|:----:|
| C1 | 双代码路径漂移 | 结构 | 🔴 高 | 大 | Phase 1 |
| C2 | Session ID 双重性 | 结构 | 🔴 高 | 中 | C1 |
| C3 | `_persist` 归属混乱 | 结构 | 🔴 高 | 中 | C1 |
| C4 | Telemetry ID 不一致 | 结构 | 🟡 中 | 低 | C2 |
| C5 | `--allowed-tools` 静默过滤 | 结构 | 🟡 中 | 低 | — |
| C6 | "恢复" vs "快照重启"认知 | 语义 | 🔴 高 | 大 | C2 + 持久化 |
| C7 | `--continue` 语义侵蚀 | 语义 | 🔴 高 | 大 | C6 |
| C8 | `append_system_prompt` 混淆 | 语义 | 🟡 中 | 低 | — |
| C9 | 文件系统状态漂移 | 状态 | 🟡 中 | 中 | — |
| C10 | Cost tracking 归零 | 状态 | 🟢 低 | 低 | — |
| C11 | MCP 服务器不同步 | 状态 | 🟡 中 | 中 | — |
| C12 | Hook side effects 丢失 | 状态 | 🟢 低 | 低 | — |
| C13 | JSONL 并发写入损坏 | 并发 | 🔴 高 | 大 | 持久化 |
| C14 | TailFollower 泄漏 | 并发 | 🟢 低 | 低 | — |

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

- [ ] 稳定性门禁全量通过（332 passed）
- [ ] 存在斜杠命令的测试场景
- [ ] text 输出格式末尾打印 `session_id` resume hint

### 7.2 Phase 2 验收

- [ ] `clawcodex -p "hello" --resume <sid>` 输出回复并显示 session_id
- [ ] `clawcodex -p "继续" --resume <sid>` 看到上一轮的回复
- [ ] `clawcodex -p "hello" --continue` 自动检测最近会话
- [ ] json 输出中 `session_id` 字段正确
- [ ] stream-json 输出中 `init` 事件的 `session_id` 正确

### 7.3 Phase 3 验收

- [ ] `--fork-session <sid>` 创建新会话但保留历史
- [ ] `--resume-session-at N` 正确截断到指定消息
- [ ] `--allowed-tools` 与历史工具冲突时发出警告
- [ ] session metadata（title/tags/agent）随 resume 恢复
- [ ] 多进程并发 resume 不会产生损坏文件（文件锁保护）

---

## 8. 参考

- 上游实现：`/mnt/c/WorkSpace/claude-code-best/src/cli/print.ts`（5843 行）
- 上游 `loadInitialMessages()`：`print.ts:5141-5424`
- 上游 `StructuredIO` 多消息支持：`print.ts:3011-4345`（`for await` stdin 循环）
- 当前实现：`clawcodex_ext/entrypoints/headless.py`（921 行）
- RuntimeContext 统一上下文：`clawcodex_ext/runtime/context.py`（277 行）
- 斜杠命令实现：`clawcodex_ext/entrypoints/headless.py:353-438`
- 会话持久化：`src/services/session_storage.py` / `clawcodex_ext/services/session_storage.py`
