---
name: clawcodex-repl-pty-debug
description: Use when an external agent needs to debug the real ClawCodex REPL by sending multi-turn inputs through a PTY and observing rendered output before deciding the next turn.
---

# ClawCodex REPL PTY Debugging

Use this skill for behavior that only appears in the real interactive REPL:
prompt rendering, slash commands, streaming output, ANSI redraws, and
multi-turn user flows.

## Decision Gate

Do not make PTY the default debugging surface. PTY is the high-fidelity layer
for real terminal behavior and multi-turn observation, not the first stop for
every ClawCodex issue.

Classify the issue before starting the controller:

| Issue class | First surface |
| --- | --- |
| Structured agent behavior, tool calls, final text | `QueryRunner` or headless tests |
| CLI black-box behavior | `clawcodex -p --output-format stream-json` |
| Event bridge without live provider | `CLAW_HEADLESS_BACKEND=stub` |
| Real REPL, same-session multi-turn flow, slash-command rendering | PTY controller |
| TUI layout, focus, keyboard, alternate screen | Textual tests or PTY/TUI harness |

Escalate to PTY only when the lower-fidelity surface cannot answer the question
or when the user explicitly asks for real REPL output, same-session observation,
or terminal-rendered behavior.

## Start The Controller

Run:

```bash
env UV_SKIP_WHEEL_FILENAME_CHECK=1 uv --cache-dir /private/tmp/clawcodex-uv-cache run --extra dev --frozen python scripts/debug/repl_pty_session.py interactive
```

Keep the process running. Send one JSON command per line to stdin. Read one JSON
response per line from stdout.

In Codex-style tool environments, start the controller as a persistent PTY
session, not as a one-shot command. For example, use `exec_command` with
`tty:true`, keep the returned `session_id`, and send later JSON operations with
`write_stdin`. If the command exits before you can send `{"op":"start"}`,
classify that as controller launch mechanics and restart with a persistent PTY;
do not treat it as a REPL, provider, or ClawCodex failure.

Use this controller like a human at a terminal: observe what changed, decide the
next input, then continue. Do not treat it as a brittle batch script unless the
behavior is already deterministic.

For an end-to-end file-creation run, prefer a unique artifact root so a failed
preflight and a later successful run do not share one `result.json`:

```bash
env UV_SKIP_WHEEL_FILENAME_CHECK=1 uv --cache-dir /private/tmp/clawcodex-uv-cache run --extra dev --frozen python scripts/debug/repl_pty_session.py interactive --artifact-root /private/tmp/clawcodex-repl-pty-e2e-<run-id>
```

In agent-debug mode, the controller redirects child state paths such as
`CLAWCODEX_HOME`, history, sessions, and telemetry into the artifact state
directory. If setting `/goal <objective>` prints `attempt to write a readonly
database`, the child is probably running through an older/custom harness that
still points goal storage at the real `~/.clawcodex` database.

## Sandbox And Live Provider Routing

The fake child and local slash-command checks can run inside the normal sandbox.
When testing a live provider, start the interactive controller outside the
sandbox if the host environment supports an approval/escalation mechanism. The
live provider request is made by the child REPL process; if the controller is
started inside a network-restricted sandbox, DNS or outbound HTTPS can fail even
when the user's machine and ClawCodex provider config are healthy.

Before starting the controller, classify whether the user's requested acceptance
requires a real model/provider request. Treat these as live-provider requests:
natural-language prompts that should be answered by the configured model,
active-goal continuation after `/goal <objective>`, "real API", "live provider",
"credentials/network are available", or any test whose success depends on an
assistant response rather than local slash-command output.

If live-provider behavior is in scope, ask for the required escalation up front
instead of first running the live REPL inside the network-restricted sandbox.
The approval request should say that the child REPL will use configured provider
credentials and outbound network. If approval is not granted, continue only with
the local/fake/stub parts and report the live-provider portion as unverified or
blocked by approval; do not classify the resulting missing live response as a
ClawCodex, goal-runtime, or PTY-controller failure.

Use this order:

1. At intake, decide whether live-provider behavior is required and request
   approval up front when it is.
