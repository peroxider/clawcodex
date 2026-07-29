# 附录 A — 能力注册表 registry.yaml

> 状态: 📋 规划中（设计已完成，资产已就绪）
> 关联 F-Number: F-174 / P174-A
> 落地形态: `clawcodex_ext/query/capability/registry.yaml`（PR-1）
> 关联资产: [assets/registry.yaml](assets/registry.yaml)

---

## §1 用途

能力注册表是 4 层 tier 推断中的 **L1 静态信号源**：

- 命中已知模型 → 直接返回 tier，跳过 bootstrap probe（~30 s 延迟）
- 未命中但 `metrics` 字段有社区分数 → 按阈值近似分级（不需要 LLM 调用）
- 完全未知 → 走 bootstrap probe

注册表支持 SIGHUP hot-reload（详见 §3），新模型发布后运维可通过更新 YAML 立即生效。

---

## §2 Schema 设计

```yaml
version: 1                         # schema 版本，便于迁移
updated_at: "2026-07-28T20:00:00Z" # 最后手工更新时间
models:                            # 模型列表
  - model: <string>                # 唯一标识符（与 provider 返回的 model 字段完全匹配）
    provider: <string>             # anthropic / openai / gemini / glm / zai / deepseek / openrouter / openai_compatible / ollama / vllm
    tier: <enum>                   # weak | standard | strong | unknown
    auto_tier: <bool>              # true = 启用 bootstrap + stream_judge 推断；false = 静态信任 registry
    confidence: <float 0-1>        # registry 静态分级的置信度（与 bootstrap probe 对接时取 max）
    metrics:                       # 开源社区 benchmark 分数（SWE-bench Verified / LiveCodeBench / MT-Bench）
      swe_bench_verified: <float 0-1>
      livecodebench: <float 0-1>
      mt_bench: <float 0-1>
      <other>: <float 0-1>
    probe_score: <float 0-1|null>  # 上一次 bootstrap probe 的综合分（None = 未跑过）
    capability_flags:              # 模型能力位图（供 prompt_assembly / tool_profile 消费）
      tool_use: <bool>
      json_mode: <bool>
      extended_thinking: <bool>
      adaptive_thinking: <bool>
      vision: <bool>
      audio: <bool>
      parallel_tool_calls: <bool>
      long_context_1m: <bool>
    reasoning_channel_mapping:     # 推理通道映射（不同 provider 字段名不同）
      reasoning_content: <string>  # openai / deepseek 风格字段名
      thinking_blocks: <string>    # anthropic 风格字段名
      reasoning_text: <string>     # gemini 风格字段名（备用）
    context_window: <int>          # 上下文窗口 token 数
    max_output_tokens: <int>       # 单轮最大输出
    probe_suite: <path>            # 该模型专属 probe 套件路径（可选，默认 tests/capability_probe/probe_spec.yaml）
    anti_hacking:                  # 反 reward-hacking 配置
      knowing_evaluated_variant: <bool>  # 是否启用 "你正在被评测吗" 探针
      judge_blind: <bool>               # judge 是否 reasoning-blind（必须 true）
      probe_rotation_days: <int>        # probe 答案池轮换周期（默认 30 天）
    cadence:                       # re-probe 调度
      re_probe_after_days: <int>   # 自动重新跑 probe 的间隔（默认 30）
      re_probe_on_drift: <bool>    # 检测到 drift 是否立即 re-probe（默认 true）
    notes: <string>                # 人工备注（如 "pre-release version, may have quirks"）
```

---

## §3 SIGHUP Hot-Reload

```python
# clawcodex_ext/query/capability/registry_loader.py
import signal

def install_sighup_handler(registry_path: Path) -> None:
    def _reload(signum, frame):
        log.info("SIGHUP received; reloading registry")
        load_registry(registry_path, force=True)
    signal.signal(signal.SIGHUP, _reload)
```

注册位置：`extensions/orchestrator/orchestrator.py:1823`（daemon 启动时）。

**为什么 hot-reload 而不是每次 session 重读？**

- 运行中 session 不会被静默改变（避免"模型刚跑通突然变 tier"的诡异行为）
- 运维可显式 `kill -HUP <daemon_pid>` 触发 reload
- mtime watch 备选：watchdog 库检测到 YAML 文件变更 > 5 s 时自动 reload

---

## §4 5 个已知模型条目（详见 assets/registry.yaml）

| 模型 | tier | auto_tier | SWE-bench Verified | 备注 |
|------|:----:|:---------:|:------------------:|------|
| Fable 5 | strong | false | 95.0% | Anthropic 闭源旗舰，tool_use SOTA |
| GPT-5.6 Codex | strong | true | 84.1% | OpenAI 编码特化，新发布，需 auto_tier 校准 |
| Sonnet 4.6 | standard | false | 71.2% | Claude Code 默认主脑 |
| GLM-4.7 | standard | false | 62.8% | 智谱旗舰 |
| Qwen3-Coder-Next 32B-active MoE | weak | true | 44.3% | 阿里本地可跑，narrow typed 工具集 |

每个模型完整字段见 [assets/registry.yaml](assets/registry.yaml)。

---

## §5 阈值映射（metrics → tier）

```yaml
# 默认阈值（可在 registry.yaml 顶层覆盖）
tier_thresholds:
  strong_min_swe_bench: 0.80        # ≥ 80% → strong
  standard_min_swe_bench: 0.50      # 50-80% → standard
  # < 50% → weak
  # confidence = (swe + lcb + mt_bench) / 3
```

无 LLM 调用即可分级（offline friendly，对本地模型也适用）：
- Qwen3.6-32B（已知 SWE-bench ~45%）→ 自动 weak，无需 probe
- 未知小模型（无任何公开分数）→ 必须 probe

---

## §6 校验（启动期）

```python
def validate_entry(entry: dict) -> None:
    assert entry["model"], "model 必填"
    assert entry["provider"] in KNOWN_PROVIDERS
    assert entry["tier"] in ("weak", "standard", "strong", "unknown")
    if entry["auto_tier"] and entry["tier"] != "unknown":
        # auto_tier 模式应让 bootstrap probe 决定，但 registry 可保留 baseline
        log.warning("auto_tier=true 但 tier 已设；bootstrap 会覆盖")
    for k, v in entry.get("metrics", {}).items():
        assert 0.0 <= v <= 1.0, f"metrics.{k} 必须 ∈ [0, 1]"
```

启动期校验失败 → 启动 OK + WARN log + 保留旧 cache + degraded mode（fallback STANDARD）。

---

## §7 关联文档

- 加载器代码：[04-code-prototypes.md §D.3](04-code-prototypes.md)
- tier 决策算法：[04-code-prototypes.md §D.1](04-code-prototypes.md)
- 资产文件：[assets/registry.yaml](assets/registry.yaml)
- Bootstrap probe：[03-probe-spec.md](03-probe-spec.md)