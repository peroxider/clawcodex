# F-87: /ultraplan LLM 驱动 + CLI 完整实现

> 状态: ✅ 已完成(`clawcodex_ext/services/ultraplan/` 15 模块 + `/ultraplan` 斜杠命令 + CCR 远程会话 + LLM Planner + 关键字检测 + 彩虹高亮 + TUI 面板)
> 章节: `docs/feature_plan/06-ccb-benchmark/f-87-ultraplan.md`
> 最后更新: 2026-07-21
> 缺口来源: [README.md §A 缺口矩阵](./README.md#a-全特性对照矩阵)

## §1 设计规划

### 1.1 目标

对标 CCB `src/commands/ultraplan.tsx`(525 行)+ `src/utils/ultraplan/ccrSession.ts`(349 行),在 ClawCodex 已落地的 `clawcodex_ext/services/ultraplan/` 原语层之上,补齐用户面向的四件套:

1. **LLM 驱动 Plan 生成** —— 用户描述目标 → 调 LLM → 生成 `Plan` JSON;
2. **`/ultraplan` 斜杠命令** —— 命令行入口,串联 LLM 规划 → 落地展示 → 用户确认 → 执行;
3. **CCR 远程会话** —— 本地/远程双模式,经由 F-82 RCS 在远程 worker 上跑 Plan 执行;
4. **关键字检测 + 彩虹高亮** —— 输入框实时识别 `/ultraplan` 触发词,在 TUI 中渲染彩虹片段提示,降低用户认知负担。

### 1.2 背景

**已完成原语层**(F-83 first iteration,`clawcodex_ext/services/ultraplan/`,共 6 模块):

| 模块 | 角色 | 关键导出 |
|------|------|----------|
| `models.py` | Plan → SubPlan → Step + AcceptanceCriteria 四层数据模型 + 状态枚举 + 校验 | `Plan` / `SubPlan` / `Step` / `AcceptanceCriteria` / `PlanStatus` / `StepStatus` / `StepKind` / `CheckKind` |
| `store.py` | 原子 JSON 持久化(thread-safe RLock + tmp + rename,无 SQLite 依赖) | `PlanStore` |
| `executor.py` | 步骤状态机(`PENDING → IN_PROGRESS → COMPLETED/FAILED/SKIPPED/BLOCKED`)+ 审计日志 | `PlanExecutor` / `StepTransition` / `Progress` |
| `verifier.py` | 验收标准沙箱执行器(FILE_EXISTS / FILE_CONTAINS / PYTHON_PREDICATE / SHELL_COMMAND / CUSTOM,白名单 globals + `shlex` 防注入) | `AcceptanceVerifier` / `CheckResult` |
| `adjuster.py` | 中途变更 Plan(add / replace / remove step/subplan,保持 step id 唯一 + 跨子计划依赖拒绝) | `PlanAdjuster` |
| `exceptions.py` | 业务异常层级(`UltraplanError` 根 + 12 个具体子类) | `PlanNotFoundError` / `IllegalStepTransitionError` / `UnsafeCheckExpressionError` 等 |

**测试覆盖**: `tests/services/ultraplan/` 5 个文件(`test_models/store/executor/verifier/adjuster`),覆盖模型校验、原子写、状态机迁移、白名单 predicate、adjuster 不变量。

**现状评估**:

- 原语层是"无 LLM 依赖的安全底座",所有副作用走 `subprocess.run` argv 列表(无 `shell=True`),`PYTHON_PREDICATE` globals 白名单 + dunder 拦截,`SHELL_COMMAND` 经 `shlex.split`;
- `__init__.py` 明确声明:"LLM-driven prompt generation (P83-A) and the `/ultraplan` CLI command (P83-B) are explicitly deferred to later iterations",为 F-87 留好接口;
- `AcceptanceCriteria` 模型直接镜像 CCB 上游 `Plan → SubPlan → Step → acceptance list` 结构,LLM 生成的 JSON 可以零成本落地;
- LLM Provider 已落地: `clawcodex_ext/providers/` (`BaseProvider.chat / chat_stream / chat_async / chat_stream_response`),`factory.py` + `runtime.py` 提供异步运行时选择;
- 命令系统注册入口已规范化: `clawcodex_ext/command_system/builtins.py::register_builtin_commands()` 调用 `get_builtin_commands()` 列表,通过 `CommandRegistry.register(cmd)` 注入,新增命令不需改 `src/command_system/builtins.py`;
- 远程桥接已落地: `extensions/ports/bridge/bridge_main.py`(986 行) + `remote_bridge_core.py` 提供 RCS 风格 HTTP/SSE;
- 输入处理统一入口: `clawcodex_ext/command_system/input_processing.py`(不是 `repl/input_processing.py` —— 缺口分析条目路径需要修正)。

**已完成**(用户面向层):

P87-A~K 已全部落地:P87-A `llm_planner.py` 接入 Provider 生成 `Plan` JSON;P87-B `templates.py` 内置 4 类预制 prompt;P87-C `ccr_session.py` 支持本地/远程双模式;P87-D `/ultraplan` 命令族 9 子命令;P87-E `keyword_detector.py` 触发词检测;P87-F TUI 彩虹高亮;P87-G 本地/远程切换;P87-H TUI Plan 状态面板;P87-I `audit.py` NDJSON 审计;P87-J `planner_recovery.py` 失败重试 + 提示;P87-K 13 个测试文件覆盖。详见 `clawcodex_ext/services/ultraplan/`、`clawcodex_ext/command_system/ultraplan_command.py`、`tests/services/ultraplan/`。

### 1.3 子特性分解

| 编号 | 子特性 | 状态 | 预计工作量 |
|:----:|--------|:----:|:----------:|
| P87-A | LLM Plan 生成器(`llm_planner.py`):Provider + Prompt 模板 + JSON Schema 校验 + 重试 | ✅ | 3-5 天 |
| P87-B | Plan 模板库(`templates.py`):refactor / write_tests / write_docs / bug_investigate 4 个预制 prompt + 自定义模板加载 | ✅ | 2-3 天 |
| P87-C | CCR 远程会话客户端(`ccr_session.py`):HTTP + SSE 调用 F-82 RCS,流式推送 step 状态 | ✅ | 5-7 天 |
| P87-D | `/ultraplan` 斜杠命令族(`command_system/ultraplan_command.py`):7 个子命令 + 参数解析 | ✅ | 3-5 天 |
| P87-E | 关键字检测(`keyword_detector.py`):`findUltraplanTriggerPositions` + `replaceUltraplanKeyword` + 转义过滤 | ✅ | 2-3 天 |
| P87-F | 输入框彩虹高亮(`tui/rainbow_highlight.py`):Rich markup 渲染 + TTY 检测 + 退化为单色 | ✅ | 2-3 天 |
| P87-G | 本地/远程模式切换 + `CCR` env 解析 | ✅ | 1-2 天 |
| P87-H | TUI Plan 状态面板(`tui/screens/ultraplan_panel.py`):Rich Table + 进度条 + 快捷键 | ✅ | 5-7 天 |
| P87-I | 审计日志 + NDJSON 增量持久化(`audit.py`):step 状态变更钩子 + 文件锁 + 轮转 | ✅ | 2-3 天 |
| P87-J | LLM 失败回退策略(`planner_recovery.py`):一次重试 + 用户提示 + fallback 到手动模式 | ✅ | 1-2 天 |
| P87-K | 单元测试 + 集成测试 + E2E(本地模式 + 模拟 CCR server) | ✅ | 5-7 天 |

**估算总工时**: 6-8 周(单人)。

### 1.4 架构设计

#### 1.4.1 端到端调用链

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 用户在 REPL 输入框输入:                                                   │
│   "/ultraplan refactor clawcodex_ext/services/ultraplan/executor.py"     │
│                                                                          │
│   ┌─────────────────────────────────────────────────────────────┐       │
│   │  input_processing.hook_before_submit                        │       │
│   │   1. keyword_detector.findUltraplanTriggerPositions(text)   │       │
│   │   2. 若命中: 彩虹高亮(triggered=True),捕获到 /ultraplan 命令│       │
│   │   3. 拦截提交 → 转交给 ULTRAPLAN_COMMAND.run()              │       │
│   └─────────────────────────────────────────────────────────────┘       │
└──────────────────────────────────────────────────────────────────────────┘
                                  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ ULTRAPLAN_COMMAND.run(args)                                              │
│   解析子命令(create / status / run / pause / ls / show / rm / template) │
│   分发到 UltraplanController.handle()                                    │
└──────────────────────────────────────────────────────────────────────────┘
                                  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ UltraplanController                                                      │
│   1. LLM Planner: llm_planner.generate_plan(prompt, ctx) → Plan JSON    │
│   2. JSON Schema 校验 → Plan.from_dict() → PlanStore.save()             │
│   3. (本地模式) PlanExecutor.run()                                       │
│      (远程模式) ccr_session.start() → 推送 SSE                          │
│   4. 状态变更 → audit.py 写 NDJSON + ultraplan_panel 更新                │
└──────────────────────────────────────────────────────────────────────────┘
                                  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ PlanExecutor / PlanAdjuster / AcceptanceVerifier (原语层,已落地)        │
│   复用现有,零侵入                                                       │
└──────────────────────────────────────────────────────────────────────────┘
                                  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ TUI Panel + 审计日志 + (可选) F-85 Pipe 广播                            │
└──────────────────────────────────────────────────────────────────────────┘
```

#### 1.4.2 进程与传输拓扑

```
┌─────────────────────────────────────────────────────────────────┐
│ 本地模式                                                          │
│                                                                 │
│   cli 进程                                                       │
│   ├── REPL 输入框(命中 /ultraplan)                              │
│   ├── UltraplanController                                       │
│   │   ├── LLM Planner (BaseProvider.chat_async)                │
│   │   ├── PlanStore (~/.clawcodex/ultraplan/<id>.json)         │
│   │   └── PlanExecutor (subprocess.run argv)                    │
│   └── TUI Panel (Shift+↓ 展开 /ultraplan 状态)                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ 远程模式(CCR)                                                    │
│                                                                 │
│   cli 进程                            远端 RCS worker           │
│   ├── REPL 输入框                      ├── PlanExecutor         │
│   ├── UltraplanController              ├── PlanStore            │
│   │   ├── LLM Planner (本地) ───────────HTTP/SSE──────────────── │
│   │   ├── ccr_session (httpx + SSE) ──POST /v1/ultraplan─────► │
│   │   │                                ◄───SSE step.status──────  │
│   │   └── Plan 预览 / 审计             └── 远程 AcceptanceVerif │
│   └── TUI Panel                                             │
└─────────────────────────────────────────────────────────────────┘
```

#### 1.4.3 包结构(全部解耦,不动 `src/`)

```
clawcodex_ext/services/ultraplan/             ← 现有原语层(扩展)
├── __init__.py                               # 公共导出扩展
├── models.py                                 # 已有
├── store.py                                  # 已有
├── executor.py                               # 已有
├── verifier.py                               # 已有
├── adjuster.py                               # 已有
├── exceptions.py                             # 已有
├── llm_planner.py                            # P87-A: LLM Plan 生成
├── planner_recovery.py                       # P87-J: LLM 失败回退
├── templates.py                              # P87-B: Plan 模板库
├── ccr_session.py                            # P87-C: 远程 CCR 客户端
├── keyword_detector.py                       # P87-E: 触发词检测
├── controller.py                             # 新:UltraplanController(串联 Planner + Executor + Panel)
└── audit.py                                  # P87-I: NDJSON 审计 + 钩子

clawcodex_ext/command_system/
├── ultraplan_command.py                      # P87-D: /ultraplan 命令族(7 子命令)
└── input_processing.py                       # 已有,扩展 hook_before_submit

clawcodex_ext/tui/screens/
├── ultraplan_panel.py                        # P87-H: TUI 状态面板 + 快捷键
└── rainbow_highlight.py                      # P87-F: 彩虹高亮 Rich markup

extensions/capabilities/ultraplan_protocol.py # Protocol 接口(Planner / Session / Panel)

extensions/remote_api/                         # 已有(扩展,F-82 协同)
├── ultraplan_endpoint.py                     # P87-C: 远端 /v1/ultraplan HTTP + SSE handler
└── ultraplan_dispatcher.py                   # 派发到远端 PlanExecutor

clawcodex_ext/feature_gate/registry.py         # 注册 ULTRAPLAN_REMOTE / CCR 标志
```

#### 1.4.4 解耦要点

| 设计点 | 解耦方式 | 理由 |
|--------|----------|------|
| 原语层扩展 | `clawcodex_ext/services/ultraplan/`(已存在,内部新增模块) | 不破坏 `models/store/executor/verifier/adjuster` 接口 |
| LLM Planner | 新建 `llm_planner.py`,依赖 `clawcodex_ext/providers/BaseProvider`(已存在) | 不写新 Provider 接口,直接复用 |
| 命令注册 | `clawcodex_ext/command_system/ultraplan_command.py` + `builtins.py::get_builtin_commands` 列表追加 | F-71 风格,避免改 `src/command_system/builtins.py` |
| 输入拦截 | `clawcodex_ext/command_system/input_processing.py::hook_before_submit`(已在) | 复用现有钩子,不侵入 `src/repl/` |
| CCR 远程 | 新建 `ccr_session.py`(本地端) + `extensions/remote_api/ultraplan_endpoint.py`(远端 handler) | Layer 1 + Layer 2 解耦,远端在 extensions/ |
| TUI Panel | 新建 `tui/screens/ultraplan_panel.py` | 与现有 TUI 风格一致 |
| 彩虹高亮 | 新建 `tui/rainbow_highlight.py`,依赖 Rich(已存在) | 单文件模块,易测试 |
| 审计 | `audit.py` 注册到 `executor.StepTransition` 钩子 | 不改 `executor.py` 的状态机实现 |
| Feature Flag | F-68 注册 `ULTRAPLAN_REMOTE` + `ULTRAPLAN_LLM_PLANNER`,默认 `LLM_PLANNER=on, REMOTE=off` | 复用 F-68 |

### 1.5 核心数据模型

#### 1.5.1 LLM 规划输入/输出 schema(P87-A)

```python
# clawcodex_ext/services/ultraplan/llm_planner.py

@dataclass(frozen=True)
class PlannerContext:
    """Planner 输入上下文。"""
    user_prompt: str                              # 用户原始 prompt
    cwd: str                                      # 当前工作目录(用于相对路径解析)
    active_files: tuple[str, ...] = ()            # REPL 当前打开的文件(可选上下文)
    template: str | None = None                   # 模板 ID(refactor / write_tests / …)
    model: str | None = None                      # 覆盖 Provider.model
    max_sub_plans: int = 5                        # 子计划上限
    max_steps_per_sub_plan: int = 8               # 每子计划步骤上限
    existing_plan_id: str | None = None           # 若增量规划,关联已有 plan


@dataclass(frozen=True)
class PlannerResult:
    """Planner 输出。"""
    plan: Plan                                    # 已通过 JSON Schema 校验
    raw_response: str                             # LLM 原始 JSON 字符串(用于调试 / 审计)
    provider: str                                 # Provider 名称
    model: str                                    # 实际使用的模型
    latency_ms: int                               # 端到端延迟
    retry_count: int = 0                          # 重试次数(0 = 一次成功)
```

#### 1.5.2 JSON Schema(P87-A)

LLM 生成的 JSON 必须严格匹配以下 schema,任何字段缺失 / 类型错误 / 越界值都通过 `Plan.from_dict()` 校验失败重试:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Ultraplan",
  "type": "object",
  "required": ["title", "sub_plans"],
  "properties": {
    "id": {"type": "string", "pattern": "^[A-Za-z0-9._-]{1,64}$"},
    "title": {"type": "string", "minLength": 1, "maxLength": 200},
    "summary": {"type": "string", "maxLength": 30000},
    "sub_plans": {
      "type": "array",
      "minItems": 1,
      "maxItems": 20,
      "items": {
        "type": "object",
        "required": ["id", "title", "steps"],
        "properties": {
          "id": {"type": "string", "pattern": "^[A-Za-z0-9._-]{1,64}$"},
          "title": {"type": "string", "minLength": 1, "maxLength": 200},
          "description": {"type": "string", "maxLength": 30000},
          "steps": {
            "type": "array",
            "minItems": 1,
            "maxItems": 30,
            "items": {
              "type": "object",
              "required": ["id", "title", "kind"],
              "properties": {
                "id": {"type": "string", "pattern": "^[A-Za-z0-9._-]{1,64}$"},
                "title": {"type": "string", "minLength": 1, "maxLength": 200},
                "description": {"type": "string", "maxLength": 30000},
                "kind": {"enum": ["research", "implement", "verify", "review", "other"]},
                "acceptance": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "required": ["id", "description", "kind", "target"],
                    "properties": {
                      "id": {"type": "string", "pattern": "^[A-Za-z0-9._-]{1,64}$"},
                      "description": {"type": "string", "minLength": 1, "maxLength": 1000},
                      "kind": {"enum": ["file_exists", "file_contains", "python_predicate", "shell_command", "custom"]},
                      "target": {"type": "string", "minLength": 1, "maxLength": 1000},
                      "args": {"type": "object"},
                      "required": {"type": "boolean"}
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
```

#### 1.5.3 CCR 会话状态(P87-C)

```python
# clawcodex_ext/services/ultraplan/ccr_session.py

class CCRSessionState(str, Enum):
    PENDING = "pending"
    STREAMING = "streaming"      # 正在接收 SSE
    EXECUTING = "executing"      # 远端 PlanExecutor 已启动
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class CCRSession:
    session_id: str
    plan_id: str
    endpoint: str                              # http://host:port
    state: CCRSessionState
    started_at: str
    last_event_at: str | None = None
    progress: Progress | None = None           # 复用 executor.Progress
    error: str | None = None
    cancel_event: asyncio.Event | None = None  # 用于 abort 协程
```

#### 1.5.4 审计日志条目(P87-I)

```python
# clawcodex_ext/services/ultraplan/audit.py

@dataclass(frozen=True)
class AuditEntry:
    timestamp: str                              # ISO 8601
    plan_id: str
    sub_plan_id: str | None
    step_id: str | None
    event: str                                 # "step.started" / "step.completed" / "plan.paused" / ...
    actor: str                                 # "executor" / "user" / "ccr" / "adjuster"
    detail: dict[str, Any] = field(default_factory=dict)
```

### 1.6 核心接口

#### 1.6.1 LLM Planner(`llm_planner.py`)

```python
from typing import Protocol, runtime_checkable
from clawcodex_ext.providers.base import BaseProvider

@runtime_checkable
class PlannerBackend(Protocol):
    """Provider 适配器 Protocol,允许 mock 或非 BaseProvider 实现。"""
    async def chat(self, messages: list[dict], *, model: str | None = None) -> str: ...


class LLMPlanner:
    """LLM 驱动的 Plan 生成器。"""

    SYSTEM_PROMPT = """You are an expert software planning assistant.
Output MUST be strict JSON matching the provided schema. No prose, no markdown fences.
- Use ASCII ids matching ^[A-Za-z0-9._-]{1,64}$.
- Each sub_plan must have at least 1 step; each step at least 1 acceptance criterion.
- Prefer FILE_EXISTS / FILE_CONTAINS / SHELL_COMMAND for acceptance checks.
- Never put secrets, credentials, or destructive commands (rm -rf, DROP TABLE) in acceptance.
"""

    def __init__(
        self,
        provider: PlannerBackend,
        *,
        max_retries: int = 1,
        retry_delay_seconds: float = 1.0,
    ) -> None: ...

    async def generate_plan(self, ctx: PlannerContext) -> PlannerResult:
        """Generate a Plan from user prompt.

        流程:
          1. 加载模板(若指定)→ 拼接到 system prompt
          2. BaseProvider.chat_async([{role:system}, {role:user, content:prompt}])
          3. 尝试直接 json.loads;失败时尝试从 markdown fence 中提取
          4. JSON Schema 校验 + Plan.from_dict()
          5. 校验失败 → 重试(max_retries),最终失败抛 PlannerFailedError
        """
```

#### 1.6.2 CCR 会话客户端(`ccr_session.py`)

```python
import httpx

class CCRClient:
    """CCR (Claude Code Remote) session client.

    与 F-82 RCS 兼容:POST /v1/ultraplan 启动,SSE 流式回传 step 状态。
    """

    def __init__(self, endpoint: str, *, token: str | None = None, timeout: float = 30.0) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout, headers={"Authorization": f"Bearer {token}"} if token else {})

    async def start_session(self, plan: Plan, *, cwd: str) -> CCRSession: ...
    async def stream_events(self, session_id: str) -> AsyncIterator[CCREvent]: ...
    async def cancel_session(self, session_id: str) -> bool: ...
    async def list_sessions(self, *, plan_id: str | None = None) -> list[CCRSession]: ...
    async def close(self) -> None: ...

    async def __aenter__(self) -> "CCRClient": ...
    async def __aexit__(self, *exc) -> None:
        await self.close()


class CCREventType(str, Enum):
    STEP_STARTED = "step.started"
    STEP_COMPLETED = "step.completed"
    STEP_FAILED = "step.failed"
    PLAN_COMPLETED = "plan.completed"
    PLAN_FAILED = "plan.failed"
    LOG = "log"

@dataclass
class CCREvent:
    type: CCREventType
    session_id: str
    timestamp: str
    payload: dict[str, Any]
```

#### 1.6.3 关键字检测(`keyword_detector.py`)

```python
@dataclass(frozen=True)
class TriggerHit:
    start: int                                  # 触发词起始字符位置
    end: int                                    # 触发词结束字符位置(不含)
    keyword: str                                # "/ultraplan" / "/ultra" / "/up"
    abbrev: bool = False                        # 是否为缩写

# 触发词列表(可配置)
TRIGGER_KEYWORDS: tuple[str, ...] = ("/ultraplan", "/ultra", "/up")

def find_ultraplan_trigger_positions(
    text: str,
    *,
    keywords: tuple[str, ...] = TRIGGER_KEYWORDS,
    inside_quotes: Literal["skip", "include"] = "skip",
    inside_code_fence: bool = False,           # 已检测到 ``` 跳过
) -> list[TriggerHit]:
    """扫描输入框文本中的 /ultraplan 触发词。

    跳过规则:
      - 反引号 / 双引号 / 单引号包裹的文本(若 inside_quotes='skip')
      - 已处于 ```code fence``` 内部(若 inside_code_fence=True)
      - 已有转义前缀 "\\/ultraplan"
    """