2. Run the fake child smoke test in the normal sandbox.
3. Run a stub/headless smoke when the behavior does not require terminal
   rendering.
4. Use PTY with local slash commands to prove the controller, prompt, and
   session loop.
5. For the approved live-provider portion, start the interactive controller
   outside the sandbox and drive the REPL with JSON operations as usual.

Failure signature: local slash commands such as `/help`, `/tools`, and `/goal`
work, but natural-language messages fail with `httpcore.ConnectError`,
`nodename nor servname provided`, `APIConnectionError`, or `Connection error`.
In that case, retest by starting the interactive controller outside the sandbox
before blaming ClawCodex, the PTY controller, or provider credentials.

## Start A REPL

Send:

```json
{"op":"start"}
```

Wait for:

```json
{"ok":true,"event":"ready"}
```

If `ready` never appears, inspect the returned error and artifact directory.

For coordinator-mode or real multi-agent validation, set the coordinator env on
the child REPL through the JSON `start.env` field. Do not assume the external
agent host inherited the user's shell environment:

```json
{
  "op": "start",
  "cmd": [".venv/bin/python3", "-P", "-m", "clawcodex_ext.cli.main", "--legacy-repl", "--stream", "--agent-debug", "--permission-mode", "bypassPermissions"],
  "env": {"CLAUDE_CODE_COORDINATOR_MODE": "1"}
}
```

Verify coordinator mode from the rendered banner
`Coordinator Mode ACTIVE`, then prove real multi-agent execution from actual
tool output such as `Agent (@worker ...)` or a worker result in `clean.txt` /
`result.json`. Do not treat planner/executor/verifier wording, or a plain
`/tools` listing, as proof that the model actually delegated.

When the task is specifically to verify file creation in isolated disposable
directories, and permission-prompt UI behavior is not under test, start the REPL
in bypass mode instead of spending turns on permission menus:

```json
{"op":"start","cmd":[".venv/bin/python3","-P","-m","clawcodex_ext.cli.main","--legacy-repl","--stream","--agent-debug","--permission-mode","bypassPermissions"]}
```

Use bypass mode only with explicit temporary target paths and external cleanup.
If permission UX is the behavior being tested, use the default start command.

## Isolate First

Before blaming the real provider or network, prove the selected layer. Start
below PTY unless the issue is truly terminal-specific.

For behavior that does not require terminal rendering, prefer the cheaper
structured path with the stub backend:

```bash
CLAW_HEADLESS_BACKEND=stub clawcodex -p --output-format stream-json "Return a short stub response"
```

For behavior that does require terminal rendering, prove the PTY controller
itself before using a live provider:

```bash
env UV_SKIP_WHEEL_FILENAME_CHECK=1 uv --cache-dir /private/tmp/clawcodex-uv-cache run --extra dev --frozen python scripts/debug/repl_pty_session.py run-script --timeout 5 --cmd .venv/bin/python3 tests/debug/fake_repl_child.py
```

Only use a live provider after stub or fake-child evidence shows the relevant
event bridge, controller, and prompt loop are healthy.

If the fake-child smoke itself fails before starting the controller because
`uv` tries to resolve dependencies and DNS/package access is blocked, classify
that as sandbox dependency resolution. Rerun the same smoke outside the network
restricted sandbox before changing the PTY controller or ClawCodex.

## Dynamic Debug Loop

For each turn:

1. Send the next user input with `{"op":"send","text":"..."}`.
2. Read `delta` first; it is the new output since the previous command.
3. Read `screen` when the whole visible transcript matters.
4. If the REPL is still streaming/thinking, or a model response was just
   rendered, send `{"op":"observe","timeout":2.0}` to confirm the prompt state.
5. Decide the next input based on the observation.

`send` submits a full line by calling the child terminal's `sendline()`. Use it
for natural-language prompts, slash commands, and other inputs where pressing
Enter is part of the action.

For raw terminal controls, use `key` (alias: `raw`). It sends exactly the
provided text with no trailing newline:

```json
{"op":"key","text":"1","timeout":1}
{"op":"key","text":"\r","timeout":1}
{"op":"key","text":"\u001b","timeout":1}
```

