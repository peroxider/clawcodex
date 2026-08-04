"""A/B evaluation: apply proposals, re-execute, compare via LLM.

Called as subprocess from evolve_hook.py.
Inputs: trace_path (conversation JSON), proposals (via stdin JSON)
Outputs: {"accepted": bool, "reason": "...", "scores": {...}}
"""

import json, os, subprocess, sys, tempfile

CX_ROOT = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", ".."
))
SEA_ROOT = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".."
))




def _gather_file_path(proposal: dict) -> str:
    """Resolve proposal target to an absolute file path."""
    ptype = proposal.get("type", "")
    target = proposal.get("target", "")
    fp = proposal.get("file_path", "")
    if fp and not os.path.isabs(fp):
        cx = os.path.join(os.path.dirname(SEA_ROOT), fp)
        if os.path.isfile(cx):
            fp = os.path.abspath(cx)
    if not fp or fp == target:
        if ptype in ("skill_addition", "skill_modification", "skill_creation"):
            md = os.path.join(CX_ROOT, "clawcodex_ext", "agent", "agents", target + ".md")
            if os.path.isfile(md):
                fp = md
            else:
                fp = os.path.join(os.path.expanduser("~/.clawcodex/skills"), target)
        elif ptype in ("prompt_optimization", "config_adjustment"):
            fp = os.path.join(CX_ROOT, "clawcodex_ext", "context_system", "prompt_assembly.py")
        elif ptype == "plugin_generation":
            tn = target if target.startswith("plugin_") else "plugin_" + target
            fp = os.path.join(CX_ROOT, "clawcodex_ext", "query", "plugins", tn + ".py")
    return fp

def _build_runner_script(prompt_text: str, append_prompt: str, max_turns: int = 20) -> str:
    """Build a Python script to run ClawCodex headless."""
    cx_esc = json.dumps(CX_ROOT)
    prompt_esc = json.dumps(prompt_text)
    append_esc = json.dumps(append_prompt)
    return (
        "import sys\n"
        f"sys.path.insert(0, {cx_esc})\n"
        "from clawcodex_ext.entrypoints.headless import HeadlessOptions, run_headless\n"
        f"options = HeadlessOptions(\n"
        f"    prompt={prompt_esc},\n"
        f"    output_format='json',\n"
        f"    max_turns={max_turns},\n"
        f"    skip_permissions=True,\n"
        f"    permission_mode='bypassPermissions',\n"
        f"    is_bypass_permissions_mode_available=True,\n"
        f"    append_system_prompt={append_esc},\n"
        ")\n"
        "exit_code = run_headless(options)\n"
        "sys.exit(exit_code)\n"
    )


def _run_clawcodex(prompt_text: str, append_prompt: str) -> dict:
    """Run ClawCodex headless and return dict with stdout, stderr, rc."""
    api_key = os.environ.get("CX_API_KEY", ""); base_url = os.environ.get("CX_BASE_URL", ""); model = os.environ.get("CX_MODEL", "")
    script = _build_runner_script(prompt_text, append_prompt)
    env = os.environ.copy()
    _pp = os.environ.get("PYTHONPATH", "")
    env["PYTHONPATH"] = CX_ROOT + os.pathsep + _pp if _pp else CX_ROOT
    env["PYTHONIOENCODING"] = "utf-8"
    provider = "deepseek" if "deepseek" in (base_url or "").lower() else "openai"
    pfx = provider.upper()
    env[f"{pfx}_API_KEY"] = api_key
    env[f"{pfx}_BASE_URL"] = base_url
    env[f"{pfx}_MODEL"] = model
    env["CX_PROVIDER"] = provider
    env["CX_MODEL"] = model
    import tempfile as _tf
    _tmp = os.path.join(_tf.gettempdir(), "_claw_headless.py")
    with open(_tmp, "w", encoding="utf-8") as _f:
        _f.write("# -*- coding: utf-8 -*-\n")
        _f.write(script)
    result = subprocess.run(
        [sys.executable, _tmp],
        capture_output=True, timeout=300, encoding="utf-8",
        env=env, cwd=CX_ROOT,
    )
    try:
        os.unlink(_tmp)
    except:
        pass
    output = result.stdout or ""
    if result.returncode != 0:
        sys.stderr.write("=== HEADLESS STDERR START ===\n")
        sys.stderr.write((result.stderr or "")[:2000])
        sys.stderr.write("\n=== HEADLESS STDERR END ===\n")
    return {"stdout": output[:3000], "stderr": (result.stderr or "")[:1000], "rc": result.returncode}



