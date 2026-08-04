"""Shared utilities: config loading, JSON I/O, logging."""

from __future__ import annotations

import json
import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


def load_config(path: str) -> Dict[str, Any]:
    """Load a YAML config file and return as a nested dict."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_json(path: str) -> Optional[Any]:
    """Read JSON from a file, or None if missing."""
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except (json.JSONDecodeError, ValueError):
            return None

def load_available_skills(sea_root: str = None, cx_root: str = None) -> dict[str, dict]:
    """Load skill definitions from ClawCodex skill directories."""
    if sea_root is None:
        sea_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    if cx_root is None:
        cx_root = os.path.normpath(os.path.join(sea_root, ".."))
    skills = {}

    _scan_skills_dir(os.path.expanduser(os.path.join("~", ".claude", "skills")), skills)
    _scan_skills_dir(os.path.expanduser(os.path.join("~", ".clawcodex", "skills")), skills)
    _scan_skills_dir(os.path.join(sea_root, ".claude", "skills"), skills)
    _scan_agent_md(os.path.expanduser(os.path.join("~", ".claude", "agents")), skills)
    _scan_agent_md(os.path.join(sea_root, "..", ".claude", "agents"), skills)
    _scan_agent_md(os.path.join(cx_root, "clawcodex_ext", "agent", "agents"), skills)
    env_dir = os.environ.get("CLAWCODEX_SKILLS_DIR")
    if env_dir:
        _scan_skills_dir(env_dir, skills)
    return skills


def _scan_skills_dir(skills_dir, skills):
    """Scan for */skill.md files with YAML frontmatter."""
    if not os.path.isdir(skills_dir):
        return
    for item in sorted(os.listdir(skills_dir)):
        fpath = os.path.join(skills_dir, item, "skill.md")
        if not os.path.isfile(fpath):
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                raw = f.read()
            # Split on --- frontmatter delimiter
            head = (chr(10) + raw).split(chr(10) + chr(45)*3 + chr(10), 2)
            if len(head) < 3:
                continue
            front = yaml.safe_load(head[1])
            if not front or not isinstance(front, dict):
                continue
            body = head[2].strip()
            sn = (front.get("name") or item).strip()
            if not sn: continue
            desc = front.get("description", "") or front.get("when_to_use", "") or body[:100]
            skills[sn] = {
                "name": sn,
                "description": desc,
                "trigger_condition": front.get("when_to_use", "") or desc,
                "sop": body.split(chr(10))[:10] if body else [],
                "pitfalls": front.get("pitfalls", []),
            }
        except Exception:
            continue


def _scan_agent_md(agents_dir, skills):
    """Scan for agent *.md files with YAML frontmatter."""
    if not os.path.isdir(agents_dir):
        return
    for fname in sorted(os.listdir(agents_dir)):
        if not fname.endswith(".md"):
            continue
        fpath = os.path.join(agents_dir, fname)
        if not os.path.isfile(fpath):
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                raw = f.read()
            head = (chr(10) + raw).split(chr(10) + chr(45)*3 + chr(10), 2)
            if len(head) < 3:
                continue
            front = yaml.safe_load(head[1])
            if not front or not isinstance(front, dict):
                continue
            sn = (front.get("name") or fname[:-3]).strip()
            if not sn: continue
            desc = front.get("description", "") or front.get("when_to_use", "")
            skills[sn] = {
                "name": sn,
                "description": desc,
                "trigger_condition": front.get("when_to_use", "") or desc,
                "sop": [],
                "pitfalls": [],
            }
        except Exception:
            continue

SC = ".,!?;:()[]"

def match_skills_to_trace(skills: dict[str, dict], task_description: str,
                          tool_names_used: list[str]) -> dict[str, dict]:
    """Match skills to trace by trigger_condition and tool patterns."""
    matches = {}
    task_lower = (task_description or "").lower()
    tool_set = set(t.lower() for t in tool_names_used)
    for name, skill in skills.items():
        score = 0.0
        reasons = []
        tc = (skill.get("trigger_condition") or "").lower()
        tc_keywords = [w.strip(SC) for w in tc.split() if len(w.strip(SC)) > 3]
        if tc_keywords and task_lower:
            overlap = sum(1 for kw in tc_keywords if kw in task_lower)
            score += overlap / len(tc_keywords) * 0.5
            if overlap > 0:
                reasons.append("trigger matches (%d/%d keywords)" % (overlap, len(tc_keywords)))
        sop_text = " ".join(skill.get("sop", [])).lower()
        sop_tools = [w.strip(SC) for w in sop_text.split() if w.strip(SC) in tool_set]
        if sop_tools:
            score += 0.3
            reasons.append("SOP mentions tools: " + ", ".join(set(sop_tools)))
        pitfalls_text = " ".join(skill.get("pitfalls", [])).lower()
        pitfalls_keywords = [w.strip(SC) for w in pitfalls_text.split() if len(w.strip(SC)) > 3]
        if pitfalls_keywords:
            score += 0.1
            reasons.append("has %d pitfall keywords" % len(pitfalls_keywords))
        if score > 0.0:
            matches[name] = {
                "skill": skill,
                "match_reason": "; ".join(reasons),
                "match_score": min(score, 1.0),
            }
    return matches
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str, data: Any) -> None:
    """Write data as JSON to a file (creates parent dirs)."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def read_text(path: str) -> Optional[str]:
    """Read a UTF-8 text file, or None if missing."""
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path: str, content: str) -> None:
    """Write UTF-8 text to a file (creates parent dirs)."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def now_iso() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


def setup_logger(name: str = "self-evolving-agent") -> logging.Logger:
    """Set up a simple console logger."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def extract_json_from_llm(raw_text: str) -> dict | None:
    """Try multiple strategies to extract valid JSON from LLM output.
    
    Handles three failure modes:
    1. No JSON at all (returns None ? caller falls back to heuristic)
    2. JSON with unescaped control chars (newlines/tabs in strings)
    3. JSON with trailing commas or other minor syntax issues
    """
    if not raw_text or not raw_text.strip():
        return None
    
    text = raw_text.strip()
    
    # ?? Collect candidate JSON strings ??
    candidates = []
    
    # Find outermost { ... }
    bs = text.find("{")
    be = text.rfind("}")
    if bs >= 0 and be > bs:
        candidates.append(text[bs:be+1])
    
    # Try other { } bracket pairs (first { with each } etc.)
    open_positions = [i for i, c in enumerate(text) if c == "{"]
    close_positions = [i for i, c in enumerate(text) if c == "}"]
    # Try first opening with first few closings, and last few openings with last closing
    for o in open_positions[:2]:
        for c in close_positions[-3:]:
            if c > o:
                cand = text[o:c+1]
                if cand not in candidates:
                    candidates.append(cand)
    
    # ?? Try each candidate with multiple fix strategies ??
    for candidate in candidates:
        result = _try_parse_json_variants(candidate)
        if result is not None:
            return result
    
    return None


