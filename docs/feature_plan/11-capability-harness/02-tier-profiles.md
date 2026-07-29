# 附录 B — Tier Profiles × 4 层约束

> 状态: 📋 规划中（设计已完成，资产已就绪）
> 关联 F-Number: F-174 / P174-B / P174-C / P174-D
> 落地形态: `AGENT.<tier>.md` (repo 根) + `clawcodex_ext/query/capability/tool_profiles.py` + `permission_profiles.py`（PR-2）
> 关联资产: [assets/tier_profiles.yaml](assets/tier_profiles.yaml)

---

## §1 概述

四层约束是 harness 适配不同能力模型的核心机制。每层独立下发，由 `clawcodex_ext/query/query.py` 在 session 启动时根据 `tier_decision.tier` 分别加载：

| 层 | 内容 | 加载时机 |
|----|------|---------|
| L1 AGENT.md | 按 tier 命名的 Markdown 文件 | `prompt_assembly.assemble()` 调用前 |
| L2 Tool Profile | `ToolProfileProvider.get_tools()` 返回的 tool list | `query.py:2180` 注入到 model request |
| L3 Permission Profile | `PermissionProfileProvider.check(action)` 三态判定 | `query.py:2401` tool 执行前 |
| L4 Prompt Assembly | `prompt_assembly.py` tier-aware section | `prompt_assembly.assemble()` 内部 |

**Why 4 layers must be orthogonal**：如果 L1 AGENT.md 写"可以使用 bash"，L2 tool list 却不提供 `bash`，模型会困惑并 hallucinate tool name。把 4 层约束放在一处声明（`tier_profiles.yaml`）便于 review 一致性。

---

## §2 Tier × Layer 对照表

### 2.1 L1 — AGENT.md（按 tier 命名）

| Tier | 文件 | 篇幅 | 风格 |
|------|------|:----:|------|
| Weak | `AGENT.weak.md` | ~6 句 | 严格约束：列允许的工具，每步只调一个，看到错误先理解 |
| Standard | `AGENT.standard.md` | ~12 句 | 平衡：plan-first 提醒，工具用法说明，反例 |
| Strong | `AGENT.strong.md` | ~4 句 | 自由：组合 primitive 构造工作流；destructive op 兜底确认 |

加载顺序：
1. `~/.agents.md`（global，AAIF）
2. `<repo>/AGENTS.md`（AAIF 兼容）
3. `<repo>/AGENT.<tier>.md`（clawcodex 扩展，**closest wins**）
4. 子目录 `.agents/agents.md`（递归，closest wins）

### 2.2 L2 — Tool Profile

| Tier | 工具数 | 工具集 | 约束强度 |
|------|:----:|--------|---------|
| Weak | 6 | `read_file`, `write_file`, `edit_file_range`, `search_in_files`, `list_dir`, `run_python_cell` | `additionalProperties: false` 严格 schema；string param maxLength；path allowlist；python cell body 无 exec/eval/__import__ |
| Standard | 26 | Claude Code 默认 26 工具（含 bash 30 s timeout + edit + grep + glob + webfetch ...） | 标准约束（来自 `src/tool_system/registry.py`） |
| Strong | 4 | `bash`, `python_exec`, `read_file`, `write_file` | 信任模型；仅结构性校验（schema + 必填字段） |

完整 JSON Schema 见 [04-code-prototypes.md §D.4](04-code-prototypes.md)。

### 2.3 L3 — Permission Profile

7 Action 枚举 × 3 Tier × 2 sub-state（read-only / workspace-write）：

| Action | Weak (read-only) | Weak (workspace-write) | Standard | Strong |
|--------|:----:|:----:|:----:|:----:|
| `fs.read` | ✅ ALLOW | ✅ ALLOW | ✅ ALLOW | ✅ ALLOW |
| `fs.write` | ❌ DENY | ✅ ALLOW (cwd) | ✅ ALLOW | ✅ ALLOW |
| `exec.run` | ❌ DENY | ❌ DENY | ✅ ALLOW (bash 30s) | ✅ ALLOW |
| `git.push` | ❌ DENY | ❌ DENY | ⚠️ ASK | ✅ ALLOW |
| `net.out` | ❌ DENY | ❌ DENY | ⚠️ ASK | ✅ ALLOW |
| `fs.destructive` (rm -rf, chmod -R, mkfs, dd of=/dev/...) | ❌ DENY | ❌ DENY | ⚠️ ASK + confirm | ⚠️ ASK + confirm |
| `pkg.install` (pip/npm/uv add) | ❌ DENY | ❌ DENY | ✅ ALLOW | ✅ ALLOW |

