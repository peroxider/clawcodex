# F-114: 阶段契约验证器

> 状态: ✅ 已完成（核心实现 + 单元测试 + 上下文注入）
> 章节: docs/feature_plan/02-orchestrator/f-114-contract-validator.md
> 最后更新: 2026-07-10

## §1 设计规划

### 1.1 目标

为声明式工作流引擎（F-110）提供阶段输出的机器可验证 DoD（Definition of Done）检查能力。验证器在以下两处被调用：

1. **AGENT 阶段完成后**：`engine.py:_run_agent_stage` 调用 `_validate_stage_output`，对阶段产物做断言；失败则抛出 `StageFailureError`。
2. **GATE auto 模式**：`stage_runner.py:_run_auto_gate` 调用 `ContractValidator.validate_all`，根据验证结果判定是否通过 GATE。

### 1.2 内置 Validator 实现

| 类型 | 实现 | 优先级 | 状态 | 说明 |
|------|------|:------:|:----:|------|
| `file_exists` | `Path.exists()` | P0 | ✅ | 验证文件/目录是否存在 |
| `file_size` | `Path.stat().st_size` | P0 | ✅ | 支持 `min_bytes` / `max_bytes` |
| `regex` | `re.findall()` + `min_matches` | P0 | ✅ | 正则匹配文件内容 |
| `line_count` | `len(content.splitlines())` | P0 | ✅ | 支持 `min_lines` / `max_lines` |
| `json_schema` | `jsonschema.validate()` | P1 | ✅ | 依赖 `jsonschema` 库；未安装时返回失败 |
| `llm_judge` | LLM 评估 + 分数阈值 | P1 | ✅ | 支持 `complete` / `chat` / `generate` 三种客户端接口 |
| `custom` | `subprocess.run()` + exit code | P2 | ✅ | 支持 `cwd` / `env` / `timeout` / `shell` |

### 1.3 实现文件

| 文件路径 | 变更描述 | 状态 |
|---------|---------|:----:|
| `extensions/orchestrator/workflow_engine/validators/__init__.py` | `ValidationResult` + `ContractValidator` 注册表 + 6 种内置同步验证器 + `llm_judge` 代理 | ✅ |
| `extensions/orchestrator/workflow_engine/validators/llm_judge.py` | LLM-as-judge 完整实现，含配置解析、多接口适配、响应解析、降级启发式评分 | ✅ |
| `extensions/orchestrator/workflow_engine/validators/custom.py` | 自定义命令验证器，支持 `cwd`/`env`/`timeout`/`shell` 等高级参数 | ✅ |
| `tests/orchestrator/test_contract_validator.py` | 单元测试（内置验证器 + LLM Judge mock + custom 命令） | ✅ |

> **注**：原规划中的 `builtin.py` 未单独拆分。当前实现将 6 种同步内置验证器直接放在 `__init__.py` 中，以减少小文件碎片；后续若内置验证器数量继续增长，再拆分为 `builtin.py`。

### 1.4 子特性分解

| 子特性 | 描述 | 状态 | 优先级 |
|--------|------|:----:|:------:|
| F-114-A | 验证结果数据结构 `ValidationResult`（passed / message / score / detail / details） | ✅ | P0 |
| F-114-B | `ContractValidator` 注册表：支持注册自定义验证器（同步/异步） | ✅ | P0 |
| F-114-C | 同步内置验证器：file_exists / file_size / regex / line_count / json_schema | ✅ | P0 |
| F-114-D | 异步内置验证器：llm_judge | ✅ | P1 |
| F-114-E | 自定义命令验证器：custom | ✅ | P2 |
| F-114-F | 与 StageRunner / WorkflowEngine 集成：AGENT 阶段输出验证 + GATE auto 判定 | ✅ | P0 |
| F-114-G | 单元测试覆盖 | ✅ | P0 |
| F-114-H | `workspace_dir` 与 `llm_client` 上下文注入机制 | ✅ | P1 |

## §2 进度跟踪

### 2.1 当前基线

核心代码、单元测试与上下文注入均已实现并通过验证：

- `ContractValidator` 可注册/执行同步与异步验证器。
- 6 种同步内置验证器（file_exists / file_size / regex / line_count / json_schema / custom 基础版）已实现。
- `llm_judge.py` 已实现完整 LLM 评分链路，含降级启发式评分。
- `custom.py` 已实现带 `cwd` / `env` / `timeout` / `shell` 的高级自定义命令验证。
- `engine.py` 在 AGENT 阶段完成后调用 `_validate_stage_output`，并复用带 `workspace_dir`/`llm_client` 注入的 `ContractValidator` 实例。
- `stage_runner.py` 在 GATE `auto` 模式下调用复用的验证器实例做判定。
- `gate_handler.py` 的 auto 模式同样复用带上下文的验证器实例。
- `WorkflowOrchestrator` 支持可选 `llm_client` 参数，并向下透传到引擎与 StageRunner。
- 新增 `tests/orchestrator/test_contract_validator.py`，覆盖 7 种内置验证器、自定义注册、上下文注入与 `validate_sync` 行为。

### 2.2 剩余缺口

1. **`detail` / `details` 字段并存**：`ValidationResult` 同时保留 `detail` 与 `details`，需统一消费方，避免字段歧义（P2，非阻塞）。

### 2.3 下一步计划

1. 清理 `ValidationResult` 的 `detail` / `details` 兼容字段，选定单一字段（P2）。
2. 当上游有可用的 LLM 客户端时，通过 `WorkflowOrchestrator(..., llm_client=...)` 接入真实评分后端。

## §3 实施细节

### 3.1 Validator Spec 格式

