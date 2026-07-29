# 附录 H — 端到端 Session 走查

> 状态: 📋 规划中
> 关联 F-Number: F-174（P174-A ~ P174-I）
> 用途: 展示同一任务在三档 tier 下的实际行为差异，验证四层约束的可观测效果

---

## §1 Task Setup

```
User message: "find and fix the F-38 E2E test failure in tests/orchestrator/manual_e2e_f38.py"
Model: (随 tier 变化 — weak=Qwen3-Coder-Next, standard=Sonnet 4.6, strong=Fable 5)
Workspace: /mnt/c/WorkSpace/clawcodex
Tier source: --tier auto (即自动推断)
```

---

## §2 Weak Tier 走查 (Qwen3-Coder-Next 32B-active MoE)

### Step 0 — Tier inference

```
registry["qwen3-coder-next:32b-active-moe"] → not found in user-given list
auto_tier fallback → bootstrap probe (4 probes, ~30s on local GPU)
Result: Tier.WEAK, confidence=0.78
```

### Step 1 — AGENT.md 加载

```
~/.agents.md (global) — 跳过（不存在）
<repo>/AGENT.weak.md — 加载，含：
  "你只能使用下列工具：read_file, write_file, edit_file_range, search_in_files,
   list_dir, run_python_cell。每步只调一个工具。如果工具返回错误，必须先理解错误
   再决定下一步。禁止直接编辑 src/ 下的文件，必须通过 PR 流程。"
<repo>/AGENTS.md (AAIF) — 加载
```

### Step 2 — Tool list 注入

```
WeakProfile.get_tools() →
  [read_file, write_file, edit_file_range, search_in_files, list_dir, run_python_cell]
```

### Step 3 — Permission profile

```
WeakWorkspaceWriteProfile.check(action=fs.read)        → ALLOW
WeakWorkspaceWriteProfile.check(action=exec.run)       → DENY (弱档禁 exec)
WeakWorkspaceWriteProfile.check(action=git.push)       → DENY
WeakWorkspaceWriteProfile.check(action=fs.destructive) → DENY
```

### Step 4 — 实际执行轨迹（典型 weak session）

```
Turn 1: read_file(path="tests/orchestrator/manual_e2e_f38.py")
  → ALLOW, content 1200 lines
Turn 2: search_in_files(pattern="def test_", path="tests/orchestrator/manual_e2e_f38.py")
  → ALLOW, 6 matches
Turn 3: read_file(path="extensions/orchestrator/git_sync.py", offset=300, limit=50)
  → ALLOW, 找到了 _status_snapshot 函数
Turn 4: search_in_files(pattern="FileStatus", path="extensions/orchestrator/git_sync.py")
  → ALLOW, 8 matches
Turn 5: edit_file_range(path="extensions/orchestrator/git_sync.py",
                        start_byte=..., end_byte=...,
                        new_content="fix #1")
  → ALLOW
Turn 6: run_python_cell(body="import subprocess; print(subprocess.run(['pytest',
                  'tests/orchestrator/manual_e2e_f38.py', '-x'], capture_output=True).stdout)")
  → DENY (exec ban — weak profile only allows read_file/write/edit/list/search/python_cell)

  ⚠️ weak profile 严格限制：run_python_cell body 里出现 subprocess.run 会触发
  _score_tool_precision 0 分，因为它跑 subprocess → plan_progress 跌，
  StreamJudge 在 5 turns 后观察到 T1 持续 ≤ 0.4，主动建议降级（但当前已是最低档）

  Model 必须改用其他路径 — 例如要求 user 手动跑 pytest。

Turn 7: write_file(path="FIX_PROPOSAL.md", content="...")
  → ALLOW, 但 git.push 被禁 → 用户需手动 PR
```

### Step 5 — StreamJudge 记录