def replace_ultraplan_keyword(
    text: str,
    old: str,
    new: str,
    *,
    positions: list[TriggerHit] | None = None,
) -> str:
    """精确替换,不破坏其他文本。"""
```

#### 1.6.4 彩虹高亮(`rainbow_highlight.py`)

```python
from rich.markup import render
from rich.text import Text

# 彩虹配色(Rich markup,可被现有 REPL 配色系统覆盖)
RAINBOW_STYLES: tuple[str, ...] = ("red", "yellow", "green", "cyan", "blue", "magenta")

def highlight_triggers(
    text: str,
    hits: list[TriggerHit],
    *,
    palette: tuple[str, ...] = RAINBOW_STYLES,
    fallback: str | None = None,               # 单色 fallback
) -> Text:
    """将命中位置渲染为 Rich Text 对象,其余保持原样。

    当 stdout 非 TTY 时,返回 fallback 风格(默认 None 表示不变)。
    """

def should_render_rainbow(stream) -> bool:
    """检测 stream 是否为 TTY(复用 src/utils/isatty)。"""
```

#### 1.6.5 UltraplanController(`controller.py`)

```python
class UltraplanController:
    """串联 Planner + Store + Executor + CCR + Panel。"""

    def __init__(
        self,
        *,
        planner: LLMPlanner,
        store: PlanStore,
        executor: PlanExecutor | None = None,        # 本地模式
        ccr: CCRClient | None = None,                 # 远程模式
        audit: "AuditLogger | None" = None,
        panel: "UltraplanPanel | None" = None,
    ) -> None: ...

    async def create_plan(self, ctx: PlannerContext) -> Plan: ...
    async def run_plan(self, plan_id: str, *, remote: bool = False) -> Progress: ...
    async def pause_plan(self, plan_id: str) -> None: ...
    async def resume_plan(self, plan_id: str) -> None: ...
    async def list_plans(self, *, status: PlanStatus | None = None) -> list[Plan]: ...
    async def show_plan(self, plan_id: str) -> Plan: ...
    async def remove_plan(self, plan_id: str) -> None: ...