def _snapshot_files(proposals: list) -> dict:
    """Read original file contents before applying proposals.
    Returns dict {file_path: original_content|None}."""
    snapshots = {}
    for proposal in proposals:
        fp = _gather_file_path(proposal)
        sys.stderr.write("[EVAL-DBG] resolve file_path -> %s\n" % fp)
        if not fp:
            continue
        proposal["file_path"] = fp
        try:
            if os.path.isfile(fp):
                with open(fp, encoding="utf-8") as f:
                    snapshots[fp] = f.read()
            else:
                snapshots[fp] = None
        except Exception as e:
            sys.stderr.write(f"[EVAL-DBG] snapshot failed for {fp}: {e}\n")
            snapshots[fp] = "_SNAPSHOT_ERROR_"
    sys.stderr.write(f"[EVAL-DBG] Snapshot {len(snapshots)} file(s)\n")
    return snapshots


def _restore_files(snapshots: dict) -> None:
    """Restore files from snapshot dict."""
    restored = 0
    for fp, content in snapshots.items():
        try:
            if content is None:
                if os.path.isfile(fp):
                    os.unlink(fp)
                    sys.stderr.write(f"[EVAL-DBG] removed new file: {fp}\n")
            elif content == "_SNAPSHOT_ERROR_":
                continue
            else:
                os.makedirs(os.path.dirname(fp), exist_ok=True)
                with open(fp, "w", encoding="utf-8") as f:
                    f.write(content)
                restored += 1
        except Exception as e:
            sys.stderr.write(f"[EVAL-DBG] restore failed for {fp}: {e}\n")
    sys.stderr.write(f"[EVAL-DBG] Restored {restored} file(s)\n")


