"""Subprocess adapter for SelfEvolvingSystem — avoids src import conflicts with ClawCodex."""

import io
import json
import os
import sys
import tempfile
import subprocess

# Force UTF-8 for stdout/stderr to avoid GBK encoding issues
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

SEA_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SEA_ROOT)

from src.main import SelfEvolvingSystem

# --- LLM caller (same pattern as evolve_evaluate.py) ---

CX_ROOT = os.path.normpath(os.path.join(SEA_ROOT, ".."))


# Hardcoded defaults (same pattern as evolve_evaluate.py / evolve_debug.py)


def _load_llm_config() -> tuple:
    """Load API key, base_url, model from CX_* env vars (set by parent process)."""
    api_key = os.environ.get("CX_API_KEY", "")
    base_url = os.environ.get("CX_BASE_URL", "")
    model = os.environ.get("CX_MODEL", "")
    return api_key, base_url, model


def _llm_caller(prompt: str) -> str:
    """Call LLM via subprocess (isolated) and return response text."""
    api_key, base_url, model = _load_llm_config()
    if not api_key or not model:
        return ""

    script = (
        "import sys\n"
        "from openai import OpenAI\n"
        f"client = OpenAI(api_key={json.dumps(api_key)}, base_url={json.dumps(base_url)}, timeout=60)\n"
        "content = " + json.dumps(prompt) + "\n"
        "resp = client.chat.completions.create(\n"
        f"  model={json.dumps(model)},\n"
        "  messages=[{'role': 'user', 'content': content}],\n"
        "  max_tokens=32768, temperature=0,\n"
        ")\n"
        'm = resp.choices[0].message; c = m.content or ""\n'
        'if not c.strip(): sys.stderr.write("empty content; reasoning_chars=%d\\n" % len(getattr(m, "reasoning_content", "") or ""))\n'
        'print(c)\n'
    )

    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(suffix=".py", prefix="llm_call_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(script)
        result = subprocess.run(
            [sys.executable, tmp],
            capture_output=True, timeout=300, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "CX_API_KEY": os.environ.get("CX_API_KEY", ""), "CX_BASE_URL": os.environ.get("CX_BASE_URL", ""), "CX_MODEL": os.environ.get("CX_MODEL", "")},
        )
        output = (result.stdout or "").strip()
        if result.returncode != 0:
            _err = (result.stderr or "").strip()[:300]
            sys.stderr.write("[Evolve] LLM subprocess rc=%d: %s\n" % (result.returncode, _err))
            sys.stderr.flush()
        elif not output:
            _err = (result.stderr or "").strip()[:300]
            sys.stderr.write("[Evolve] LLM subprocess rc=0 but empty output: %s\n" % _err)
            sys.stderr.flush()
        return output if output else ""
    except subprocess.TimeoutExpired:
        sys.stderr.write("[Evolve] LLM subprocess timed out after 300s\n")
        sys.stderr.flush()
        return ""
    except Exception as exc:
        sys.stderr.write("[Evolve] LLM subprocess error: %s\n" % exc)
        sys.stderr.flush()
        return ""
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except Exception:
                pass


# --- Map analyzer: evolve_map_analyze.py subprocess ---

def _run_map_analyzer(trace_path: str, focus_areas: list[str] | None) -> list[dict]:
    """Call evolve_map_analyze.py as subprocess, return proposals or []."""
    if focus_areas is not None and "code" not in focus_areas:
        return []
    map_script = os.path.join(SEA_ROOT, "src", "evolve_map_analyze.py")
    if not os.path.isfile(map_script):
        sys.stderr.write("[MapAnalyze] Script not found: %s\n" % map_script)
        return []
    sys.stderr.write("[MapAnalyze] Starting codebase-driven analysis...\n")
    try:
        result = subprocess.run(
            [sys.executable, map_script, trace_path],
            capture_output=True, text=True, timeout=1500,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "CX_API_KEY": os.environ.get("CX_API_KEY", ""), "CX_BASE_URL": os.environ.get("CX_BASE_URL", ""), "CX_MODEL": os.environ.get("CX_MODEL", "")},
        )
        # Forward subprocess stderr to parent (visible in evolve_hook console)
        if result.stderr:
            for _line in result.stderr.strip().split("\n"):
                _ls = _line.strip()
                if _ls:
                    sys.stderr.write(_ls + "\n")
        if result.returncode != 0:
            sys.stderr.write("[MapAnalyze] Subprocess exited with code %d\n" % result.returncode)
            return []
        data = json.loads(result.stdout.strip())
        proposals = data.get("proposals", [])
        if proposals:
            sys.stderr.write("[MapAnalyze] Generated %d proposal(s)\n" % len(proposals))
            for _p in proposals:
                _fp = _p.get("file_path", _p.get("target", "?"))
                _r = _p.get("reason", "")[:80]
                sys.stderr.write("  -> %s: %s\n" % (_fp, _r))
        else:
            sys.stderr.write("[MapAnalyze] No proposals generated\n")
        return proposals
    except subprocess.TimeoutExpired:
        sys.stderr.write("[MapAnalyze] Timeout (1500s)\n")
        return []
    except json.JSONDecodeError:
        sys.stderr.write("[MapAnalyze] Invalid JSON output from subprocess\n")
        return []
    except Exception as e:
        sys.stderr.write("[MapAnalyze] Error: %s\n" % e)
        return []