```

#### 1.6.6 `/ultraplan` 命令族(`command_system/ultraplan_command.py`)

```python
ULTRAPLAN_COMMAND = Command(
    name="ultraplan",
    type=CommandType.LOCAL,
    description="LLM-driven planning & multi-step execution",
    arguments=[
        CommandArgument(name="subcommand", required=False, choices=[
            "create", "run", "pause", "resume", "status", "ls", "show", "rm", "template",
        ]),
        CommandArgument(name="args", required=False, variadic=True),
    ],
    handler=handle_ultraplan_command,
)

async def handle_ultraplan_command(args: list[str], ctx: CommandContext) -> CommandResult:
    """分发到 UltraplanController;输出 Rich 渲染。"""
```

子命令契约(节选):

| 子命令 | 语法 | 说明 |
|--------|------|------|
| `create` | `/ultraplan create <prompt...>` | LLM 规划 → 预览 → 询问用户确认 → 落盘 |
| `run` | `/ultraplan run [plan_id]` | 执行指定 Plan(默认最新 DRAFT);`--remote` 切 CCR 模式 |
| `pause` / `resume` | `/ultraplan pause <plan_id>` | 暂停 / 恢复 |
| `status` | `/ultraplan status [plan_id]` | 当前 Plan 进度 + 当前 step + ETA |
| `ls` | `/ultraplan ls [--status=...] [--limit=20]` | 列表 |
| `show` | `/ultraplan show <plan_id>` | 完整 Plan dump |
| `rm` | `/ultraplan rm <plan_id>` | 删除(仅 DRAFT / ABANDONED 可删) |
| `template` | `/ultraplan template list\|apply <id>` | 模板库管理 |

### 1.7 输入拦截集成(P87-E + P87-F)

```python
# clawcodex_ext/command_system/input_processing.py(扩展 hook_before_submit)

