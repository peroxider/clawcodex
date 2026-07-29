# 能力感知 Harness 自适应设计文档集

> 本目录是 ClawCodex **能力感知 Harness 自适应**的设计、调研与落地蓝图。
> 解决的问题：让 harness 同时且自动支持强智力（如 Fable 5 / GPT-5.6）到弱模型（如本地 Qwen3.6-32B），且中间档位也要覆盖。判断过程自动化（避免依赖人工标注），约束按四层（AGENT.md / 工具 / 权限 / 提示词）下发。
> 产出日期: 2026-07-28 | 关联项目: clawcodex-dev (Layer 0 上游 + Layer 1 补丁 + Layer 2 扩展)

## 阅读顺序

| # | 文档 | 作用 | 时长 |
|---|------|------|:----:|
| 0 | [00-capability-harness.md](00-capability-harness.md) | 主报告 — 现状诊断 + 6 大 gap + 三层架构骨架 | 25 min |
| 1 | [01-registry-yaml.md](01-registry-yaml.md) + [assets/registry.yaml](assets/registry.yaml) | 附录 A — 能力注册表（5 known model + 静态分级 + 社区 benchmark fallback） | 10 min |
| 2 | [02-tier-profiles.md](02-tier-profiles.md) + [assets/tier_profiles.yaml](assets/tier_profiles.yaml) | 附录 B — Tier Profiles × 4 层约束（3 tier × 4 层） | 15 min |
| 3 | [03-probe-spec.md](03-probe-spec.md) + [assets/probe_spec.yaml](assets/probe_spec.yaml) | 附录 C — 探针套件（4 probe kind + tier_mapping + anti-reward-hacking） | 12 min |
| 4 | [04-code-prototypes.md](04-code-prototypes.md) | 附录 D — 6 个 Python 原型文件（tier_decision / stream_judge / registry_loader / tool_profiles / permission_profiles / bootstrap_runner） | 30 min |
| 5 | [05-patch-blueprint.md](05-patch-blueprint.md) | 附录 E — clawcodex 改造蓝图（17 处 patch + 5-PR 拆分 + 兼容性矩阵） | 20 min |
| 6 | [06-ci-deployment.md](06-ci-deployment.md) | 附录 F — CI 集成（Stage 7/8）+ Day-1/30/90 渐进 rollout + 风险登记 | 15 min |
| 7 | [07-community-research.md](07-community-research.md) | 附录 G — 一手调研（Codex / Anthropic Auto Mode / AAIF / SWE-bench / AgentPRM） | 20 min |
| 8 | [08-end-to-end-walkthrough.md](08-end-to-end-walkthrough.md) | 附录 H — 三档端到端 session walk-through + 横向对比矩阵 | 15 min |
| 9 | [09-failure-modes.md](09-failure-modes.md) | 附录 I — 8 类失败模式与回退策略 | 12 min |
| 10 | [10-recommendations-open-q.md](10-recommendations-open-q.md) | 附录 J — 10 条 actionable 建议 + 5 个开放问题 + Goal 闭环对照 | 10 min |

## 核心论点（TL;DR）

1. **强→弱连续光谱不是 3 档而是 3 tier + 内部动态微调**：3 tier（Weak/Standard/Strong）是粗粒度骨架；每 tier 内部由 stream_judge 4 维 EMA（tool_precision / plan_progress / error_recovery / context_efficiency）做细粒度动态调整。
2. **自动化判断三层叠加**：
   - L1 静态注册表（registry.yaml + SWE-bench/LiveCodeBench 分数 fallback）
   - L2 Bootstrap 探针（首次遇到未知模型跑 4 probe kind，~30 s）
   - L3 Stream Judge（rolling N=20 turns EMA，reasoning-blind by design）
3. **四层约束必须正交下发**：L1 AGENT.md（tier-scoped 文件） + L2 ToolProfileProvider（Weak 6 narrow / Standard 26 / Strong 4 CodeAct） + L3 PermissionProfileProvider（7 Action × 3 tier × workspace_write sub-state） + L4 prompt_assembly.py tier-aware section。
4. **与 clawcodex 现有架构对齐**：全部新增代码落 `clawcodex_ext/query/capability/` + `extensions/capability_probe/`（Layer 1 + Layer 2），对 `src/` 仅做 additive hook；5-PR 拆分确保可独立 revert。

## F-Number 状态总表

> 本章节归属 F-174，拆分为 P174-A ~ P174-I；各子特性均处于规划阶段。

| 编号 | 名称 | 状态 | 章节路径 |
|------|------|:----:|---------|
| F-174 | 能力感知 Harness 自适应 | 📋 规划中 | [00-capability-harness.md](00-capability-harness.md) |
| P174-A | Capability Registry & Loader | 📋 规划中 | [01-registry-yaml.md](01-registry-yaml.md) |
| P174-B | Tier-Aware AGENT.md Loader | 📋 规划中 | [02-tier-profiles.md §L1](02-tier-profiles.md) |
| P174-C | Tool Profile Provider (Weak/Standard/Strong) | 📋 规划中 | [02-tier-profiles.md §L2](02-tier-profiles.md) + [04 §D.4](04-code-prototypes.md) |
| P174-D | Permission Profile Provider (7 Action × 3 Tier) | 📋 规划中 | [02-tier-profiles.md §L3](02-tier-profiles.md) + [04 §D.5](04-code-prototypes.md) |
| P174-E | Bootstrap Probe Suite (4 kinds) | 📋 规划中 | [03-probe-spec.md](03-probe-spec.md) |
| P174-F | Stream Judge (4-dim EMA) | 📋 规划中 | [04 §D.2](04-code-prototypes.md) |
| P174-G | Tier Decision & Query Loop Integration | 📋 规划中 | [04 §D.1](04-code-prototypes.md) + [05-patch-blueprint.md](05-patch-blueprint.md) |
| P174-H | CI Integration (Stage 7/8) | 📋 规划中 | [06-ci-deployment.md §1](06-ci-deployment.md) |
| P174-I | Telemetry & Per-Subagent Tier Override | 📋 规划中 | [06-ci-deployment.md §4](06-ci-deployment.md) |

## 变更历史

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-07-28 | 初始创建（主报告 + 10 附录 + 3 YAML 资产） | 用户提出"能力感知 harness"分析报告需求；产出 25 万字完整设计与落地蓝图 |