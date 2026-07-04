# ClawCodex 三层解耦方案

> 本目录是 ClawCodex **三层解耦**相关工作的唯一事实源。
> 涵盖：`src/` (Layer 0) / `clawcodex_ext/` (Layer 1) / `extensions/` (Layer 2) 之间的层间约束、违规整改历史、facade 设计原则与已知遗留问题。
> 创建日期: 2026-06-29 | 起始版本: v1.0
>
> **历史背景**: 本目录延续自 legacy `F-48: src/ 解耦方案`（在 `docs/ARCHIVED_FEATURES.legacy.md:3576` 与 `docs/ARCHIVED_PROGRESS.legacy.md:1755` 详述）。F-48 在 [docs/feature_plan/README.md](../../README.md) 融合时按"独立规划，不在特性规划中体现"原则移除；本目录承接其职责并扩展到 P3 整改全量记录。F-48 的核心约束（三层架构、Layer 2 不依赖 Layer 0 内部模块、最小化修改 `src/`）已纳入 [CLAUDE.md §二次开发解耦原则](../../CLAUDE.md#二次开发解耦原则decoupling-mandate)。

## 目录索引

| 文档 | 内容 | 状态 |
|------|------|:----:|
| [p3-layer2-direct-imports.md](p3-layer2-direct-imports.md) | P3 整改全量 step 详情（6 个 step / 67+ 迁移 imports / 8 新 facade） | ✅ |
| [facade-patterns.md](facade-patterns.md) | 三类 `clawcodex_ext.*` facade 模式（直接 re-export / 同包 sibling / lazy proxy）与选型指南 | ✅ |
| [known-issues.md](known-issues.md) | 已知遗留问题（submodule shadowing / P3-skip 公开 API mock 兼容 / 完整迁移未完成的 facade） | 🔄 |

## 背景与目标

ClawCodex 是 [clawcodex](https://gitcode.com/chadwweng/clawcodex) 的下游 fork。三层架构详见 [CLAUDE.md §二次开发解耦原则](../CLAUDE.md#二次开发解耦原则decoupling-mandate) 与 [docs/feature_plan/01-overview.md §当前架构](../feature_plan/01-overview.md#当前架构三层解耦)。

**层约束（黄金法则摘录）**：

| # | 规则 | 强制层 |
|---|------|--------|
| 1 | 尽量避免修改 `src/` 用于功能开发 | 全部 |
| 2 | Layer 1（`clawcodex_ext/`）可导入 `src.` | Layer 1 |
| 3 | Layer 2（`extensions/`）可导入 `src.` 和 `clawcodex_ext.` | Layer 2 |
| 4 | `extensions/capabilities/` 定义层间 Protocol 契约 | Layer 2 |
| 5 | 优先使用注册/钩子/依赖注入 | 全部 |
| 6 | 增强上游 → `clawcodex_ext/`；新子系统 → `extensions/` | 全部 |

**P3 整改关注点**：第 3 条规则实际允许 Layer 2 import `src.*` 公开 API，但实践中大量 Layer 2 文件直接 import `src.*` 内部模块（甚至 `_internals` 之外但仍属上游核心），与"扩展层尽量走 Layer 1 facade"的最佳实践不符。P3 整改目标是把 Layer 2 对 `src.*` 的直接依赖批量迁移到 `clawcodex_ext.*` facade / 真实实现，让层间依赖更清晰、上游 merge 冲突更少。

## P3 整改累计进度

| Step | Commit | 范围 | 迁移 imports | 新 facade |
|------|--------|------|:------------:|:---------:|
| P3-step1 | `eadc9d6a` | `extensions/capabilities/` 自身清洗 | 6 | 0 |
| P3-step2 | `2258e310` | `orchestrator/git_sync` 清洗 `src.utils.git` | 1 | 0 |
| P3-step3 | `390bc86b` | 7 个 Layer 2 文件（orchestrator/registration/sop/agent/ports/skills） | 7 | 0 |
| P3-step4 | `b4ed35d3` | `extensions/ports/bridge/` 4 文件 + 1 facade | 28 | 1 |
| P3-step5 | `d863cfa3` | `remote_api/runner.py` + `hybrid_v1.py` + 7 facade | 10 (12 中 2 个 P3-skip) | 7 |
| P3-step6 | `8cc3b9a8` | 7 个 Layer 2 文件 12 imports | 12 | 0 |
| **合计** | **6 commits** | **~25 个文件** | **~67 真实迁移 + 2 P3-skip** | **8** |

**P3 完成后状态**：

- `extensions/` 子树中真实 `from src.*` 导入仅剩 **2 个 P3-skip**（公开 API + 测试 mock 路径兼容，详见 [known-issues.md](known-issues.md#p3-skip-公开-api--测试-mock-兼容)）
- 新增 8 个 `clawcodex_ext.*` 薄 facade（`from X import *` 模式），让 Layer 2 静态依赖关系完全在 `clawcodex_ext.*` 层之上
- 验证基线：每次 step 提交前都通过 `py_compile` + `ruff check` + 针对性测试 + `tests/stability_gate/` 全量门禁 + `tests/orchestrator/` 单元套件

## 解耦类工作的下一阶段（P3-out 候选）

详见 [known-issues.md §后续候选](known-issues.md#后续候选)：

1. **P3-out-1: 修复 submodule shadowing 风险** — `clawcodex_ext/tool_system/__init__.py` 中 `from .build_tool import build_tool` 重新导出覆盖子模块名
2. **P3-out-2: 完整迁移遗留 facade** — `src/bridge/repl_bridge_transport.py` 400+ 行真实现 + `src/bridge/session_runner.py` re-export 当前仍以薄 facade 形式留在 src
3. **P3-out-3: P3 文档化** — 即本目录
4. **P-其他: P4 类别方向** — 解耦整改的下一阶段可能聚焦 `clawcodex_ext/` 自身的 `src._internals` 使用模式