def hook_before_submit(text: str, *, context: ToolContext) -> str:
    """在 REPL 提交前调用,返回可能被改写的 text。

    F-87 新增:
      1. 检测 text 是否以 /ultraplan(支持 /ultra / /up 缩写)开头
      2. 若命中,标注 triggered=True,触发彩虹高亮并把命令直接转交
         UltraplanController(跳过常规 query loop)
      3. text 中间出现 /ultraplan 不拦截(留给普通文本流)
    """
    hits = find_ultraplan_trigger_positions(text)
    if not hits or hits[0].start != 0:
        return text                                  # 仅拦截行首触发
    keyword = text[hits[0].start:hits[0].end]
    remainder = text[hits[0].end:].lstrip()
    # 委托给 UltraplanController(异步,因 Planner 是 async)
    asyncio.create_task(_dispatch_ultraplan(keyword, remainder, context))
    return ""                                       # 返回空字符串,告诉 REPL 已处理
```

### 1.8 失败模式与错误分类

| 错误类型 | 触发场景 | 处理策略 |
|----------|----------|----------|
| `PlannerFailedError` | LLM JSON 解析失败 / schema 校验失败 / 重试耗尽 | 提示用户简化 prompt;fallback 到手动模式(由用户直接编辑 JSON) |
| `ProviderUnavailableError` | 当前 Provider 不可用 / API key 缺失 | 提示切换 Provider;`/provider` 命令辅助 |
| `CCRUnavailableError` | 远程 endpoint 不可达 / 401 / 5xx | 提示检查 `CCR_ENDPOINT` + 网络;fallback 本地模式 |
| `CCRTimeoutError` | 远程 SSE 30s 无事件 | 自动 reconnect 一次;再次失败抛错 |
| `PlanNotFoundError` | 用户引用了不存在的 plan_id | 列出当前可用的 plan_id 前 5 个 |
| `IllegalStepTransitionError` | 用户在面板试图把 COMPLETED → IN_PROGRESS | 拒绝 + 提示需要走 `adjuster.reset_step()`(只允许 PENDING) |
| `TemplateNotFoundError` | `/ultraplan template apply unknown-id` | 列出内置模板列表 |
| `RateLimitError` | Provider 触发 rate limit | 退避 60s;提示用户切更便宜模型 |
| `QuotaExceededError` | Token 配额耗尽 | 与 F-69 Budget Mode 联动,自动降级 |

### 1.9 测试策略

| 层级 | 框架 | 覆盖范围 |
|------|------|----------|
| 单元 | pytest | `LLMPlanner.generate_plan` 用 mock Provider 测重试 + JSON 解析 + schema 校验 |
| 单元 | pytest | `find_ultraplan_trigger_positions` 测转义 / 引号 / code fence |
| 单元 | pytest | `highlight_triggers` 测 TTY / 非 TTY fallback |
| 单元 | pytest | `CCRSession` 用 mock httpx 测 start/cancel/stream |
| 集成 | pytest + real PlanExecutor | `UltraplanController.create_plan → run_plan` 全链路(本地) |
| 集成 | pytest + mock CCR server | `/ultraplan run --remote` 跑 mock aiohttp server |
| E2E | pytest + REPL harness | 模拟用户输入 `/ultraplan refactor foo.py`,断言 Plan 落盘 + Step 推进 |
| 安全 | 静态 | `grep -E "shell=True" clawcodex_ext/services/ultraplan/` 必须为空 |
| 安全 | 静态 | `PYTHON_PREDICATE` globals 白名单不能新增危险 builtins(`open` / `__import__` 等) |

### 1.10 远程 vs 本地模式对比

| 维度 | 本地模式 | 远程 CCR 模式 |
|------|----------|---------------|
| Plan 生成 | 本地 BaseProvider | 本地 BaseProvider(LLM 不上传远端) |
| Plan 存储 | `~/.clawcodex/ultraplan/<id>.json` | `~/.clawcodex/ultraplan/<id>.json`(元数据) + 远端 worker 完整执行 |
| Plan 执行 | `PlanExecutor`(subprocess.run) | 远端 `extensions/remote_api/ultraplan_endpoint.py` |
| 验收 | 本地 `AcceptanceVerifier` | 远端 + 结果回传(evidence dict) |
| 状态推送 | 进程内事件 | SSE 推流(30s 心跳) |
| 失败恢复 | 进程重启 + executor 状态机 | 远端 worker 重启后由 SSE 续传 |
| 资源占用 | 单机 CPU | 远端 worker 资源(可跑重型 build / test) |
| 触发方式 | `CCR` env 未设 / `--local` | `CCR=http://host:port` env / `--remote <endpoint>` |
| Feature Flag | 默认 | `ULTRAPLAN_REMOTE=on` 才注册命令 |

