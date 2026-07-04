# 项目概述与边界约束

> 融合自: `docs/FEATURE_PLAN.md` 项目概述与边界约束

## 项目定位

ClawCodex 是 Anthropic Claude Code 的 Python 移植版，同时扩展多 Provider 支持，目标成为功能完整的 AI Agent CLI 工具。

## 当前架构（三层解耦）

```
src/
├── upstream/            # Layer 1: 上游快照（git archive 提取的原始代码）
│   └── v2025_04/        #     具体版本标签镜像
├── capabilities/        # Layer 2: ClawCodex Protocol 接口定义
│   ├── agent_protocol.py
│   ├── tool_protocol.py
│   ├── context_protocol.py
│   ├── provider_protocol.py
│   ├── event_protocol.py
│   ├── headless_protocol.py
│   └── headless_runner.py
├── orchestrator/        # Layer 3: 自主模式编排
├── api/                 # Layer 3: 公共 Python API
└── ...                  # 其余为上游原有模块
```

**层约束（upstream-sync audit 强制）：**
- `src.upstream` → 只能被 `src.capabilities` 依赖
- `src.capabilities` → 不能导入 `src.upstream`
- `src.orchestrator` / `src.api` → 只能从 `src.capabilities` 导入

## 二次开发层级

```
src/               Layer 0 — 上游源码（Upstream Claude Code）
clawcodex_ext/     Layer 1 — 下游补丁层（Downstream Patches）
extensions/        Layer 2 — 三方扩展层（Extensions）
  ├── orchestrator/       编排器（agent_runner, git_sync, report_writer, tracker…）
  ├── capabilities/       Protocol 接口定义（层间契约，无实现）
  ├── remote_api/         远程 API 服务
  ├── ports/              桥接端口（bridge_main, transports）
  ├── sop_converter/      SOP 编译器
  ├── providers_ext/      三方 LLM 提供者（LiteLLM）
  ├── skills_ext/         三方技能扩展
  ├── tool_system_ext/    三方工具注册
  ├── visualizer/         可视化仪表盘
  ├── agent/              代理持久化扩展
  ├── prompt_lab/         System Prompt 自迭代实验平台（F-119）
  └── ...                 其他三方子系统
```

详见 `docs/decoupling/` 解耦方案文档。F-119 规划详见 `docs/feature_plan/03-agent-core/f-119-prompt-assembly.md`。

## 核心约束

1. **默认路径**: 所有 downstream/custom 开发默认进入 `clawcodex_ext/*`；**不得**在 `src/*` 中直接添加项目专属逻辑。
2. **`src/*` 定位**: 上游形状/core 兼容区，只接受 thin forwarding seams、最小适配层、上游同步更新、窄范围 bug fix。
3. **新功能实现流程**: 先 `clawcodex_ext/*` 实现，`src/*` 仅限 thin forwarding seams。

## 技术栈

- **语言**: Python 3.10+
- **运行时**: asyncio (headless) / Textual (TUI)
- **LLM Provider**: LiteLLM（100+ 模型统一接口）
- **存储**: JSON / JSONL / NDJSON 文件系统持久化
- **CI/CD**: GitHub Actions / GitCode Pipeline