def _surgical_apply(proposal: dict) -> bool:
    """Apply a surgical modification to a file.
    Uses same strategy as SelfEvolvingSystem.apply_proposal:
      1. Exact match: str.replace original with new
      2. Fuzzy match: difflib find similar block >0.6 ratio
      3. Full file write (fallback)
    Returns True if file was modified, False if needs append_prompt fallback."""
    import difflib
    fp = proposal.get("file_path", "")
    if not fp:
        return False
    orig = proposal.get("original_content", "") or ""
    newc = proposal.get("new_content") or proposal.get("proposed_content", "")
    if not newc:
        return False

    # New file creation: full write
    if not os.path.isfile(fp):
        try:
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            with open(fp, "w", encoding="utf-8") as f:
                f.write(newc)
            sys.stderr.write(f"[EVAL-DBG] created new file: {fp}\n")
            return True
        except Exception as e:
            sys.stderr.write(f"[EVAL-DBG] create failed for {fp}: {e}\n")
            return False

    # Read file from disk
    try:
        with open(fp, "r", encoding="utf-8") as f:
            disk_content = f.read()
    except Exception as e:
        sys.stderr.write(f"[EVAL-DBG] read failed for {fp}: {e}\n")
        return False

    final_content = None

    # Strategy 0: AST-based replace for prompt_assembly.py
    if "prompt_assembly" in fp:
        try:
            import sys as _seasys; _seasrc=__import__('os').path.normpath(__import__('os').path.join(__import__('os').path.dirname(__file__))); _seasys.path.insert(0,_seasrc); from utils import replace_prompt_section_in_file
            section_id = proposal.get("target", "")
            if section_id and replace_prompt_section_in_file(newc, section_id, fp):
                sys.stderr.write("[EVAL-DBG] AST replace OK for %s section %s\n" % (fp, section_id))
                return True
        except Exception as e:
            sys.stderr.write("[EVAL-DBG] AST replace failed for %s: %s\n" % (fp, e))
        return False  # Don't fall through to text-match strategies

    # Strategy 1: Exact match
    if orig and orig in disk_content:
        sys.stderr.write("[EVAL-DBG] exact match FOUND in %s (orig=%d chars)\n" % (fp, len(orig)))
        final_content = disk_content.replace(orig, newc, 1)
        if final_content == disk_content:
            final_content = None

    # Strategy 2: Fuzzy match (original not found)
    if final_content is None and orig:
        sys.stderr.write("[EVAL-DBG] exact match NOT found in %s, trying fuzzy match (orig=%d chars)\n" % (fp, len(orig)))
        lines = disk_content.splitlines(True)
        old_lines = orig.splitlines()
        best_match = None
        best_ratio = 0.0
        for i in range(len(lines) - len(old_lines) + 1):
            chunk = ''.join(lines[i:i+len(old_lines)])
            ratio = difflib.SequenceMatcher(None, chunk, orig).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = i
        sys.stderr.write("[EVAL-DBG] fuzzy best_ratio=%.3f for %s\n" % (best_ratio, fp))
        if best_match is not None and best_ratio > 0.6:
            before = ''.join(lines[:best_match])
            after = ''.join(lines[best_match+len(old_lines):])
            final_content = before + newc + after

    # Strategy 3: Full file write (heuristic: newc > 50% of file size)
    if final_content is None and len(newc) > len(disk_content) * 0.5:
        sys.stderr.write("[EVAL-DBG] strategy 3 (full file write) for %s\n" % fp)
        final_content = newc

    if final_content is not None:
        try:
            with open(fp, "w", encoding="utf-8") as f:
                f.write(final_content)
            sys.stderr.write(f"[EVAL-DBG] surgically applied: {fp}\n")
            return True
        except Exception as e:
            sys.stderr.write(f"[EVAL-DBG] write failed for {fp}: {e}\n")
            return False

    sys.stderr.write(f"[EVAL-DBG] ALL strategies failed for {fp}, falling back to text injection\n")
    return False


def _apply_proposals_to_files(proposals: list) -> list:
    """Surgically apply proposals. Returns list of proposals that were NOT applied (need text injection)."""
    text_only = []
    applied_count = 0
    for proposal in proposals:
        if not _surgical_apply(proposal):
            text_only.append(proposal)
        else:
            applied_count += 1
    sys.stderr.write(f"[EVAL-DBG] Surgically applied {applied_count}/{len(proposals)}, "
                     f"{len(text_only)} fall back to text injection\n")
    return text_only


def _build_append_prompt(proposals: list) -> str:
    """Convert proposals into an append_system_prompt string (fallback for text-only proposals)."""
    if not proposals:
        return ""
    parts = ["## Instructions from Self-Evolution Optimization\n"]
    for p in proposals:
        ptype = p.get("type", "optimization")
        target = p.get("target", "unknown")
        reason = p.get("reason", "")[:200]
        parts.append(f"- [{ptype}] {target}: {reason}")
    return "\n".join(parts)


