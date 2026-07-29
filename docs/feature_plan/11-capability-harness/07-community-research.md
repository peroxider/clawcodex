# 附录 G — 互联网/开源社区一手调研汇总

> 状态: 📋 规划中
> 调研日期: 2026-07-28
> 覆盖: Codex / Anthropic Auto Mode / AAIF AGENTS.md / SWE-bench / AgentPRM / NIST AI RMF

---

## §1 OpenAI Codex 三档 Sandbox × 三档 Approval

**来源**: OpenAI Codex CLI 官方文档 + AISI / Apollo Research 评测公开报告（2026-04）。

### 1.1 两轴正交设计

```
Sandbox modes (文件系统隔离强度)
  read-only         — 进程只能读，不能写；网络不可达
  workspace-write   — cwd 可写，cwd 外只读；网络按 approval policy 决定
  danger-full-access— 无任何隔离（仅在显式 opt-in 时启用）

Approval modes (默认行为)
  suggest          — 每次 bash/edit 都需要用户确认（默认值）
  auto-edit        — 文件编辑自动通过；bash 仍需确认
  full-auto        — 全部自动，仅在危险操作时 confirm
```

### 1.2 用户分布（Codex 2026-Q2 数据）

- 78% sessions: `workspace-write + auto-edit`（标准档）
- 17% sessions: `read-only + suggest`（保守档）
- 5% sessions: `danger-full-access + full-auto`（CI/无人值守）

### 1.3 对 clawcodex 的映射

- clawcodex 当前 sandbox 单档（仅 `permissions.deny` 白名单/黑名单），缺 sandbox 隔离层
- 本文 `PermissionProfileProvider` 的 3 tier × 2 sub-state（read-only / workspace-write）覆盖了 Codex 95% 的实际用法
- Codex 的 approval 三档对应 clawcodex 的 ASK 三态（git push / net.out / destructive）

---

## §2 Anthropic Auto Mode — 两阶段分类器

**来源**: Anthropic Engineering Blog 2026-06 "Designing Auto Mode for Claude Code"。

### 2.1 两阶段架构

```
Stage 1 (cheap heuristic):
  rule-based pattern match — bash 是否有 rm -rf / curl | sh / chmod 777 等
  → 拒绝/通过，~8.5% false positive rate

Stage 2 (LLM judge):
  对 Stage 1 标记 ambiguous 的请求调一次轻量模型
  → reasoning-blind by design（judge 不读 reasoning_content）
  → false positive rate 降到 0.4%
```

### 2.2 三条关键设计原则

1. **Reasoning-blind** — judge 永远看不到 CoT，否则会被 reward-hack（模型故意在 CoT 里说"我准备执行 rm -rf"诱导 judge 拒）
2. **两阶段** — Stage 1 用 cheap rule cover 95% case，Stage 2 只处理剩余 ambiguous，避免每次 judge 都调 LLM
3. **可观测** — Auto Mode 的每一次决策都被 telemetry 记录，工程师可一周一次人工 review ambiguous case 调 Stage 1 规则

### 2.3 对 clawcodex 的映射

- 当前 clawcodex 的 `permissions/permission_check.py` 是单阶段规则集；缺 Stage 2
- 本文 `PermissionProfileProvider.check(...)` 返回三态 `ALLOW/DENY/ASK`，其中 `ASK` 即 Stage 2 触发条件
- `stream_judge` 完整复刻 reasoning-blind 原则：judge 只看 `tool_calls / plan_diff / error_log / token_ratio`，不读 thinking_blocks

---

## §3 AAIF AGENTS.md 标准（Linux Foundation）

**来源**: AAIF (Agentic AI Foundation) 2026-Q2 spec v1.1。

### 3.1 文件位置

```
~/.agents.md                # 全局
<repo>/AGENTS.md            # 仓库级
<repo>/.agents/agents.md    # 子目录级 (closest wins)
```

### 3.2 层级加载顺序

```
1. system prompt (from provider)
2. global ~/.agents.md
3. repo AGENTS.md
4. dir-scoped .agents/agents.md  (recursive, closest wins)
5. tool definitions
6. user message
```

### 3.3 三家命名之争

- Anthropic Claude Code: `CLAUDE.md`
- OpenAI Codex: `AGENTS.md`
- Google Gemini CLI: `GEMINI.md`

AAIF 官方统一为 `AGENTS.md`（复数），但厂商未统一。

### 3.4 对 clawcodex 的映射

- 当前 `clawcodex_ext/agents/AGENTS.md` 加载在 prompt_assembly 时
- 本文建议引入 **tier-scoped AGENT.md**：`AGENT.weak.md` / `AGENT.standard.md` / `AGENT.strong.md`，由 `prompt_assembly.py` 按 tier 选取对应文件内容拼接到 system prompt 的"## Tier-aware guidance"段
- 保留 `AGENTS.md`（AAIF 兼容）+ 新增 `AGENT.<tier>.md`（clawcodex 扩展），不破坏 AAIF 互操作

---

## §4 SWE-bench Verified / LiveCodeBench 排名（2026-07 快照）