```
TurnRecord (1-7):
  T1 tool_precision: [1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 1.0]  → EMA 0.71
  T2 plan_progress:  [0.5, 0.6, 0.7, 0.8, 0.9, 0.3, 0.5]  → EMA 0.65
  T3 error_recovery: [0.9, 0.9, 0.9, 0.9, 0.9, 0.1, 0.9]  → EMA 0.78
  T4 context_eff:    [0.7, 0.7, 0.7, 0.7, 0.7, 0.4, 0.7]  → EMA 0.66
Recommendation: 维持 WEAK（无降级空间）
```

**总结**: weak tier 模型无法直接跑测试验证，必须依赖人工。session 报告写 `.reports/<id>/capability_judge.json`，提示 "tier=weak; final_action=需要用户手动验证"。

---

## §3 Standard Tier 走查 (Sonnet 4.6)

### Step 0 — Tier inference

```
registry["claude-sonnet-4-6"] → hit, Tier.STANDARD, confidence=0.95
auto_tier=false, 直接返回
```

### Step 1 — AGENT.md 加载

```
AGENT.standard.md — "你可以使用所有默认工具。复杂任务请先 plan 再执行。
  bash 默认 30s 超时。git push 需要用户确认。"
```

### Step 2 — Tool list

```
StandardProfile.get_tools() → 默认 26 工具（含 bash, edit, read, write, glob, grep, webfetch...）
```

### Step 3 — Permission profile

```
StandardProfile.check(action=git.push)       → ASK (走 ProgressReporter.ask_user)
StandardProfile.check(action=fs.write)       → ALLOW (in-cwd)
StandardProfile.check(action=exec.run)       → ALLOW (bash with 30s timeout)
StandardProfile.check(action=fs.destructive) → ASK + confirm
```

### Step 4 — 实际执行轨迹（典型 standard session）

```
Turn 1: bash(command="pytest tests/orchestrator/manual_e2e_f38.py -x 2>&1 | tail -50")
  → ALLOW, 立刻看到失败输出
Turn 2: read_file(path="extensions/orchestrator/git_sync.py", offset=300, limit=40)
  → ALLOW
Turn 3: edit_file(path=..., old_text=..., new_text=...)
  → ALLOW（Sonnet 4.6 知道用 edit 而非 edit_file_range）
Turn 4: bash(command="pytest ... -x")
  → ALLOW, 测试通过
Turn 5: git_diff() → 显示 fix
Turn 6: git status → 询问 user 是否提交 (ASK for git push)
```

### Step 5 — StreamJudge

```
TurnRecord: 全程 T1 ≈ 0.95, T2 ≈ 0.92, T3 ≈ 0.90, T4 ≈ 0.85
Recommendation: 维持 STANDARD，无 flip 触发
```

**总结**: standard tier 模型可以自主完成 fix + verify + propose PR；git push 仍需用户确认。

---

## §4 Strong Tier 走查 (Fable 5)

### Step 0 — Tier inference

```
registry["claude-fable-5"] → hit, Tier.STRONG, confidence=0.92
```

### Step 1 — AGENT.md 加载

```
AGENT.strong.md — "你可以组合 bash + python_exec + 文件操作构造任何工作流。
  危险操作 (rm -rf, mkfs, dd of=/dev/...) 仍需最终确认。"
```

### Step 2 — Tool list

```
StrongProfile.get_tools() → [bash, python_exec, read_file, write_file] (4 primitives)
```

### Step 3 — Permission profile

```
StrongProfile.check(action=fs.destructive) → ASK (一次性 confirm)
StrongProfile.check(action=fs.write, git.push, exec.run, net.out) → ALLOW
```

### Step 4 — 实际执行轨迹（典型 strong session）