def _call_llm(prompt: str) -> str | None:
    """Call DeepSeek LLM."""
    api_key = os.environ.get("CX_API_KEY", ""); base_url = os.environ.get("CX_BASE_URL", ""); model = os.environ.get("CX_MODEL", "")
    script = (
        "import sys\n"
        "from openai import OpenAI\n"
        f"client = OpenAI(api_key={json.dumps(api_key)}, base_url={json.dumps(base_url)}, timeout=60)\n"
        "content = " + json.dumps(prompt) + "\n"
        "resp = client.chat.completions.create(\n"
        f"  model={json.dumps(model)},\n"
        "  messages=[{'role': 'user', 'content': content}],\n"
        "  max_tokens=2048, temperature=0,\n"
        ")\n"
        'print(resp.choices[0].message.content or "")\n'
    )
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(script)
            tmp = f.name
        result = subprocess.run(
            [sys.executable, tmp],
            capture_output=True, timeout=120, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "CX_API_KEY": os.environ.get("CX_API_KEY", ""), "CX_BASE_URL": os.environ.get("CX_BASE_URL", ""), "CX_MODEL": os.environ.get("CX_MODEL", "")},
        )
        if result.returncode != 0:
            _err = (result.stderr or "").strip()[:100]
            sys.stderr.write(f"[EVAL-DBG] LLM subprocess rc={result.returncode}: {_err}\n")
            sys.stderr.flush()
        return (result.stdout or "").strip()
    except Exception as exc:
        sys.stderr.write(f"[EVAL-DBG] _call_llm exception: {exc}\n")
        return ""
    finally:
        if tmp and os.path.isfile(tmp):
            try: os.unlink(tmp)
            except: pass