## §2 落地步骤

> 顺序原则:先 LLM Planner(P87-A)→ 模板库(P87-B)→ 命令族(P87-D)→ 关键字检测 + 高亮(P87-E/F)→ 审计(P87-I)→ CCR 远程(P87-C/G)→ TUI 面板(P87-H)→ 失败回退(P87-J)→ 测试(P87-K)。

| 步骤 | 内容 | 涉及子特性 | 工时 |
|:----:|------|:----------:|:----:|
| 1 | `llm_planner.py` 实现 + JSON Schema + 重试 + AuditEntry 关联 | P87-A | 3-5 天 |
| 2 | `templates.py` 实现 4 个内置模板 + 自定义模板加载(从 `~/.clawcodex/ultraplan/templates/*.yaml`) | P87-B | 2-3 天 |
| 3 | `command_system/ultraplan_command.py` + `builtins.py` 注册 | P87-D | 3-5 天 |
| 4 | `keyword_detector.py` + `input_processing.py::hook_before_submit` 集成 + 跳过规则单元测试 | P87-E | 2-3 天 |
| 5 | `rainbow_highlight.py` + TUI 集成 + TTY fallback + 不破坏现有 REPL 配色 | P87-F | 2-3 天 |
| 6 | `audit.py` NDJSON + 注册到 `PlanExecutor` 状态机钩子 | P87-I | 2-3 天 |
| 7 | `controller.py` 串联 Planner + Store + Executor + CCR + Panel + Audit | P87-D + A + I | 2-3 天 |
| 8 | `ccr_session.py` + `extensions/remote_api/ultraplan_endpoint.py`(远端 handler) + SSE 协议 | P87-C | 5-7 天 |
| 9 | `CCR` env 解析 + `--local` / `--remote` 命令行参数 | P87-G | 1-2 天 |
| 10 | `tui/screens/ultraplan_panel.py` + Rich Table + 进度条 + 快捷键 `n/p/e/q` | P87-H | 5-7 天 |
| 11 | `planner_recovery.py` 一次重试 + 用户提示 + 手动模式 fallback | P87-J | 1-2 天 |
| 12 | 单元 + 集成 + E2E 测试 + mock CCR server + 真实 Provider 烟雾测试 | P87-K | 5-7 天 |
| 13 | README 更新(命令族 + 模板列表 + CCR 配置示例)+ 文档(状态机图) | P87-备 | 1-2 天 |