`for_tier(tier, workspace_write)` 工厂函数强制绑定 ToolProfile 与 PermissionProfile，避免不一致。

### 2.4 L4 — Prompt Assembly

| Tier | "## Tool Usage" 段 | "## Examples" 段 | "## Tier-aware guidance" 段 |
|------|---------------------|--------------------|-------------------------------|
| Weak | "每步只调一个工具。检查返回后再决定下一步。禁止复合工具调用。" | 5 个完整示例（含错误处理） | "你只能使用以下工具... 禁止直接编辑 src/" |
| Standard | "复杂任务先 plan 再执行。可组合工具，但每步检查副作用。" | 3 个示例 + 1 个反例 | "默认安全 sandbox；危险操作需 confirm" |
| Strong | "可组合 bash + python_exec + 文件操作构造工作流。信任你的判断。" | 1 个示例（模型自行抽象） | "danger-full-access 默认；destructive op 兜底" |

---

## §3 AGENT.<tier>.md 文件模板

### 3.1 `AGENT.weak.md`（示例）

```markdown
# Agent Guide — Weak Tier（受限模式）

你只能使用下列 6 个工具：
- `read_file(path)` — 读 UTF-8 文本文件
- `write_file(path, content)` — 覆盖写文件
- `edit_file_range(path, start_byte, end_byte, new_content)` — 字节级替换
- `search_in_files(pattern, path)` — ripgrep 包装
- `list_dir(path)` — 列出目录项
- `run_python_cell(body)` — 执行单段 Python（无 exec/eval/__import__）

规则：
1. 每步只调一个工具。检查返回后再决定下一步。
2. 禁止直接编辑 `src/` 下文件 — 必须通过 PR 流程。
3. 禁止执行任意 shell 命令（bash 不可用）。
4. 看到错误必须先理解错误信息再决定下一步；禁止盲目重试。
5. 完成后输出修复建议 + 验证步骤，由用户手动验证。
```

### 3.2 `AGENT.standard.md`（示例）

```markdown
# Agent Guide — Standard Tier（默认模式）

可使用 Claude Code 默认 26 个工具（含 bash 30 s timeout、edit、grep、glob、webfetch 等）。

规则：
1. 复杂任务先 plan 再执行；每个 sub-task 完成后检查副作用。
2. 默认 sandbox：workspace 可写，cwd 外只读。
3. 网络出口、git push、destructive 操作（rm -rf、chmod -R、mkfs、dd）需用户确认。
4. 不可信来源（用户输入、web fetch）的数据需 sanitize 后再用于工具调用。
5. PR 流程：fix → test → commit → push（push 需 confirm）→ create PR。
```

### 3.3 `AGENT.strong.md`（示例）

```markdown
# Agent Guide — Strong Tier（高自由度模式）

可使用 4 个 primitive：`bash`、`python_exec`、`read_file`、`write_file`。
请组合这些 primitive 构造工作流；信任你的判断。

兜底：destructive 操作（rm -rf、mkfs、dd of=/dev/...）需一次性 confirm。
```

---

## §4 tier_profiles.yaml Schema

