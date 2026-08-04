"""Standalone evolution window — runs the full /evolve flow in its own terminal.
Usage: python evolve_standalone.py --trace <path> [--focus prompt,skill,code]
"""
from __future__ import annotations
import json, os, subprocess, sys, threading, difflib, argparse, time, tempfile
from datetime import datetime

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
    ptype = (proposal.get("type") or "").lower()
    if "skill" in focus_areas and any(kw in ptype for kw in ["skill"]): return True
    if "prompt" in focus_areas and any(kw in ptype for kw in ["prompt","config"]): return True
    if "code" in focus_areas and any(kw in ptype for kw in ["plugin","workflow","loop","code_modification"]): return True
    return False

def _show_proposal_categories(proposals: list, extracted_skill=None):
#     cats = {"prompt_optimization","config_adjustment":"prompt","skill_addition","skill_modification":"skill","skill_creation":"new_skill","plugin_generation","workflow_optimization","loop_parameter_adjustment":"code"} if False else {}
    pn = sum(1 for p in proposals if p.get("type") in ("prompt_optimization","config_adjustment"))
    sn = sum(1 for p in proposals if p.get("type") in ("skill_addition","skill_modification"))
    scn = sum(1 for p in proposals if p.get("type") == "skill_creation") + (1 if extracted_skill else 0)
    cn = sum(1 for p in proposals if p.get("type") in ("plugin_generation","workflow_optimization","loop_parameter_adjustment","code_modification"))
    print(f"  Prompt proposals: {pn}")
    print(f"  Skill proposals: {sn}")
    print(f"  Skill creation: {scn}")
    print(f"  Code proposals: {cn}")
    print()

def _run_evaluation(trace_path: str, proposals: list) -> dict:
    if not proposals: return {"accepted":False,"reason":"no proposals"}
    try:
        r = subprocess.run([sys.executable, os.path.join(SEA_ROOT,"src","evolve_evaluate.py"), trace_path],
            input=json.dumps(proposals,ensure_ascii=False), capture_output=True, encoding="utf-8", timeout=360,
            env={**_CX_ENV,"PYTHONIOENCODING":"utf-8"})
        if r.stderr:
            for l in r.stderr.strip().split("\n"):
                _l_stripped = l.strip()
                if _l_stripped:
                    print(f"  {l}")
        if r.stdout.strip():
            try: return json.loads(r.stdout.strip())
            except json.JSONDecodeError: pass
    except subprocess.TimeoutExpired: print("  Evaluation timed out (360s)")
    except Exception as e: print(f"  Evaluation error: {e}")
    return {"accepted":True}

def _run_debug(trace_path: str, proposals: list, eval_result: dict):
    try:
        r = subprocess.run([sys.executable, os.path.join(SEA_ROOT,"src","evolve_debug.py"), trace_path],
            input=json.dumps({"proposals":proposals,"evaluation":eval_result},ensure_ascii=False),
            capture_output=True, encoding="utf-8", timeout=300,
            env={**_CX_ENV,"PYTHONIOENCODING":"utf-8"})
        if r.stderr:
            for l in r.stderr.strip().split("\n"):
                _ls = l.strip()
                if _ls:
                    print(f"  {l}")
        if r.stdout.strip():
            lines = [l.strip() for l in r.stdout.strip().split("\n") if l.strip()]
            data = json.loads(lines[-1])
            corr = data.get("corrected_proposals")
            if corr: print(f"  Debug corrected {len(corr)} proposal(s)"); return corr
    except: pass
    return None

def _gather_file_path(proposal: dict) -> str:
    ptype, target = proposal.get("type",""), proposal.get("target","")
    fp = proposal.get("file_path","")
    if fp and not os.path.isabs(fp):
        c = os.path.join(os.path.dirname(SEA_ROOT), fp)
        if os.path.isfile(c): fp = os.path.abspath(c)
    if not fp or fp == target:
        if ptype in ("skill_addition","skill_modification","skill_creation"):
            md = os.path.join(CX_ROOT,"clawcodex_ext","agent","agents",target+".md")
            if os.path.isfile(md): fp = md
            else: fp = os.path.join(os.path.expanduser("~/.clawcodex/skills"), target)
        elif ptype in ("prompt_optimization","config_adjustment"):
            fp = os.path.join(CX_ROOT,"clawcodex_ext","context_system","prompt_assembly.py")
        elif ptype == "plugin_generation":
            tn = target if target.startswith("plugin_") else "plugin_"+target
            fp = os.path.join(CX_ROOT,"clawcodex_ext","query","plugins",tn+".py")
    return fp