**累计工时**:6-8 周(单人)。

## §3 风险与缓解

| 风险 | 等级 | 缓解措施 |
|------|:----:|----------|
| LLM 生成非法 JSON / 字段越界 | 🔴 | JSON Schema 校验 + 一次自动重试 + 失败后 fallback 手动编辑模式 |
| LLM 在 acceptance 中塞入危险命令(`rm -rf`) | 🔴 | 后置扫描 + 黑名单(`rm -rf`, `mkfs`, `dd if=`, `DROP TABLE`, `kill -9`);命中则拒绝该 plan |
| LLM 暴露 secret / 凭证 | 🟠 | 后置扫描 PII / 凭证模式;hit 则告警用户 |
| CCR 远程 endpoint 不可信 | 🔴 | 仅允许配置在 `CCR_ALLOWLIST` 中的 endpoint;首次连接需用户交互式确认 |
| SSE 长连接断流 | 🟠 | 30s 心跳 + 自动 reconnect 一次 + 重连失败 fallback 本地 |
| TUI 彩虹高亮破坏现有配色 | 🟡 | Rich markup 限定在 `/ultraplan` 触发词 + 用户可 `/theme` 关闭 |
| Plan 模板库被滥用为 prompt injection | 🟠 | 模板来自 `~/.clawcodex/ultraplan/templates/*.yaml` + 用户显式 `/ultraplan template apply <id>` 才注入;内置模板固定 |
| 关键字检测误拦截普通文本 | 🟡 | 仅拦截行首触发(`hits[0].start == 0`);中间出现的 `/ultraplan` 不拦截 |
| 远程 CCR 把敏感 plan 数据外发 | 🟠 | 元数据(plan_id / progress)可外发;Plan 详细内容(用户 prompt)在 CCR 模式下走端到端加密(TLS + 可选 mTLS) |
| `PlanExecutor.subprocess.run` 误用 `shell=True` | 🔴 | 静态检查 `grep -E "shell=True"` 必须为空;原语层已遵守 |
| LLM 规划时间过长,REPL 卡住 | 🟡 | 默认 60s 超时;`/ultraplan create --no-llm <manual_json>` 走手动模式 |
| Plan ID 冲突 | 🟡 | `PlanStore.save` 拒绝重名 + 提示用户 `replace` 或 `new_id` |