This matters for prompt-toolkit menus. A permission prompt's `[y]`/`[n]`
letters are labels, not key bindings, in arrow-selection mode. The current item
can be accepted with Enter (`{"op":"key","text":"\r"}`); prefer Enter when the
highlighted item is `Yes, allow this action`. Quick-select digits, if you use
them, must be sent as a single raw key (`{"op":"key","text":"1"}`), not as
`{"op":"send","text":"1"}`. If a raw digit only echoes and no tool output
follows, stop and classify the failure as permission-prompt handling instead of
blindly retrying.

Each observation includes `kind`, `state`, `error_kind`, and `signals`. Use
`kind` to separate `input_echo`, `slash_command`, `assistant_output`,
`permission_prompt`, `provider_error`, `network_error`, `ready`, `prompt`, and
`stopped`. A permission menu is reported as `kind:"permission_prompt"` and
`state:"awaiting_permission"`. Use `signals` as an audit trail for why that
classification was chosen.

The controller ignores the initial terminal echo when checking `expect`, but
`expect` is still best for stable command output such as slash-command status.
For assistant/model responses, prefer `send` followed by one or more `observe`
turns so you do not confuse prompt echo, streaming spinners, provider errors,
and final assistant text.

For slash commands, keep `expect` tied to current stable output. Match casing:
`/help` reports `Available Commands:`, `/tools` reports `Available tools:`, a
fresh `/goal` reports `No goal is currently set.`, an active `/goal` summary
reports `Tokens used:`, and `/cost` reports `Total units:`. A case-mismatched
or stale `expect` creates a controller timeout even though the REPL printed the
command output correctly.

Use `/goal <objective>` carefully as a local slash-command proof. On the real
REPL it can print `Goal active` and then immediately start an assistant turn;
inside a network-restricted sandbox that follow-up provider turn can fail even
though the slash command itself succeeded. For local controller proof, prefer
read-only commands such as `/help`, `/tools`, and fresh `/goal`; for active-goal
continuation behavior, run the controller where provider traffic is allowed and
follow the command with `observe`.

Example:

```json
{"op":"send","text":"/help","expect":"Available Commands:"}
{"op":"send","text":"/tools","expect":"Available tools:"}
{"op":"send","text":"/goal","expect":"No goal is currently set."}
{"op":"send","text":"Return the token named goal pty ok using hyphens and uppercase.","timeout":3}
{"op":"observe","timeout":10}
{"op":"send","text":"/cost","expect":"Total units:"}
```

## Observe Without Sending

Use:

```json
{"op":"observe","timeout":2.0}
```

This is useful after streaming output or when the previous command may still be
printing.

## Stop

Send:

```json
{"op":"stop"}
```

This stops the child REPL and writes artifacts. The interactive controller keeps
running so you can start another REPL in the same process.

To end the controller loop too, send:

```json
{"op":"exit"}
```

The controller writes:

```text
raw.log
clean.txt
result.json
```

Read `result.json` to identify which step failed. Read `clean.txt` for the
human-readable transcript. Read `raw.log` only for ANSI, cursor, or redraw bugs.
For a quick artifact audit without dumping the whole transcript, summarize the
JSON first:

```bash
jq '{ok,error,events:[.events[] | {event,ok,kind,state,error_kind,signals}]}' /path/to/result.json
```

## Rules

- Do not force all debugging through PTY. PTY is for real terminal behavior,
  rendered REPL state, and same-session multi-turn observation.
- Prefer headless `QueryRunner`, stream-json, or stub tests for pure structured
  behavior, tool calls, final text, and event-bridge checks.
- Avoid bare `python` in fake-child commands on this machine; use the repo
  `.venv/bin/python3` created by `uv run`.
- Do not use `subprocess.run(capture_output=True)` as a replacement.
- Keep `--agent-debug` enabled so the REPL emits a stable readiness marker and
  writes history under the debug state directory.
- Use short timeouts while exploring. A timeout should return a structured JSON
  error; inspect `delta`, `screen`, and artifacts before deciding the next turn.
- Stop escalating fidelity once the current layer answers the question.
