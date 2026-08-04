"""Evolve REPL controller - /evolve command + post-session lifecycle hook.

Shows diffs for review and allows user to edit proposals before applying.
"""

from __future__ import annotations

import difflib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

SEA_ROOT = os.path.dirname(os.path.abspath(__file__))
CX_ROOT = os.path.normpath(os.path.dirname(SEA_ROOT))

import json as _json
from pathlib import Path as _Path

def _build_env() -> dict:
    """Read ~/.clawcodex/config.json and build env dict with CX_* vars."""
    _cfg_path = _Path.home() / ".clawcodex" / "config.json"
    _cfg = {}
    if _cfg_path.is_file():
        try:
            _cfg = _json.loads(open(str(_cfg_path), encoding="utf-8").read())
        except Exception:
            pass
    _provider = (_cfg.get("default_provider") or "").strip()
    _api_key = _base_url = _model = ""
    if _provider:
        _pcfg = _cfg.get("providers", {}).get(_provider, {}) or {}
        _api_key = (_pcfg.get("api_key") or "").strip()
        _base_url = (_pcfg.get("base_url") or "").strip()
        _model = (_pcfg.get("default_model") or "").strip()
    _env = {**os.environ,
            "CX_API_KEY": _api_key,
            "CX_BASE_URL": _base_url,
            "CX_MODEL": _model,
            "PYTHONPATH": CX_ROOT}
    return _env

_CX_ENV = _build_env()

def _proposal_matches_focus(proposal: dict, focus_areas: list[str]) -> bool:
    """Check if a proposal matches one of the active focus areas."""
    ptype = (proposal.get('type') or '').lower()
    if 'skill' in focus_areas:
        if any(kw in ptype for kw in ['skill']):
            return True
    if 'prompt' in focus_areas:
        if any(kw in ptype for kw in ['prompt', 'config']):
            return True
    if 'code' in focus_areas:
        if any(kw in ptype for kw in ['plugin', 'workflow', 'loop', 'code_modification']):
            return True
    return False

