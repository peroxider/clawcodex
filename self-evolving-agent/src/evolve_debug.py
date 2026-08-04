"""Debug failed proposals: LLM analyzes execution errors and generates corrected proposals.

Called as subprocess from evolve_hook.py.
Input: trace_path (argv[1]), proposals + eval_result (via stdin JSON)
Output: JSON with corrected_proposals list.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
from typing import Any



def _call_llm(prompt: str) -> str | None:
    """Call DeepSeek API via subprocess (avoids import conflicts)."""
    script_lines = [
        "import sys, os, json",
        "from openai import OpenAI",
        f"client = OpenAI(api_key={json.dumps(os.environ.get('CX_API_KEY', ''))}, base_url={json.dumps(os.environ.get('CX_BASE_URL', ''))}, timeout=60)",
        "content = " + json.dumps(prompt),
        "resp = client.chat.completions.create(",
        f" model={json.dumps(os.environ.get('CX_MODEL', ''))},",
        "  messages=[{'role': 'user', 'content': content}],",
        "  max_tokens=4096, temperature=0,",
        ")",
        'print(resp.choices[0].message.content or "")',
    ]
    script = "\n".join(script_lines)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(script)
            tmp = f.name
        result = subprocess.run(
            [sys.executable, tmp],
            capture_output=True, timeout=60, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "CX_API_KEY": os.environ.get("CX_API_KEY", ""), "CX_BASE_URL": os.environ.get("CX_BASE_URL", ""), "CX_MODEL": os.environ.get("CX_MODEL", "")},
        )
        if result.returncode != 0:
            return None
        return (result.stdout or "").strip()
    except Exception:
        return None
    finally:
        if tmp and os.path.isfile(tmp):
            try:
                os.unlink(tmp)
            except Exception:
                pass


def _build_debug_prompt(proposals: list[dict], eval_result: dict[str, Any], debug_out=None) -> str:
    if debug_out is not None:
        _stderr_snip = (eval_result.get("clawcodex_stderr", "") or "")[:200]
        _reason = eval_result.get("reason", "")
        _rc = eval_result.get("clawcodex_rc", 0)
        debug_out(f"  [DBG] reason={_reason}, rc={_rc}, stderr={_stderr_snip}")
    """Build LLM prompt to debug failed proposals."""
    proposals_text = json.dumps(proposals, ensure_ascii=False, indent=2)
    reason = eval_result.get("reason", "")
    stderr = eval_result.get("clawcodex_stderr", "")
    rc = eval_result.get("clawcodex_rc", 0)

    stdout_text = eval_result.get("clawcodex_stdout", "")
    # Build corrupted file content section for real_apply mode
    corrupted_text = ""
    if eval_result.get("corrupted_files"):
        corrupted_text = "\n## Corrupted File Content (after surgical apply)\n"
        for _fp, _content in eval_result["corrupted_files"].items():
            corrupted_text += f"File: {_fp}\n{_content[:2000]}\n---\n"
    return f"""# Debug Failed Optimization Proposals

The following optimization proposals did NOT improve the agent's output.
Re-execution produced errors or worse results.

## Original Proposals
{proposals_text}
{corrupted_text}

## Evaluation Details
- Reason: {reason}
- ClawCodex return code: {rc}
- Eval mode: real_apply (proposals were written to actual files before re-execution)

## Execution Errors (stderr)
{stderr[:1000]}

## ClawCodex Output (stdout) ? includes tool execution details
{stdout_text[:2000]}

## Task
Analyze WHY these proposals failed. Then produce corrected versions.

Diagnose by checking:
1. Did the appended instructions cause the agent to get stuck in loops?
2. Did the agent hit max_turns or tool call limits? (Look for "max_turns", "tool call limit", timeout signals)
3. Are there syntax errors or contradictory instructions in the proposals?
4. Is the proposal type wrong for the target? (e.g. prompt_optimization when it should be something else)

## Common Failure: File Corruption (SyntaxError)
If the stderr shows a SyntaxError inside a .py file (e.g. prompt_assembly.py),
the proposal's new_content was applied to the file but broke Python syntax.
FIX: Rewrite new_content as VALID Python code that implements the original
optimization intention. The new_content must be syntactically valid Python
that can be inserted into the target file without breaking it.

Rules:
1. Focus ONLY on fixing bugs or contradictions in the proposals that caused the failure
2. Keep the original intention, structure, and approach unchanged
3. Do NOT add new optimization opportunities beyond fixing the current ones
4. If a proposal is fundamentally flawed and cannot be fixed, omit it entirely
5. Ensure fixed proposals have clear, valid content
6. If a proposal corrupts Python syntax when applied to a .py file, rewrite its
   new_content as valid Python code. Keep the file_path. The new_content must parse
   as valid Python (think: no unclosed strings, valid syntax).

## Output Format (valid JSON only)
{{"corrected_proposals": [
  {{
    "type": "prompt_optimization",
    "target": "original target name",
    "reason": "original reason",
    "priority": 3,
    "file_path": "original file path",
    "original_content": "",
    "new_content": "corrected content here"
  }}
]}}

Respond ONLY with valid JSON, no other text."""


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"corrected_proposals": [], "error": "no trace path"}))
        return 1

    trace_path = sys.argv[1]
    proposals: list[dict] = []
    eval_result: dict[str, Any] = {}

    try:
        stdin_data = sys.stdin.read().strip()
        if stdin_data:
            data = json.loads(stdin_data)
            proposals = data.get("proposals", [])
            eval_result = data.get("evaluation", {})
    except Exception:
        pass

    if not proposals:
        print(json.dumps({"corrected_proposals": [], "error": "no proposals to debug"}))
        return 1

    # Build prompt and call LLM
    if eval_result.get("eval_mode") == "real_apply":
        sys.stderr.write("[DBG] eval mode: real_apply (proposals were applied to files)\n")
    if eval_result.get("clawcodex_stdout"):
        sys.stderr.write("[DBG] debug input: clawcodex_stdout available (" + str(len(eval_result["clawcodex_stdout"])) + " chars)\n")
    prompt = _build_debug_prompt(proposals, eval_result, debug_out=lambda msg: sys.stderr.write(msg + "\n"))
    raw = _call_llm(prompt)
    if not raw:
        # LLM call failed; return original proposals unchanged
        print(json.dumps({"corrected_proposals": proposals, "error": "LLM call failed"}))
        return 2

    # Extract JSON from LLM response
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        print(json.dumps({"corrected_proposals": proposals, "error": "no JSON in response"}))
        return 2

    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        print(json.dumps({"corrected_proposals": proposals, "error": "invalid JSON from LLM"}))
        return 2

    corrected = data.get("corrected_proposals", [])
    if not corrected:
        corrected = proposals  # fallback: return originals unchanged

    print(json.dumps({"corrected_proposals": corrected}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