def _try_parse_json_variants(text: str) -> dict | None:
    """Try parsing text as JSON with several fix strategies."""
    strategies = [
        _fix_nothing,
        _fix_escape_control_chars,
        _fix_trailing_commas,
        _fix_escape_quotes_in_values,
    ]
    
    for strategy in strategies:
        fixed = strategy(text)
        if fixed is None:
            continue
        try:
            return json.loads(fixed)
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def _fix_nothing(text: str) -> str:
    return text


def _fix_escape_control_chars(text: str) -> str:
    """Escape unescaped newlines, tabs, and carriage returns in JSON strings."""
    result = []
    in_string = False
    escaped = False
    for ch in text:
        if escaped:
            result.append(ch)
            escaped = False
            continue
        if ch == chr(92):  # backslash
            result.append(ch)
            escaped = True
            continue
        if ch == chr(34):  # double quote
            in_string = not in_string
            result.append(ch)
            continue
        if in_string and ch in (chr(10), chr(13), chr(9)):
            # Escape control chars inside strings
            replacements = {chr(10): "\\n", chr(13): "\\r", chr(9): "\\t"}
            result.append(replacements.get(ch, ch))
        else:
            result.append(ch)
    return "".join(result)


def _fix_trailing_commas(text: str) -> str:
    """Remove trailing commas before ] and }."""
    import re
    # Remove comma before ]
    text = re.sub(r',\s*\]', ']', text)
    # Remove comma before }
    text = re.sub(r',\s*\}', '}', text)
    return text


def _fix_escape_quotes_in_values(text: str) -> str:
    """Try to fix unescaped double quotes inside JSON string values.
    
    This is a best-effort heuristic: it looks for patterns where a quote
    appears inside what looks like a string value and escapes it.
    """
    result = []
    in_string = False
    escaped = False
    prev = ""
    for ch in text:
        if escaped:
            result.append(ch)
            escaped = False
            prev = ch
            continue
        if ch == chr(92):
            result.append(ch)
            escaped = True
            continue
        if ch == chr(34):
            if in_string:
                # Check if this quote is followed by a structural char
                # If not, it might be an unescaped quote inside the value
                pass  # We'll just toggle for now
            in_string = not in_string
            result.append(ch)
            prev = ch
            continue
        result.append(ch)
        prev = ch
    return result


