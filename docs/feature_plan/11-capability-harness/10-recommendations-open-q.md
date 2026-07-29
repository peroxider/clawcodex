# 附录 J — 终极建议与开放问题

> 状态: 📋 规划中
> 用途: 综合所有附录给出 actionable 建议 + 待研究开放问题 + Goal 闭环对照

---

## §1 10 条 Actionable 建议（按优先级）

### P0 — 必须做

1. **落地 `clawcodex_ext/query/capability/` 模块**（附录 D 全套 + 附录 E patch）。这是整个能力感知体系的物理基础；不做后续都免谈。

2. **5 个已知模型写进 registry.yaml**（附录 A）：Fable 5、GPT-5.6 Codex、Sonnet 4.6、GLM-4.7、Qwen3-Coder-Next 32B-active MoE。包含 SWE-bench 分数作为 fallback signal。

### P1 — 应该做

3. **Stage 7 + Stage 8 CI gate**（附录 F）：先于 Day-30 rollout 上线，作为 capability 模块的 contract test，防止后续 patch 破坏不变量。

4. **Bootstrap probe + Tier-aware AGENT.md 加载**（附录 B + C）。Day-30 完成。

5. **ToolProfileProvider + PermissionProfileProvider 双 Protocol**（附录 D.4 + D.5）。Day-1 即落地，无 query.py 改动。

### P2 — 推荐做

6. **StreamJudge runtime 接入**（附录 D.2 + E.2 第 5-7 行）。Day-30 上线，仅作 telemetry + 建议，不实际 flip tier（保守起步）。

7. **Telemetry 收集**（附录 F.4）：每次 session 写 `.reports/<id>/capability_trace.json`。Day-30 起用于校准 bootstrap probe 阈值。

8. **`--tier auto` 默认值切换**：Day-90 完成。先 30 天 `--tier manual` 默认，期间收集 telemetry；Day-90 再切 auto。

### P3 — 长期

9. **Probe 答案池月度轮换**：Day-90 后实施，避免 anti-reward-hacking 漂移。

10. **跨模型 A/B dashboard**：Day-180+ 长期工作 — 在 `extensions/visualizer/` 加 capability_judge 视图，对比 weak/standard/strong 在同一任务族的实际表现。

---

## §2 5 个开放问题（待研究）

### Q1: Tier 数量上限

3 tier 还是 5 tier（加 weak-std、std-strong）？3 tier 已能覆盖 SOTA 分布，但 mid-tier 内仍有梯度（如 Sonnet 4.6 vs GPT-5.6 都是 standard，但前者 weak-leaning，后者 strong-leaning）。

**判断依据**: 需更多 telemetry 才能定论。Day-90 后看 `stream_judge_internal_grade_distribution` 数据：
- 若 standard tier 内 80% 集中在 ±0.1 区间 → 3 tier 够用
- 若分散到 ±0.3 → 考虑扩到 5 tier

### Q2: Stream judge 的 flip 上限

当前 1 次/session 是否过保守？强模型 session 可能跑 50+ turns，1 次 flip 不够。

**判断依据**:
- 监控 `flip_max_per_session_reached_rate`
- 若 > 5% session 触发到上限 → 提高到 2-3
- 但上限过高会引入抖动，需配合 EMA 平滑参数调整

### Q3: Bootstrap probe 的成本

5 个 probe × 4 kind × ~30s/local model = 2 分钟首次启动延迟。是否要做 lazy-load — 仅在 user prompt 含 "complex task" 关键词时才跑 probe？

**判断依据**:
- 监控 `bootstrap_probe_avg_latency_s`
- 若用户反馈启动慢 → 引入 lazy-load 或后台 pre-warm
- 短期：Day-90 后看 1000 session 数据决定

### Q4: PermissionProfile 的 Action 枚举完备性

当前 7 种（READ/WRITE/EXEC/GIT_PUSH/NETWORK_OUT/DESTRUCTIVE/INSTALL）。是否漏了 `WEB_FETCH`、`DB_QUERY`、`K8S_APPLY` 等？

**判断依据**: Day-30 telemetry 收集 DENY/ASK 实际命中的 Action 分布，若 > 5% session 命中未定义 action → 补 Action 枚举。

### Q5: 跨 session 的能力画像

用户跑 100 次 Qwen3-Coder-Next 后，是否能聚合出"该 user + 该 model 的实际 tier 画像"（而非每次 session 重测）？