## §4 与其他特性的关系

| 依赖 / 协同 | 说明 |
|-------------|------|
| **F-68 Feature Gate** | 注册 `ULTRAPLAN_REMOTE` + `ULTRAPLAN_LLM_PLANNER`,默认 `LLM=on, REMOTE=off` |
| **F-69 Budget Mode** | LLM 规划触发 rate limit 时联动 BudgetModeManager 自动降级 |
| **F-82 RCS** | `CCR` 远程模式直接复用 `extensions/remote_api/` 的 HTTP + SSE 框架 |
| **F-83 Ultraplan 原语层** | `LLMPlanner` 生成结果经 `Plan.from_dict()` 直接落地,执行走 `PlanExecutor` |
| **F-85 Pipe IPC** | 远程模式下可经 `PipeMessageType.PLAN_EVENT` 跨机器广播 step 状态 |
| **F-88 Monitor** | 长跑 Plan 可挂载到 `kind='monitor'` 后台任务,TUI 面板 + Monitor Panel 双视图 |
| **F-89 Proactive** | Proactive Tick 可周期性触发 `/ultraplan status` 报告当前进度 |
| **F-71 Tool Gap** | LLM Planner 可选用 `WebBrowserTool` 抓取在线文档辅助规划(可选增强) |
| **F-66 ACP** | 远端 worker 通过 ACP 协议接入 Zed / Cursor 等 IDE 时,Plan 也可走相同通道 |
| **Provider 体系** | 复用 `clawcodex_ext/providers/BaseProvider`;不引入新 Provider 接口 |
| **上游 CCB** | 跟踪 `src/commands/ultraplan.tsx` 与 `src/utils/ultraplan/ccrSession.ts` 的演进 |

