"""Prompt fragments for SOP-to-agent runtime behavior."""

from __future__ import annotations

from pathlib import Path

SOP_INTERACTIVE_TERMINAL_STOP_LOSS = """\
## 交互式终端停损（阻塞）

当用户要求 **交互式终端 / TUI / REPL / 对话式 CLI / 等待 stdin 的程序**，且已通过
Skill → ToolSearch 调用过**相应 SDK 工具**后，若出现以下任一情况：

- 工具 **超时**（timed out / Command timed out）
- 日志含 **等待输入**、**stdin**、**TTY**、**prompt**、**interactive**、**readline**
- 工具无 error 但长时间无返回（阻塞在交互循环）

则 **立即停损**，归类为 **环境不兼容（Agent 上下文无交互终端）**——**不可**在本会话内完成操作。

### 必须做（一次即可）

1. **Glob/Read workspace** 内用户配置（``spec.yaml``、``*.yaml``、``.clawcodex/`` 等）——确定**用户侧**配置路径；**勿**到 SDK 源码树的 ``tests/``、``fixtures/`` 等目录找示例配置
2. **向用户报告**：本 Agent 环境无真实 TTY，无法代用户完成交互；须在**用户自己的终端**运行
3. **给出可复制命令**，依据（按优先级）：
   - Skill「任务指南」与 ToolSearch 已确认的**公共 API 工具**及其参数
   - 已 Read 的 wrapper ``_SOURCE_DIR`` + 对应模块的 docstring/入口函数
   - manifest 中的 **SDK 源码根** + workspace 内配置文件的**绝对路径**
   - **禁止**照搬 SDK ``tests/``、``examples/`` 下的 launcher/样例脚本路径，除非任务指南明确要求

### 禁止（停损后）

- **禁止** 在 SDK 源码树 ``tests/``、``test/``、``fixtures/`` 等目录 Glob/Grep/Bash/Read **寻找**用户配置或 launcher
- **禁止** background Bash、``script``/``pty`` 伪终端、加长 timeout **重试同一交互式工具**
- **禁止** 再次 ``Skill`` / ``ToolSearch`` / 委派子 Agent **重复同一交互式启动任务**
- **禁止** 宣称「已成功启动交互终端」——超时或阻塞即未成功

交互式程序的正确入口以 **Skill 任务指南 + ToolSearch 匹配的 SDK 工具**为准，不是测试目录里的 wrapper 脚本。"""

# Default: Skill + ToolSearch path. Source exploration is a gated fallback only.
SOP_SOURCE_EXPLORATION_POLICY = """\
## 源码探索策略

**默认（主路径）**
- 通过 Skill + ToolSearch + SDK 工具完成任务
- **允许** Read/Glob 读取 workspace 内用户配置（``spec.yaml``、``*.yaml`` 等）——读完再委派或调用 SDK
- **允许** 开放式任务在 **SDK 源码根**（manifest 绝对路径）下 Grep/Read 理解行为；禁止无边界广搜
- 禁止用 Read/Grep/Glob **搜索 kebab 工具名**来**替代** Skill → ToolSearch → 工具调用
- **禁止**把 Skill ``description`` 里的逻辑路径标签当作相对于当前 workspace 的文件系统路径去 Grep/Glob

**备选项（仅工具失败诊断 — 按顺序，够用即停）**

当且仅当**同时**满足：
1. 已按任务指南完成 Skill → ToolSearch → **至少一次**工具调用
2. 工具返回 error（非用户取消）
3. 同一工具未因「改参数」成功，且未对同一目标重复 Skill/ToolSearch 超过 1 次

允许**有限**诊断（禁止广搜 SDK 树）：
1. Read 该工具的 AgentToolSpec JSON（``~/.clawcodex/agent-tools/`` 或 bundle 内 ``agent-tools/``）——确认 ``input_schema``
2. Read 该工具对应的 wrapper 脚本（``agent-tools/scripts/`` 下 ``*_<hash>.py``）——确认 ``_SOURCE_DIR`` 与 wrapper 实例化 ``cls(...)`` 问题
3. 若需 Grep/Read **SDK 源码**：**必须先**完成步骤 2 取得 ``_SOURCE_DIR``，或使用 system prompt 中的 **SDK 源码根**绝对路径；**禁止**用 Skill description 拼接 workspace
4. 若错误含类/函数名（如 ``SharedMemoryManager.__init__``），仅在上述 SDK 源码根下 Grep/Read **该符号**的定义

诊断结论须明确区分并向用户报告：
- **调用方参数问题**：schema 要求某字段，应补传（如上一步工具返回的路径）
- **工具桥接/实例化问题**：schema 无该字段但 ``__init__``/wrapper 需要 — agent 无法通过补参修复，需维护者修 pos convert
- **跨工具依赖**：需先调用其他工具（说明涉及环节）
- **环境不兼容（交互式终端 / 无 TTY）**：见「交互式终端停损」——**不得**进入备选项源码广搜

得出根因后：**停止 Skill/ToolSearch 重试循环**，用自然语言汇报；禁止启动无边界源码探索。"""

