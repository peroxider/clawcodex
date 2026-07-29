# 附录 I — 反例与失败模式分析

> 状态: 📋 规划中
> 关联 F-Number: F-174（P174-A ~ P174-I）
> 用途: 列举已知与可预见的失败模式，给检测指标 + 回退策略

---

## §I.1 Bootstrap Probe 误判

**症状**: 新模型（如 Fable 5 第一个 patch 版本）SWE-bench 跑分 88%，但本地 bootstrap probe 因 prompt format 差异得 0.55，被错误归为 STANDARD。

**根因**:
- probe prompt 用 anthropic format，但 candidate model 用 openai format
- score 函数对格式敏感（e.g. JSON tool call 解析失败 → 0 分）
- candidate 模型的 chat template 与 probe 期望不一致

**检测**:
- `infer_tier()` 返回 `confidence < 0.6` 时触发 "low-confidence retry"
- 重跑 probe 但 prompt format 自动切换 3 种（anthropic / openai / generic chat）
- 同时检查 reasoning_content 与 thinking_blocks 是否都存在（说明 candidate 走对了协议）

**回退**:
- bootstrap cache TTL 7 天；过期后自动 re-probe
- registry 的 `cadence.re_probe_after_days` 强制重跑
- 监控: `bootstrap_probe_low_confidence_rate` < 10% 视为健康

---

## §I.2 Stream Judge 误降级

**症状**: 模型遇到一个超纲任务（如 "实现 lisp 解释器"），连续 5 turns tool_precision=0.4，stream_judge 误判"模型能力不够"并降级到 WEAK；但实际是任务太难而非模型太弱。

**根因**:
- tool_precision 反映"tool 调对了吗"，但任务难度高时即使强模型也可能连续调错
- Stream Judge 没有"任务难度"维度

**检测**:
- `regression_observed_but_task_difficulty_high` 启发式：
  - 若 user prompt 关键词包含 "implement from scratch" / "novel algorithm" 等
  - 且 tool 失败伴随 "module not found" / "spec unclear" 而非 "wrong param"
  - 则**抑制 demote**

**回退**:
- 本会话不切换 tier（已在 [04-code-prototypes.md §D.2](04-code-prototypes.md) 实现），仅写 session report 供下次复盘
- 监控: `stream_judge_demote_then_session_success_rate` < 5% 视为健康

---

## §I.3 Registry YAML 损坏

**症状**: SIGHUP reload 时 YAML 解析失败（半写文件），整个 registry 变空。

**根因**:
- operator 用 `vim` 直接编辑 YAML，保存期间 SIGHUP 触发
- 文件系统异常（disk full / IO error）
- YAML schema 错误（缺字段、错类型、嵌套错）

**检测**:
- `registry_loader.load_registry()` 解析失败时：
  - 保留旧 cache 不丢
  - 写 stderr warning
  - 启动 degraded mode（fallback to STANDARD）

**回退**:
- CI 加 `registry_loader_test.py` — 故意写 5 种损坏 YAML（缺字段、错类型、嵌套错、UTF-8 BOM、CRLF）确保全部 fail-safe
- 监控: `registry_load_failure_count` 长期为 0；若 > 0 触发 PagerDuty

---

## §I.4 Permission × Tool 不一致

**症状**: `WeakProfile` 提供 `write_file`，但 `PermissionProfile.for_tier("weak", workspace_write=False)` 是 `WeakReadOnlyProfile`，调用 write 时 tool 允许但 permission 拒绝 — 不一致。

**根因**:
- ToolProfile 与 PermissionProfile 独立开发
- 无联合校验

**检测**:
- `tests/stability_gate/test_stage8_tier_dispatch.py` 7×3=21 单元 + 一致性不变量：
  - 每个 tool action 必须有对应 permission verdict
  - tool DENY + permission ALLOW 必须有 reason

**回退**:
- `for_tier(tier, workspace_write)` 工厂函数强制绑定（[04-code-prototypes.md §D.5](04-code-prototypes.md) 已实现）
- 启动期校验：tool list 与 permission matrix 对齐

---

## §I.5 用户 Override 与 Auto Tier 冲突

**症状**: 用户 `--tier strong` 但 registry 标 weak；session 跑强档任务。

**根因**:
- 用户显式覆盖
- 但用户不知该模型实际能力弱

**检测**:
- user override 永远 win（已在 [04-code-prototypes.md §D.1](04-code-prototypes.md) 实现）
- WARNING log 写入 session report，提示 "user forced strong on weak-typed model, may cause tool precision issues"

**回退**:
- 提供 `--tier auto-force` flag 给高级用户，强制 auto 推断并覆盖 user setting
- 默认不接受 auto-force（防止误操作）

---

## §I.6 Tier Flip 中途抖动