def _apply_proposals(proposals: list, proxy) -> int:
    sv = datetime.now().strftime("v%Y%m%d_%H%M%S")
    applied = 0
    for p in proposals:
        fp = p.get("file_path","")
        if not fp: continue
        if "proposed_content" not in p and "new_content" in p:
            p["proposed_content"] = p["new_content"]
        p["session_version"] = sv
        if proxy.apply_proposal(p):
            applied += 1; print(f"  [OK] Applied: {fp}")
        else: print(f"  [FAIL] {fp}")
    return applied


def _prompt(text: str) -> str:
    """Prompt user for input."""
    try:
        from prompt_toolkit import prompt as pt_prompt
        return pt_prompt(text)
    except Exception:
        try:
            return input(text)
        except Exception:
            return ""


def _edit_proposal_content(proposal: dict, is_new: bool, orig: str, newc: str) -> str | None:
    """Open Notepad for editing proposal content."""
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
        orig_commented = "\n".join(f"# {line}" for line in (orig or "").splitlines())
        initial_content = (
            f"{header}"
            f"{orig_commented}\n"
            f"# --- END ORIGINAL ---\n"
            f"# --- NEW CONTENT (edit below):\n"
            f"{newc or ''}\n"
        )

    tmppath = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=ext, delete=False, encoding="utf-8"
        ) as f:
            f.write(initial_content)
            tmppath = f.name

        print(f"  Opening Notepad for editing: {tmppath}")
        print("  Save and close Notepad when done. Leave unchanged to cancel.")
        subprocess.run(["notepad.exe", tmppath], check=True, shell=True)

        with open(tmppath, encoding="utf-8") as f:
            edited_content = f.read()

        clean_lines = [
            line for line in edited_content.splitlines()
            if not line.strip().startswith("#")
        ]
        clean_content = "\n".join(clean_lines).strip()

        if clean_content and clean_content != (newc or "").strip():
            return clean_content
        return None
    except Exception as e:
        print(f"  Editor error: {e}")
        return None
    finally:
        if tmppath:
            try:
                os.unlink(tmppath)
            except Exception:
                pass


def main():
    try:
        _main_impl()
    except Exception:
        import traceback
        traceback.print_exc()
        input("\n[ERROR] Press Enter to close...")

