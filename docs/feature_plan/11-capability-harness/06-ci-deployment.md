# 附录 F — CI / 部署计划

> 状态: 📋 规划中
> 关联 F-Number: F-174 / P174-H / P174-I
> 落地形态: Stage 7/8 CI gate + Day-1/30/90 渐进 rollout + Telemetry 监控

---

## §1 稳定性门禁新增 Stage 7 / 8

### 1.1 Stage 7 — `test_stage7_capability_probe.py`

**覆盖**：
- `registry_loader` 解析 + 校验（含 unknown tier 抛错、auto_tier 默认 false、metrics 缺失不报错）
- `tier_decision` 4 个 layer 优先级（user override > registry > bootstrap > fallback）
- `bootstrap_runner` 在 mock model 下给出 deterministic tier
- `stream_judge` EMA 收敛、5-turn 全零触发 demote、tier flip 上限 1 次/会话
- `knowing_evaluated_variant` 探测 — mock 模型答错时 score=0

**门禁阈值**：
- 全部用例 < 5 s（mock 模型，无真实 LLM 调用）
- 失败即阻断 PR

**典型耗时**: ~3 s

### 1.2 Stage 8 — `test_stage8_tier_dispatch.py`

**覆盖**：
- `WeakProfile.get_tools()` 返回 6 个工具，schema `additionalProperties: false` 全覆盖
- `StandardProfile.get_tools()` 委托给 `src/tool_system/registry.get_default_tools`
- `StrongProfile.get_tools()` 含 `bash` + `python_exec`
- 三种 `PermissionProfile.for_tier()` 对 7 种 Action 的 verdict 表（7×3=21 单元）
- `permission_profiles.for_tier("weak", workspace_write=True)` → WeakWorkspaceWriteProfile
- `permission_profiles.for_tier("weak", workspace_write=False)` → WeakReadOnlyProfile
- `query.py` patch 集成测试：mock provider + 注入 3 个 tier，断言 tool 列表随 tier 变化

**门禁阈值**：
- 全部用例 < 8 s（含 query.py 集成）
- 失败即阻断 PR

**典型耗时**: ~5 s

### 1.3 CI workflow 调整

`.github/workflows/ci.yml` 的 `test-gate` job：

```yaml
- name: stability_gate (Stage 1-5 + 7-8)
  run: python3 -m pytest tests/stability_gate/ --ignore=tests/stability_gate/test_stage6_perf.py -q --tb=short
  env:
    CLAWCODEX_CI_THRESHOLD_MULT: 2
```

`audit` job 不变（osv-scanner 不需新增依赖 — capability 模块只引 `pyyaml`，已在 requirements）。

`.github/workflows/stage6-perf-nightly.yml` 不变。

---

## §2 Day-1 / Day-30 / Day-90 部署计划

### 2.1 Day-1（PR-1 + PR-2 上线）

**目标**: 能力可观测 + L2/L3 解耦完成。**默认 tier=manual**，用户必须显式 `--tier`。

**启用**:
- ✅ `registry.yaml` + `registry_loader.py` 上线
- ✅ `WeakProfile` / `StandardProfile` / `StrongProfile` 上线
- ✅ CLI `clawcodex-dev capability show --tier <weak|standard|strong>`
- ✅ SIGHUP watcher 注册（orchestrator daemon）
- ❌ `infer_tier()` 未接入 query.py
- ❌ `stream_judge` 未启用
- ❌ `--tier auto` flag 未开放

**Guardrails**:
- `CLAWCODEX_AUTO_TIER=false` 默认（环境变量开关，hard-coded fallback）
- 用户文档：「如果你不知道选什么 tier，先 `--tier standard`，再用 `clawcodex-dev capability show` 看模型建议」
- Telemetry: 记录每个 session 的 (model, tier, session_id) 三元组，用于 Day-30 bootstrap 校准

**回滚**: 删除 `clawcodex_ext/query/capability/` 目录 + 撤销 CLI flag。无 src/ 改动，回滚成本 < 5 分钟。