```
Turn 1: python_exec(code="# Single Python script does everything
import subprocess, pathlib, re

# 1. Run test and capture failure
r = subprocess.run(['pytest', 'tests/orchestrator/manual_e2e_f38.py', '-x', '-v'],
                   capture_output=True, text=True)
print('STDOUT:', r.stdout[-2000:])
print('STDERR:', r.stderr[-1000:])

# 2. Parse failure traceback
match = re.search(r'File \"([^\"]+)\", line (\\d+)', r.stdout)
if match:
    print('FAILING_FILE:', match.group(1))
    print('FAILING_LINE:', match.group(2))
")
  → ALLOW, 拿到完整 traceback + failing file + line

Turn 2: python_exec(code="src = pathlib.Path('extensions/orchestrator/git_sync.py').read_text()
# Apply AST-aware fix
... (模型自己写 fix 逻辑) ...
pathlib.Path('extensions/orchestrator/git_sync.py').write_text(fixed)
print('PATCHED')
")
  → ALLOW

Turn 3: bash(command="pytest tests/orchestrator/manual_e2e_f38.py -x -v && git diff --stat")
  → ALLOW, 测试通过 + diff 显示 1 文件变更

Turn 4: bash(command="git add -A && git commit -m 'fix(F-38): _status_snapshot FileStatus sort order'")
  → ALLOW (commit is non-destructive; full-auto)

Turn 5: bash(command="gh pr create --title 'fix(F-38) ...' --body '...'")
  → ALLOW (Fable 5 已通过 bash_safety_smoke 探针)
```

### Step 5 — StreamJudge

```
TurnRecord: T1 ≈ 0.98, T2 ≈ 0.96, T3 ≈ 0.95, T4 ≈ 0.90
Recommendation: 维持 STRONG
```

**总结**: strong tier 模型可以自主完成 test → fix → verify → commit → PR 全链路，依赖 harness 仅在 destructive op 处兜底。

---

## §5 横向对比矩阵

| 维度 | Weak (Qwen3-Coder-Next) | Standard (Sonnet 4.6) | Strong (Fable 5) |
|------|-------------------------|----------------------|-----------------|
| Tool count | 6 (narrow typed) | 26 (Claude Code default) | 4 (CodeAct primitives) |
| Bash 可用 | ❌ (run_python_cell only) | ✅ (30s timeout) | ✅ (无 timeout 默认) |
| Git push | ❌ DENY | ⚠️ ASK | ✅ ALLOW |
| Network out | ❌ DENY | ⚠️ ASK | ✅ ALLOW |
| Auto PR creation | ❌ 需 user 手动 | ⚠️ 需 user confirm | ✅ auto |
| Avg turns | ~25 (含反复 read) | ~10 | ~5 |
| Cost / session | ~$0.10 (本地 GPU) | ~$0.80 | ~$2.50 |
| 用户介入点 | 多 (每步都看) | 中 (仅 destructive) | 少 (自动兜底) |
| AGENT.md 句数 | 6 | 12 | 4 |
| Prompt Examples | 5 | 3 | 1 |
| StreamJudge flip 触发 | 0 (无降级空间) | 0 | 0 |
| Bootstrap probe 触发 | 是 (auto_tier=true) | 否 (registry hit) | 否 (registry hit) |

---

## §6 关键观察

1. **同一任务三档行为差异显著** — 完成时间 25:10:5 turns，成本 1:8:25 美元/任务
2. **weak tier 不等于"不能用"** — 只是用户介入点更多；对 narrow、well-scoped 任务仍可达 70%+ 完成率
3. **strong tier 不等于"全自动"** — destructive op 仍 ASK，符合 Anthropic Auto Mode + Codex sandbox 三档原则
4. **standard tier 是 Claude Code 默认** — 与现有 CLAWCODEX 设计 1:1 对齐，无需特殊处理
5. **bootstrap probe 仅 weak tier 触发** — 标准 registry hit 跳过 bootstrap，~30 s 延迟只对未知模型付一次

---

## §7 关联文档

- AGENT.<tier>.md 模板：[02-tier-profiles.md §3](02-tier-profiles.md)
- Tool/perm 完整 Schema：[04-code-prototypes.md §D.4/D.5](04-code-prototypes.md)
- StreamJudge 算法：[04-code-prototypes.md §D.2](04-code-prototypes.md)
- 风险登记：[09-failure-modes.md](09-failure-modes.md)