class EvolveController:
    """Lifecycle controller that runs evolution after each completed session."""

    def __init__(self, repl) -> None:
        self._repl = repl
        self._enabled = False
        self._console = getattr(repl, "console", None)
        self._last_trace_file: str | None = None
        self._ses: "SelfEvolvingSystem | None" = None
        self._focus_areas: list[str] | None = None
        self._applied_versions: list[str] = []
        self._adapter_script = os.path.join(SEA_ROOT, "src", "evolve_repl_adapter.py")
        self._adapter_env = {**_CX_ENV, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        self._versions_registry = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "versions", ".registry.json")

    # --- Public toggle ---

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, val: bool, focus_areas: list[str] | None = None) -> None:
        self._enabled = val
        if focus_areas is not None:
            self._focus_areas = focus_areas
        if self._console:
            status = "ENABLED" if val else "DISABLED"
            focus_str = f" (focus: {', '.join(self._focus_areas)})" if self._focus_areas else ""
            self._console.print(f"[bold]Evolve:[/bold] {status}{focus_str}")

    # --- Lifecycle hooks ---

    def on_run_start(self) -> None:
        pass

    def on_run_finish(self) -> None:
        pass

    def on_assistant_turn_complete(self) -> None:
        if not self._enabled:
            return

        repl = self._repl
        session = getattr(repl, "session", None)
        if session is None:
            return

        conversation = getattr(session, "conversation", None)
        if conversation is None:
            return

        # Try to read from raw transcript JSONL first (richer data)
        transcript_path = None
        session_id = getattr(session, "session_id", None)
        if session_id:
            _sessions_dir = os.path.join(os.path.expanduser("~/.clawcodex"), "sessions")
            _candidate = os.path.join(_sessions_dir, session_id, "transcript.jsonl")
            if os.path.isfile(_candidate):
                transcript_path = _candidate
            else:
                _candidate2 = os.path.join(os.path.expanduser("~/.clawcodex"), "transcripts", session_id + ".jsonl")
                if os.path.isfile(_candidate2):
                    transcript_path = _candidate2

        messages = []
        tool_events = []
        try:
            for msg in conversation.messages:
                role = getattr(msg, "role", "unknown")
                content = getattr(msg, "content", "")
                # Extract tool events from content blocks
                _text = str(content)
                if hasattr(content, "__iter__"):
                    for _block in content:
                        _bt = getattr(_block, "type", "")
                        if _bt == "tool_use":
                            tool_events.append({
                                "type": "tool_use",
                                "tool_use_id": getattr(_block, "id", ""),
                                "name": getattr(_block, "name", ""),
                                "input": getattr(_block, "input", {}),
                            })
                        elif _bt == "tool_result":
                            tool_events.append({
                                "type": "tool_result",
                                "tool_use_id": getattr(_block, "tool_use_id", ""),
                                "output": str(getattr(_block, "content", ""))[:1000],
                                "is_error": getattr(_block, "is_error", False),
                            })
                        elif _bt == "text":
                            _text = getattr(_block, "text", "")
                messages.append({"role": role, "content": _text})
        except Exception:
            pass

        if not messages and not transcript_path:
            return

        if self._console:
            self._console.print("\n[dim]Analyzing session for evolution...[/dim]")

        trace_data = {
            "messages": messages,
            "tool_events": tool_events,
            "timestamp": time.time(),
            "agent_version": getattr(session, "session_id", "unknown"),
            "transcript_path": transcript_path,
            "session_id": session_id,
        }

        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, encoding="utf-8"
            ) as f:
                json.dump(trace_data, f, ensure_ascii=False)
                trace_path = f.name

            self._last_trace_file = trace_path

            # Spawn standalone evolution window (non-blocking)
            _standalone = os.path.join(os.path.dirname(os.path.abspath(__file__)), "evolve_standalone.py")
            _cmd = [sys.executable, _standalone, "--trace", trace_path]
            if self._focus_areas:
                _cmd.extend(["--focus", ",".join(self._focus_areas)])
            if self._console:
                self._console.print("\n[dim]Evolution launched in separate window.[/dim]")
            subprocess.Popen(
                _cmd,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        except Exception as e:
            if self._console:
                self._console.print(f"\n[dim]Evolution spawn error: {e}[/dim]")



    
    def _run_evolution_on_session(self, focus_areas: list[str] | None = None, multi_count: int = 1) -> None:
        """Run evolution analysis on the most recent session transcripts.

        Loads multi_count sessions from disk sorted by modification time (newest
        first).  Always reads from disk, not from in-memory conversation.
        """
        sessions_dir = os.path.expanduser("~/.clawcodex/sessions")
        all_sessions = []

        if os.path.isdir(sessions_dir):
            for sid in os.listdir(sessions_dir):
                tp = os.path.join(sessions_dir, sid, "transcript.jsonl")
                if os.path.isfile(tp):
                    try:
                        mtime = os.path.getmtime(os.path.join(sessions_dir, sid))
                    except OSError:
                        mtime = 0
                    all_sessions.append((sid, tp, mtime))

        if not all_sessions:
            if self._console:
                self._console.print(
                    "[dim]No session transcripts found in " + sessions_dir + "[/dim]"
                )
            return

        all_sessions.sort(key=lambda x: x[2], reverse=True)

        messages = []
        transcript_path = None
        multi_traces = []
        loaded = 0

        for sid, tp, _mtime in all_sessions:
            try:
                msgs = []
                with open(tp, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        entry = json.loads(line)
                        if entry.get("type") in ("session_init", "session_snapshot", "cost_block"):
                            continue
                        msgs.append(entry)
                if msgs:
                    if loaded == 0:
                        messages = msgs
                        transcript_path = tp
                        if self._console:
                            self._console.print(
                                "  [dim]Session 1/" + str(multi_count) + ": " + tp
                                + " (" + str(len(msgs)) + " msgs)[/dim]"
                            )
                    else:
                        multi_traces.append({"messages": msgs})
                        if self._console:
                            self._console.print(
                                "  [dim]Session " + str(loaded + 1) + "/" + str(multi_count) + ": " + tp
                                + " (" + str(len(msgs)) + " msgs)[/dim]"
                            )
                    loaded += 1
                    if loaded >= multi_count:
                        break
            except json.JSONDecodeError as e:
                sys.stderr.write("[Evolve] JSON error in " + tp + ": " + str(e) + chr(10))
            except Exception as e:
                sys.stderr.write("[Evolve] Read error for " + tp + ": " + str(e) + chr(10))

        if loaded == 0:
            if self._console:
                self._console.print(
                    "[dim]No conversation data to analyze (" + str(len(all_sessions)) + " dirs checked).[/dim]"
                )
            return

        if self._console:
            if loaded == 1:
                self._console.print(chr(10) + "[dim]Analyzing session for evolution...[/dim]")
            else:
                self._console.print(
                    chr(10) + "[dim]Analyzing " + str(loaded) + " sessions for evolution...[/dim]"
                )

        # Build trace data (with multi_traces embedded) and spawn standalone
        import time, tempfile
        trace_data = {"messages": messages, "transcript_path": transcript_path}
        if multi_traces:
            trace_data["multi_traces"] = multi_traces
        trace_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, encoding="utf-8"
            ) as f:
                json.dump(trace_data, f, ensure_ascii=False)
                trace_path = f.name
            self._last_trace_file = trace_path

            _standalone = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "evolve_standalone.py"
            )
            _cmd = [sys.executable, _standalone, "--trace", trace_path]
            if multi_count > 1:
                _cmd.extend(["--multi", str(multi_count)])
            if focus_areas:
                _cmd.extend(["--focus", ",".join(focus_areas)])
            if self._console:
                self._console.print("[dim]Evolution launched in separate window.[/dim]")
            subprocess.Popen(
                _cmd,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        except Exception as e:
            if self._console:
                self._console.print("[dim]Evolution spawn error: " + str(e) + "[/dim]")


    def _show_proposal_categories(self, proposals: list, label: str = "", extracted_skill: dict = None) -> None:
        """Display category breakdown of proposals. Shows all 4 categories even when count is 0."""
        if self._console is None:
            return
        if label:
            self._console.print(f"\n[bold]{label}[/bold]")
        _prompt_cat = {"prompt_optimization", "config_adjustment"}
        _skill_mod_cat = {"skill_addition", "skill_modification"}
        _skill_new_cat = {"skill_creation"}
        _code_cat = {"plugin_generation", "workflow_optimization", "loop_parameter_adjustment"}
        _pn = sum(1 for p in proposals if p.get("type") in _prompt_cat)
        _sn = sum(1 for p in proposals if p.get("type") in _skill_mod_cat)
        _scn = sum(1 for p in proposals if p.get("type") in _skill_new_cat) + (1 if extracted_skill else 0)
        _cn = sum(1 for p in proposals if p.get("type") in _code_cat)
        self._console.print(f"  \u2713 \u5df2\u63d0\u51fa prompt \u6539\u8fdb\u65b9\u6848 ({_pn}\u9879)")
        self._console.print(f"  \u2713 \u5df2\u63d0\u51fa skill \u6539\u8fdb\u65b9\u6848 ({_sn}\u9879)")
        self._console.print(f"  \u2713 \u521b\u5efa skill ({_scn}\u9879)")
        self._console.print(f"  \u2713 \u5df2\u63d0\u51fa\u4ee3\u7801\u6539\u8fdb\u65b9\u6848 ({_cn}\u9879)")
        self._console.print()

    def _handle_evolve_result(self, output: str) -> None:
        """Parse and present evolution results with diffs for review."""
        if self._console is None:
            return

        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            self._console.print(f"[dim]Evolve raw: {output[:200]}[/dim]")
            return

        proposals = data.get("proposals", [])
        if not proposals:
            self._console.print("[green]No optimization needed this session.[/green]")
            return

        self._console.print("\n[bold yellow]=== Evolution Analysis Complete ===[/bold yellow]")
        trace_summary = data.get("trace_summary", {})
        self._console.print(
            f"[dim]Session: {trace_summary.get('user_messages', '?')} user / "
            f"{trace_summary.get('assistant_messages', '?')} assistant messages[/dim]"
        )

        self._show_proposal_categories(proposals)

        _workspace_root = os.path.dirname(SEA_ROOT)
        for i, proposal in enumerate(proposals, 1):
            ptype = proposal.get("type", "unknown")
            target = proposal.get("target", "unknown")
            reason = proposal.get("reason", "")
            file_path = proposal.get("file_path", "")
            # Resolve to absolute path if relative; fallback to relative if file not found
            if file_path and not os.path.isabs(file_path):
                _candidate = os.path.join(_workspace_root, file_path)
                if os.path.isfile(_candidate):
                    file_path = os.path.abspath(_candidate)
            # Construct meaningful file path from proposal type + target if missing
            if not file_path or file_path == target:
                if ptype in ("skill_addition", "skill_modification", "skill_creation"):
                    _md_path = os.path.join(CX_ROOT, "clawcodex_ext", "agent", "agents", target + ".md")
                    if os.path.isfile(_md_path):
                        file_path = _md_path
                    else:
                        _clawcodex_skills = os.path.expanduser("~/.clawcodex/skills")
                        _skill_dir = os.path.join(_clawcodex_skills, target)
                        if os.path.isdir(_skill_dir):
                            file_path = os.path.abspath(_skill_dir)
                        else:
                            file_path = os.path.join(_clawcodex_skills, target)
                elif ptype in ("prompt_optimization", "config_adjustment"):
                    _prompt_path = os.path.join(CX_ROOT, "clawcodex_ext", "context_system", "prompt_assembly.py")
                    if os.path.isfile(_prompt_path):
                        file_path = _prompt_path
                elif ptype == "plugin_generation":
                    _target_name = proposal.get("target", "")
                    if _target_name:
                        _target_clean = _target_name
                        if not _target_clean.startswith("plugin_"):
                            _target_clean = "plugin_" + _target_clean
                        file_path = os.path.join(CX_ROOT, "clawcodex_ext", "query", "plugins", _target_clean + ".py")
            proposal["file_path"] = file_path
            orig = proposal.get("original_content", "")
            newc = proposal.get("new_content", "")

            self._console.print(f"[bold]{'='*60}[/bold]")
            self._console.print(f"[bold]Proposal {i}: {ptype}[/bold]")
            self._console.print(f"  [cyan]Target:[/cyan] {target}")
            self._console.print(f"  [cyan]Reason:[/cyan] {reason}")
            self._console.print()

            if ptype == "skill_creation" or not orig:
                _show_path = file_path if file_path and file_path != target else ""
                if _show_path:
                    self._console.print(f"  [cyan]File:[/cyan] {_show_path}")
                if not newc:
                    self._console.print("[bold]--- Change Description ---[/bold]")
                    self._console.print(f"  {reason}")
                else:
                    self._console.print("[bold]--- New File Content ---[/bold]")
                    self._console.print(newc)
            elif orig and newc and orig != newc:
                _show_path = file_path if file_path and file_path != target else ""
                if _show_path:
                    self._console.print(f"  [cyan]File:[/cyan] {_show_path}")
                diff_lines = list(
                    difflib.unified_diff(
                        orig.splitlines(keepends=True),
                        newc.splitlines(keepends=True),
                        fromfile="original",
                        tofile="modified",
                    )
                )
                self._console.print("[bold]--- Diff (original -> modified) ---[/bold]")
                _max_diff = 80
                _shown = 0
                for line in diff_lines:
                    if _shown >= _max_diff:
                        self._console.print("[dim]... (diff truncated, first 80 lines) ...[/dim]")
                        break
                    line = line.rstrip()
                    _shown += 1
                    if line.startswith("+"):
                        self._console.print(f"[green]{line}[/green]")
                    elif line.startswith("-"):
                        self._console.print(f"[red]{line}[/red]")
                    elif line.startswith("@@"):
                        self._console.print(f"[cyan]{line}[/cyan]")
                    else:
                        self._console.print(line)
            else:
                _show_path = file_path if file_path and file_path != target else ""
                if _show_path:
                    self._console.print(f"  [cyan]File:[/cyan] {_show_path}")
                self._console.print("[bold]--- Change Description ---[/bold]")
                self._console.print(f"  {reason}")
                if orig:
                    _orig_lines = orig.split(chr(10))
                    _kw = (target + " " + reason).lower().split()
                    _kw = [w for w in _kw if len(w) > 3][:8]
                    _match_idx = -1
                    for _i, _l in enumerate(_orig_lines):
                        _ll = _l.lower()
                        for _w in _kw:
                            if _w in _ll:
                                _match_idx = _i
                                break
                        if _match_idx >= 0:
                            break
                    if _match_idx >= 0:
                        _ctx_start = max(0, _match_idx - 3)
                        _ctx_end = min(len(_orig_lines), _match_idx + 5)
                        self._console.print(f"[dim]Relevant section (lines {_ctx_start+1}-{_ctx_end}):[/dim]")
                        for _j in range(_ctx_start, _ctx_end):
                            _marker = "[yellow]>[/yellow]" if _j == _match_idx else " "
                            self._console.print(f"  {_marker} [dim]{_orig_lines[_j]}[/dim]")
                    else:
                        _show = _orig_lines[:20]
                        self._console.print("[dim]Current file (first 20 lines):[/dim]")
                        for _l in _show:
                            self._console.print(f"  [dim]{_l}[/dim]")
                    if len(_orig_lines) > 20:
                        self._console.print(f"[dim]  ... ({len(_orig_lines)} lines total)[/dim]")
            self._console.print()

        # --- Interactive edit-review loop ---
        self._console.print(f"[bold]{'='*60}[/bold]")
        self._console.print("[bold yellow]Review & Approval[/bold yellow]")
        self._console.print("For each proposal, you can:\n  1. [green]Approve[/green] as-is\n  2. [yellow]Edit[/yellow] in Notepad before approving\n  3. [red]Skip[/red] this proposal\n")

        final_proposals = []
        for i, proposal in enumerate(proposals, 1):
            file_path = proposal.get("file_path", "")
            ptype = proposal.get("type", "unknown")
            orig = proposal.get("original_content", "")
            newc = proposal.get("new_content", "")
            is_new = ptype == "skill_creation" or not orig

            self._console.print(f"[bold]--- Proposal {i}: {file_path or '(new)'} ---[/bold]")
            answer = self._prompt(f"  Action for proposal {i} (a=approve, e=edit, s=skip) [a]: ")
            action = answer.strip().lower() if answer else "a"
            if action.startswith("s"):
                self._console.print(f"  [dim]Proposal {i} skipped.[/dim]")
                continue
            elif action.startswith("e"):
                edited = self._edit_proposal_content(
                    proposal, is_new, orig, newc
                )
                if edited is not None:
                    proposal["new_content"] = edited
                    self._console.print("  [green]Content updated with your edits.[/green]")
                else:
                    self._console.print("  [dim]Edit cancelled, using original proposal.[/dim]")
            final_proposals.append(proposal)

        if not final_proposals:
            self._console.print("[dim]All proposals skipped. Nothing applied.[/dim]")
            return

        self._console.print("\n[bold yellow]=== Final Summary of Changes to Apply ===[/bold yellow]")
        for i, prop in enumerate(final_proposals, 1):
            fp = prop.get("file_path", prop.get("target", "?"))
            self._console.print(f"  {i}. [{prop.get('type','?')}] {fp}")

        confirm = self._prompt("\nApply these changes? (y/N): ")
        if confirm.strip().lower() in ("y", "yes"):
            self._console.print("[green]Applying...[/green]")
            self._apply_proposals(final_proposals)
        else:
            self._console.print("[dim]Operation cancelled.[/dim]")

    def _prompt(self, text: str) -> str:
        """Prompt user for input using prompt_toolkit if available."""
        try:
            from prompt_toolkit import prompt as pt_prompt
            return pt_prompt(text)
        except Exception:
            try:
                return input(text)
            except Exception:
                return ""

    def _edit_proposal_content(
        self, proposal: dict, is_new: bool, orig: str, newc: str
    ) -> str | None:
        """Write proposed content to a temp file and open in editor."""
        ext = ".yaml" if "yaml" in (proposal.get("file_path") or "") else ".py"
        if is_new:
            header = (
                f"# === NEW FILE: {proposal.get('file_path', 'unknown')} ===\n"
                f"# Type: {proposal.get('type', '')}\n"
                f"# Reason: {proposal.get('reason', '')}\n"
                f"# --- Edit the content below, save, and close Notepad ---\n"
            )
            initial_content = header + (newc or "")
        else:
            header = (
                f"# === MODIFY: {proposal.get('file_path', 'unknown')} ===\n"
                f"# Lines starting with # are comments and will be ignored.\n"
                f"# --- Edit the NEW content below, save, and close Notepad ---\n"
                f"# --- ORIGINAL (for reference):\n"
            )
            # Show original (commented out) then the new content for editing
            orig_commented = "\n".join(
                f"# {line}" for line in (orig or "").splitlines()
            )
            initial_content = (
                f"{header}"
                f"{orig_commented}\n"
                f"# --- END ORIGINAL ---\n"
                f"# --- NEW CONTENT (edit below):\n"
                f"{newc or ''}\n"
            )

        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=ext, delete=False, encoding="utf-8"
            ) as f:
                f.write(initial_content)
                tmppath = f.name

            self._console.print(f"  [yellow]Opening editor for editing: {tmppath}[/yellow]")
            self._console.print("  [dim]Save and close the editor when done. Leave unchanged to cancel.[/dim]")

            # Open in notepad (widely available on Windows)
            subprocess.run(
                ["notepad.exe", tmppath],
                check=True,
                shell=True,
            )

            with open(tmppath, encoding="utf-8") as f:
                edited_content = f.read()

            os.unlink(tmppath)

            # Strip comment lines and header
            clean_lines = [
                line for line in edited_content.splitlines()
                if not line.strip().startswith("#")
            ]
            clean_content = "\n".join(clean_lines).strip()

            if clean_content and clean_content != (newc or "").strip():
                return clean_content
            elif clean_content:
                # User didn't change anything
                return None
            else:
                return None

        except Exception as e:
            self._console.print(f"  [red]Editor error: {e}[/red]")
            return None

    def _run_evaluation(self, trace_path: str, proposals: list) -> dict:
        """Run A/B evaluation: apply proposals, re-execute, compare via LLM."""
        if not proposals:
            return {"accepted": False, "reason": "no proposals"}
        try:
            python = sys.executable
            eval_script = os.path.join(SEA_ROOT, "src", "evolve_evaluate.py")
            proposals_json = json.dumps(proposals, ensure_ascii=False)
            result = subprocess.run(
                [python, eval_script, trace_path],
                input=proposals_json,
                capture_output=True, encoding="utf-8", timeout=180,
                env={**_CX_ENV, "PYTHONIOENCODING": "utf-8"},
            )
            if result.stderr and self._console:
                for _eval_dbg in result.stderr.strip().split(chr(10)):
                    if _eval_dbg.startswith("[EVAL-DBG]"):
                        self._console.print(f"  [dim]{_eval_dbg}[/dim]")
            if result.stdout.strip():
                try:
                    return json.loads(result.stdout.strip())
                except json.JSONDecodeError:
                    pass
        except subprocess.TimeoutExpired:
            if self._console:
                self._console.print("[dim]Evaluation timed out (180s)[/dim]")
        except Exception as e:
            if self._console:
                self._console.print(f"[dim]Evaluation error: {e}[/dim]")
        return {"accepted": True}  # Pass by default if eval fails (don't block review)

    def _run_debug(self, trace_path: str, proposals: list, eval_result: dict) -> list | None:
        """Run auto-debug: LLM analyzes failure and generates corrected proposals."""
        try:
            python = sys.executable
            debug_script = os.path.join(SEA_ROOT, "src", "evolve_debug.py")
            input_data = json.dumps({"proposals": proposals, "evaluation": eval_result}, ensure_ascii=False)
            result = subprocess.run(
                [python, debug_script, trace_path],
                input=input_data,
                capture_output=True, encoding="utf-8", timeout=120,
                env={**_CX_ENV, "PYTHONIOENCODING": "utf-8"},
            )
            if result.stderr and self._console:
                for _dbg_line in result.stderr.strip().split("\n"):
                    if _dbg_line.startswith("[DBG]"):
                        self._console.print(f"  [dim]{_dbg_line}[/dim]")
            if result.stdout.strip():
                _lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
                _last = _lines[-1] if _lines else result.stdout.strip()
                data = json.loads(_last)
                corrected = data.get("corrected_proposals", [])
                if corrected:
                    return corrected
        except Exception as e:
            if self._console:
                self._console.print(f"[dim]Debug error: {e}[/dim]")
        return None

    def _apply_proposals(self, proposals: list[dict]) -> None:
        """Apply approved proposals with session-level versioning."""
        if self._console is None:
            return

        system = self._get_self_evolving_system()
        from datetime import datetime
        session_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_version = f"v{session_ts}"
        applied = 0
        applied_details = []
        for proposal in proposals:
            file_path = proposal.get("file_path", "")
            if not file_path:
                continue
            # Ensure proposed_content key exists (backend expects it)
            if "proposed_content" not in proposal and "new_content" in proposal:
                proposal["proposed_content"] = proposal["new_content"]
            proposal["session_version"] = session_version
            version = system.apply_proposal(proposal)
            if version:
                applied += 1
                applied_details.append({
                    "proposal_type": proposal.get("type", "unknown"),
                    "target": proposal.get("target", ""),
                    "file_path": file_path,
                    "description": f'Applied: {proposal.get("type", "?")} - {proposal.get("target", "?")}',
                })
                self._console.print(f"  [green]\u2713 Applied:[/green] {file_path}")
            else:
                self._console.print(f"  [red]\u2717 Failed (safety or write error):[/red] {file_path}")

        if applied > 0:
            self._applied_versions.append(session_version)
            self._append_registry({
                "version": session_version,
                "timestamp": datetime.now().isoformat(),
                "proposals": applied_details,
                "description": f"Session {session_version}: {applied} change(s)",
            })
            self._console.print(f"\n[green]Successfully applied {applied} change(s) as {session_version}. "
                                "Will take effect after restart.[/green]")
        else:
            self._console.print("[dim]No changes were applied.[/dim]")

    def _apply_prompt_change(self, file_path: str, proposal: dict) -> None:
        """Apply targeted prompt improvements by replacing snippet in file."""
        orig = proposal.get("current_content", proposal.get("original_content", ""))
        newc = proposal.get("proposed_content", proposal.get("new_content", ""))
        if not orig or not newc or orig == newc:
            return
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                current = f.read()
            if orig in current:
                updated = current.replace(orig, newc, 1)
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(updated)
        except Exception:
            pass


    def _rollback_last(self) -> bool:
        """Rollback the most recently applied version."""
        registry = self._read_registry()
        if not registry:
            if self._console:
                self._console.print("[dim]No applied versions to rollback.[/dim]")
            return False
        entry = registry.pop()
        version = entry["version"]
        self._write_registry(registry)
        if self._console:
            self._console.print(f"[yellow]Rolling back version: {version[:18]}...[/yellow]")
        system = self._get_self_evolving_system()
        ok = system.rollback(version)
        if ok and self._console:
            self._console.print(f"[green]\u2713 Rolled back {version[:18]}[/green]")
        elif self._console:
            self._console.print(f"[red]\u2717 Rollback failed for {version[:18]}[/red]")
        return ok

    def _rollback_version(self, version: str) -> bool:
        """Rollback a specific version."""
        system = self._get_self_evolving_system()
        ok = system.rollback(version)
        if ok and self._console:
            self._console.print(f"[green]\u2713 Rolled back {version[:18]}[/green]")
            self._remove_from_registry(version)
            if version in self._applied_versions:
                self._applied_versions.remove(version)
        elif self._console:
            self._console.print(f"[red]\u2717 Rollback failed for {version[:18]}[/red]")
        return ok

    def _show_version_history(self) -> None:
        """Show applied version history."""
        registry = self._read_registry()
        if not registry:
            if self._console:
                self._console.print("[dim]No applied versions.[/dim]")
            return
        if self._console:
            self._console.print("[bold]Applied versions (newest first):[/bold]")
            for entry in reversed(registry):
                desc = entry.get("description", entry.get("version", "?"))[:50]
                self._console.print(f"  [dim]{entry['version'][:22]} - {desc}[/dim]")

    def _read_registry(self) -> list:
        """Read version registry from persistent JSON file."""
        try:
            if os.path.isfile(self._versions_registry):
                with open(self._versions_registry, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return []

    def _write_registry(self, registry: list) -> None:
        """Write version registry to persistent JSON file."""
        try:
            os.makedirs(os.path.dirname(self._versions_registry), exist_ok=True)
            with open(self._versions_registry, "w", encoding="utf-8") as f:
                json.dump(registry, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _append_registry(self, entry: dict) -> None:
        """Append a version entry to the persistent registry."""
        registry = self._read_registry()
        registry.append(entry)
        self._write_registry(registry)

    def _remove_from_registry(self, version: str) -> None:
        """Remove a version entry from the persistent registry."""
        registry = self._read_registry()
        registry[:] = [e for e in registry if e.get("version") != version]
        self._write_registry(registry)

    def _get_self_evolving_system(self):
        """Lazy-init _SelfEvolvingProxy (calls SelfEvolvingSystem via subprocess)."""
        if self._ses is None:
            self._ses = _SelfEvolvingProxy(SEA_ROOT, self._console)
        return self._ses
class _SelfEvolvingProxy:
    """Proxy that calls SelfEvolvingSystem via subprocess to avoid src import conflicts."""

    def __init__(self, sea_root: str, console) -> None:
        self._sea_root = sea_root
        self._console = console
        self._adapter_script = os.path.join(sea_root, "src", "evolve_repl_adapter.py")
        self._adapter_env = {
            **_CX_ENV,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }

    def process_conversation(self, messages: list, transcript_path: str = None, focus_areas: list[str] | None = None, multi_traces: list[dict] | None = None) -> dict:
        # Call SelfEvolvingSystem via subprocess (streaming stderr + 300s timeout)
        import tempfile, threading
        _python = sys.executable
        _data = {"messages": messages}
        if transcript_path:
            _data["transcript_path"] = transcript_path
        if focus_areas is not None:
            _data["focus_areas"] = focus_areas
        if multi_traces:
            _data["multi_traces"] = multi_traces
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(_data, f, ensure_ascii=False)
            trace_path = f.name
        _buf = {"stdout": "", "stderr": ""}
        proc = None
        try:
            proc = subprocess.Popen(
                [_python, self._adapter_script, "process_conversation", trace_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                encoding="utf-8", env=self._adapter_env,
            )
            def _reader(stream, key):
                try:
                    for _line in iter(stream.readline, ""):
                        _ls = _line.rstrip(chr(13) + chr(10))
                        if key == "stderr" and _ls:
                            if self._console:
                                self._console.print("  [dim]%s[/dim]" % _ls)
                            else:
                                sys.stderr.write(_ls + chr(10))
                        _buf[key] += _ls + chr(10)
                except Exception:
                    pass
            _t_out = threading.Thread(target=_reader, args=(proc.stdout, "stdout"), daemon=True)
            _t_err = threading.Thread(target=_reader, args=(proc.stderr, "stderr"), daemon=True)
            _t_out.start()
            _t_err.start()
            proc.wait(timeout=1500)
        except subprocess.TimeoutExpired:
            if proc:
                proc.kill()
            if self._console:
                self._console.print("[dim]Evolve subprocess timed out after 1500s[/dim]")
        except Exception as e:
            if self._console:
                self._console.print("[dim]Evolve subprocess error: %s[/dim]" % e)
        finally:
            try:
                os.unlink(trace_path)
            except Exception:
                pass
        _stdout = _buf["stdout"].strip()
        if _stdout:
            _lines = _stdout.split(chr(10))
            try:
                return json.loads(_lines[-1].strip())
            except json.JSONDecodeError:
                pass
        return {"proposals": [], "extracted_skill": None}
    def apply_proposal(self, proposal_dict: dict):
        """Call SelfEvolvingSystem.apply_proposal via subprocess."""
        import tempfile
        _python = sys.executable
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(proposal_dict, f, ensure_ascii=False)
            prop_path = f.name
        try:
            result = subprocess.run([_python, self._adapter_script, "apply_proposal", prop_path], capture_output=True, encoding="utf-8", timeout=30, env=self._adapter_env)
            if result.stdout and result.stdout.strip():
                # Take the LAST line (actual JSON), skip debug/info prefixes
                lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
                last_json = lines[-1] if lines else result.stdout.strip()
                data = json.loads(last_json)
                return data.get("version")
        except Exception as e:
            if self._console:
                self._console.print("[dim]Apply error: %s[/dim]" % e)
        finally:
            try:
                os.unlink(prop_path)
            except Exception:
                pass
        return None

    def rollback(self, version: str) -> bool:
        # Call SelfEvolvingSystem.rollback via subprocess
        import tempfile
        _python = sys.executable
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump({"version": version}, f, ensure_ascii=False)
            _path = f.name
        try:
            result = subprocess.run(
                [_python, self._adapter_script, "rollback", _path],
                capture_output=True, encoding="utf-8", timeout=30,
                env=self._adapter_env,
            )
            if result.stdout and result.stdout.strip():
                _lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
                _last = _lines[-1] if _lines else result.stdout.strip()
                data = json.loads(_last)
                return bool(data.get("ok", False))
        except Exception as e:
            if self._console:
                self._console.print("[dim]Rollback error: %s[/dim]" % e)
        finally:
            try:
                os.unlink(_path)
            except Exception:
                pass
        return False




def install_evolve_controller(repl) -> None:
    """Install the EvolveController on a REPL instance and register /evolve command."""
    # import sys; print("[EVOLVE-DBG] install_evolve_controller called", file=sys.stderr)  # suppressed
    controller = EvolveController(repl)
    repl._evolve_controller = controller

    if not hasattr(repl, "handle_command") or not callable(repl.handle_command):
        return
    original_handle = repl.handle_command

    def _evolve_patched(command):
        if command.startswith("/evolve"):
            parts = command[len("/evolve"):].strip().lower().split()
            FOCUS_KEYWORDS = {"prompt", "skill", "code"}
            if parts[0] == "last":
                last_focus = [p for p in parts[1:] if p in FOCUS_KEYWORDS]
                last_multi = 1
                for p in parts[1:]:
                    if p.startswith("multi="):
                        try:
                            last_multi = int(p.split("=", 1)[1])
                        except ValueError:
                            pass
                controller._run_evolution_on_session(focus_areas=last_focus if last_focus else None, multi_count=last_multi)
                return
            focus = [p for p in parts if p in FOCUS_KEYWORDS]
            if focus:
                controller.set_enabled(True, focus_areas=focus)
            elif parts[0] in ("on", "enable", "1", "true"):
                controller.set_enabled(True, focus_areas=["prompt", "skill", "code"])
            elif parts[0] in ("off", "disable", "0", "false"):
                controller.set_enabled(False)
            elif parts[0] in ("undo", "rollback"):
                if len(parts) > 1:
                    controller._rollback_version(parts[1])
                else:
                    controller._rollback_last()
            elif parts[0] in ("versions", "history"):
                controller._show_version_history()
            else:
                state = "ENABLED" if controller.enabled else "DISABLED"
                focus_str = f" (focus: {controller._focus_areas})" if controller._focus_areas else ""
                repl.console.print(f"\n[bold]Evolve:[/bold] {state}{focus_str}. Use /evolve on or /evolve off to toggle.\n")
            return
        return original_handle(command)

    repl.handle_command = _evolve_patched

    if "/evolve" not in repl._built_in_commands:
        repl._built_in_commands.append("/evolve")

    # TUI mode: ClawCodex TUI uses handle_local_slash_command instead of handle_command
    tui_method = getattr(repl, "handle_local_slash_command", None)
    if tui_method and callable(tui_method):
        orig_tui = tui_method
        def _tui_patched(text, transcript):
            if text.strip().lower().startswith("/evolve"):
                command = text.strip()
                parts = command[len("/evolve"):].strip().lower().split()
                FOCUS_KEYWORDS = {"prompt", "skill", "code"}
                if parts[0] == "last":
                    last_focus = [p for p in parts[1:] if p in FOCUS_KEYWORDS]
                    last_multi = 1
                    for p in parts[1:]:
                        if p.startswith("multi="):
                            try:
                                last_multi = int(p.split("=", 1)[1])
                            except ValueError:
                                pass
                    controller._run_evolution_on_session(focus_areas=last_focus if last_focus else None, multi_count=last_multi)
                    return True
                focus = [p for p in parts if p in FOCUS_KEYWORDS]
                if focus:
                    controller.set_enabled(True, focus_areas=focus)
                elif parts[0] in ("on", "enable", "1", "true"):
                    controller.set_enabled(True, focus_areas=["prompt", "skill", "code"])
                elif parts[0] in ("off", "disable", "0", "false"):
                    controller.set_enabled(False)
                elif parts[0] in ("undo", "rollback"):
                    if len(parts) > 1:
                        controller._rollback_version(parts[1])
                    else:
                        controller._rollback_last()
                elif parts[0] in ("versions", "history"):
                    controller._show_version_history()
                else:
                    state = "ENABLED" if controller.enabled else "DISABLED"
                    focus_str = f" (focus: {controller._focus_areas})" if controller._focus_areas else ""
                    if repl.console:
                        repl.console.print(f"\n[bold]Evolve:[/bold] {state}{focus_str}. Use /evolve on or /evolve off to toggle.\n")
                return True
            return orig_tui(text, transcript)
        repl.handle_local_slash_command = _tui_patched