### 2.2 Day-30（PR-3 + PR-4 上线）

**目标**: 能力推断 + Query Loop 集成。**`--tier auto` 开放**，默认仍是 manual。

**启用**:
- ✅ `tier_decision.py` + `stream_judge.py` + `bootstrap_runner.py` 上线
- ✅ `query.py` 7 处 hook 接入
- ✅ `prompt_assembly.py` 3 处 tier-aware section
- ✅ `cli/main.py` 新增 `--tier {manual,weak,standard,strong,auto}`（5 选 1，默认 manual）
- ✅ Stage 7 + Stage 8 CI gate 启用
- ✅ `bootstrap_probe` cache 目录 `.capability_cache/` 加入 `.gitignore`

**Guardrails**:
- `auto_tier` 仅对 registry.yaml 中显式标 `auto_tier: true` 的模型生效
- 已知模型（Sonnet 4.6、GLM-4.7）仍走 registry 直接查表，不触发 probe
- Stream judge tier flip 上限 1 次/会话，超出仅 WARN log
- `--tier manual` 为新会话默认（不破坏既有 user mental model）
- 文档: migration guide —「`--tier auto` 是 opt-in，新模型自动跑 ~30 s bootstrap probe」

**Rollback flag**: `CLAWCODEX_DISABLE_AUTO_TIER=1` → 强制所有 session 走 manual tier，不调 `infer_tier()`。

**Day-30 验收**:
- 5 个 known model 全部分类正确
- 2 个 unknown model 通过 bootstrap probe 正确分级
- Stage 7 + Stage 8 全绿
- 无 query.py 集成导致的 session 崩溃（错误率 < 0.1%）

### 2.3 Day-90（PR-5 + 全量 rollout）

**目标**: 全量 auto_tier + per-subagent tier + 自动 re-probe。

**启用**:
- ✅ `--tier auto` 成为新默认值（`manual` 仍可手动选）
- ✅ `run_agent.py` per-subagent tier override 上线
- ✅ `settings.TierSettings`（`allow_elevation: true`、`allow_demotion: true` 默认）
- ✅ 自动 re-probe：`registry.cadence.re_probe_after_days` 触发（典型 30 天）
- ✅ Stream judge tier flip 上限可配置（默认 1）

**Guardrails**:
- 用户的 `permissions.defaultMode` 不被 tier 自动覆盖
- tier 变更写入 `.reports/<session>/tier_history.json`，可在 dashboard 查看
- Stream judge 触发 demote 时，本会话**不切换**（避免雪崩），仅记 log

**Day-90 验收**:
- 1000 个 session telemetry 中，tier 自动调整命中率 > 85%
- 用户手工 override `--tier` 比例 < 15%
- Stream judge 误判率 < 5%（人工复盘 50 个 session 验证）
- CI perf: Stage 6 阈值未上涨（capability 模块导入 < 50 ms）

---

## §3 风险登记

| 风险 | 概率 | 影响 | 缓解 |
|------|:----:|:----:|------|
| Bootstrap probe 模型掉线，~30 s 启动延迟 | 中 | 中 | probe_cache 复用；CI 跳过；`--tier manual` 绕过 |
| Stream judge 误判 demote，用户体验降级 | 低 | 中 | 1 次/会话上限；本会话不切换；telemetry 监控 |
| Registry YAML 损坏 | 低 | 高 | `load_registry` 解析失败保留旧 cache + degraded mode |
| Permission × Tool profile 不一致 | 中 | 高 | `for_tier()` 工厂函数强制绑定；21 单元覆盖 |
| 用户 `--tier` 与 auto 冲突 | 低 | 低 | user override 永远 win；WARN log |
| Stream judge 误判 demote 引起雪崩 | 低 | 高 | flip 上限 1 次；本会话不切换 |
| Anti-reward-hacking 失败（模型识别 probe） | 低 | 高 | `knowing_evaluated_variant` 监控；probe 答案池月度轮换 |
| Capability Drift（模型升级） | 中 | 中 | `cadence.re_probe_after_days: 30` + CI weekly re-probe |
| Day-30 后老 user session 被 auto tier 改变 | 中 | 中 | `--tier manual` 默认；migration guide 强调 opt-in |
| Stream judge 增加 query.py 每次 turn ~5 ms 开销 | 中 | 低 | score_turn 是纯函数；可后台 batch；perf gate Stage 6 守 |