def _main_impl():
    p = argparse.ArgumentParser()
    p.add_argument("--trace", required=True)
    p.add_argument("--focus", default="")
    p.add_argument("--multi", type=int, default=0, help="Number of past traces to include for cross-trace analysis")
    args = p.parse_args()
    focus = [a.strip() for a in args.focus.split(",") if a.strip()] or None

    print("="*60)
    print("  Self-Evolving Agent — Evolution Analysis")
    print("="*60)
    if not os.path.isfile(args.trace):
        print(f"[ERROR] Trace file not found: {args.trace}"); input("\nPress Enter to close..."); return
    with open(args.trace,"r",encoding="utf-8") as f: td = json.load(f)
    messages, tp = td.get("messages",[]), td.get("transcript_path")
    if not messages: print("No conversation data."); input("\nPress Enter to close..."); return
    if focus: print(f"  Focus: {', '.join(focus)}")

    # Load past traces for cross-trace analysis (--multi N)
    # Prefer pre-embedded multi_traces from the caller (already sorted by mtime)
    multi_traces = td.get("multi_traces", [])
    if not multi_traces and args.multi > 0:
        sessions_dirs = [
            os.path.expanduser("~/.clawcodex/sessions"),
            os.path.expanduser("~/.claude/sessions"),
        ]
        seen_sessions = set()
        # Collect (sid, tp, mtime) and sort by mtime (newest first)
        all_candidates = []
        for sd in sessions_dirs:
            if os.path.isdir(sd):
                for sid in os.listdir(sd):
                    tp2 = os.path.join(sd, sid, "transcript.jsonl")
                    if os.path.isfile(tp2):
                        try:
                            mt = os.path.getmtime(os.path.join(sd, sid))
                        except OSError:
                            mt = 0
                        all_candidates.append((sid, tp2, mt, sd))
        all_candidates.sort(key=lambda x: x[2], reverse=True)
        for sid, tp2, _mt, _sd in all_candidates:
            if sid in seen_sessions:
                continue
            seen_sessions.add(sid)
            try:
                msgs = []
                with open(tp2, "r", encoding="utf-8") as f2:
                    for line in f2:
                        line = line.strip()
                        if not line:
                            continue
                        entry = json.loads(line)
                        if entry.get("type") in ("session_init", "session_snapshot", "cost_block"):
                            continue
                        msgs.append(entry)
                if msgs:
                    multi_traces.append({"messages": msgs})
                    if len(multi_traces) >= args.multi:
                        break
            except Exception:
                pass
        print(f"  Past traces loaded: {len(multi_traces)}")

    print("\n  [*] Analyzing session (LLM analysis running)..."); sys.stdout.flush()
    _t0 = time.time()
    from evolve_hook import _SelfEvolvingProxy
    proxy = _SelfEvolvingProxy(SEA_ROOT, console=None)
    result = proxy.process_conversation(messages, transcript_path=tp, focus_areas=focus, multi_traces=multi_traces or None)
    _elapsed = time.time() - _t0
    print(f"  [*] Analysis complete ({_elapsed:.1f}s)")
    proposals = result.get("proposals",[])
    extracted = result.get("extracted_skill")
    if extracted: print(f"\n  [NEW SKILL] {extracted.get('name')}")
    if not proposals: print("\n  No optimization proposals."); input("\nPress Enter to close..."); return

    print(); print("  --- Proposals ---"); _show_proposal_categories(proposals, extracted)
    if focus: proposals = [p for p in proposals if _proposal_matches_focus(p, focus)]
    if not proposals: print("  No matching proposals."); input("\nPress Enter to close..."); return

    print("  [*] Running evaluation..."); sys.stdout.flush()
    ev = _run_evaluation(args.trace, proposals)
    imp_score = ev.get("improvement_score", "?")
    orig_score = ev.get("original_score", "?")
    ev_reason = ev.get("reason", "")
    accepted = ev.get("accepted", False)
    print(f"  Evaluation: {'ACCEPTED' if accepted else 'REJECTED'}  (improvement={imp_score}, original={orig_score})")
    if ev_reason:
        print(f"  Reason: {ev_reason}")
    if not accepted:
        print("  [*] Running debug..."); sys.stdout.flush()
        dc = _run_debug(args.trace, proposals, ev)
        if dc:
            print(f"  Debug corrected {len(dc)} proposal(s)")
            print("  [*] Re-evaluating..."); sys.stdout.flush()
            ev2 = _run_evaluation(args.trace, dc)
            imp_score2 = ev2.get("improvement_score", "?")
            orig_score2 = ev2.get("original_score", "?")
            ev2_reason = ev2.get("reason", "")
            accepted2 = ev2.get("accepted", False)
            print(f"  Re-evaluation: {'ACCEPTED' if accepted2 else 'REJECTED'}  (improvement={imp_score2}, original={orig_score2})")
            if ev2_reason:
                print(f"  Reason: {ev2_reason}")
            if accepted2: proposals = dc
            else: print("  Debug also failed."); proposals = []
        else: print("  Debug could not fix."); proposals = []
    if not proposals: print("\n  No viable optimization."); input("\nPress Enter to close..."); return

    for pr in proposals:
        pr["file_path"] = _gather_file_path(pr)

    print()
    print("=" * 60)
    print("=== Evolution Analysis Complete ===")
    print()

    _workspace_root = os.path.dirname(SEA_ROOT)
    for i, proposal in enumerate(proposals, 1):
        ptype = proposal.get("type", "unknown")
        target = proposal.get("target", "unknown")
        reason = proposal.get("reason", "")
        file_path = proposal.get("file_path", "")
        if file_path and not os.path.isabs(file_path):
            _candidate = os.path.join(_workspace_root, file_path)
            if os.path.isfile(_candidate):
                file_path = os.path.abspath(_candidate)
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

        print("=" * 60)
        print(f"Proposal {i}: {ptype}")
        print(f"  Target: {target}")
        print(f"  Reason: {reason}")
        print()

        if ptype == "skill_creation" or not orig:
            _show_path = file_path if file_path and file_path != target else ""
            if _show_path:
                print(f"  File: {_show_path}")
            if not newc:
                print("--- Change Description ---")
                print(f"  {reason}")
            else:
                print("--- New File Content ---")
                print(newc)
        elif orig and newc and orig != newc:
            _show_path = file_path if file_path and file_path != target else ""
            if _show_path:
                print(f"  File: {_show_path}")
            diff_lines = list(
                difflib.unified_diff(
                    orig.splitlines(keepends=True),
                    newc.splitlines(keepends=True),
                    fromfile="original",
                    tofile="modified",
                )
            )
            print("--- Diff (original -> modified) ---")
            _max_diff = 80
            _shown = 0
            for line in diff_lines:
                if _shown >= _max_diff:
                    print("... (diff truncated, first 80 lines) ...")
                    break
                line = line.rstrip()
                _shown += 1
                if line.startswith("+"):
                    print(f"[32m{line}[0m")
                elif line.startswith("-"):
                    print(f"[31m{line}[0m")
                elif line.startswith("@@"):
                    print(f"[36m{line}[0m")
                else:
                    print(line)
        else:
            _show_path = file_path if file_path and file_path != target else ""
            if _show_path:
                print(f"  File: {_show_path}")
            print("--- Change Description ---")
            print(f"  {reason}")
            if orig:
                _orig_lines = orig.split("\n")
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
                    print(f"Relevant section (lines {_ctx_start+1}-{_ctx_end}):")
                    for _j in range(_ctx_start, _ctx_end):
                        _marker = ">" if _j == _match_idx else " "
                        print(f"  {_marker} {_orig_lines[_j]}")
                else:
                    _show = _orig_lines[:20]
                    print("Current file (first 20 lines):")
                    for _l in _show:
                        print(f"  {_l}")
                if len(_orig_lines) > 20:
                    print(f"  ... ({len(_orig_lines)} lines total)")
        print()

    # --- Interactive edit-review loop ---
    print("=" * 60)
    print("Review & Approval")
    print("For each proposal, you can:")
    print("  1. Approve as-is")
    print("  2. Edit in Notepad before approving")
    print("  3. Skip this proposal")
    print()

    final_proposals = []
    for i, proposal in enumerate(proposals, 1):
        file_path = proposal.get("file_path", "")
        ptype = proposal.get("type", "unknown")
        orig = proposal.get("original_content", "")
        newc = proposal.get("new_content", "")
        is_new = ptype == "skill_creation" or not orig

        print(f"--- Proposal {i}: {file_path or '(new)'} ---")
        answer = _prompt(f"  Action for proposal {i} (a=approve, e=edit, s=skip) [a]: ")
        action = answer.strip().lower() if answer else "a"
        if action.startswith("s"):
            print(f"  Proposal {i} skipped.")
            continue
        elif action.startswith("e"):
            edited = _edit_proposal_content(
                proposal, is_new, orig, newc
            )
            if edited is not None:
                proposal["new_content"] = edited
                print("  Content updated with your edits.")
            else:
                print("  Edit cancelled, using original proposal.")
        final_proposals.append(proposal)

    if not final_proposals:
        print("All proposals skipped. Nothing applied.")
        input("\nPress Enter to close...")
        return

    print()
    print("=== Final Summary of Changes to Apply ===")
    for i, prop in enumerate(final_proposals, 1):
        fp = prop.get("file_path", prop.get("target", "?"))
        print(f"  {i}. [{prop.get('type','?')}] {fp}")

    confirm = _prompt("\nApply these changes? (y/N): ")
    if confirm.strip().lower() in ("y", "yes"):
        print("Applying...")
        n = _apply_proposals(final_proposals, proxy)
        print(f"\nApplied {n}/{len(final_proposals)}.")
    else:
        print("Operation cancelled.")
    # Cleanup temp copy (original session data untouched)
    try:
        import os as _os
        _os.unlink(args.trace)
    except Exception:
        pass
    input("\n  Press Enter to close this window...")

if __name__ == "__main__":
    main()