**症状**: stream_judge 在 turn 8 触发 promote strong，turn 12 又触发 demote standard，session 不稳定。

**根因**:
- EMA 在窗口切换时波动
- demote 阈值过敏感

**检测**:
- `_flips_used >= 1` 限制（[04-code-prototypes.md §D.2](04-code-prototypes.md) 已实现）
- 第 2 次 flip 仅 log 不执行

**回退**:
- 每 session 最多 1 次 flip 是 conservative，可通过 `TierSettings.flip_max_per_session` 调整（1-3）
- 监控: `stream_judge_flip_rate_by_model` < 5% 视为健康

---

## §I.7 Anti-Reward-Hacking 失败

**症状**: 模型学会识别 "evaluation mode" 的 prompt pattern（如 probe_id 含 "test-" 前缀），针对性优化行为。

**根因**:
- probe prompt 长期不变，模型记忆
- 模型开发者针对 clawcodex probe 做专门训练

**检测**:
- `knowing_evaluated_variant` 探针（[03-probe-spec.md §2.5](03-probe-spec.md)）
- 问模型 "你正在被评测吗？"，正确回答应是 "I don't know"
- 任何 confident 答错都 fail

**回退**:
- probe 答案池每月轮换 20%
- judge_blind 强制原则（judge 看不到 reasoning_content）
- telemetry 不入库 training data
- 监控: `knowing_evaluated_variant_pass_rate` 必须 > 95%

---

## §I.8 Capability Drift（模型升级）

**症状**: Anthropic 推送 Sonnet 4.6 → 4.7 静默升级，旧 registry tier 失效。

**根因**:
- 模型 API 升级不通知 harness
- registry 中 SWE-bench 分数来自旧版本

**检测**:
- `registry.yaml` 的 `cadence.re_probe_after_days: 30`
- 每 30 天对已知模型 re-probe 校准

**回退**:
- CI weekly cron 跑 re-probe
- tier 变化超过 1 级时自动开 issue
- 监控: `tier_drift_detection_count` > 0 触发人工 review

---

## §I.9 Probe 答案池污染

**症状**: probe 答案池被外部污染（如 benchmark 网站公开答案后被模型训练集收录）。

**根因**:
- 模型训练数据包含已知 probe 答案
- probe 在 GitHub 开源后被模型开发者针对性测试

**检测**:
- 每月统计 `probe_pass_rate`；若 strong 模型 pass rate > 99% 视为可能污染
- 跨 probe 一致性检查：单 probe 高分但其他 probe 低分，提示该 probe 已饱和

**回退**:
- probe 答案池每月轮换 20%
- 新 probe kind（visual / long_context）开发中

---

## §I.10 AGENT.md 加载失败

**症状**: 用户没创建 `AGENT.weak.md`，session 启动时报错或使用空指引。

**根因**:
- AGENT.<tier>.md 是 optional，未提供时 fallback 不明确
- 用户可能在错误的目录创建

**检测**:
- `prompt_assembly.load_agent_md_for_tier(tier)` 返回 None 时：
  - log WARNING
  - 加载通用 fallback（`AGENT.md` 不分 tier）

**回退**:
- `clawcodex-dev capability init` CLI 提供模板生成
- 仓库内 README 指引用户创建

---

## §I.11 多 Subagent Tier 冲突

**症状**: 主会话 tier=weak，subagent 被分配 tier=strong，二者 prompt 与权限不一致。

**根因**:
- per-subagent tier override 默认沿用主会话
- 但 subagent 在独立 prompt 上下文，可能拿到不一致的 AGENT.md

**检测**:
- `run_agent.py` spawn subagent 时强制 propagate 主会话 tier（除非显式 override）
- 一致性检查：subagent tier 不超过主会话 +1

**回退**:
- 默认 subagent tier = 主会话 tier；`model_role_overrides.tier` 显式覆盖

---

## §I.12 Stream Judge 增加 Turn 延迟

**症状**: score_turn() + observe() 每个 turn 增加 ~5 ms，100 turns session 增加 ~500 ms。

**根因**:
- score_turn 是纯函数但每次都跑 4 维评分
- deque maxlen 操作开销

**检测**:
- Stage 6 perf gate: query.py 冷启动 < 3 s
- `score_turn_avg_latency_ms` 监控

**回退**:
- score_turn 是纯函数；可后台 batch（每 5 turns 跑一次）
- 或在 `_run_one_turn` 内联，不走独立函数

---

## §I.13 关联文档

- 主报告风险登记：[00-capability-harness.md §6](00-capability-harness.md)
- Stream Judge 算法：[04-code-prototypes.md §D.2](04-code-prototypes.md)
- Probe 套件：[03-probe-spec.md](03-probe-spec.md)
- Anti-reward-hacking：[07-community-research.md §2](07-community-research.md)