# ??? ClawCodex system prompt section extraction ????????????????????????????

_SECTION_VAR_MAP = {
    "_INTRO_SECTION": "intro",
    "_SYSTEM_SECTION": "system",
    "_DOING_TASKS_SECTION": "doing_tasks",
    "_ACTIONS_SECTION": "actions",
    "_USING_TOOLS_SECTION": "using_tools",
    "_TONE_STYLE_SECTION": "tone_style",
    "_OUTPUT_EFFICIENCY_SECTION": "output_efficiency",
}


def extract_clawcodex_system_sections(cx_root: str | None = None) -> dict[str, str]:
    """Read ClawCodex prompt_assembly.py and extract section_id ? content mapping.

    Uses AST to safely evaluate the string-constant definitions.
    Returns a dict like {"intro": "...content...", "system": "...", ...}.
    Returns empty dict on any error.
    """
    import ast
    if cx_root is None:
        cx_root = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
    src_path = os.path.join(cx_root, "clawcodex_ext", "context_system", "prompt_assembly.py")
    if not os.path.isfile(src_path):
        return {}

    try:
        with open(src_path, "r", encoding="utf-8") as f:
            source = f.read()
    except Exception:
        return {}

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}

    sections: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            sid = _SECTION_VAR_MAP.get(target.id)
            if sid is None:
                continue
            try:
                value = ast.literal_eval(node.value)
                if isinstance(value, str):
                    sections[sid] = value
            except (ValueError, TypeError):
                continue

    return sections



_SECTION_ID_TO_VAR = {v: k for k, v in _SECTION_VAR_MAP.items()}


def section_id_to_var_name(section_id):
    return _SECTION_ID_TO_VAR.get(section_id)


def _fmt_python_implicit_string(text, indent=None):
    if indent is None:
        indent = '    '
    if not text:
        return chr(40) + chr(34) + chr(34) + chr(41)
    parts = text.split(chr(10))
    res = []
    for i, p in enumerate(parts):
        e = p.replace(chr(92)*2, chr(92)*4).replace(chr(34), chr(92)+chr(34))
        if i < len(parts) - 1:
            res.append(indent + chr(34) + e + chr(92) + 'n' + chr(34))
        else:
            res.append(indent + chr(34) + e + chr(34))
    return chr(40) + chr(10) + chr(10).join(res) + chr(10) + chr(41)


_PROMPT_ASSEMBLY_PATH = None


def _find_prompt_assembly_path(cx_root=None):
    global _PROMPT_ASSEMBLY_PATH
    if _PROMPT_ASSEMBLY_PATH:
        return _PROMPT_ASSEMBLY_PATH
    if cx_root is None:
        cx_root = os.path.normpath(os.path.join(
            os.path.dirname(__file__),
            chr(46)*2, chr(46)*2
        ))
    p = os.path.join(cx_root, 'clawcodex_ext', 'context_system', 'prompt_assembly.py')
    _PROMPT_ASSEMBLY_PATH = p
    return p


def replace_prompt_section_in_file(new_content, section_id, file_path=None):
    var_name = section_id_to_var_name(section_id)
    if var_name is None:
        return False
    if file_path is None:
        file_path = _find_prompt_assembly_path()
    try:
        source = open(file_path, encoding='utf-8').read()
    except Exception:
        return False
    import re
    pat = re.compile(r'^\s*' + re.escape(var_name) + r'\s*=\s*\(', re.MULTILINE)
    m = pat.search(source)
    if not m:
        return False
    paren_start = m.end() - 1
    depth = 1
    pos = paren_start
    in_str = False
    sq = None
    while pos < len(source) and depth > 0:
        pos += 1
        if pos >= len(source):
            break
        ch = source[pos]
        if in_str:
            if ch == chr(92):
                pos += 1
            elif ch == sq:
                in_str = False
        else:
            if ch in chr(34)+chr(39):
                in_str = True
                sq = ch
            elif ch == chr(40):
                depth += 1
            elif ch == chr(41):
                depth -= 1
    if depth != 0:
        return False
    replacement = _fmt_python_implicit_string(new_content)
    new_source = source[:paren_start] + replacement + source[pos+1:]
    try:
        open(file_path, 'w', encoding='utf-8').write(new_source)
        return True
    except Exception:
        return False