def _merge_map_proposals(result: dict, map_proposals: list[dict]) -> None:
    """Merge map analyzer proposals into result, dedup by file_path."""
    if not map_proposals:
        return
    # Normalize field names for downstream compatibility
    # (evolve_map_analyze outputs original_content/new_content, downstream uses current_content/proposed_content)
    for mp in map_proposals:
        if "new_content" in mp and "proposed_content" not in mp:
            mp["proposed_content"] = mp["new_content"]
        if "original_content" in mp and "current_content" not in mp:
            mp["current_content"] = mp["original_content"]
    if "proposals" not in result:
        result["proposals"] = []
    before = len(result["proposals"])
    existing_targets = {
        p.get("file_path") for p in result.get("proposals", [])
        if p.get("file_path")
    }
    added = 0
    for mp in map_proposals:
        fp = mp.get("file_path", "")
        if fp and fp not in existing_targets:
            result["proposals"].append(mp)
            existing_targets.add(fp)
            added += 1
        elif not fp:
            result["proposals"].append(mp)
            added += 1
    if added:
        sys.stderr.write("[MapAnalyze] Merged %d proposal(s) into pipeline (total: %d)\n" % (added, len(result["proposals"])))

# --- Adapter commands ---

def _process_transcript(transcript_path: str, config_path: str, focus_areas: list[str] | None = None, multi_traces: list[dict] | None = None) -> str:
    """Read full message dicts from raw JSONL transcript file."""
    messages = []
    with open(transcript_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            # Skip session_init / session_snapshot / cost_block administrative lines
            if entry.get("type") in ("session_init", "session_snapshot", "cost_block"):
                continue
            messages.append(entry)
    _agents_dir = os.path.join(CX_ROOT, "clawcodex_ext", "agent", "agents")
    system = SelfEvolvingSystem(config_path, llm_caller=_llm_caller, clawcodex_agents_dir=_agents_dir)
    result = system.process_conversation(messages, transcript_path=transcript_path, focus_areas=focus_areas, multi_traces=multi_traces)

    # --- Run map analyzer alongside code plugins ---
    _tmp_trace = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({"messages": messages, "multi_traces": multi_traces or []}, f, ensure_ascii=False)
            _tmp_trace = f.name
        map_proposals = _run_map_analyzer(_tmp_trace, focus_areas)
        _merge_map_proposals(result, map_proposals)
    finally:
        if _tmp_trace and os.path.isfile(_tmp_trace):
            os.unlink(_tmp_trace)
    # --- END map analyzer ---

    return json.dumps(result, ensure_ascii=False)


def _process_conversation(trace_path: str, config_path: str) -> str:
    with open(trace_path, encoding="utf-8") as f:
        data = json.load(f)
    messages = data.get("messages", [])
    focus_areas = data.get("focus_areas")
    multi_traces = data.get("multi_traces")

    # If transcript_path is provided, use the raw JSONL file instead
    transcript_path = data.get("transcript_path")
    if transcript_path and os.path.isfile(transcript_path):
        return _process_transcript(transcript_path, config_path, focus_areas, multi_traces)

    _agents_dir = os.path.join(CX_ROOT, "clawcodex_ext", "agent", "agents")
    system = SelfEvolvingSystem(config_path, llm_caller=_llm_caller, clawcodex_agents_dir=_agents_dir)
    tool_events = data.get("tool_events", [])
    result = system.process_conversation(messages, tool_events=tool_events, transcript_path=transcript_path, focus_areas=focus_areas, multi_traces=multi_traces)

    # --- Run map analyzer alongside code plugins ---
    map_proposals = _run_map_analyzer(trace_path, focus_areas)
    _merge_map_proposals(result, map_proposals)
    # --- END map analyzer ---

    return json.dumps(result, ensure_ascii=False)


def _rollback(version_path: str, config_path: str) -> str:
    with open(version_path, encoding="utf-8") as f:
        data = json.load(f)
    version = data.get("version", "")
    _agents_dir = os.path.join(CX_ROOT, "clawcodex_ext", "agent", "agents")
    system = SelfEvolvingSystem(config_path, llm_caller=_llm_caller, clawcodex_agents_dir=_agents_dir)
    ok = system.rollback(version)
    return json.dumps({"ok": ok}, ensure_ascii=False)


def _apply_proposal(proposal_path: str, config_path: str) -> str:
    with open(proposal_path, encoding="utf-8") as f:
        proposal = json.load(f)
    _agents_dir = os.path.join(CX_ROOT, "clawcodex_ext", "agent", "agents")
    system = SelfEvolvingSystem(config_path, llm_caller=_llm_caller, clawcodex_agents_dir=_agents_dir)
    version = system.apply_proposal(proposal)
    return json.dumps({"version": version}, ensure_ascii=False)


def main():
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: evolve_repl_adapter.py <command> <json_path>"}))
        sys.exit(1)

    command = sys.argv[1]
    json_path = sys.argv[2]
    config_path = os.path.join(SEA_ROOT, "config", "default_config.yaml")

    if command == "process_conversation":
        result = _process_conversation(json_path, config_path)
        print(result)
    elif command == "apply_proposal":
        result = _apply_proposal(json_path, config_path)
        print(result)
    elif command == "rollback":
        result = _rollback(json_path, config_path)
        print(result)
    else:
        print(json.dumps({"error": f"Unknown command: {command}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