def _evaluate_proposals(conv_text: str, old_output: str, new_output: str, proposals_text: str) -> dict:
    # Debug: log input sizes so we can diagnose 0-score issues
    _sz = f"[EVAL-DBG] inputs: conv={len(conv_text)}, old={len(old_output)}, new={len(new_output)}, props={len(proposals_text)}"
    sys.stderr.write(_sz + "\n")
    """Use LLM to evaluate if proposals improve the output."""
    prompt = f"""You are an AI agent optimization evaluator. Given a conversation, the original agent response, and a new response generated with proposed optimizations applied, determine if the optimization is an improvement.

## Original Conversation Context
{conv_text[:2000]}

## Original Response (before optimization)
{old_output[:2000]}

## New Response (after optimization)
{new_output[:2000]}

## Proposed Optimization
{proposals_text[:1000]}

## Evaluation
Does the new response show measurable improvement over the original? Consider:
1. Quality: Is the response more accurate, helpful, and complete?
2. Efficiency: Is the approach more focused and effective?
3. Correctness: Are there fewer errors or misunderstandings?

## Output Format (valid JSON only)
{{"accepted": true, "reason": "brief explanation", "improvement_score": 7, "original_score": 5}}

- accepted: true if the new response is clearly better
- improvement_score: 1-10 (how good the new response is)
- original_score: 1-10 (how good the original response was)
- reason: 1-2 sentence explanation

Respond ONLY with valid JSON, no other text."""
    
    raw = _call_llm(prompt)
    if not raw:
        return {"accepted": False, "reason": "LLM evaluation failed"}
    
    sys.stderr.write(f"[EVAL-DBG] raw_llm_response length={len(raw)}\n")
    sys.stderr.write(f"[EVAL-DBG] raw_llm_first_200={repr(raw[:200])}\n")
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        sys.stderr.write("[EVAL-DBG] no JSON found in raw response\n")
        return {"accepted": False, "reason": "Could not parse evaluation"}
    
    try:
        data = json.loads(raw[start:end+1])
        _ac = data.get("accepted", False)
        _im = data.get("improvement_score", 0)
        _or = data.get("original_score", 0)
        _has_im = "improvement_score" in data
        _has_or = "original_score" in data
        sys.stderr.write(f"[EVAL-DBG] parsed: accepted={_ac}, im_score_in_data={_has_im}, orig_score_in_data={_has_or}, improvement_score={_im}, original_score={_or}\n")
        return {
            "accepted": _ac,
            "reason": data.get("reason", ""),
            "improvement_score": _im,
            "original_score": _or,
        }
    except json.JSONDecodeError:
        return {"accepted": False, "reason": "Invalid JSON from evaluator"}


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"accepted": False, "reason": "no trace path"}))
        return 1
    
    trace_path = sys.argv[1]
    if not os.path.isfile(trace_path):
        print(json.dumps({"accepted": False, "reason": "trace not found"}))
        return 1
    
    with open(trace_path, encoding="utf-8") as f:
        trace = json.load(f)
    
    messages = trace.get("messages", [])
    if not messages:
        print(json.dumps({"accepted": False, "reason": "empty trace"}))
        return 1
    
    # Read proposals from stdin (passed as JSON line)
    proposals = []
    try:
        raw_proposals = sys.stdin.read().strip()
        if raw_proposals:
            data = json.loads(raw_proposals)
            proposals = data if isinstance(data, list) else data.get("proposals", data)
    except Exception:
        pass
    
    if not proposals:
        print(json.dumps({"accepted": False, "reason": "no proposals to evaluate"}))
        return 1
    
    # Get last user message and original assistant responses
    last_user_msg = ""
    original_outputs = []
    for m in messages:
        raw = m.get("content", "")
        if isinstance(raw, list):
            texts = []
            for block in raw:
                if isinstance(block, dict):
                    bt = block.get("type", "")
                    if bt == "text":
                        texts.append(block.get("text", ""))
                    elif bt == "tool_use":
                        texts.append("[tool_use: " + block.get("name", "") + "]")
                    elif bt == "tool_result":
                        texts.append("[tool_result]")
                elif isinstance(block, str):
                    texts.append(block)
            raw = " ".join(texts)
        if m.get("role") == "user":
            last_user_msg = raw
        elif m.get("role") == "assistant":
            original_outputs.append(raw)
    
    if not last_user_msg:
        print(json.dumps({"accepted": False, "reason": "no user message found"}))
        return 1
    
    # Build conversation text and original output
    conv_lines = []
    for m in messages[-6:]:  # last 6 messages
        role = m.get("role", "?")
        content = (m.get("content", "") or "")[:500]
        conv_lines.append(f"[{role}] {content}")
    conv_text = "\n".join(conv_lines)
    old_output = "\n".join(original_outputs[-3:])  # last 3 assistant responses
    
    # Snapshot original files, surgically apply proposals, re-run, then restore
    sys.stderr.write("[EVAL-DBG] Snapshotting files before real-world apply...\n")
    snapshots = _snapshot_files(proposals)
    new_output = ""
    _claw_result = {"stdout": "", "stderr": "", "rc": 0}
    try:
        text_only = _apply_proposals_to_files(proposals)
        append_prompt = _build_append_prompt(text_only)
        # Re-execute (files surgically modified + text injection for the rest)
        _claw_result = _run_clawcodex(last_user_msg, append_prompt)
        new_output = _claw_result["stdout"]
        # If headless failed, capture corrupted files for debug
        if _claw_result["rc"] != 0:
            _corrupted = {}
            for _fp in snapshots:
                try:
                    with open(_fp, encoding="utf-8") as _f:
                        _corrupted[_fp] = _f.read()[:2000]
                except:
                    pass
            if _corrupted:
                _claw_result["corrupted_files"] = _corrupted
    finally:
        _restore_files(snapshots)
    
    if not new_output.strip():
        print(json.dumps({"accepted": False, "reason": "ClawCodex returned no output"}))
        return 1
    
    # Evaluate old vs new
    proposals_text = json.dumps(proposals, ensure_ascii=False, indent=2)
    result = _evaluate_proposals(conv_text, old_output, new_output, proposals_text)
    result["eval_mode"] = "real_apply"
    
    result["clawcodex_stderr"] = _claw_result["stderr"]
    result["clawcodex_rc"] = _claw_result["rc"]
    result["clawcodex_stdout"] = _claw_result["stdout"]
    if _claw_result.get("corrupted_files"):
        result["corrupted_files"] = _claw_result["corrupted_files"]
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("accepted") else 2


if __name__ == "__main__":
    sys.exit(main())
