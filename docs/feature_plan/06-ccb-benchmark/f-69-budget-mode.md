# F-69: Budget / Poor Mode 资源节俭模式

> 状态: 🔄 进行中（token_budget 已落地）
> 章节: docs/feature_plan/06-ccb-benchmark/f-69-budget-mode.md
> 最后更新: 2026-06-24

## §1 设计规划

### 1.1 目标

对标 CCB `/poor` 命令（穷鬼模式），实现资源节俭模式，减少 LLM token 消耗，使用户能在简单任务中自主降低资源消耗。

### 1.2 背景

CCB 的 `/poor` 命令开启"穷鬼模式"，跳过高消耗步骤（`extract_memories`、`verification_agent`），减小 context 窗口，减少 API token 消耗。clawcodex 当前无等价机制。

### 1.3 子特性分解

| 编号 | 子特性 | 状态 | 预计工时 |
|:----:|--------|:----:|:--------:|
| P69-A | BudgetMode 配置模型（4 级行为矩阵） | 📋 | 2-3d |
| P69-B | Agent 循环节俭钩子（skip memory/verification） | 📋 | 3-5d |
| P69-C | Tool 级别节俭策略（降级搜索深度/禁用高消耗工具） | 📋 | 2-3d |
| P69-D | `/budget` CLI 斜杠命令 | 📋 | 2-3d |
| P69-E | Token 用量实时统计与自动降级告警 | 🔄 部分完成 | 3-5d |

**已落地**: `clawcodex_ext/query/token_budget.py`（~159 行），提供 `BudgetTracker` / `ContinueDecision` / `StopDecision` 数据结构与 per-turn / per-session 计数。

### 1.4 行为矩阵设计

| 行为 | off | light | medium | aggressive |
|------|:---:|:-----:|:------:|:----------:|
| extract_memories | ✅ | ✅ | ❌ | ❌ |
| verification_agent | ✅ | ❌ | ❌ | ❌ |
| search_depth | 10 | 5 | 3 | 1 |
| max_tool_calls/turn | 20 | 10 | 5 | 3 |
| context_window | max | 80% | 50% | 30% |
| 自动 Web 搜索 | ✅ | ✅ | ❌ | ❌ |

### 1.5 Agent 循环 Hook 点

```python
class AgentLoop:
    def __init__(self, config: AgentConfig):
        self.budget = BudgetModeManager(config.budget_mode or "off")
        self.token_counter = TokenCounter()

    async def run(self, conversation):
        # Hook 1: Memory Recall
        if self.budget.is_enabled("extract_memories"):
            memories = await self._extract_memories(conversation)
        else:
            memories = []

        # Hook 2: 最大轮次限制
        max_turns = self.budget.get("max_tool_calls/turn")
        for turn in range(max_turns):
            # Hook 3: Verification Agent
            if self.budget.is_enabled("verification_agent"):
                await self._run_verification(...)

            # Hook 4: Token 消耗控制
            tool_result = await self._call_tool(...)
            self.token_counter.add(tool_result.token_usage)
            if self.token_counter.exceeds(self.budget.get("context_window")):
                self.budget.downgrade()  # 自动降级

            # Hook 5: Web 搜索条件启用
            if tool_result.requires_web_search and not self.budget.is_enabled("auto_web_search"):
                continue
```

### 1.6 配置模型

```python
@dataclass
class BudgetConfig:
    mode: str = "off"                     # off/light/medium/aggressive
    token_limit: int = 0                  # per-session token 阈值
    auto_downgrade: bool = False          # 超阈值自动降级
    downgrade_to: str = "medium"           # 降级目标
```

**注入点**:
- `src/query/config.py`: QueryConfig 增加 budget 字段
- `src/cli.py`: 增加 `--budget light/medium/aggressive` 参数
- 斜杠命令注册: `/budget`

### 1.7 依赖

- 无第三方依赖
- F-68 Feature Gate 可作为底层开关机制复用
- F-102 pre-LLM 钩子用于注入节俭提示

## §2 进度跟踪

### 2.1 已完成

| 日期 | 里程碑 | 涉及文件 |
|------|--------|---------|
| 2026-06 | TokenBudget 数据结构 | token_budget.py ~159 行 |

### 2.2 下一步计划

1. BudgetMode 配置模型
2. Agent 循环节俭钩子集成
3. tool 级别节俭策略
4. /budget CLI 命令

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-06-24 | 补全详细设计（行为矩阵+Hook 点+配置模型） | 对齐 FEATURE_PLAN.legacy.md |