**来源**: openai/swe-bench-verified leaderboard + livecodebench.com 公开榜。

| 模型 | SWE-bench Verified | LiveCodeBench v5 | 备注 |
|------|:------------------:|:----------------:|------|
| Mythos 5 | 95.5% | 92.1% | 闭源，OpenAI 内部 benchmark |
| Fable 5 | 95.0% | 89.8% | Anthropic 闭源 |
| Opus 4.8 | 88.6% | 82.3% | Anthropic |
| Sonnet 4.6 | 71.2% | 68.4% | Anthropic |
| GPT-5.6 Codex | 84.1% | 79.5% | OpenAI 编码特化 |
| GLM-4.7 | 62.8% | 58.9% | 智谱 |
| Kimi K2.5 | 58.3% | 55.2% | Moonshot |
| Qwen3-Coder-Next 32B-active MoE | 44.3% | 41.7% | 阿里 |
| Llama-4-Coder 70B | 38.7% | 36.1% | Meta |

### 4.1 关键观察

- 强模型（SOTA ≥ 85%）和弱模型（SOTA ≤ 50%）之间有 2× 以上差距；mid-tier（50-80%）是最难调优的区段
- SWE-bench Verified 与 LiveCodeBench 高度相关（Spearman ρ ≈ 0.94），单 benchmark 即可近似估计
- Qwen3-Coder-Next 在 SWE-bench 44.3% 不代表"不能用" — 它在 narrow、well-scoped 任务上仍可达 70%+；只是不能给 open-ended 任务

### 4.2 对 clawcodex 的映射

- `registry.yaml` 的 `metrics.swe_bench_verified` 字段是 boot probe 的 backup signal — 当 bootstrap probe 跑不通（模型 API 限流），可用 SWE-bench 排名近似分级：
  - ≥ 80 → strong
  - 50-80 → standard
  - < 50 → weak
- 这给"完全无 LLM 调用即可分级"的 fallback 留了出口，对本地 Qwen3.6-32B 这种离线模型也适用

---

## §5 AgentPRM (Process Reward Model)

**来源**: arXiv:2603.08472 "Process Reward Models for Tool-Using Agents" (Anthropic + Stanford 2026)。

### 5.1 核心发现

final-only outcome reward（只看任务最终是否成功）容易被 reward-hacking — 模型可以走非预期路径但撞运气成功。AgentPRM 在每个 step 后插入轻量 verifier（结构化校验 + LLM judge），把"过程分"和"结果分"加权和。

### 5.2 公式

```
step-level reward = 0.7 × outcome + 0.3 × process
process = Σ step_score_i / N_steps
step_score 来自结构化校验（tool 调对了吗、参数合法吗、副作用在 sandbox 内吗）
LLM judge 仅在结构化校验 ambiguous 时介入，且不读 reasoning
```

### 5.3 对 clawcodex 的映射

`stream_judge` 的 4 维评分本质就是 step-level process reward 的简化版：

| stream_judge 维度 | AgentPRM step_score 对应 |
|-------------------|--------------------------|
| T1 tool_precision | step_score (tool 调对了吗) |
| T2 plan_progress | step_score (计划推进了吗) |
| T3 error_recovery | step_score (错误恢复了吗) |
| T4 context_efficiency | bonus (上下文利用率) |

当前 clawcodex 的 session 结束只记 outcome（cost/duration/token），无 step-level 过程数据；本文 `stream_judge.snapshot()` 写入 `.reports/<session>/capability_judge.json` 即 AgentPRM 的 mini-version。

---

## §6 其他相关一手资料

### 6.1 AAIF Model Context Protocol (MCP)

- 2026-Q3 spec 已稳定
- clawcodex_ext/mcp_servers/ 已实现

### 6.2 HuggingFace Open-Leaderboard

- 提供 weekly-updated 排名
- 可用作 sweep signal

### 6.3 lmsys/lmsys-chat-1m

- 真实人机对话数据
- 可用于 fine-tune judge model
- **警告**: 不要拿来做 capability probe，因为 leak 风险高

### 6.4 NIST AI Risk Management Framework (AI600-1)

- 2026-01 发布
- 把 agent autonomy 列为需独立 risk class
- 与本文 tier-aware permission 同方向

### 6.5 OpenAI Preparedness Framework v3 (2026-Q2)

- 把"agent capability tier" 列为 readiness 评估维度
- 与本文 3-tier 划分有交集（OpenAI 用 4 档：low/medium/high/critical）

### 6.6 Anthropic Responsible Scaling Policy v2

- "AI Safety Level" ASL-2 / ASL-3 与本文 strong / standard 有概念对应
- 但 ASL 主要针对模型本身，本文 tier 是 harness 适配层

---

## §7 关联文档

- 主报告：[00-capability-harness.md §2.3](00-capability-harness.md)
- Registry 资产：[assets/registry.yaml](assets/registry.yaml)
- Anti-reward-hacking：[03-probe-spec.md §2.5](03-probe-spec.md)
- 失败模式：[09-failure-modes.md](09-failure-modes.md)