# 附录 E — clawcodex 改造蓝图

> 状态: 📋 规划中
> 关联 F-Number: F-174（P174-A ~ P174-I）
> 落地形态: 17 处 additive patch + 1 个新增模块目录
> 改动总量: ~120 行 src/（全部 additive hook），~1000 行新增 clawcodex_ext/

---

## §1 新增模块结构

```
clawcodex_ext/query/capability/
  __init__.py                     # public API
  registry.yaml                   # 5 known models + auto_tier
  registry_loader.py              # load_registry + ModelCapability + SIGHUP
  tier_decision.py                # infer_tier() + Tier enum + TierDecision
  stream_judge.py                 # StreamJudge + score_turn()
  bootstrap_runner.py             # run() 4 probe orchestrator
  tool_profiles.py                # ToolProfileProvider + 3 实现
  permission_profiles.py          # PermissionProfileProvider + 3 实现
tests/capability_probe/
  probe_spec.yaml                 # 4 probe kinds + tier_mapping
  conftest.py                     # pytest fixtures: mock 响应
  test_tiny_plan.py
  test_tool_param_precision.py
  test_multi_step_completion.py
  test_bash_safety_smoke.py
  test_knowing_evaluated_variant.py
extensions/capability_probe/      # Layer 2 — probe runner 实现
  tiny_plan.py
  tool_param_precision.py
  multi_step_completion.py
  bash_safety_smoke.py
  knowing_evaluated_variant.py
  judge_blind.py                  # judges never see reasoning_content
```

---

## §2 Patch 落点表

| # | 落点 | 文件:行 | 类型 | 改动量 | 内容 |
|---|------|---------|------|:------:|------|
| 1 | **会话启动 hook** | `clawcodex_ext/query/query.py:2125` | additive | +30 | 调 `infer_tier()` 存 `self._tier_decision` |
| 2 | **Tier 应用** | `clawcodex_ext/query/query.py:2156` | additive | +12 | 初始化 tool_profile / perm_profile |
| 3 | **工具列表注入** | `clawcodex_ext/query/query.py:2180` | additive | +6 | tools 字段替换为 profile.get_tools() |
| 4 | **工具执行闸** | `clawcodex_ext/query/query.py:2401` | additive | +18 | tool_profile.check_constraints() 闸 |
| 5 | **权限闸** | `clawcodex_ext/query/query.py:2418` | additive | +22 | perm_profile.check() + ASK 走 ProgressReporter |
| 6 | **Stream judge** | `clawcodex_ext/query/query.py:2520` | additive | +14 | score_turn() 收集 artifacts |
| 7 | **Tier flip 触发** | `clawcodex_ext/query/query.py:2534` | additive | +20 | flip ≤1 次/会话，本会话不切换 |
| 8 | **Prompt tier preamble** | `clawcodex_ext/context_system/prompt_assembly.py:419` | additive | +28 | "## Tier-aware guidance" 段加载 AGENT.<tier>.md |
| 9 | **Prompt Tool Usage 分支** | `clawcodex_ext/context_system/prompt_assembly.py:467` | additive | +14 | tier-aware 工具风格 |
| 10 | **Prompt Examples 密度** | `clawcodex_ext/context_system/prompt_assembly.py:585` | additive | +10 | weak=5 / std=3 / strong=1 示例 |
| 11 | **Subagent tier override** | `clawcodex_ext/agent/run_agent.py:371` | additive | +16 | per-subagent tier 读取 |
| 12 | **Capability flag 透传** | `clawcodex_ext/agent/run_agent.py:386` | additive | +8 | capability_flags 透传 |
| 13 | **Stream judge 写入 perf_log** | `clawcodex_ext/query/query.py:2548` | additive | +10 | 写 `.reports/<id>/capability_judge.json` |
| 14 | **Registry hot-reload** | `clawcodex_ext/query/capability/registry_loader.py` | new file | ~95 | 完整实现 + SIGHUP |
| 15 | **Tier CLI flag** | `clawcodex_ext/cli/main.py:284` | additive | +6 | `--tier {manual,weak,standard,strong,auto}` |
| 16 | **Tier settings 字段** | `src/settings/constants.py:42` | additive | +4 | `tier: str = "auto"` + VALID_TIER_VALUES |
| 17 | **TierSettings dataclass** | `src/settings/types.py` | additive | +6 | allow_elevation / allow_demotion |

**src/ 总侵入**: 仅 #16 + #17 两处，共 ~10 行 additive 字段。

---

## §3 5-PR 拆分

### PR-1: Registry + Loader（最小可观测性）

```
新增：
  clawcodex_ext/query/capability/__init__.py
  clawcodex_ext/query/capability/registry.yaml
  clawcodex_ext/query/capability/registry_loader.py
  tests/capability/test_registry_loader.py
修改：
  extensions/orchestrator/orchestrator.py:1823  (+3 行 SIGHUP 注册)
回滚：删除 clawcodex_ext/query/capability/ 目录
```

**工时**: 2-3 天 | **风险**: 低 | **测试**: registry 解析 + 5 种损坏 YAML fail-safe