```yaml
stages:
  - id: 1
    name: generate-report
    phase: implement
    prompt: "生成报告到 output/report.md"
    validators:
      - type: file_exists
        path: output/report.md
      - type: file_size
        path: output/report.md
        min_bytes: 100
      - type: regex
        path: output/report.md
        pattern: "## Summary"
        min_matches: 1
      - type: line_count
        path: output/report.md
        min_lines: 10
        max_lines: 1000
      - type: json_schema
        path: output/metrics.json
        schema:
          type: object
          required: ["version"]
          properties:
            version: { type: string }
      - type: llm_judge
        path: output/report.md
        threshold: 0.7
        rubric: "评估报告完整性、清晰度与格式规范性"
        model: "gpt-4"
      - type: custom
        command: "python -m pytest tests/ -q"
        cwd: "."
        timeout: 120
        shell: false
```

### 3.2 错误处理策略

- 验证器内部异常（文件不存在、JSON 非法、命令超时等）统一捕获并返回 `passed=False`，不直接抛异常。
- AGENT 阶段：`_validate_stage_output` 收集所有失败 message，合并为 `StageFailureError`。
- GATE auto 模式：任一验证器失败即 `approved=False`，reason 包含失败消息列表。

### 3.3 与 F-110/F-111/F-112 的集成

```
DeclarativeWorkflowEngine._run_agent_stage
  └── ContractValidator.validate_all(stage.validators)
        └── 失败 → StageFailureError

StageRunner._run_auto_gate
  └── ContractValidator.validate_all(stage.validators)
        └── 全通过 → GateRunResult(approved=True)
```

## §4 验收标准

1. 7 种内置验证器均可通过 `ContractValidator.validate_all` 独立调用并返回 `ValidationResult`。
2. `file_exists` / `file_size` / `regex` / `line_count` 支持相对路径与 `~` 展开。
3. `json_schema` 在 `jsonschema` 未安装时给出明确失败提示，不抛未捕获异常。
4. `llm_judge` 在有 `llm_client` 时返回 LLM 评分，无客户端时走降级启发式评分。
5. `custom` 验证器支持 `cwd` / `env` / `timeout` / `shell`，超时返回失败而非抛异常。
6. AGENT 阶段输出验证失败能正确触发 `StageFailureError` 并停止工作流（或按 `on_error` 策略处理）。
7. GATE `auto` 模式下验证器全通过则 `approved=True`，任一失败则 `approved=False`。
8. 新增 `tests/orchestrator/test_contract_validator.py`，覆盖全部 7 种验证器及注册自定义验证器场景。

## §5 风险与约束

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| `custom` 验证器执行任意 shell 命令 | 安全风险 | 仅在工作流配置受信任时启用；`shell` 默认 `False`；后续可接入权限系统 |
| `llm_judge` 评分不稳定 | 可能误拒/误过 | 默认阈值 0.7，支持 rubric 自定义；关键路径建议搭配确定性验证器 |
| `jsonschema` 未安装导致验证失败 | P1 功能降级 | 失败信息明确提示安装依赖 |
| `workspace_dir` / `llm_client` 未注入导致部分功能失效 | 已解决 | `ContractValidator` 构造时注入并向下透传；`WorkflowOrchestrator` 支持 `llm_client` 参数 |
| 验证器在 GATE 中同步顺序执行 | 大量验证器时延迟累加 | 当前 stage 级验证器数量通常 <10，可接受；后续可考虑并发 |

## §6 已拟定的设计决定

| ID | 决定 | 原因 |
|----|------|------|
| DD-F114-1 | 内置同步验证器直接放在 `__init__.py`，暂不拆 `builtin.py` | 6 种同步验证器代码量可控，避免过度拆分；待超过 10 种或需要独立版本控制时再拆分 |
| DD-F114-2 | `llm_judge` 单独文件 `llm_judge.py` | LLM 适配逻辑较复杂，独立文件便于维护和替换评分后端 |
| DD-F114-3 | `custom` 验证器单独文件 `custom.py` | 支持 subprocess 的高级参数，独立文件避免 `__init__.py` 膨胀 |
| DD-F114-4 | 验证器异常统一在 `ContractValidator.validate` 内捕获 | 保证单个验证器失败不影响其他验证器执行，且输出结构一致 |
| DD-F114-5 | `ValidationResult` 同时保留 `detail` 与 `details`（兼容旧字段） | 当前消费方未统一，保留双字段避免破坏既有调用；后续在清理字段时收敛 |
| DD-F114-6 | `json_schema` 依赖可选 `jsonschema` 库 | 避免对非 JSON 工作流强制引入重型依赖 |
| DD-F114-7 | `ContractValidator` 构造时注入 `workspace_dir` / `llm_client` | 让 `custom` 与 `llm_judge` 验证器能获得执行上下文，避免每次调用都重新创建实例 |
| DD-F114-8 | `validate_sync` 在已有事件循环中显式抛 `RuntimeError` | 避免在运行中的协程里阻塞事件循环；调用方应使用异步 `validate()` 接口 |

## §7 依赖与协同

- **前置**：F-110（WorkflowEngine 需具备阶段输出验证钩子）、F-111（StageRunner 需调用验证器做 GATE 判定）。
- **协同**：F-112（GATE auto 模式直接消费验证结果）、F-113（DECISION 阶段可基于验证分数做分支）。
- **复用**：后续 F-116 可观测性通过 `EventBus` 发射 `stage_validation_failed` 事件。
- **无上游侵入**：所有实现位于 `extensions/orchestrator/workflow_engine/validators/`，符合解耦原则。

## §8 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-07-10 | 补全子特性、进度跟踪、验收标准、风险、设计决定、依赖协同 | 代码已落地，补齐规划缺口 |
| 2026-07-10 | 实现上下文注入并新增 `tests/orchestrator/test_contract_validator.py` | F-114-G / F-114-H 完成 |