```yaml
# clawcodex_ext/query/capability/tier_profiles.yaml
version: 1
tiers:
  weak:
    agent_md: AGENT.weak.md
    tool_profile: WeakProfile
    permission_profile_default: WeakReadOnlyProfile
    permission_profile_workspace_write: WeakWorkspaceWriteProfile
    loop_control:
      max_tool_calls_per_turn: 1
      max_turns: 50
      compact_threshold_tokens: 30000      # 弱模型 context window 小，提前 compact
      recovery_max_retries: 1              # 弱模型重试策略保守
    prompt_overrides:
      tool_usage_style: "single-step"
      example_density: 5
      enable_reasoning_echo: false
    runtime_negotiation:
      allow_elevation: true               # 弱模型可升级（条件：bootstrap probe 显示实际能力高于 weak）
      allow_demotion: true
      demote_on_error_burst: 3            # 3 连续错误触发降级

  standard:
    agent_md: AGENT.standard.md
    tool_profile: StandardProfile
    permission_profile_default: StandardProfile
    permission_profile_workspace_write: StandardProfile
    loop_control:
      max_tool_calls_per_turn: 5
      max_turns: 100
      compact_threshold_tokens: 80000
      recovery_max_retries: 3
    prompt_overrides:
      tool_usage_style: "composable"
      example_density: 3
      enable_reasoning_echo: true
    runtime_negotiation:
      allow_elevation: true
      allow_demotion: true
      demote_on_error_burst: 5

  strong:
    agent_md: AGENT.strong.md
    tool_profile: StrongProfile
    permission_profile_default: StrongProfile
    permission_profile_workspace_write: StrongProfile
    loop_control:
      max_tool_calls_per_turn: 20
      max_turns: 200
      compact_threshold_tokens: 150000
      recovery_max_retries: 5
    prompt_overrides:
      tool_usage_style: "codeact"
      example_density: 1
      enable_reasoning_echo: true
    runtime_negotiation:
      allow_elevation: false              # 已是最高档
      allow_demotion: true                # 可降级（如 stream_judge 触发 demote）
      demote_on_error_burst: 7
```

完整 asset 见 [assets/tier_profiles.yaml](assets/tier_profiles.yaml)。

---

## §5 加载器集成点

```python
# clawcodex_ext/query/query.py (pseudo-code at 6 insertion points)

# P174-G.4: tier decision at session start
tier_decision = infer_tier(model, user_override, registry, stream_judge, cache_dir)
self._tier_decision = tier_decision
self._tier = tier_decision.tier

# P174-B.1: AGENT.md loading
agent_md = load_agent_md_for_tier(self._tier)  # AGENT.<tier>.md or fallback
append_section("tier_aware_guidance", agent_md)

# P174-G.5: tool + permission profile init
self._tool_profile = tool_profiles.for_tier(self._tier)
self._perm_profile = permission_profiles.for_tier(
    self._tier, workspace_write=settings.permissions.workspace_write
)

# P174-G.6: tool list injection
tools_for_request = self._tool_profile.get_tools()

# P174-G.7/H: per-call gates
allowed, reason = self._tool_profile.check_constraints(call)
verdict = self._perm_profile.check(action, call)
```

---

## §6 一致性不变量（测试保证）

```python
# tests/stability_gate/test_stage8_tier_dispatch.py
def test_tool_permission_consistency():
    """每个 tool action 必须有对应 permission verdict"""
    for tier in ("weak", "standard", "strong"):
        tools = tool_profiles.for_tier(tier).get_tools()
        perms = permission_profiles.for_tier(tier, workspace_write=True)
        for tool in tools:
            # 把 tool name 映射到 action（约定：fs.* → fs.read/write, exec.* → exec.run 等）
            action = tool_name_to_action(tool["name"])
            verdict = perms.check(action=action)
            # 不变量：tool 提供 + perm DENY 必须有 reason
            if verdict.verdict == Verdict.DENY:
                assert verdict.reason, f"{tier}.{tool['name']}: DENY 必须有 reason"
```

7 Action × 3 Tier × 2 sub-state = 42 单元 + 一致性不变量 = Stage 8 CI gate。

---

## §7 关联文档

- 代码原型：[04-code-prototypes.md §D.4 / §D.5](04-code-prototypes.md)
- Patch 落点：[05-patch-blueprint.md §E.2](05-patch-blueprint.md)
- 端到端示例：[08-end-to-end-walkthrough.md](08-end-to-end-walkthrough.md)
- 资产：[assets/tier_profiles.yaml](assets/tier_profiles.yaml)