**需要**:
- session report 的长期存储 + 时序分析
- 与 F-166 记忆分层（W/E）协同 — Episodic Memory 可存历史 session 报告
- Day-180+ 远期工作

---

## §3 Goal 闭环对照（来自原始目标）

> "一个架构合理的 harness 需要同时且自动支持强智力(例如 fable5、gpt-5.6)到弱模型(例如本地 Qwen3.6-32B)，且强到弱是一个无级变速过程(即强到弱之间的模型也要能支持)。这种支持需要尽可能自动化判断(因为模型在快速发展)，例如通过整体任务完成率，阶段完成率，任务过程错误率等客观数据，固定测试题与开源社区 benchmark 进行判断。harness 需要通过 AGENT.md，提供的工具以及工具约束(强模型完全可以基于基础工具自建新工具而弱模型需要使用工程师精心构建的工具)，权限设置(文件，执行，哪些事情不能做)，提示词等方面对不同智能模型进行限制。"

### 逐句对照

| 原文要求 | 本文交付物 | 验证 |
|---------|----------|------|
| 同时且自动支持强智力到弱模型 | 附录 A 5 model；附录 D 7 文件；附录 H walk-through | ✅ |
| 强到弱无级变速过程 | 3 tier + 4 维 EMA + bootstrap probe；附录 H 横向对比 | ✅ |
| 中间档支持 | registry metrics 阈值 + bootstrap 4 probe；附录 A §5 | ✅ |
| 自动化判断（避免人工标注） | registry + bootstrap + stream_judge 三层全自动 | ✅ |
| 整体任务完成率 | stream_judge T1（tool precision） | ✅ |
| 阶段完成率 | stream_judge T2（plan progress） | ✅ |
| 任务过程错误率 | stream_judge T3（error recovery） | ✅ |
| 客观数据驱动 | T1/T2/T3/T4 + 4 probe + registry metrics | ✅ |
| 固定测试题 | 附录 C 4 probe kind（tiny_plan / tool_param_precision / multi_step_completion / bash_safety_smoke） | ✅ |
| 开源社区 benchmark | SWE-bench Verified / LiveCodeBench / MT-Bench（附录 G §4） | ✅ |
| AGENT.md 约束 | tier-scoped AGENT.<tier>.md（附录 B §3 + 附录 H §2-4） | ✅ |
| 提供的工具以及工具约束 | 附录 D.4 + 附录 B §2.2 + 附录 H §5 | ✅ |
| 强模型自建工具 | StrongProfile 4 CodeAct primitives（bash + python_exec + 2 file） | ✅ |
| 弱模型工程师构建工具 | WeakProfile 6 narrow typed tools | ✅ |
| 权限设置 | 附录 D.5 + 附录 B §2.3 + 附录 H §5 | ✅ |
| 文件 | Action.fs.read / fs.write / fs.destructive | ✅ |
| 执行 | Action.exec.run（tier-aware ALLOW/DENY/ASK） | ✅ |
| 哪些事情不能做 | DENY rules + bash_safety_smoke probe | ✅ |
| 提示词约束 | 附录 E.2 prompt_assembly.py 3 处 tier-aware section | ✅ |

**所有 12 项子要求全部覆盖且未收窄范围**。

---

## §4 与上游 Claude Code 的差异

| 维度 | 上游 Claude Code | 本文 clawcodex 扩展 |
|------|-----------------|-------------------|
| Tier 概念 | 单一模式 + 用户 permission_mode | 3 tier × user override |
| AGENT.md | 单一 `CLAUDE.md` | tier-scoped `AGENT.<tier>.md` + AAIF `AGENTS.md` 兼容 |
| Tool 列表 | 26 工具硬编码 | Tier-aware dynamic（6/26/4） |
| Permission | deny list 单档 | 7 Action × 3 Tier × 2 sub-state |
| 能力评估 | 无 | registry + bootstrap + stream_judge 三层 |
| 自动化 | 完全靠用户标注 | registry hit → bootstrap → stream_judge 全自动 |

差异点符合 clawcodex 二次开发解耦原则 — 全部新增落 `clawcodex_ext/` 与 `extensions/`，对 `src/` 仅做 additive hook；未来若上游合并类似能力，可平滑迁移。

---

## §5 关联文档

- 主报告：[00-capability-harness.md](00-capability-harness.md)
- 全部附录：[README.md](README.md)
- 风险登记：[09-failure-modes.md](09-failure-modes.md)
- CI / 部署：[06-ci-deployment.md](06-ci-deployment.md)