详见 [09-failure-modes.md](09-failure-modes.md) 每类失败模式的检测 + 回退策略。

---

## §4 Telemetry 关键指标

每次 session 结束写入 `.reports/<session_id>/capability_trace.json`：

```json
{
  "session_id": "...",
  "model": "fable-5",
  "decision": {
    "tier": "strong",
    "source": "registry",
    "confidence": 0.92,
    "decided_at_ms": 1234567890000
  },
  "stream_judge": {
    "turns_observed": 47,
    "ema": {"tool_precision": 0.88, "plan_progress": 0.82, "error_recovery": 0.91, "context_efficiency": 0.79},
    "tier_changes": [],
    "final_snapshot_tier": "strong"
  },
  "tools_used": ["bash", "python_exec", "read_file", "write_file"],
  "permissions_used": ["fs.read", "fs.write", "exec.run", "git.push"],
  "user_override": null
}
```

聚合查询（每日 cron）:
- `avg_decision_confidence_by_model` — 低于 0.7 触发 re-probe 调度
- `tier_override_rate_by_user` — 高于 30% 说明 auto 不准
- `stream_judge_flip_rate_by_model` — 高于 5% 触发人工复盘
- `bootstrap_probe_cache_hit_rate` — 低于 80% 说明 cache key 设计有问题
- `tier_auto_hit_rate_by_model` — auto 推断与 registry 一致率

---

## §5 文档清单

| 文件 | 章节 | 内容 |
|------|------|------|
| `docs/feature_plan/11-capability-harness/README.md` | 索引 | F-Number 状态总表 |
| `docs/feature_plan/11-capability-harness/00-capability-harness.md` | 主报告 | 设计目标 + 架构 + 子特性 |
| `docs/feature_plan/11-capability-harness/01-registry-yaml.md` | 附录 A | 能力注册表 schema |
| `docs/feature_plan/11-capability-harness/02-tier-profiles.md` | 附录 B | Tier Profiles × 4 层约束 |
| `docs/feature_plan/11-capability-harness/03-probe-spec.md` | 附录 C | 4 probe kind |
| `docs/feature_plan/11-capability-harness/04-code-prototypes.md` | 附录 D | 6 个 Python 原型 |
| `docs/feature_plan/11-capability-harness/05-patch-blueprint.md` | 附录 E | patch 落点表 + 5-PR 拆分 |
| `docs/feature_plan/11-capability-harness/06-ci-deployment.md` | 附录 F | 本文 |
| `docs/feature_plan/11-capability-harness/07-community-research.md` | 附录 G | 一手调研 |
| `docs/feature_plan/11-capability-harness/08-end-to-end-walkthrough.md` | 附录 H | 三档 walk-through |
| `docs/feature_plan/11-capability-harness/09-failure-modes.md` | 附录 I | 失败模式 |
| `docs/feature_plan/11-capability-harness/10-recommendations-open-q.md` | 附录 J | 建议与开放问题 |
| `docs/feature_plan/11-capability-harness/assets/registry.yaml` | 附录 A 资产 | 5 known model |
| `docs/feature_plan/11-capability-harness/assets/tier_profiles.yaml` | 附录 B 资产 | tier_profiles 配置 |
| `docs/feature_plan/11-capability-harness/assets/probe_spec.yaml` | 附录 C 资产 | probe 套件 |
| `CLAUDE.md` | 增量段 | Common commands 加 capability probe 命令 |
| `docs/feature_plan/README.md` | 增量 | P174-A ~ P174-I 行 + 变更历史 |