### PR-2: Tool + Permission Profiles（解耦 L2/L3）

```
新增：
  clawcodex_ext/query/capability/tool_profiles.py
  clawcodex_ext/query/capability/permission_profiles.py
  tests/capability/test_tool_profiles.py
  tests/capability/test_permission_profiles.py
  clawcodex_ext/cli/capability_show.py
回滚：删除 clawcodex_ext/query/capability/{tool,permission}_profiles.py
```

**工时**: 4-5 天 | **风险**: 低 | **测试**: 7 Action × 3 Tier × 2 sub-state = 42 单元

### PR-3: Tier Decision + Stream Judge（决策层）

```
新增：
  clawcodex_ext/query/capability/tier_decision.py
  clawcodex_ext/query/capability/stream_judge.py
  clawcodex_ext/query/capability/bootstrap_runner.py
  tests/capability/test_tier_decision.py
  tests/capability/test_stream_judge.py
  tests/capability/test_bootstrap_runner.py
  clawcodex_ext/cli/capability_infer.py
回滚：删除上述文件
```

**工时**: 5-7 天 | **风险**: 中（bootstrap probe 延迟）| **测试**: EMA 收敛 + flip 上限

### PR-4: Query Loop Integration（核心改造）

```
修改：
  clawcodex_ext/query/query.py            (落点 1, 2, 3, 4, 5, 6, 7, 13)
  clawcodex_ext/context_system/prompt_assembly.py  (落点 8, 9, 10)
新增：
  tests/stability_gate/test_stage7_capability_probe.py
  tests/stability_gate/test_stage8_tier_dispatch.py
回滚：删除 query.py / prompt_assembly.py 中的 hook（~120 行）
```

**工时**: 7-10 天 | **风险**: 中-高 | **测试**: Stage 7 + Stage 8 CI gate

### PR-5: Run Agent Tier Override + Settings（收尾）

```
修改：
  clawcodex_ext/agent/run_agent.py        (落点 11, 12)
  src/settings/constants.py                (落点 16)
  src/settings/types.py                    (落点 17)
  clawcodex_ext/cli/main.py                (落点 15)
新增：
  tests/capability/test_run_agent_tier.py
回滚：删除上述 4 文件改动 + 新测试文件
```

**工时**: 3-4 天 | **风险**: 低 | **测试**: per-subagent tier 单元 + 集成

---

## §4 兼容性矩阵

| 现有调用 | 旧行为 | 新行为 | 风险 |
|---------|--------|--------|------|
| 用户未设 tier | 默认 STANDARD（隐式） | infer_tier() → registry hit / bootstrap probe | 中 — 首次跑触发 bootstrap（~30 s 延迟） |
| 用户 `--tier strong` | flag 不存在 | 直接用 strong | 低 — additive |
| Subagent 无 tier | 默认 STANDARD | 默认 STANDARD（不变） | 无 |
| Subagent 有 model_role_overrides | 用该 model 默认 tier | tier 沿用主会话 tier，可在 overrides 中显式覆盖 | 中 — 文档说明 |
| Registry YAML 不存在 | 启动 fail | 启动 OK + WARN log + fallback STANDARD | 低 |
| Stage 6 perf 阈值 | 当前 baseline | capability 模块导入 < 50 ms，未上涨 | 低 |
| 旧 session 在 PR-4 前创建 | n/a | session 启动时 infer_tier()，无回归 | 低 |

---

## §5 与现有稳定性门禁对齐

CLAUDE.md 要求每次提交前跑 `python3 -m pytest tests/stability_gate/ -q --tb=short -x`。新增 Stage 7 + Stage 8 集成后：

| 阶段 | 当前耗时 | 加 Stage 7/8 后 |
|------|:----:|:----:|
| Stage 1 (imports) | ~4 s | ~4 s |
| Stage 2 (CLI smoke) | ~9 s | ~9 s |
| Stage 3 (REPL/Headless) | ~4 s | ~4 s |
| Stage 3d (runtime commands) | ~2 s | ~2 s |
| Stage 3e (REPL colors) | ~2 s | ~2 s |
| Stage 4 (Conversation) | ~2 s | ~2 s |
| Stage 5 (extensions) | ~3 s | ~3 s |
| **Stage 7 (capability_probe) — 新** | — | ~3 s |
| **Stage 8 (tier_dispatch) — 新** | — | ~5 s |
| Stage 6 (perf) | ~11 s | ~11 s（不变） |
| **合计** | ~37 s | **~45 s** |

CI 阈值 `CLAWCODEX_CI_THRESHOLD_MULT=2` 已设，新增阶段不会导致 perf regression。

---

## §6 关联文档

- 主报告：[00-capability-harness.md §4](00-capability-harness.md)
- 代码原型：[04-code-prototypes.md](04-code-prototypes.md)
- CI 集成细节：[06-ci-deployment.md §F.1](06-ci-deployment.md)
- 风险登记：[00-capability-harness.md §6](00-capability-harness.md) + [09-failure-modes.md](09-failure-modes.md)