## §5 验收标准

1. **LLM 规划端到端**: 输入 `/ultraplan refactor executor.py`,50s 内 Plan 落盘 + 子计划数 ≤ 5 + 每子计划 step 数 ≤ 8,JSON 100% 通过 `Plan.from_dict()` 校验;
2. **重试与回退**: mock Provider 首次返回非法 JSON → 自动重试一次 → 第二次仍失败 → 抛 `PlannerFailedError` + 提示手动编辑;
3. **关键字检测**: `"  /ultraplan foo"` 命中行首;`"echo /ultraplan"` 不拦截;`"\"\\/ultraplan\""` 不命中;`"```py /ultraplan```"` 不命中(code fence);
4. **彩虹高亮**: TTY 模式下命中位置渲染为彩虹;非 TTY 返回纯文本不破坏布局;
5. **命令族完整**: `/ultraplan create/run/pause/resume/status/ls/show/rm/template` 9 个子命令全部可用,`--help` 输出符合 `CommandArgument` schema;
6. **审计日志**: 跑一次完整 Plan 后,`~/.clawcodex/ultraplan/audit/<plan_id>.ndjson` 包含 ≥ 步骤数条事件,JSONL 格式正确;
7. **CCR 远程**: mock CCR server 接收到 `POST /v1/ultraplan` + 后续 SSE 流式回传 step 状态,本地 TUI 面板实时刷新;
8. **Feature Gate**: `CCR` env 未设时 `CCRClient.start_session` 抛 `CCRUnavailableError`;`ULTRAPLAN_REMOTE=off` 时 `--remote` 参数拒绝;
9. **静态安全**: `grep -rE "shell=True" clawcodex_ext/services/ultraplan/` 为空;`PYTHON_PREDICATE` globals 白名单无新增;
10. **测试覆盖**: 单元测试覆盖率 ≥ 85%(models/store/executor/verifier/adjuster 已 100%),新增模块不低于同水平;
11. **回归兼容**: 原 `clawcodex_ext/services/ultraplan/` 6 模块接口 100% 兼容,F-83 first iteration 的 5 个测试文件 0 修改通过;
12. **文档完整**: README 提供 `/ultraplan` 命令族 + 模板列表 + CCR 配置示例 + LLM Prompt 调优建议。

## §6 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-07-21 | 代码落地并标记完成 | `clawcodex_ext/services/ultraplan/` 扩展至 15 模块,`/ultraplan` 命令族、`CCRClient`、LLM Planner、关键字检测、彩虹高亮、TUI 面板、审计日志全部落地;P87-A~K 全部 ✅ |
| 2026-06-30 | 初始创建(从 gap-analysis 派工) | 原语层已存在,需补齐用户面向层 |

## §7 后续展望(P88+)

- **P87-L Plan diff UI**: TUI 面板支持 `diff` 视图(显示 LLM 重新规划前后的 step 变更);
- **P87-M Plan 回放**: 历史 Plan + audit log 可在 TUI 中按时间线回放(用于调试 LLM 规划质量);
- **P87-N 多 LLM 交叉验证**: 同一 prompt 同时调 2 个 Provider,选择更高 confidence 的 Plan;
- **P87-O Agent 协作**: Plan 内 step 可委托给 `SendMessageTool` 给其他 teammate(类似 F-50 SOP 模式);
- **P87-P Plan 自适应**: 根据 step 失败率自动触发 `PlanAdjuster.replace_step()` 重新规划失败节点;
- **P87-Q 模板版本管理**: 模板库支持 git-style 版本化,团队共享 template repo。

---

**关联文档**:

- 缺口分析: [README.md §A 缺口矩阵](./README.md#a-全特性对照矩阵)
- README 索引: [README.md#f-87-ultraplan-llm-驱动--cli-完整实现](#f-87)
- 现实现代码: `clawcodex_ext/services/ultraplan/`(models/store/executor/verifier/adjuster + 5 测试文件)
- 对标上游: CCB `src/commands/ultraplan.tsx` + `src/utils/ultraplan/ccrSession.ts`
- 协同特性: F-68 Feature Gate / F-69 Budget / F-82 RCS / F-83 原语层 / F-85 Pipe / F-88 Monitor / F-89 Proactive