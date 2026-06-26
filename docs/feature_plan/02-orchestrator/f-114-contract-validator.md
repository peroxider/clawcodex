# F-114: 阶段契约验证器

> 状态: 📋 规划中
> 章节: docs/feature_plan/02-orchestrator/f-114-contract-validator.md
> 最后更新: 2026-06-24

## §1 设计规划

### 1.1 目标

执行阶段输出的机器可验证 DoD 检查。

### 1.2 内置 Validator 实现

| 类型 | 实现 | 优先级 |
|------|------|:------:|
| `file_exists` | `Path.exists()` | P0 |
| `file_size` | `Path.stat().st_size` | P0 |
| `regex` | `re.findall()` + `min_matches` | P0 |
| `json_schema` | `jsonschema.validate()` | P1 |
| `line_count` | `len(file.readlines())` | P0 |
| `llm_judge` | LLM 评估 + 分数阈值 | P1 |
| `custom` | `subprocess.run()` + exit code | P2 |

### 1.3 实现文件

| 文件路径 | 变更描述 | 状态 |
|---------|---------|:----:|
| `extensions/orchestrator/workflow_engine/validators/__init__.py` | `ContractValidator` + 注册表 | 📋 |
| `extensions/orchestrator/workflow_engine/validators/builtin.py` | 6 种内置 Validator | 📋 |
| `extensions/orchestrator/workflow_engine/validators/llm_judge.py` | LLM-as-judge | 📋 |
| `extensions/orchestrator/workflow_engine/validators/custom.py` | 自定义命令 | 📋 |

## §2 进度跟踪

尚未开始。

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
