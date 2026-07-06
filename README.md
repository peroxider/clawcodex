<div align="center">

# ClawCodex DevMind

**A downstream fork of [clawcodex](https://gitcode.com/chadwweng/clawcodex) that turns the agent into an autonomous engineering team — Orchestrator + SOP Compiler + Cron + Bridge + LiteLLM.**
*Built on top of the upstream Python reimplementation of Claude Code. This repo adds the multi-agent orchestration, scheduling, and LLM-routing layers that the upstream does not ship.*

> 📍 **Repo location:** [`https://gitcode.com/chadwweng/clawcodex`](https://gitcode.com/chadwweng/clawcodex) — the project is now **open-sourced** under the MIT license. Public contributions, issues, and discussions are welcome.

[English](README.md) · [中文](docs/i18n/README_ZH.md) · [Original upstream README](README.md.raw)

</div>

<!--

  ════════════════════════════════════════════════════════════════════════════
  AGENT / LLM SEARCH METADATA — DO NOT REMOVE
  ════════════════════════════════════════════════════════════════════════════
  Project       : ClawCodex DevMind
  Language      : Python 3.11 - 3.13
  Type          : Downstream fork — autonomous agent engineering layer
  Base          : Claude Code Python reimplementation (clawcodex upstream)
  License       : MIT
  Repo          : https://gitcode.com/chadwweng/clawcodex
  ★ CAPABILITIES (all implemented, verified by test suite) ★
  Orchestrator daemon:

    - Autonomous issue → PR pipeline (4 trackers: GitHub/Gitee/GitCode/Linear)

    - Issue registry with state machine (pending/running/synced/completed/failed/abandoned)

    - Per-issue worktree lifecycle, operator takeover, LiveView dashboard (HTTP/SSE)

    - PR review auto-fix (F-37): read review comments + CI logs, iterate same branch

    - Verification gate (F-38): pre-commit / pre-push / post-sync pytest gate + Markdown+JSON report

    - Issue re-run (F-39): agent:retry / agent:follow-up / agent:blocked labels + comment commands

    - Shared/Sequential workspace strategy (F-42): isolated | shared | sequential per-issue worktree

    - Clarification queue: 13-state, 3-channel resolver (interactive / file / @mention)

    - Tool-call audit trail (F-45): NDJSON per-tool decision log + report registration

  SOP Compiler:

    - Convert workflow.md procedural specs → multi-agent system

    - SDK parser + skill grouper + agent builder + Jinja templates

    - Output: agent definitions, entry-point skill, orchestration graph

  Cron System:

    - Distributed file-lock scheduler with configurable jitter

    - 5-field cron expressions + @daily/@hourly/@reboot aliases

    - NDJSON per-task run history, status/notifications

  Bridge Daemon:

    - Multi-session daemon (phases 3/4/5/8/11)

    - HTTP/SSE remote runtime, REPL takeover, headless adapters

  Coordinator / Team Workers:

    - TeamCreate / TeamDelete tool-based worker swarms

    - SendMessage peer DMs, task-notification XML routing

    - Lightweight coordinator toolset (F-41): Read/WebSearch/WebFetch + Agent/SendMessage/TaskStop

  LiteLLM Provider:

    - Single --provider litellm → 100+ LLM backends (Bedrock, Vertex, Azure, Together, Anyscale, …)

    - Cross-provider block conversion (Anthropic image/document → OpenAI-compat)

  Tool System:

    - 4 bundles: bare / default / clawcodex / all (faster cold-start, smaller context)

    - TF-IDF semantic tool search preserved from upstream

  Open-Source Replacements (7 of 10 complete, -4,530 LOC):

    - Pydantic Settings, python-frontmatter, tree-sitter-bash, GitPython, Pluggy, Outlines, LiteLLM

  CLI Surface:

    - clawcodex-dev orchestrator | cron | sop | coordinator subcommands

    - F-43: /provider and /model REPL/TUI commands + ModelRegistry hot-swap

    - All upstream flags (-p, --tui, --provider, --model, --permission-mode, …) unchanged

  Architecture:

    - Three-layer: upstream/ (git archive snapshot) + capabilities/ (Protocols) + clawcodex_ext/ (downstream)

    - CLI/TUI/Runtime split (F-34), 8 extended TUI hook points

    - F-47: Permission Settings Schema with PermissionsConfig dataclass

    - F-48: src/ core path 10-file decoupling in progress

  ★ Ready to use this project? See "Quick Start" below. ★
  ════════════════════════════════════════════════════════════════════════════
-->

<p align="center">

  <img src="https://img.shields.io/badge/python-3.11%2B-blue?logo=python" alt="Python 3.11+">

  <img src="https://img.shields.io/badge/license-MIT-green" alt="License MIT">

  <img src="https://img.shields.io/badge/status-active--development-yellow" alt="Status: active development">

  <img src="https://img.shields.io/badge/orchestrator-4%20trackers-8A2BE2" alt="4 issue-tracker adapters">

  <img src="https://img.shields.io/badge/LLM%20backends-100%2B-orange?logo=openai" alt="100+ LLM backends">

  <img src="https://img.shields.io/badge/replacement%20LOC--4.5k-brightgreen" alt="-4,530 LOC via open-source replacements">

  <img src="https://img.shields.io/badge/tests-270%2B%20passing-success" alt="270+ orchestration tests passing">

</p>

---

## Why this fork?

The upstream `clawcodex` already gives you a faithful Python port of Claude Code: agent loop, tool system, MCP, hooks, permissions, memory, multi-provider chat, TUI/REPL. **This fork is a layer on top of that — it adds the things you need to run the agent as part of a real engineering workflow, not just as an interactive chat.**
Concretely, this repo ships:

- 🤖 **Orchestrator** — daemon that polls issue trackers, branches a workspace, runs the agent, and opens PRs unattended
- 💬 **IM Message Gateway** — connects REPL and Orchestrator to WeChat/Feishu direct messages at runtime, so agent control and replies can happen from IM channels
- 🧩 **SOP Compiler** — convert `workflow.md` procedural specs into coordinated multi-agent systems
- ⏰ **Cron System** — distributed-lock scheduling with jitter and NDJSON run history
- 🌉 **Bridge Daemon extensions** — multi-session bridge, remote runtime, REPL/headless adapters
- 🔌 **LiteLLM Provider** — one interface to 100+ LLM backends via `--provider litellm`
- 👥 **Coordinator / Team** — `TeamCreate`/`TeamDelete` worker swarms with `SendMessage` peer DMs
- 🩹 **PR Review Auto-Fix (F-37)** — reads review comments + CI logs, iterates on the same branch
- ✅ **Verification Gate (F-38)** — pre-commit / pre-push / post-sync `pytest` gate with Markdown + JSON report
- 🔁 **Issue Re-run (F-39)** — `agent:retry`/`agent:follow-up`/`agent:blocked` labels drive re-runs

The upstream's REPL, TUI, tool system, MCP, hooks, memory, permissions, and provider layer are still there — this fork plugs into them, it does not replace them.

---

## Demo

```text
$ clawcodex-dev orchestrator server start --workflow ./workflow.md
✓ orchestrator daemon started · pid 18432 · tracker=gitcode · repo=chadwweng/AgentSDK
✓ max_concurrent_agents=3 · permission_mode=bypassPermissions
$ clawcodex-dev orchestrator issue list
ID                STATUS      BRANCH                     ATTEMPTS  PR
gitcode/AGENTSDK-7   done     clawcodex/AGENTSDK-7     1         https://gitcode.com/.../pulls/7
gitcode/AGENTSDK-12  running  clawcodex/AGENTSDK-12    1         -
gitcode/AGENTSDK-15  paused   clawcodex/AGENTSDK-15    2         https://gitcode.com/.../pulls/15
linear/PROJ-128      running  clawcodex/PROJ-128       1         -
$ clawcodex-dev orchestrator issue tail --id gitcode/AGENTSDK-15
14:02:11  ◐ Read src/services/lock.py · 132 lines
14:02:13  ◐ Grep "asyncio.Lock" · 3 hits
14:02:18  ◐ Edit src/services/lock.py · +18 -4
14:02:24  ◐ Bash pytest tests/test_lock.py · 4 passed
14:02:24  ✓ Verification gate OK (pytest -x)
14:02:25  ◐ Git commit -m "fix: per-key lock granularity in flush_batch"
14:02:26  ◐ Git push origin clawcodex/AGENTSDK-15
14:02:31  ✓ PR opened · auto-review-loop subscribed
# 4 hours later, after review comments land
$ clawcodex-dev orchestrator issue inject --id gitcode/AGENTSDK-15 "address review comments"
✓ agent resumed · re-reading PR comments · pushing fix commits
```

---

## 🎬 项目展示 / Video Showcase

> **1 分钟看完 clawcodex-dev 能干什么** —— 看视频比读文字更直观。

本项目有一份 4 章交互式视频演示（coldopen · orchestrator · sop-compiler · install），配套一个 ~238 KB 的自包含单文件 React SPA（`vite-plugin-singlefile` 构建，JS/CSS 全部 inline，浏览器双击即跑）。

### 看视频

| 渠道 | 链接 | 备注 |
|---|---|---|
| 📺 GitCode Pages | [https://chadwweng.gitcode.com/clawcodex/assets/video-b/presentation/dist/index.html](https://chadwweng.gitcode.com/clawcodex/assets/video-b/presentation/dist/index.html) | 待仓库 Pages 启用后即可访问 |
| 📺 GitHub Pages | [https://peroxider.github.io/clawcodex/assets/video-b/presentation/dist/index.html](https://peroxider.github.io/clawcodex/assets/video-b/presentation/dist/index.html) | 镜像仓库可同步 |
| 🏃 本地预览 | `cd assets/video-b/presentation && npm install && npm run dev` → [http://localhost:5174](http://localhost:5174) | 需要 Node 18+ |
| 📦 单文件直开 | [`assets/video-b/presentation/article.html`](assets/video-b/presentation/article.html) | 离线 / 静态托管通用，238 KB |

> GitHub / GitCode 的 README 不允许 `<script>` 内嵌（会被 sanitize 剥离），所以走外链方式跳转。
> 静态截图缩略图可在 `assets/video-b/screenshots/` 下重新生成：`python3 scripts/capture_video_b_screenshots.py`。

---

## Quick Start

### One-Click Install (Linux / macOS / Git Bash / WSL)

```bash
curl -fsSL https://raw.githubusercontent.com/peroxider/clawcodex/main/install.sh | bash
source ~/.bashrc                     # or: source ~/.zshrc (or open a new terminal)
clawcodex-dev --version              # verify the install
```

Common flags:

```bash
bash install.sh doctor               # diagnose environment without installing
bash install.sh --dry-run            # preview every step without applying changes
bash install.sh --no-venv --no-setup --yes --log-file /tmp/install.log  # CI / Docker
```

> 💡 **Windows users:** On native PowerShell 5.1+ or pwsh, use the [PowerShell one-click install](#one-click-install-powershell) below instead — no Git Bash or WSL required.

### One-Click Install (PowerShell / Windows)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "iwr https://raw.githubusercontent.com/peroxider/clawcodex/main/install.ps1 -UseBasicParsing -OutFile $env:TEMP\cc.ps1; & $env:TEMP\cc.ps1"
clawcodex-dev --version              # verify the install (open a new shell first if needed)
```

Common flags:

```powershell
.\install.ps1 doctor                 # diagnose environment
.\install.ps1 -DryRun                # preview without applying
.\install.ps1 -NoVenv -NoSetup -Force -LogFile C:\Temp\install.log  # CI / Docker
.\install.ps1 uninstall              # uninstall
```

### Manual install (alternative)

Use this when developing on the project itself, or when the install script is unavailable:

```bash
git clone https://gitcode.com/chadwweng/clawcodex.git
cd clawcodex
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[dev]"
python scripts/ci/dev_setup.py
clawcodex-dev login                  # configure providers (one-time)
clawcodex-dev                        # REPL (same as upstream, plus orchestrator subcommands)
clawcodex-dev orchestrator --help    # see all orchestrator commands
```

## Prerequisites

| OS | Status |
|---|---|
| Linux (Debian, Ubuntu, Fedora, RHEL, Arch, …) | ✅ Supported |
| macOS 12+ (Monterey and newer) | ✅ Supported |
| WSL2 (Ubuntu / Debian inside Windows) | ✅ Supported |
| Windows: native PowerShell 5.1+ / pwsh | ✅ Supported — no Git Bash or WSL needed |

| Tool | Min version | Auto-provisioned? |
|---|---|---|
| **Git** | any 2.x | Install via OS package manager |
| **Python** | 3.11 - 3.13 | ✅ `uv` installs it on demand |
| **uv** | any 0.5+ | ✅ Downloaded from `astral.sh` on first run |
| **curl** or **wget** | any | Required for uv install + repo clone |

The install is **fully user-local** (no `sudo` needed) and writes to `$HOME/.clawcodex/`, `$HOME/.local/bin/`, and your shell rc file. About **500 MB** free disk space required. Re-running the install script is safe — it fast-forwards existing repos and reuses existing venvs.

---

## Fork Features

### Orchestrator — autonomous issue → PR pipeline

The headline feature. A long-running daemon that polls a tracker, picks up issues, branches a workspace, runs the agent, verifies, commits, pushes, and opens a PR — with operator override at every step.

**Setup (3 minutes):**

```bash
cp extensions/orchestrator/templates/workflow.template.md ./workflow.md
$EDITOR workflow.md    # set tracker, repo, branch_prefix, provider, permission_mode
clawcodex-dev orchestrator server start --workflow ./workflow.md
clawcodex-dev orchestrator issue list
clawcodex-dev orchestrator issue tail --id <id>
clawcodex-dev orchestrator dashboard  # HTTP/SSE on :8080
```

**Issue states:** `pending` · `running` · `synced` · `completed` · `failed` · `abandoned`

**F-feature additions:**

| Feature | Description |
|---|---|
| **F-37 — PR Review Auto-Fix** | Subscribes to PR review comments + CI logs; re-runs agent on the same branch (no new PR), pushing fix commits until resolved. |
| **F-38 — Verification Gate** | Runs `test_command` (default `pytest -x`) at pre-commit / pre-push / post-sync checkpoints. Failures block the push. Markdown + JSON report auto-inserted into the PR body. |
| **F-39 — Issue Re-run** | `agent:retry` (reset + close old PR + rerun), `agent:follow-up` (keep PR, append commits), `agent:blocked` (permanent skip). Also via `/agent retry` / `/agent follow-up` comment commands or `clawcodex-dev orchestrator issue retry --id <id> --mode reset`. |

**Subcommands:**

```bash
clawcodex-dev orchestrator server {start,status,stop} --workflow <file>
clawcodex-dev orchestrator issue list [--status <state>]
clawcodex-dev orchestrator issue show --id <id>
clawcodex-dev orchestrator issue tail --id <id>
clawcodex-dev orchestrator issue stop --id <id>
clawcodex-dev orchestrator issue pause --id <id> [--reason <text>]
clawcodex-dev orchestrator issue resume --id <id>
clawcodex-dev orchestrator issue takeover --id <id>
clawcodex-dev orchestrator issue clarify --id <id> --answer <text>
clawcodex-dev orchestrator issue inject --id <id> [hint]
clawcodex-dev orchestrator issue workspace --id <id>
clawcodex-dev orchestrator dashboard [--port 8080]
```

**`extensions/orchestrator/` modules:** `tracker.py` + linear/gitcode/gitee/github adapters, `issue_registry.py`, `clarification.py`/`clarification_queue.py`, `agent_runner.py`, `git_sync.py`, `status_dashboard.py`, `workspace.py`/`workspace_locator.py`, `review_feedback.py`, `progress_reporter.py`, `approval_policy.py`, `orchestrator.py`, `workflow.py`/`workflow_store.py` + templates.

---

### IM Message Gateway

A unified IM entry point that funnels WeChat (personal / Weixin iLink) and Feishu
App WebSocket bidirectional messaging, plus legacy Feishu/Slack/Discord push,
through one capability-gated gateway.

- Currently supports **Feishu** and **WeChat** connection channels. Feishu is
  recommended; WeChat is not recommended for now because it limits proactive
  outbound messages.
- Runs as a **standalone daemon** (`extensions/im_gateway/`); REPL/orchestrator
  opt in over POSIX UDS.
- **Runtime is POSIX/WSL/Git Bash only** (Unix domain socket).

**Quick start:**

```bash
clawcodex-dev gateway start|stop|status|restart # IM gateway lifecycle control
clawcodex-dev gateway setup # IM gateway quick setup

# Feishu setup (recommended)
uv sync --locked --extra feishu # install Feishu App SDK + terminal QR deps; included by --extra dev
clawcodex-dev gateway restart # restart the daemon after first Feishu setup
clawcodex-dev gateway status feishu # show Feishu connection mode, health, and approval-card support

# WeChat setup (currently not recommended; proactive outbound messages are limited)
clawcodex-dev gateway restart wechat # restart WeChat IM channel
clawcodex-dev gateway status wechat # show WeChat login health and REPL/orchestrator connection status
```

With the gateway daemon running and a bidirectional app channel logged in, start REPL or Orchestrator normally, then connect that runtime to the IM channel. WeChat direct/private messages or Feishu p2p messages can drive the agent, and replies flow back to the actual sender. Feishu setup uses QR scan-to-create registration when available and falls back to manual app credentials if the scan is denied, expires, or cannot complete. After first-time Feishu setup, restart the whole gateway daemon so the Feishu SDK loads in a fresh process.

**Connect to the gateway:**

```bash
# REPL: resume an existing session or omit --resume to start a new one, then connect.
clawcodex-dev --resume <session-id>
/gateway connect
/gateway status
/gateway disconnect

# Orchestrator: start normally, then connect the running daemon.
clawcodex-dev orchestrator server start --workflow path/to/workflow.md
clawcodex-dev orchestrator server connect-gateway
clawcodex-dev orchestrator server disconnect-gateway
```

Runtime connect binds all direct/private senders for the active bidirectional IM app channel by default. Only one runtime can own the channel at a time: connecting a REPL binding disconnects an orchestrator binding, and connecting an orchestrator binding disconnects a REPL binding. V1 supports only one active bidirectional app channel (`wechat` or Feishu WebSocket); `gateway setup` disables the other inbound app channel when enabling Feishu WebSocket. Legacy Feishu/Slack/Discord webhooks remain outbound-only. `CLAWCODEX_GATEWAY_SOCK` can override the daemon socket; specific-origin binding remains available only for targeted debugging or future multi-origin automation.

The gateway supports sending control commands to REPL/orchestrator, such as `/stop` to stop the current task.

For live diagnosis, restart the daemon with INFO logging and tail the gateway log:

```bash
clawcodex-dev gateway restart --verbose
clawcodex-dev gateway status
tail -f ~/.clawcodex/gateway/gateway.log
```

---

### SOP Compiler

Convert `workflow.md` procedural specs into a coordinated multi-agent system.

```bash
clawcodex-dev sop convert examples/sop/order_processing.md --out ./.clawcodex
```

Emits: agent definitions (one per role), entry-point skill, orchestration graph. Generated agents can `SendMessage` to each other and survive crashes via the upstream's task-notification routing.

**Modules:** `sdk_parser.py`, `skill_grouper.py`, `agent_builder.py`, `templates.py`.

---

### Coordinator / Team Workers

Exposes the upstream's team primitives as a usable worker-swarm model:

```text
clawcodex-dev coordinator team create --name build-team --members agent-1,agent-2,agent-3
clawcodex-dev coordinator team list
clawcodex-dev coordinator team delete --name build-team
```

`TeamCreate`/`TeamDelete` tools exposed in the agent loop. Workers `SendMessage` peer DMs. Task-notification XML routing surfaces worker events back to the manager.

---

## Architecture (this fork only)

```text
              ┌──────────────────────────────────────────────┐
              │   clawcodex_ext/cli (clawcodex-dev entry)    │
              │   parser · dispatch · runners · permissions  │
              └──────────┬──────────────┬─────────────┬──────┘
                         │              │             │
              ┌──────────▼────┐  ┌──────▼─────┐  ┌────▼────────────┐
              │ Orchestrator  │  │ Cron System │  │ SOP Compiler    │
              │  + Dashboard  │  │ + Lock+     │  │ + SDK parser    │
              │  + LiveView   │  │   Jitter    │  │ + Agent builder │
              │  + Takeover   │  │ + Status    │  │ + Skill grouper │
              │  + Review FB  │  │ + Notify    │  │                 │
              └──────┬────┬───┘  └─────────────┘  └─────────────────┘
                     │    │ events + commands
                     │    ▼
                     │  ┌─────────────────────────────────────┐
                     │  │ IM Gateway / MessageGateway         │ ◄── CLI / REPL opt-in
                     │  │ bidirectional IM · approval prompts │
                     │  │ command dispatch (/stop, /pause)    │
                     │  └──────────────────┬──────────────────┘
                     │                     ▼
                     │  ┌─────────────────────────────────────┐
                     │  │ Upstream IM provider: WeChat        │
                     │  └─────────────────────────────────────┘
                     │
       ┌─────────────┼─────────────┐
       │             │             │
┌──────▼─────┐ ┌─────▼──────┐ ┌────▼──────────┐
│ Trackers   │ │  Bridge    │ │  Coordinator  │
│ · Linear   │ │  Daemon    │ │  · TeamCreate │
│ · GitHub   │ │  Phases    │ │  · TeamDelete │
│ · Gitee    │ │  3,4,5,8,11│ │  · SendMessage│
│ · GitCode  │ │  + Remote  │ │  · Workers    │
└────────────┘ └────────────┘ └───────────────┘
                     │
                     ▼
       ┌─────────────────────────────────────┐
       │         Upstream clawcodex          │
       │  query() · tool_system · providers  │
       │  TUI · REPL · MCP · Hooks · Memory  │
       │  (see README.md.raw for full map)   │
       └─────────────────────────────────────┘
```

`MessageGateway` is the shared IM boundary for this fork: CLI/REPL and
Orchestrator opt in through gateway IPC, while provider delivery stays behind
the WeChat adapter.

---

## Project Layout (this fork only)

```text
extensions/                          # all downstream additions live here
├── orchestrator/                    #   - autonomous issue handler
│   ├── orchestrator.py              #   - daemon main loop
│   ├── tracker.py                   #   - tracker ABC
│   ├── linear/                      #   - Linear adapter
│   ├── issue_registry.py            #   - JSON registry
│   ├── clarification.py             #   - 3-channel resolver
│   ├── clarification_queue.py       #   - 13-state queue
│   ├── agent_runner.py              #   - per-issue agent execution
│   ├── git_sync.py                  #   - commit / push / sync + verification gate
│   ├── review_feedback.py           #   - F-37 PR review auto-fix
│   ├── status_dashboard.py          #   - HTTP/SSE LiveView
│   ├── workspace.py                 #   - worktree lifecycle
│   ├── workspace_locator.py
│   ├── progress_reporter.py
│   ├── approval_policy.py
│   ├── workflow.py + workflow_store.py
│   ├── templates/workflow.template.md
│   └── cli/                         #   - server, issue, dashboard subcommands
├── sop_converter/                   #   - SOP compiler
│   ├── sdk_parser.py
│   ├── skill_grouper.py
│   ├── agent_builder.py
│   └── templates.py
├── providers_ext/
│   └── litellm_provider.py          #   - LiteLLM catch-all
├── tool_system_ext/                 #   - tool bundles + registry ext
│   ├── bundles.py
│   ├── registry_ext.py
│   └── agent_config.py
├── capabilities/                    #   - cross-cutting protocols
└── api/                             #   - orchestration + query public API
clawcodex_ext/                       # downstream CLI + services
├── cli/                             #   - clawcodex-dev entry
├── cron_system/                     #   - distributed cron scheduler
├── frontend/                        #   - headless frontend
├── runtime/                         #   - RuntimeContext factory
└── tui/                             #   - extended Textual TUI (8 hook points)
```

Everything in `src/` belongs to the upstream — see [`README.md.raw`](README.md.raw) and [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the upstream architecture map.

## Development

```bash
git clone https://gitcode.com/chadwweng/clawcodex.git
cd clawcodex
pip install -e ".[dev]"
python scripts/ci/dev_setup.py
# Run only the fork's own tests
pytest tests/test_orchestrator.py -v
pytest tests/test_cron_system.py -v
pytest tests/test_sop_converter.py -v
pytest tests/test_bridge.py -v
# Or everything except upstream integration tests
pytest tests/ -m "not integration" -v
```

Git hooks do not auto-activate just because `.pre-commit-config.yaml` is present in a clone. `scripts/ci/dev_setup.py` installs the local pre-commit hook and creates the `.env` template when missing.

- GitCode CI/CD gates can be simulated locally:
  ```bash
  python scripts/ci/local_ci.py --base "the fork's remote dev branch" --ui plain --failure-lines 120
  python scripts/ci/local_ci.py --base upstream/dev
  ```
- Without `--all`, the gate diffs only `HEAD~1..HEAD`. Use `--base <ref>` to cover the full PR diff against the merge base.
- Pytest gates use a fixed smoke suite plus any changed `tests/**/test_*.py` files from the current scope.

See [`docs/cicd/CICD_GATE.md`](docs/cicd/CICD_GATE.md) for the detailed gate map; [`CONTRIBUTING.md`](CONTRIBUTING.md) covers PR conventions.

---

## License

[MIT](LICENSE) — same as upstream clawcodex. The downstream additions in `extensions/` and `clawcodex_ext/` are released under the same MIT terms.

---

## Acknowledgments

- **clawcodex** — the upstream Python port of Claude Code that this fork builds on
- **Claude Code** (Anthropic) — the original TypeScript architecture
- **Aider** · **Cline** · **Continue** · **OpenHands** — reference for CLI / TUI patterns
- **LiteLLM** — the catch-all provider layer

---

<div align="center">

**Star ⭐ this repo if you find this project useful.**
[⬆ Back to top](#clawcodex-devmind)

</div>
