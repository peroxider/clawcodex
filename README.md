<div align="center">

# ClawCodex DevMind

**A downstream fork of [clawcodex](https://gitcode.com/chadwweng/clawcodex) that turns the agent into an autonomous engineering team — Orchestrator + SOP Compiler + Cron + Bridge + LiteLLM.**

*Built on top of the upstream Python reimplementation of Claude Code. This repo adds the multi-agent orchestration, scheduling, and LLM-routing layers that the upstream does not ship.*

> 📍 **Repo location:** [`https://gitcode.com/chadwweng/clawcodex`](https://gitcode.com/chadwweng/clawcodex) — the project is **not yet open-sourced**, so public search engines / GitHub search will not find it. Use this URL directly to clone and browse.

[English](README.md) · [中文](docs/i18n/README_ZH.md) · [Original upstream README](README.md.raw)

</div>

<!--
  ════════════════════════════════════════════════════════════════════════════
  AGENT / LLM SEARCH METADATA — DO NOT REMOVE
  ════════════════════════════════════════════════════════════════════════════
  Project       : ClawCodex DevMind
  Language      : Python 3.10+
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
    - clawcodex-dev orchestrator | cron | pos | coordinator subcommands
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
  <img src="https://img.shields.io/badge/python-3.10%2B-blue?logo=python" alt="Python 3.10+">
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

- 🤖 **Orchestrator** — a daemon that polls issue trackers, branches a workspace, runs the agent, and opens PRs unattended
- 🧩 **SOP Compiler** — convert any `workflow.md` procedural spec into a coordinated multi-agent system
- ⏰ **Cron System** — distributed-lock scheduling with jitter and NDJSON run history
- 🌉 **Bridge Daemon extensions** — multi-session bridge, remote runtime, REPL/headless adapters
- 🔌 **LiteLLM Provider** — one interface to 100+ LLM backends (catch-all behind `--provider litellm`)
- 👥 **Coordinator / Team** — `TeamCreate` / `TeamDelete` worker swarms with `SendMessage` peer DMs
- 🩹 **PR Review Auto-Fix (F-37)** — read review comments + CI logs, iterate on the same branch
- ✅ **Verification Gate (F-38)** — pre-commit / pre-push / post-sync `pytest` gate with Markdown + JSON report
- 🔁 **Issue Re-run Mechanism (F-39)** — `agent:retry` / `agent:follow-up` / `agent:blocked` labels drive re-runs

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

## Quick Start

**Compatible versions in this README** (matched 1:1 with the bundled `install.sh`):

| Component | Version | Notes |
|---|---|---|
| `install.sh` | v0.5.0 | The installer script that ships with this README (released with the clawcodex tag it installs) |
| `clawcodex` | v0.5.0 | The version this `install.sh` installs |
| Git ref | `v0.5.0` | The git tag/branch the installer clones |

To install a different clawcodex version, download the `install.sh` that ships on that version's tag.

### One-Click Install (recommended)

The fastest path. `install.sh` does everything end-to-end: OS detection,
Git / uv / Python prerequisite checks, repo clone, venv creation,
lock-pinned dep install, global command registration, and shell rc
patching.

```bash
git clone --depth 1 https://gitcode.com/chadwweng/clawcodex /tmp/clawcodex \
  && bash /tmp/clawcodex/install.sh
```

After it finishes (typically ~20s on a fresh box):

```bash
source ~/.bashrc                # or: source ~/.zshrc   (or open a new terminal)
clawcodex-dev --version         # verify the install
```

Common flag / subcommand variants:

```bash
# Diagnose environment without installing
bash /tmp/clawcodex/install.sh doctor

# Preview every step without applying changes
bash /tmp/clawcodex/install.sh --dry-run

# Non-interactive install (CI / Docker)
bash /tmp/clawcodex/install.sh --no-venv --no-setup --yes \
                                  --log-file /tmp/install.log

# Install a specific tag / commit
bash /tmp/clawcodex/install.sh --ref v0.5.0
```

> **💡 Windows 用户请注意：** 以上命令需要在 **Git Bash**（[Git for Windows](https://git-scm.com/download/win) 自带）或 **WSL2** 中执行。
> 原生 `cmd.exe` / PowerShell 不支持 bash 脚本。如果你只有 cmd/PowerShell，可以：
>
> ```powershell
> # 方案 A：使用 Git Bash（推荐）
> # 1. 从 https://git-scm.com/download/win 安装 Git for Windows
> # 2. 在开始菜单中打开 "Git Bash"
> # 3. 在 Git Bash 中运行：
> #    git clone --depth 1 https://gitcode.com/chadwweng/clawcodex /tmp/clawcodex
> #    bash /tmp/clawcodex/install.sh
>
> # 方案 B：使用 WSL2（Ubuntu）
> # 1. 以管理员身份打开 PowerShell，运行：
> #    wsl --install -d Ubuntu
> # 2. 重启后打开 Ubuntu 终端，运行：
> #    git clone --depth 1 https://gitcode.com/chadwweng/clawcodex /tmp/clawcodex
> #    bash /tmp/clawcodex/install.sh
> ```

When you're done with the temp clone:

```bash
rm -rf /tmp/clawcodex
```

### Manual install (alternative)

If you prefer to wire it up by hand — useful when developing on the
project itself, or when `install.sh` is unavailable:

```bash
git clone https://gitcode.com/chadwweng/clawcodex.git
cd clawcodex

# Install (uv recommended; pip also works)
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[dev]"
python scripts/ci/dev_setup.py

# Configure providers (one-time)
clawcodex-dev login

# Run the downstream CLI
clawcodex-dev                      # REPL (same as upstream, plus orchestrator subcommands)
clawcodex-dev orchestrator --help  # see all orchestrator commands
clawcodex-dev cron --help          # see cron subcommands
clawcodex-dev pos --help           # see SOP compiler subcommands
```

### Shell tab completion

`clawcodex-dev` ships with [argcomplete](https://github.com/kislyuk/argcomplete)
support. After installation, enable completion for your shell:

```bash
# bash
eval "$(register-python-argcomplete clawcodex-dev)"

# zsh
eval "$(register-python-argcomplete clawcodex-dev)"

# fish
register-python-argcomplete --shell fish clawcodex-dev | source
```

Tab completion covers the top-level subcommands (`login`, `config`, `mcp`,
`daemon`, `doctor`, `orchestrator`, `autonomy`, `schedule`, `provider`,
`model`, `pos`, `viz`) and the top-level flags. The `orchestrator`
subcommand also completes its nouns (`server` / `issue` / `dashboard`).

> The upstream CLI (`python -m src.cli`) still works — this fork adds a parallel `clawcodex-dev` entry that registers the downstream subcommands (`orchestrator`, `cron`, `pos`, ...).

## Prerequisites & Supported Platforms

### Operating systems

| OS | Status | Notes |
|---|---|---|
| Linux (Debian, Ubuntu, Fedora, RHEL, Arch, openSUSE, …) | ✅ Supported | Default test platform |
| macOS 12+ (Monterey and newer) | ✅ Supported | Apple Silicon and Intel |
| WSL2 (Ubuntu / Debian inside Windows) | ✅ Supported | Recommended on Windows |
| Git Bash on Windows | ✅ Supported | For users who can't enable WSL |
| Windows: native `cmd.exe` / PowerShell | ❌ Not supported | Use Git Bash or WSL instead |

> Native Windows shells (`cmd.exe`, PowerShell) are not supported by
> `install.sh` because it is a bash script. Use Git Bash (ships with
> [Git for Windows](https://git-scm.com/download/win)) or WSL2
> ([install guide](https://learn.microsoft.com/windows/wsl/install)).

### Required software

| Tool | Min version | Auto-provisioned? |
|---|---|---|
| **Git** | any 2.x | No — install via OS package manager |
| **Python** | 3.10+ (3.11 recommended) | ✅ Yes — `uv` installs it on demand |
| **uv** | any 0.5+ | ✅ Yes — downloaded from `astral.sh` on first run |
| **curl** or **wget** | any | No — required for `uv` install + repo clone |
| **bash** | 4+ | Pre-installed on Linux/macOS; macOS 3.2 is fine via `bash -s` |

Install Git on your platform:

```bash
sudo apt install -y git          # Debian / Ubuntu
sudo dnf install -y git          # Fedora / RHEL
sudo pacman -S --noconfirm git   # Arch
xcode-select --install           # macOS
```

### Network

The install reaches out to three HTTPS endpoints. All three are
required for a first-time install (subsequent runs reuse the cache):

- `https://gitcode.com/chadwweng/clawcodex` — repo clone
- `https://astral.sh/uv/install.sh` — uv installer (first run only)
- `https://pypi.org/` (and the default PyPI index) — Python deps

If you're behind a corporate proxy / firewall, set `HTTPS_PROXY` /
`HTTP_PROXY` and the standard Python `REQUESTS_CA_BUNDLE` variables
before running `install.sh`. The script honors `https_proxy` /
`http_proxy` env vars for `curl`.

### Disk

About **500 MB** free in the install directory (`$HOME/.clawcodex/`
by default) — covers the repo, `.venv`, and the resolved dep tree.
The runtime config dir (`$HOME/.clawcodex/`) also accumulates session
history, logs, and auth tokens; budget an extra **~100 MB** for that.

### Permissions

`install.sh` is **fully user-local** — it does **not** require
`sudo` or root. All writes go to:

- `$HOME/.clawcodex/clawcodex/` — project source + venv
- `$HOME/.clawcodex/` — runtime config
- `$HOME/.local/bin/` — `clawcodex` and `clawcodex-dev` wrappers
- `~/.bashrc` / `~/.zshrc` / `~/.profile` — adds `~/.local/bin` to `PATH`

If you point `--install-dir` at a system path (e.g. `/opt/clawcodex`),
you **will** need sudo. The script will fail otherwise.

### Things to know

- **No system Python is touched when using the default venv mode** —
  the install creates a project-local `.venv` and only writes there.
- **In `--no-venv` mode**, the install uses `uv pip install --system`
  and falls back to `--break-system-packages` on PEP 668 systems.
  Only use this in Docker images, throwaway CI runners, or other
  already-isolated environments.
- **After install, open a new shell** (or `source ~/.bashrc` /
  `~/.zshrc` / `~/.profile`) for the `clawcodex-dev` command to be
  on `$PATH`. `install.sh` patches the rc file but cannot reload
  the current shell.
- **Re-running `install.sh` is safe** — existing repos are
  fast-forwarded, existing venvs are reused, command wrappers are
  regenerated. To start completely fresh, run `./install.sh
  uninstall` first.
- **To install a different clawcodex version** (older or newer
  than the one this README's `install.sh` ships with), download
  the `install.sh` that lives on that version's tag — each
  release ships with its own installer, and the lockfile pins
  every transitive dependency.

---

## Fork Features

### 🤖 Orchestrator — autonomous issue → PR pipeline

The headline feature of this fork. A long-running daemon that continuously polls a tracker, picks up issues, branches a workspace, runs the agent with the right tools and permission mode, verifies, commits, pushes, and opens a PR — with operator override at every step.

**Setup (3 minutes):**

```bash
# 1. Copy the template
cp extensions/orchestrator/templates/workflow.template.md ./workflow.md
$EDITOR workflow.md    # set tracker, repo, branch_prefix, provider, permission_mode

# 2. Start the daemon
clawcodex-dev orchestrator server start --workflow ./workflow.md

# 3. Watch
clawcodex-dev orchestrator issue list
clawcodex-dev orchestrator issue tail --id <id>
clawcodex-dev orchestrator dashboard                   # HTTP/SSE on :8080
```

**What ships in `extensions/orchestrator/`:**

| Module | Purpose |
|---|---|
| `tracker.py` + `linear/`, `gitcode`, `gitee`, `github` adapters | Pluggable issue source (4 trackers) |
| `issue_registry.py` | JSON-backed mapping: issue ↔ branch ↔ PR ↔ attempts |
| `clarification.py` + `clarification_queue.py` | 13-state clarification queue with 3-channel resolver (interactive / file / @mention) |
| `agent_runner.py` | Spawn the agent inside a per-issue worktree, with retries, backoff, and verification gate |
| `git_sync.py` | Pre-commit / pre-push / post-sync hooks (F-38), PR body templating |
| `status_dashboard.py` + `cli/dashboard.py` | HTTP/SSE LiveView on port 8080, embedded HTML/JS |
| `workspace.py` + `workspace_locator.py` | Per-issue worktree lifecycle |
| `review_feedback.py` | Read PR review comments, drive `agent_runner` to fix on the same branch (F-37) |
| `progress_reporter.py` | Stage-based progress events to NDJSON |
| `approval_policy.py` | Tool-level approval routing for headless runs |
| `orchestrator.py` | The main daemon loop |
| `workflow.py` + `workflow_store.py` + `templates/workflow.template.md` | YAML frontmatter config with Jinja-style agent prompt |

**Subcommands:**

```bash
# Server lifecycle
clawcodex-dev orchestrator server {start,status,stop} --workflow <file>

# Issue query
clawcodex-dev orchestrator issue list [--status <state>] [--workspace <path>]
clawcodex-dev orchestrator issue show --id <id>
clawcodex-dev orchestrator issue tail --id <id>             # live NDJSON tail

# Issue lifecycle
clawcodex-dev orchestrator issue stop    --id <id>          # force-terminate
clawcodex-dev orchestrator issue pause   --id <id> [--reason <text>]
clawcodex-dev orchestrator issue resume  --id <id>
clawcodex-dev orchestrator issue takeover --id <id>         # stop agent + spawn REPL in workspace

# Operator interaction
clawcodex-dev orchestrator issue clarify --id <id> --answer <text> [--forward-to-author]
clawcodex-dev orchestrator issue inject  --id <id> [hint]   # inject operator hint into .operator_hints.md

# Workspace inspection
clawcodex-dev orchestrator issue workspace --id <id> [--ls|--cat FILE|--edit FILE --with CONTENT]

# Dashboard
clawcodex-dev orchestrator dashboard [--port 8080] [--host 127.0.0.1]
```

**Issue states tracked by the registry:** `pending` · `running` · `synced` · `completed` · `failed` · `abandoned`.

**F-feature additions on top of the basic orchestrator:**

- **F-37 — PR Review Auto-Fix** — after a PR is opened, the orchestrator subscribes to review comments, inline review threads, and CI failure logs. When feedback arrives it re-runs the agent on the **same branch** (no new PR), pushing fix commits until the reviewer is satisfied or a max-iteration cap is hit.
- **F-38 — Verification Gate** — `git_sync` runs a `test_command` (default `pytest -x`) at three checkpoints: `pre_commit`, `pre_push`, `post_sync`. Failures block the push. The Markdown + JSON report is auto-inserted into the PR body and posted as a single summary comment.
- **F-39 — Issue Re-run Mechanism** — three repo labels drive re-runs:
  - `agent:retry` — reset local state, close old PR, re-run the entire issue from scratch
  - `agent:follow-up` — keep PR, push additional commits for the new comments (F-37 path)
  - `agent:blocked` — permanently skip the issue
  - Also reachable as `/agent retry` / `/agent follow-up` comment commands (originator-only, rate-limited), and as a CLI fallback `clawcodex-dev orchestrator issue retry --id <id> --mode reset`.

---

### 🧩 SOP Compiler

Many engineering processes are still documented as procedural `workflow.md` scripts — "if X happens, do Y, then notify Z". The SOP compiler (`extensions/pos_converter/`) turns those specs into a coordinated multi-agent runtime.

```bash
clawcodex-dev pos convert examples/pos/order_processing.md \
    --out ./.clawcodex
```

Emits:

- `.clawcodex/agents/pos-order-processing.yaml` — agent definitions (one per role)
- `.clawcodex/skills/pos-order-processing/SKILL.md` — entry-point skill
- `.clawcodex/workflows/pos-order-processing.yaml` — orchestration graph

The runtime plugs into the upstream `Coordinator` / `Team` subsystem, so generated agents can `SendMessage` to each other and survive crashes via the upstream's task-notification routing.

**Modules:**

- `sdk_parser.py` — parse the `workflow.md` spec (frontmatter + body)
- `skill_grouper.py` — group steps into role-coherent skills
- `agent_builder.py` — materialize each role as a `TeamCreate` agent
- `templates.py` — Jinja templates for the emitted YAML

---

### ⏰ Cron System

A standalone scheduling layer (`clawcodex_ext/cron_system/`) — separate from the agent loop — for "run this on a schedule" workloads.

```bash
clawcodex-dev cron add "0 2 * * *"   "run nightly test suite"
clawcodex-dev cron list
clawcodex-dev cron status <task_id>
clawcodex-dev cron enable <task_id> | disable <task_id> | remove <task_id>
```

**Features:**

| Capability | Detail |
|---|---|
| Cron expression parser | Standard 5-field syntax, plus `@daily` / `@hourly` / `@reboot` aliases |
| Distributed file-lock | Safe to run multiple scheduler instances — only one wins per slot |
| Jitter | Random offset (configurable) to avoid thundering herd |
| NDJSON run history | `.cron_runs/{task_id}.ndjson` per-task run log |
| Notifications | Optional webhooks / log notifications on success / failure |
| Status commands | `status`, `last_run`, `next_run`, `exit_code`, `duration_ms` |

Used by the orchestrator for background retries, and exposed directly to users for any automation.

---

### 🌉 Bridge Daemon Extensions

The upstream ships a bridge skeleton. This fork fills it out into a working multi-session daemon with five phases (`src/bridge/` + `src/remote/`):

| Phase | File | What it does |
|---|---|---|
| 3 | `bridge_api.py` | HTTP client (long-poll, SSE) for remote control |
| 4 | `session_runner.py` | Spawn sub-CLIs per session |
| 5 | `remote_bridge_core.py` | Core remote runtime (exec, attach, detach) |
| 8 | `bridge_main.py` | Multi-session daemon — multiplex N sessions over one process |
| 11 | `repl_bridge.py` | Bridge into an existing REPL (used by orchestrator `takeover`) |

**Use cases:**

- Drive a headless agent from an IDE plugin over HTTP/SSE
- Attach the orchestrator to a long-running sandbox VM
- `takeover` from the orchestrator — kill the agent and drop into a REPL in the same workspace for manual fix-up

---

### 🔌 LiteLLM Provider

A single `--provider litellm` that talks to **any** LLM backend LiteLLM supports (Bedrock, Vertex, Azure, Together, Anyscale, …) without writing a new provider class.

```bash
# All of these work out of the box
clawcodex-dev --provider litellm --model bedrock/anthropic.claude-3-5-sonnet -p "hi"
clawcodex-dev --provider litellm --model vertex_ai/gemini-1.5-pro         -p "hi"
clawcodex-dev --provider litellm --model azure/gpt-4o                     -p "hi"
clawcodex-dev --provider litellm --model openai/<your-finetune>           -p "hi"
```

Implementation: `extensions/providers_ext/litellm_provider.py` (a thin adapter on top of the upstream `BaseProvider`).

It also handles the cross-provider quirks the upstream needed help with: Anthropic `image` / `document` blocks → OpenAI `image_url` / `file` for vision-capable OpenAI-compat backends.

---

### 👥 Coordinator / Team Workers

Exposes the upstream's team primitives as a usable worker-swarm model:

```text
clawcodex-dev coordinator team create --name build-team --members agent-1,agent-2,agent-3
clawcodex-dev coordinator team list
clawcodex-dev coordinator team delete --name build-team
```

- `TeamCreate` / `TeamDelete` tools exposed in the agent loop
- Workers can `SendMessage` each other (peer DMs) and the manager
- Task-notification XML routing surfaces worker events back to the manager
- Used by the SOP compiler and the orchestrator for parallel issue handling

---

### 🛠 Tool Bundles

The upstream loads all 30+ tools at startup. This fork adds **bundles** for faster cold-start and smaller context (`extensions/tool_system_ext/`):

| Bundle | Loaded at startup | Use when |
|---|---|---|
| `bare` | Read, Write, Edit, Bash, Grep, Glob | Headless CI runs |
| `default` | + WebFetch, WebSearch, TodoWrite, AskUserQuestion | Normal REPL sessions |
| `clawcodex` | v0.5.0 | Full REPL with team workflows |
| `all` | Everything in the registry | Maximum flexibility |

Switch with `clawcodex-dev --tool-bundle clawcodex` (or `tool_bundles` in `~/.clawcodex/config.json`).

TF-IDF `ToolSearch` is preserved from the upstream — semantic tool discovery still works on top of bundles.

---

### 🖥 Extended TUI Hooks

The downstream Textual TUI (`clawcodex_ext/tui/`) adds 8 hook points to the upstream TUI, so users can customise layout / themes / key bindings without forking the TUI itself. Configurable through `~/.clawcodex/keybindings.json` (a keybinding-help skill is also surfaced in the slash menu).

---

### 🔁 Open-Source Component Replacements

A non-obvious but high-leverage contribution of this fork: **six subsystems that the upstream shipped as hand-rolled code are replaced with mature open-source libraries** — removing ~3,100 lines of bespoke infrastructure and inheriting battle-tested behaviour, security fixes, and community maintenance for free.

| Upstream hand-rolled code | Replaced with | Why | LOC delta |
|---|---|---|---|
| Config layer (~220 LOC of dataclass + env-var glue) | **[Pydantic Settings](https://docs.pydantic-settings.dev/)** | Type-safe config, env-var parsing, `.env` support, nested models out of the box | **−220** |
| YAML frontmatter parser (SKILL.md, agent files, output styles) | **[python-frontmatter](https://python-frontmatter.readthedocs.io/)** | Round-trips nested structures (`hooks:`, `shell:`) through `parse_frontmatter()`; widely used in the static-site ecosystem | **−80** |
| Bash command parser for permission checks | **[tree-sitter-bash](https://github.com/tree-sitter/tree-sitter-bash)** | Proper AST instead of regex; catches `&&`, `\|`, redirects, subshells, command substitution — the regex parser missed a class of bypasses | **−1,400** |
| Git operations (clone, branch, push, diff, status) | **[GitPython](https://gitpython.readthedocs.io/)** | Stable API over `git(1)`, handles edge cases (detached HEAD, shallow clones, submodules) the hand-rolled wrapper did not | **−200** |
| Hook system (registry, executor, event dispatch) | **[Pluggy](https://pluggy.readthedocs.io/)** | The de-facto plugin manager (used by `pytest`, `tox`, `devpi`); gives the hook system a stable contract, hookspec validation, and lazy loading | **−1,000** |
| Structured-output / JSON-schema enforcement | **[Outlines](https://outlines-dev.github.io/outlines/)** | Token-budget-aware structured generation; lets the agent decide tool calls under a real token budget instead of post-hoc regex | **−200** |

**Total: ~3,100 LOC of bespoke code removed**, replaced by libraries that are independently maintained, security-audited, and used across the Python ecosystem.

**Why it matters:**

- **Smaller attack surface** — the replaced components were the most likely places for permission bypasses (regex bash parser) and config injection (manual env-var glue).
- **Better correctness** — `tree-sitter-bash` is a real grammar, not a regex; Pydantic Settings validates types at load time; Pluggy enforces hookspec contracts.
- **Easier to upstream** — the replacements are drop-in and use the same public interfaces, so this layer can be merged back into the upstream `clawcodex` repo without breaking consumers.

You can see these choices declared in `pyproject.toml` under `[project.dependencies]`. The upstream-specific sub-comment block keeps each replacement discoverable from the package metadata.

---

## Downstream CLI surface

`clawcodex-dev` is a parallel entry point to the upstream `python -m src.cli`. It registers everything upstream does, **plus**:

```bash
clawcodex-dev orchestrator ...    # autonomous issue handling (this fork)
clawcodex-dev cron           ...   # distributed cron (this fork)
clawcodex-dev pos            ...   # SOP compiler (this fork)
clawcodex-dev coordinator    ...   # team / worker primitives (this fork)
```

All the upstream flags (`-p`, `--tui`, `--provider`, `--model`, `--permission-mode`, `--dangerously-skip-permissions`, `--allow-dangerously-skip-permissions`, `--tool-bundle`, …) keep working unchanged.

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
              └──────┬────────┘  └─────────────┘  └─────────────────┘
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
├── pos_converter/                   #   - SOP compiler
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
├── cli/                             #   - clawcodex-dev entry (parser, dispatch, runners)
├── cron_system/                     #   - distributed cron scheduler
├── frontend/                        #   - headless frontend
├── runtime/                         #   - RuntimeContext factory
└── tui/                             #   - extended Textual TUI (8 hook points)
```

Everything in `src/` belongs to the upstream — see [`README.md.raw`](README.md.raw) and [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the upstream architecture map.

---

## Roadmap (this fork)

| F-id | Feature | Status |
|---|---|---|
| F-34 | Downstream CLI / TUI / Runtime split (`clawcodex_ext/`) | ✅ Phase 1-3 complete |
| F-37 | PR review comment auto-fix on the same branch | ✅ |
| F-38 | Pre-commit / pre-push / post-sync verification gate + report | ✅ |
| F-39 | Issue re-run labels (`agent:retry` / `agent:follow-up` / `agent:blocked`) | ✅ |
| — | Orchestrator daemon + 4 trackers + LiveView dashboard | ✅ |
| — | SOP compiler | ✅ |
| — | Cron System with distributed lock + jitter | ✅ |
| — | LiteLLM provider | ✅ |
| — | Coordinator / TeamCreate / TeamDelete | ✅ |
| — | Tool bundles (`bare` / `default` / `clawcodex` / `all`) | ✅ |
| — | Bridge daemon phases 3, 4, 5, 8, 11 | ✅ |
| — | 8 extended TUI hooks | ✅ |

See [`docs/FEATURE_PLAN.md`](docs/FEATURE_PLAN.md) for the full F-feature backlog and the active roadmap.

---

## Development

```bash
git clone https://gitcode.com/chadwweng/clawcodex.git
cd clawcodex
pip install -e ".[dev]"
# Create CI/CD environment
python scripts/ci/dev_setup.py
python -m pre_commit run --all-files  # optional first-run confidence check

# Run only the fork's own tests
pytest tests/test_orchestrator.py -v
pytest tests/test_cron_system.py -v
pytest tests/test_pos_converter.py -v
pytest tests/test_bridge.py -v

# Or everything except upstream integration tests
pytest tests/ -m "not integration" -v
```

Git hooks do not auto-activate just because `.pre-commit-config.yaml` is
present in a clone. `scripts/ci/dev_setup.py` installs the local pre-commit hook
and creates the ignored `.env` template when missing; `install.sh install` and
`install.sh update` do the same for one-click installs. The hook is an early
local hygiene check, not a replacement for the GitCode `push` / `pull_request`
gates.

- GitCode CI/CD gates live in `.gitcode/workflows/`. Because GitCode Pipeline may be unavailable for this repository, the same gate shape can be simulated locally. In interactive terminals it shows a live colored dashboard; in CI/logs force plain output with `--ui plain`. When an AI agent is involved in development, it is recommended to have it run the command below as a pre-commit self-check before committing.

    ```bash
    # Plain-text form for AI involvement
    python scripts/ci/local_ci.py --base "the fork's remote dev branch" --ui plain --failure-lines 120
    # Graphical form for developer involvement
    python scripts/ci/local_ci.py --base upstream/dev-decoupling-refactor-b24b8cb
    ```

    - **Scope of the changed-file check.** Without `--all`, the gate diffs only `HEAD~1..HEAD` — i.e. the *last* commit on the branch. That is fine for a single-commit change, but **before opening a PR with multiple commits it under-checks**: earlier commits on the branch are not covered, so the local result can diverge from the GitCode PR gate (which diffs the whole PR against its merge base). Use `--base <ref>` to cover the full PR diff.
        - `--base` accepts any ref; `local_ci` computes `merge-base(<ref>, HEAD)` and checks `merge-base...HEAD`, so it stays correct as your branch grows. To check the entire tracked tree instead (slowest; also surfaces historical debt), use `--all`.
    - **Keep `upstream` current with `git fetch upstream` before running the gate.**
    - Pytest gates use a fixed smoke suite plus any changed `tests/**/test_*.py` or `tests/**/*_test.py` files from the current PR/push scope, so newly added tests are picked up without manually editing every workflow.

- The detailed gate map is in [`docs/cicd/CICD_GATE.md`](docs/cicd/CICD_GATE.md); [`CONTRIBUTING.md`](CONTRIBUTING.md) covers PR conventions.

---

## Release

Release publishing changes external services, so run it only from a clean
tracked working tree. When `--tag` is provided, the local fallback creates the
missing local tag at `HEAD`; an existing release tag must already point at
`HEAD`.

`.env` is ignored by Git. Generate it once from `.env.example` with the developer
setup helper, then edit it locally:

```powershell
.\.venv\Scripts\python.exe scripts\ci\dev_setup.py
```

Fill tokens according to the publish target:

| Publish target | `.env` value to fill | Notes |
|---|---|---|
| TestPyPI rehearsal | `TEST_PYPI_TOKEN=...` | Default `--release-target testpypi`. |
| PyPI promotion | `PYPI_TOKEN=...` | Use `--release-target pypi` after checking TestPyPI. |
| GitCode Release assets | `GITCODE_TOKEN=...` | Only needed when you do **not** pass `--skip-gitcode-release`. Keep `GITCODE_OWNER=` and `GITCODE_REPO=` empty until GitCode Release upload is enabled here. |

Credential-only checks do not build or upload anything:

```powershell
.\.venv\Scripts\python.exe scripts\ci\local_publish.py --release-target testpypi --check-credentials --skip-gitcode-release
.\.venv\Scripts\python.exe scripts\ci\local_publish.py --release-target pypi --check-credentials --skip-gitcode-release
```

A normal publish run performs, in order: load `.env`, check credentials, require a
clean tracked tree, create or verify the release tag, clean old artifacts, run release lint,
run required mypy, run release tests, build/check/install the package in
`.release-smoke/`, upload to TestPyPI or PyPI, then upload GitCode Release assets
unless skipped.

Useful options:

| Option | Effect |
|---|---|
| `--release-target testpypi` | Upload package artifacts to TestPyPI; this is the default. |
| `--release-target pypi` | Upload package artifacts to PyPI. |
| `--tag v0.0.0` | Create the missing local tag at `HEAD`; if it already exists, require it to point at `HEAD`. |
| `--dry-run` | Run validation and package smoke, then list uploads without changing PyPI or GitCode. |
| `--check-credentials` | Only create/load `.env` and verify required token names. |
| `--skip-gitcode-release` | Do not create GitCode Release assets; currently recommended for this repository. |
| `--skip-tests` | Skip the release pytest set; use only when another trusted gate already ran. |

Recommended flow:

```powershell
# Validate release checks and package build without uploading artifacts.
.\.venv\Scripts\python.exe scripts\ci\local_publish.py --release-target testpypi --tag v0.5.0 --dry-run --skip-gitcode-release
# Upload package artifacts to TestPyPI only.
.\.venv\Scripts\python.exe scripts\ci\local_publish.py --release-target testpypi --tag v0.5.0 --skip-gitcode-release
# Promote package artifacts to production PyPI.
\.venv\Scripts\python.exe scripts\ci\local_publish.py --release-target pypi --tag v0.5.0
```


---

## Sync with upstream

This fork tracks the upstream `clawcodex` repo. The sync pipeline is at `upstream_sync/` and the design is in [`upstream_sync/UPSTREAM_SYNC_DESIGN.md`](upstream_sync/UPSTREAM_SYNC_DESIGN.md). When upstream moves, run:

```bash
python -m upstream_sync.pull --since 2026-05-20
python -m upstream_sync.verify
pytest tests/ -m "not integration" -v
```

---

## License

[MIT](LICENSE) — same as upstream clawcodex. The downstream additions in `extensions/` and `clawcodex_ext/` are released under the same MIT terms.

This is an independent project, not affiliated with Anthropic. Built on the publicly-documented Claude Code TypeScript reference, ported to Python by the upstream team, extended here.

---

## Acknowledgments

- **clawcodex** — the upstream Python port of Claude Code that this fork builds on
- **Claude Code** (Anthropic) — the original TypeScript architecture
- **Aider** · **Cline** · **Continue** · **OpenHands** — reference for CLI / TUI patterns
- **LiteLLM** — the catch-all provider layer

---

<div align="center">

**Star ⭐ this repo if you find the autonomous issue pipeline useful.**

[⬆ Back to top](#clawcodex-devmind)

</div>