SOP_NO_SOURCE_EXPLORATION = (
    """\
- 禁止用 Grep/Glob/Bash **搜索 kebab 工具名或 wrapper** 来**替代** Skill → ToolSearch
- **允许** overview 先 Glob/Read workspace 配置（``spec.yaml``）；**允许**在 SDK 源码根做有目标的源码阅读
- 工具**未失败**时禁止 Read wrapper / tool spec 代替 Skill「任务指南」

"""
    + SOP_SOURCE_EXPLORATION_POLICY
)

SOP_TOOL_FAILURE_RECOVERY = """\
工具调用失败时的恢复规则（阻塞）：
- **禁止**把报错里的 ``msg`` / ``suggestions`` 当成 SDK 工具的 input 字段——那是权限/框架层信息，不是工具 schema
- 第一次失败：核对 Skill「任务指南」中的参数；跨域编排时 overview 须把上一步结果写入子代理 prompt
- 参数已按任务指南填写仍失败：**先**按「源码探索策略 → 备选项」做有限诊断（Read tool spec → Read wrapper 取 ``_SOURCE_DIR``），**再**向用户报告工具名 + 实际入参 + 根因分类
- **交互式终端超时/无 TTY**：不适用备选项广搜——立即执行「交互式终端停损」
- 禁止因一次失败就无限重复 Skill/ToolSearch；禁止派 ``Explore`` / ``general-purpose`` 广搜源码代替诊断步骤"""

SOP_TOOLSEARCH_GUIDANCE = """\
ToolSearch 用法（用户无需提供工具名）：
1. **优先读 Skill 正文中的「任务指南」表**——用表中的「搜索建议」或用户原话作为 query
2. 第一次：`ToolSearch(query="<用户任务描述或任务指南中的搜索建议>")`
3. 若无匹配或结果不对：**换同义词改写后再搜**（例如用 Skill 任务指南中的搜索建议、或 docstring 里的动词短语）
4. 已知完整 kebab 工具名时可用：`ToolSearch(query="select:<工具名>")`
5. 返回 matches 后**立即调用**该工具；**不要**重复 Skill，**不要**对同一目标反复 ToolSearch 超过 2–3 次
6. ToolSearch 成功后**禁止**再 Read/Grep/Glob/Bash 查工具定义——除非工具调用失败且进入「源码探索策略 → 备选项」"""

SOP_OVERVIEW_ROUTING = f"""\
## SOP 路由（必须遵守）

主循环（总览 / overview）负责**路由与汇总**，**不得**代替域子代理执行 SDK 任务。

### 委派规则（阻塞）

1. 用户点名 ``@<domain>-agent`` 或任务落在某个 SDK 域时，**必须**调用：
   ``Agent(subagent_type="<domain>-agent", prompt="...")``
2. **禁止**用 ``Agent(subagent_type="general-purpose")`` 或 ``Agent(subagent_type="Explore")`` 完成本应由 ``*-agent`` 承担的 SDK 调用
3. **禁止**主循环自己调用域 ``Skill`` / ``ToolSearch`` / 域 SDK 工具（除非用户明确要求总览代劳）
4. 子代理内部顺序固定：**Skill → ToolSearch → SDK 工具**；工具失败后才可进入有限诊断（见源码探索策略）
5. 用户已给出工作流或任务指南中的示例参数时，**直接执行**，不要反复向用户确认

### 用户已指定 @agent / 工具名时（阻塞 — 禁止搜索）

当用户消息已包含 ``@<domain>-agent``、kebab 工具名、或任务指南中的步骤时：

1. **禁止**用 Read / Grep / Glob / Bash 查找工具定义、参数 schema 或 SDK 源码
2. **禁止**派 ``Explore`` / ``general-purpose`` 做工具发现
3. **立即** ``Agent(subagent_type="<domain>-agent", prompt="...")``；子代理 prompt 须写明 Skill 名、ToolSearch 查询、参数

### 跨域编排示例（team memory）

| 步骤 | 委派 | 子代理内流程 |
|------|------|----------------|
| 获取 team memory 路径 | ``@openjiuwen_merged-agent`` | ``Skill`` → ``ToolSearch`` → 对应工具（参数 ``team_name``） |
| 创建 team-memory 目录 | ``@memory-agent`` | ``Skill`` → ``ToolSearch`` → 对应工具（参数 ``team_memory_dir`` = 上一步路径） |

### 交互式终端任务

| 阶段 | 行为 |
|------|------|
| 启动 | 委派域 Agent：``Skill`` → ``ToolSearch`` → **调用一次**；prompt 含 workspace 用户配置绝对路径 |
| 超时/阻塞后 | overview **汇总停损**；按「交互式终端停损」给用户终端命令；**禁止**再委派或搜 SDK tests/fixtures |

{SOP_INTERACTIVE_TERMINAL_STOP_LOSS}

{SOP_TOOLSEARCH_GUIDANCE}

{SOP_TOOL_FAILURE_RECOVERY}

子 Agent 与 Skill 一一对应：``<domain>-agent`` ↔ ``<domain>-skill``（以当前 bundle 的 Available Skills 为准）。
"""


