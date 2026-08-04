"""Codebase map-driven trace analysis.

Uses codebase_map.md to identify relevant source files for a failed trace,
reads their full content, and generates targeted modification proposals.

Called as subprocess from evolve_hook.py.
Input: trace JSON path (argv[1])
Output: JSON with proposals (same format as evolve_analyze.py).
Two-phase LLM pipeline:
  Phase 1 — analyze full trace, select 1-3 candidate files from map
  Phase 2 — read candidate files, generate specific modification proposals
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile

# ─── Config ──────────────────────────────────────────────────────────────────
LLM_TIMEOUT = 120
PHASE1_MAX_TOKENS = 16384
PHASE2_MAX_TOKENS = 32768
TEMPERATURE = 0
MAX_CANDIDATES = 3
MAX_FILE_SIZE = 200 * 1024  # 200 KB


# ─── Path resolution ─────────────────────────────────────────────────────────

def _sea_root() -> str:
    """Get self-evolving-agent root directory."""
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def _cx_root() -> str:
    """Get ClawCodex root directory."""
    sea = _sea_root()
    return os.environ.get("CX_ROOT") or os.path.normpath(os.path.join(sea, ".."))


# ─── LLM call (nested subprocess to avoid src package conflicts) ─────────────

def _call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 4096, timeout: int | None = None) -> str | None:
    """Call LLM API via temporary subprocess script."""
    _llm_to = timeout if timeout is not None else LLM_TIMEOUT
    script_lines = [
        "import sys, os, json",
        "from openai import OpenAI",
        "client = OpenAI(api_key=%s, base_url=%s, timeout=%s)" % (json.dumps(os.environ.get('CX_API_KEY', '')), json.dumps(os.environ.get('CX_BASE_URL', '')), _llm_to),
        'messages = [{"role": "system", "content": %s}, {"role": "user", "content": %s}]' % (json.dumps(system_prompt), json.dumps(user_prompt)),
        "resp = client.chat.completions.create(",
        "  model=%s," % json.dumps(os.environ.get('CX_MODEL', '')),
        "  messages=messages,",
        "  max_tokens=%s, temperature=%s," % (max_tokens, TEMPERATURE),
        ")",
        'm = resp.choices[0].message; c = m.content or ""',
        'if not c.strip(): sys.stderr.write("empty content; reasoning_chars=%d\\n" % len(getattr(m, "reasoning_content", "") or ""))',
        'print(c)',
    ]
    script = "\n".join(script_lines)

    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(script)
            tmp = f.name

        python = sys.executable
        result = subprocess.run(
            [python, tmp],
            capture_output=True, timeout=_llm_to,
            encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "CX_API_KEY": os.environ.get("CX_API_KEY", ""), "CX_BASE_URL": os.environ.get("CX_BASE_URL", ""), "CX_MODEL": os.environ.get("CX_MODEL", "")},
        )
        if result.returncode != 0:
            sys.stderr.write("LLM subprocess error (rc=%s):\n%s\n" % (result.returncode, (result.stderr or "")[:2000]))
            return None
        out = (result.stdout or "").strip()
        if not out and result.stderr:
            sys.stderr.write("[MapAnalyze] LLM empty output; stderr: %s\n" % (result.stderr.strip()[:300]))
        return out if out else None
    except subprocess.TimeoutExpired:
        sys.stderr.write("LLM call timed out\n")
        return None
    except Exception as e:
        sys.stderr.write("LLM call failed: %s\n" % e)
        return None
    finally:
        if tmp and os.path.isfile(tmp):
            try:
                os.unlink(tmp)
            except Exception:
                pass

# ─── JSON extraction from LLM response ───────────────────────────────────────

def _extract_json(text: str) -> dict | list | None:
    """Extract JSON from LLM response (handles markdown fences, nested braces, raw newlines in strings)."""
    t = text.strip()
    # Remove markdown code fence
    t = re.sub(r'^```(?:json)?\s*\n?', "", t)
    t = re.sub(r'\n```\s*$', "", t)
    t = t.strip()

    # Try direct parse first (fast path)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass

    # Find first { and use brace-depth matching to find proper end
    start = t.find("{")
    if start < 0:
        start = t.find("[")
    if start < 0:
        return None

    # Brace-depth parsing: handles nested {} and strings correctly
    s = t[start:]
    depth = 0
    in_str = False
    escape = False
    end = 0
    for i, c in enumerate(s):
        if escape:
            escape = False
            continue
        if c == "\\" and in_str:
            escape = True
            continue
        if c == "\"" and not escape:
            in_str = not in_str
            continue
        if in_str:
            continue
        if c in ("{", "["):
            depth += 1
        elif c in ("}", "]"):
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end <= 0:
        return None

    json_str = s[:end]

    # Try strict parse first
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    # Repair: replace raw newlines/tabs inside JSON string values with escapes
    # (common LLM issue: Python source code contains unescaped newlines)
    repaired = []
    in_str = False
    escape = False
    for c in json_str:
        if escape:
            repaired.append(c)
            escape = False
            continue
        if c == "\\" and in_str:
            repaired.append(c)
            escape = True
            continue
        if c == "\"" and not escape:
            in_str = not in_str
            repaired.append(c)
            continue
        if in_str:
            if c == "\n":
                repaired.append("\\n")
            elif c == "\r":
                repaired.append("\\r")
            elif c == "\t":
                repaired.append("\\t")
            else:
                repaired.append(c)
        else:
            repaired.append(c)
    repaired_str = "".join(repaired)

    try:
        return json.loads(repaired_str)
    except json.JSONDecodeError:
        return None


# ─── Codebase map parsing ────────────────────────────────────────────────────

def _parse_codebase_map(map_path: str, cx_root: str) -> dict[str, str]:
    """Parse codebase_map.md into {rel_path: description}.

    Map format:
        ## dirname/ (N files)
        - [x] filename.py: description
    """
    if not os.path.isfile(map_path):
        return {}

    try:
        with open(map_path, encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return {}

    entries: dict[str, str] = {}
    current_dir = ""

    for line in lines:
        line = line.rstrip()

        # Section header: ## dirname/ (N files)
        m = re.match(r"^##\s+(\S+/?)\s*(?:\(\d+ files?\))?\s*$", line)
        if m:
            dir_name = m.group(1).rstrip("/")
            if dir_name.lower() in ("facade mappings", "facade"):
                current_dir = ""
            else:
                current_dir = dir_name
            continue

        # File entry: - [x] filename.py: description
        if current_dir and line.startswith("- ["):
            m2 = re.match(r"-\s*\[\S+\]\s+([^\s:]+(?:\.py|\.md|\.yaml)):?\s*(.*)", line)
            if m2:
                fname = m2.group(1)
                desc = m2.group(2).strip()
                if desc:
                    rel_path = "%s/%s" % (current_dir, fname)
                    entries[rel_path] = desc

    return entries

# ─── Message formatting ──────────────────────────────────────────────────────

def _format_content(content, max_len: int = 2000) -> str:
    """Format message content (string or list of blocks) to plain text."""
    if isinstance(content, str):
        return content[:max_len]
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                bt = block.get("type", "")
                if bt == "text":
                    parts.append(block.get("text", "")[:max_len])
                elif bt == "tool_use":
                    parts.append("[tool_use: %s]" % block.get("name", "?"))
                elif bt == "tool_result":
                    out = str(block.get("content", ""))[:500]
                    is_err = block.get("is_error", False)
                    prefix = "[tool_result ERROR]" if is_err else "[tool_result]"
                    parts.append("%s %s" % (prefix, out))
                else:
                    parts.append("[%s: %s]" % (bt, str(block)[:200]))
            elif isinstance(block, str):
                parts.append(block[:max_len])
            else:
                parts.append(str(block)[:200])
        return "\n".join(parts)
    return str(content)[:max_len]


def _format_trace(messages: list[dict]) -> str:
    """Format all trace messages for LLM prompt."""
    parts = []
    for i, msg in enumerate(messages):
        role = msg.get("role", "?")
        content = _format_content(msg.get("content", ""), max_len=2000)
        parts.append("[%s][%s]\n%s" % (i, role, content))
    return "\n\n---\n\n".join(parts)


def _format_traces_cross(all_traces: list[list[dict]]) -> str:
    """Format multiple traces for cross-trace LLM prompt, labeled Trace N."""
    parts = []
    for i, msgs in enumerate(all_traces):
        label = "Trace %d (Primary - most recent session)" % i if i == 0 else "Trace %d (Historical session)" % i
        trace_text = _format_trace(msgs)
        parts.append("## %s\n\n%s" % (label, trace_text))
    return "\n\n".join(parts)


# ─── Phase 1: Analyze trace + select candidates ──────────────────────────────

PHASE1_SYSTEM_PROMPT = (
    "You are a code problem diagnosis expert. "
    "Analyze the complete agent execution trace to find the root cause of failures, "
    "then identify which source files need modification.\n\n"
    "Rules:\n"
    "- Analyze the ENTIRE conversation, not just the last few messages\n"
    "- Look for error patterns, misunderstandings, repeated retries, truncated responses\n"
    "- Be precise about which file is the root cause\n"
    "- Only select files that are directly related to the failure\n"
    "- Limit to 1-3 files, ranked by priority (1 = most important)"
)


PHASE1_CROSS_SYSTEM_PROMPT = (
    "You are a code problem diagnosis expert. Analyze MULTIPLE agent execution traces "
    "to find cross-session failure patterns, then identify which source files need modification.\n\n"
    "Rules:\n"
    "- Analyze ALL traces, not just the primary one\n"
    "- Focus on patterns that appear in 2+ traces (cross-session issues)\n"
    "- Distinguish between one-off failures and systemic patterns\n"
    "- For systemic patterns, trace back to the root cause file\n"
    "- Be precise about which file is the root cause\n"
    "- Only select files that are directly related to the failure\n"
    "- Limit to 1-3 files total (across all traces)"
)


def _build_phase1_prompt(map_entries: dict[str, str]) -> str:
    """Build Phase 1 user prompt with codebase map entries grouped by directory."""
    # Group by directory
    dirs: dict[str, list[tuple[str, str]]] = {}
    for rel_path, desc in map_entries.items():
        d = os.path.dirname(rel_path)
        if d not in dirs:
            dirs[d] = []
        dirs[d].append((rel_path, desc))

    map_lines = []
    for d in sorted(dirs.keys()):
        label = d if d else "(root)"
        map_lines.append("### %s/" % label)
        for rel_path, desc in sorted(dirs[d], key=lambda x: x[0]):
            map_lines.append("- %s: %s" % (rel_path, desc))
        map_lines.append("")

    map_text = "\n".join(map_lines)

    return (
        "## Codebase Structure\n\n"
        "Below is the complete ClawCodex codebase map. "
        "Each entry shows a file path and its one-line functional description.\n\n"
        "%s\n"
        "## Task\n\n"
        "1. Analyze the execution trace provided above (in the conversation history)\n"
        "2. Write a concise Chinese failure summary explaining what went wrong\n"
        "3. Select 1-3 files from the codebase map that are most likely the ROOT CAUSE\n"
        "   of the failure and need modification\n\n"
        "## Output Format (valid JSON only)\n\n"
        "```json\n"
        '{\n'
        '  "summary": "Failure summary in Chinese...",\n'
        '  "candidates": [\n'
        '    {\n'
        '      "file_path": "relative/path/to/file.py",\n'
        '      "relevance": "Why this file needs modification",\n'
        '      "priority": 1\n'
        '    }\n'
        '  ]\n'
        '}\n'
        "```\n"
    ) % map_text


def _build_phase1_cross_prompt(map_entries: dict[str, str]) -> str:
    """Build cross-trace Phase 1 prompt with codebase map entries."""
    # Group by directory (same as _build_phase1_prompt)
    dirs: dict[str, list[tuple[str, str]]] = {}
    for rel_path, desc in map_entries.items():
        d = os.path.dirname(rel_path)
        if d not in dirs:
            dirs[d] = []
        dirs[d].append((rel_path, desc))

    map_lines = []
    for d in sorted(dirs.keys()):
        label = d if d else "(root)"
        map_lines.append("### %s/" % label)
        for rel_path, desc in sorted(dirs[d], key=lambda x: x[0]):
            map_lines.append("- %s: %s" % (rel_path, desc))
        map_lines.append("")

    map_text = "\n".join(map_lines)

    return (
        "## ClawCodex Codebase Structure\n\n"
        "Below is the complete ClawCodex codebase map. "
        "Each entry shows a file path and its one-line functional description.\n\n"
        "%s\n"
        "## Task\n\n"
        "1. Analyze ALL traces above and find patterns that appear in MULTIPLE traces\n"
        "2. Distinguish between one-off glitches and systemic issues\n"
        "3. Write a concise Chinese cross-trace failure summary explaining the root cause\n"
        "4. Select 1-3 files from the codebase map that address the ROOT CAUSE of the systemic issues\n\n"
        "## Output Format (valid JSON only)\n\n"
        "```json\n"
        "{\n"
        "  \"summary\": \"Cross-trace failure summary in Chinese...\",\n"
        "  \"cross_patterns\": [\n"
        "    {\n"
        "      \"pattern\": \"Description of repeated pattern\",\n"
        "      \"affected_traces\": [0, 2],\n"
        "      \"priority\": 1\n"
        "    }\n"
        "  ],\n"
        "  \"candidates\": [\n"
        "    {\n"
        "      \"file_path\": \"relative/path/to/file.py\",\n"
        "      \"relevance\": \"Why this file (with cross-trace evidence)\",\n"
        "      \"priority\": 1\n"
        "    }\n"
        "  ]\n"
        "}\n"
        "```\n"
    ) % map_text

# ─── Phase 2: Generate proposals ─────────────────────────────────────────────

PHASE2_SYSTEM_PROMPT = (
    "You are a code optimization expert. Based on failure analysis, error context, and full source code, "
    "generate precise, surgical modifications.\n\n"
    "CRITICAL: Before writing code, think about the function\'s contract -- its signature, return format, and what callers expect.\n"
    "  Keep the signature and return contract IDENTICAL. Only change internal logic.\n"
    "  A broken tool is worse than no change.\n"
    "- Make the MINIMAL change possible. Prefer adding 1-3 lines over rewriting entire functions.\n"
    "- If your change uses a module (like `sys`, `os`, `re`), INCLUDE the import in `original_content`/`new_content`.\n"
    "  Find the relevant import at the top of the source file and include it in the snippet.\n"
    "- If your code references a module (sys, os, re, etc.), INCLUDE `import module` in your snippet.\n"
    "  Duplicate imports are harmless; missing imports crash the tool (NameError).\n"
    "- If a file needs no changes, omit it entirely.\n"
    "- Do NOT add new features or refactor unrelated code"
)

def _build_phase2_prompt(summary: str, file_contents: list[dict], trace_errors: str = "", cross_patterns: list[dict] | None = None) -> str:
    """Build Phase 2 user prompt with failure analysis, trace error context, and full file sources.
    Uses snippet-based change format instead of full file output."""
    # Build cross-trace patterns section if available
    cross_text = ""
    if cross_patterns:
        pattern_lines = []
        for cp in cross_patterns:
            pattern_lines.append(
                "- %s (traces: %s, priority: %s)"
                % (cp.get("pattern", "?"), cp.get("affected_traces", []), cp.get("priority", "?"))
            )
        cross_text = "## Cross-Trace Patterns\n\n%s\n\n" % "\n".join(pattern_lines)

    files_parts = []
    for fc in file_contents:
        files_parts.append("### %s\n\n```python\n%s\n```\n" % (fc["file_path"], fc["content"]))

    files_text = "\n".join(files_parts)

    error_section = ""
    if trace_errors:
        error_section = "## Error Context from Trace\n\n%s\n\n" % trace_errors

    return (
        "%s"
        "## Failure Analysis\n\n%s\n\n"
        "%s"
        "## Source Files to Modify\n\n%s\n"
        "## Task\n\n"
        "For each file above, specify the EXACT changes needed.\n\n"
        "RULES:\n"
        "1. DO NOT output the entire file. Only output the complete functions/methods/classes that need to change.\n"
        "2. You must provide:\n"
        "   - `original_content`: an EXACT copy-paste of the COMPLETE function/method/class to replace\n"
        "     (must include the entire def/class block from its signature to its end, not just internal lines)\n"
        "   - `new_content`: the new version, keeping signature and return contract IDENTICAL\n"
        "3. After replacement, the rest of the file remains exactly as it is.\n"
        "4. `original_content` must EXACTLY match the source code provided (character for character).\n"
        "5. Only change what\'s needed to fix the root cause.\n"
        "6. IMPORTANT: The `original_content` snippet MUST cover the ENTIRE function/method/class definition from its first line (def/class/async def) to its last line.\n"
        "   DO NOT output only the internal lines of a function. Include the def/class signature, docstring, and all internal code.\n"
        "7. CRITICAL: Only include files that ACTUALLY need changes. If a file is fine as-is, OMIT it from the proposals list entirely. Do NOT output no-op proposals.\n"
        "8. CRITICAL: If your snippet references a module, ALWAYS include the `import` line.\n"
        "   Duplicate imports are harmless (Python ignores them); missing imports crash the tool.\n"
        "   Find the existing import at the top of the file and include it in BOTH `original_content` and `new_content`.\n\n"
        "## Output Format (valid JSON only)\n\n"
        "```json\n"
        "{\n"
        '  "proposals": [\n'
        "    {\n"
        '      "file_path": "relative/path/to/file.py",\n'
        '      "original_content": "def existing_function(...):\\n    ...",\n'
        '      "new_content": "def existing_function(...):\\n    ... # modified version",\n'
        '      "reason": "Why this change is needed",\n'
        '      "priority": 1\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "```\n"
    ) % (cross_text, summary, error_section, files_text)
def _read_file_safe(path: str) -> str | None:
    """Read file safely; return None if too large or unreadable."""
    try:
        size = os.path.getsize(path)
        if size > MAX_FILE_SIZE:
            sys.stderr.write("  File too large (%s bytes): %s\n" % (size, path))
            return None
        with open(path, encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        sys.stderr.write("  Failed to read %s: %s\n" % (path, e))
        return None

# ─── Main ────────────────────────────────────────────────────────────────────

def _extract_trace_errors(messages: list[dict]) -> str:
    """Extract key error messages, failed tool calls, and last user request from trace."""
    parts = []

    # Last user message
    for m in reversed(messages):
        if m.get("role") == "user":
            content = _format_content(m.get("content", ""), max_len=1000)
            parts.append("## Last User Request\n%s" % content)
            break

    # Assistant messages with errors
    error_msgs = []
    for m in messages:
        if m.get("role") == "assistant":
            content = _format_content(m.get("content", ""), max_len=500)
            if any(k in content.lower() for k in ["error", "exception", "traceback", "failed"]):
                error_msgs.append(content[:500])
    if error_msgs:
        parts.append("## Error Messages\n%s" % "\n---\n".join(error_msgs[-3:]))

    # Failed tool calls
    failed_tools = []
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error"):
                    tuid = block.get("tool_use_id", "")
                    tool_name = "(unknown)"
                    for m2 in messages:
                        c2 = m2.get("content", "")
                        if isinstance(c2, list):
                            for b2 in c2:
                                if isinstance(b2, dict) and b2.get("type") == "tool_use" and b2.get("id") == tuid:
                                    tool_name = b2.get("name", "(unknown)")
                    out = str(block.get("content", ""))[:300]
                    failed_tools.append("Tool '%s': %s" % (tool_name, out))
    if failed_tools:
        parts.append("## Failed Tool Calls\n%s" % "\n".join(failed_tools))

    return "\n\n".join(parts)


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "no trace file provided", "proposals": [], "trace_summary": {}}))
        return 1

    trace_path = sys.argv[1]
    if not os.path.isfile(trace_path):
        print(json.dumps({"error": "trace file not found", "proposals": [], "trace_summary": {}}))
        return 1

    # 1. Load trace
    with open(trace_path, encoding="utf-8") as f:
        trace = json.load(f)

    messages = trace.get("messages", [])
    if not messages:
        print(json.dumps({"proposals": [], "trace_summary": {}}))
        return 0

    # Load optional multi_traces for cross-trace analysis (same format as evolve_hook.py)
    multi_traces_raw = trace.get("multi_traces", [])
    all_traces_msgs = [messages]
    for mt in multi_traces_raw:
        mt_msgs = mt.get("messages", [])
        if mt_msgs:
            all_traces_msgs.append(mt_msgs)
    is_cross = len(all_traces_msgs) > 1

    cx_root = _cx_root()
    sea_root = _sea_root()
    map_path = os.path.join(sea_root, "data", "codebase_map.md")

    # 2. Load and parse codebase map
    map_entries = _parse_codebase_map(map_path, cx_root)
    if not map_entries:
        sys.stderr.write("[MapAnalyze] Codebase map is empty or not found\n")
        _write_empty(messages)
        return 0

    sys.stderr.write("[MapAnalyze] Loaded %s codebase map entries\n" % len(map_entries))

    # 3. Phase 1: LLM analyzes trace(s) + selects candidate files
    if is_cross:
        # Cross-trace: send all traces together
        trace_text = _format_traces_cross(all_traces_msgs)
        phase1_user = _build_phase1_cross_prompt(map_entries)
        phase1_sys = PHASE1_CROSS_SYSTEM_PROMPT
        sys.stderr.write("[MapAnalyze] Phase 1: cross-trace analysis (%s traces, %s map entries)...\n" % (len(all_traces_msgs), len(map_entries)))
    else:
        # Single trace: original logic
        trace_text = _format_trace(messages)
        phase1_user = _build_phase1_prompt(map_entries)
        phase1_sys = PHASE1_SYSTEM_PROMPT
        sys.stderr.write("[MapAnalyze] Phase 1: analyzing trace (%s msgs, %s map entries)...\n" % (len(messages), len(map_entries)))

    _phase1_input = trace_text + "\n\n" + phase1_user
    sys.stderr.write("[MapAnalyze] Phase 1 prompt size: sys=%d chars, user=%d chars, total=%d chars\n" % (len(phase1_sys), len(_phase1_input), len(phase1_sys) + len(_phase1_input)))
    phase1_raw = _call_llm(phase1_sys, _phase1_input, max_tokens=PHASE1_MAX_TOKENS, timeout=900)

    if not phase1_raw:
        sys.stderr.write("[MapAnalyze] Phase 1: LLM returned no output\n")
        _write_empty(messages)
        return 0

    phase1_data = _extract_json(phase1_raw)
    if not phase1_data or not isinstance(phase1_data, dict):
        sys.stderr.write("[MapAnalyze] Phase 1: failed to parse LLM output\n")
        _write_empty(messages)
        return 0

    summary = phase1_data.get("summary", "")
    cross_patterns = phase1_data.get("cross_patterns", [])
    if not isinstance(cross_patterns, list):
        cross_patterns = []
    candidates = phase1_data.get("candidates", [])
    if not candidates or not isinstance(candidates, list):
        sys.stderr.write("[MapAnalyze] Phase 1: no candidates selected\n")
        _write_empty(messages)
        return 0

    candidates = candidates[:MAX_CANDIDATES]
    mode = "Cross-trace" if is_cross else "Single-trace"
    sys.stderr.write("[MapAnalyze] Phase 1 (%s): selected %s candidate(s), %s cross-pattern(s)\n" % (mode, len(candidates), len(cross_patterns)))
    for c in candidates:
        fp = c.get("file_path", "?")
        pri = c.get("priority", "?")
        rel = c.get("relevance", "")[:100]
        sys.stderr.write("  - %s (priority %s): %s\n" % (fp, pri, rel))
    for cp in cross_patterns[:3]:
        pat = cp.get("pattern", "")[:80]
        aff = cp.get("affected_traces", [])
        sys.stderr.write("  pattern: %s (traces: %s)\n" % (pat, aff))

    # 4. Read candidate files from disk
    file_contents: list[dict] = []
    for c in candidates:
        fp = c.get("file_path", "")
        if not fp:
            continue
        abs_fp = fp if os.path.isabs(fp) else os.path.normpath(os.path.join(cx_root, fp))
        if not os.path.isfile(abs_fp):
            sys.stderr.write("  File not found: %s\n" % abs_fp)
            continue
        content = _read_file_safe(abs_fp)
        if content is None:
            continue
        file_contents.append({"file_path": fp, "abs_path": abs_fp, "content": content})

    if not file_contents:
        sys.stderr.write("[MapAnalyze] No candidate files could be read\n")
        _write_empty(messages)
        return 0

    # 5. Phase 2: LLM generates modification proposals (one call per candidate file)
    trace_errors = _extract_trace_errors(messages)
    proposals_raw = []
    for fc in file_contents:
        fp = fc["file_path"]
        sys.stderr.write("[MapAnalyze] Phase 2: analyzing %s...\n" % fp)
        phase2_user = _build_phase2_prompt(summary, [fc], trace_errors=trace_errors, cross_patterns=cross_patterns)
        phase2_raw = _call_llm(PHASE2_SYSTEM_PROMPT, phase2_user, max_tokens=PHASE2_MAX_TOKENS, timeout=900)
        if not phase2_raw:
            sys.stderr.write("[MapAnalyze] Phase 2: no output for %s\n" % fp)
            continue
        phase2_data = _extract_json(phase2_raw)
        if not phase2_data:
            sys.stderr.write("[MapAnalyze] Phase 2: failed to parse output for %s\n" % fp)
            continue
        per_file = phase2_data if isinstance(phase2_data, list) else phase2_data.get("proposals", [])
        if isinstance(per_file, list):
            proposals_raw.extend(per_file)
            sys.stderr.write("[MapAnalyze] Phase 2: %s -> %d proposal(s)\n" % (fp, len(per_file)))
    if not proposals_raw:
        sys.stderr.write("[MapAnalyze] Phase 2: no proposals generated for any file\n")
        _write_empty(messages)
        return 0

    # 6. Validate and finalize proposals (snippet-based, passthrough)
    proposals = []
    for p in proposals_raw:
        fp = p.get("file_path", "")
        orig_snip = p.get("original_content", "")
        new_snip = p.get("new_content", "")
        if not fp or not orig_snip or not new_snip:
            continue
        # Skip no-op proposals (identical original and new content)
        if orig_snip == new_snip:
            sys.stderr.write("[MapAnalyze] Skipping no-op proposal for %s (original == new)\n" % fp)
            continue
        # Compile check: apply snippet to real file and verify the result is valid Python
        abs_fp_check = fp if os.path.isabs(fp) else os.path.normpath(os.path.join(cx_root, fp))
        if os.path.isfile(abs_fp_check):
            try:
                disk_content = open(abs_fp_check, encoding="utf-8").read()
                if orig_snip in disk_content:
                    patched = disk_content.replace(orig_snip, new_snip, 1)
                    compile(patched, abs_fp_check, "exec")
            except SyntaxError as e:
                sys.stderr.write("[MapAnalyze] Skipping proposal that breaks syntax in %s: %s\n" % (fp, e))
                continue
            except Exception:
                pass
        # Collect missing-import warnings and attach to proposal for debug module
        _missing_imports = []
        for _mod in ("sys", "os", "re", "json", "subprocess", "shutil", "pathlib"):
            if _mod + "." in new_snip and "import " + _mod not in new_snip and "from " + _mod not in new_snip:
                _missing_imports.append(_mod)
        if _missing_imports:
            sys.stderr.write("[MapAnalyze] WARNING: %s missing imports: %s (attached to proposal for debug)\n" % (fp, ", ".join(_missing_imports)))
        # Resolve to absolute path for downstream compatibility
        abs_fp = fp if os.path.isabs(fp) else os.path.normpath(os.path.join(cx_root, fp))
        # Debug: log snippet sizes for verification
        sys.stderr.write("[MapAnalyze] Proposal: %s (orig=%d chars, new=%d chars)\n" % (abs_fp, len(orig_snip), len(new_snip)))
        proposals.append({
            "type": "code_modification",
            "target": os.path.basename(fp),
            "reason": p.get("reason", ""),
            "priority": p.get("priority", 3),
            "file_path": abs_fp,
            "original_content": orig_snip,
            "new_content": new_snip,
            "_notes": ("missing imports: " + ", ".join(_missing_imports)) if _missing_imports else "",
        })
    user_msgs = [m for m in messages if m.get("role") == "user"]
    assistant_msgs = [m for m in messages if m.get("role") == "assistant"]

    output = {
        "proposals": proposals,
        "trace_summary": {
            "user_messages": len(user_msgs),
            "assistant_messages": len(assistant_msgs),
        },
    }

    sys.stderr.write("[MapAnalyze] Generated %s proposal(s)\n" % len(proposals))
    print(json.dumps(output, ensure_ascii=False))
    return 0


def _write_empty(messages: list[dict]) -> None:
    """Write empty result when no proposals can be generated."""
    user_msgs = [m for m in messages if m.get("role") == "user"]
    assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
    print(json.dumps({
        "proposals": [],
        "trace_summary": {
            "user_messages": len(user_msgs),
            "assistant_messages": len(assistant_msgs),
        },
    }))


if __name__ == "__main__":
    sys.exit(main())