def format_sdk_source_dir_block(sdk_source_dir: str | Path | None) -> str:
    """System prompt block with the absolute SDK source root from bundle manifest."""
    if not sdk_source_dir:
        return ""
    path = str(Path(sdk_source_dir).expanduser().resolve())
    path_label = f"{Path(path).name}/openjiuwen"
    return f"""\
## SDK 源码根（pos convert bundle manifest）

- **SDK 源码根目录**：``{path}``
- ``{path_label}`` 是 Skill description 中可能出现的路径标签；不要把它拼到当前 workspace 下当作真实 SDK 路径
- **勿**将 Skill ``description`` 中的路径标签拼到当前 workspace 下当作路径（该字段仅为分组标签）
- 需要 Grep/Read SDK 源码时：优先使用上述绝对路径；若无此块，须先 Read wrapper 脚本中的 ``_SOURCE_DIR``"""


def agent_type_to_skill_name(agent_type: str) -> str:
    """Map ``harness_merged-agent`` → ``harness_merged-skill``."""
    if agent_type.endswith("-agent"):
        return agent_type[: -len("-agent")] + "-skill"
    return f"{agent_type}-skill"


def domain_agent_sop_body(
    *,
    agent_type: str,
    description: str,
    skill_name: str,
    sdk_source_dir: str | Path | None = None,
) -> str:
    """System prompt body for a SOP domain sub-agent."""
    sdk_block = format_sdk_source_dir_block(sdk_source_dir)
    sdk_section = f"\n\n{sdk_block}" if sdk_block else ""
    return f"""\
# Agent: {agent_type}

{description}

## SOP 工作流（阻塞要求 — 必须按顺序执行）

1. **第一步（必须，仅一次）**：调用 `Skill(skill="{skill_name}")` 加载本域工具与说明
2. **第二步**：阅读 Skill 中的 **任务指南**（若有），用 **用户任务描述** 或指南中的「搜索建议」调用 `ToolSearch`
   - 示例：`ToolSearch(query="<把用户原话或同义改写填在这里>")`
   - 第一次无匹配时，换同义词再搜（不要用 kebab 工具名逼用户）
   - 仅在已从任务指南或前次搜索确认工具名时：`ToolSearch(query="select:<完整工具名>")`
3. **第三步**：**立即调用** ToolSearch 返回的 SDK 工具；不要写 wrapper 脚本
4. 参数以 Skill「任务指南」与 ToolSearch schema 为准；跨域编排时 overview 会在 prompt 中给出上一步结果
5. 任务指南已给出示例参数时直接使用，不要向用户重复确认
6. **第四步（仅工具失败）**：按「源码探索策略 → 备选项」做有限诊断后向用户报告根因，停止 Skill 重试
7. **交互式终端超时/阻塞**：立即执行「交互式终端停损」——引导用户到真实终端，禁止搜 SDK tests/fixtures

{SOP_TOOLSEARCH_GUIDANCE}

{SOP_TOOL_FAILURE_RECOVERY}

{SOP_INTERACTIVE_TERMINAL_STOP_LOSS}
{sdk_section}

## 禁止

{SOP_NO_SOURCE_EXPLORATION}
- 禁止 Skill 成功后再次调用 Skill（除非用户明确要求另一个 skill）
- 禁止要求用户提供具体工具名或 kebab 名称
- ToolSearch 已有合适 matches 时禁止继续 ToolSearch 同一任务
- 禁止调用 ``Agent(subagent_type="Explore")`` 或 ``Agent(subagent_type="general-purpose")`` 代替本域 SDK 工具调用
"""


def append_sop_overview_routing(body: str, *, sdk_source_dir: str | Path | None = None) -> str:
    body = (body or "").strip()
    parts: list[str] = []
    if body:
        parts.append(body)
    routing = SOP_OVERVIEW_ROUTING.strip()
    if routing not in body:
        parts.append(routing)
    sdk_block = format_sdk_source_dir_block(sdk_source_dir)
    if sdk_block and sdk_block.strip() not in body:
        parts.append(sdk_block.strip())
    return "\n\n".join(parts).strip() if parts else SOP_OVERVIEW_ROUTING.strip()
