"""Runtime guards blocking SDK *tool-discovery* exploration in SOP bundle mode.

Workspace config lookup (``spec.yaml``, ``*.yaml``), OPENJIUWEN_HOME runtime
data, and reads under the bundle manifest ``sdk_source_dir`` remain allowed.
Only searches that substitute Skill → ToolSearch → call are blocked.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any
_EXPLORATION_TOOLS = frozenset({"Grep", "Glob", "Read", "Bash"})

# Kebab tool ids / ToolSearch hints — searching for these means skipping ToolSearch.
_TOOL_DISCOVERY_RE = re.compile(
    r"\bopenjiuwen-[a-z0-9-]+\b|\bselect:[a-z0-9-]+\b|"
    r"team-memory(?:-dir)?|sharedmemorymanager-ensure-dir|"
    r"ensure[-_. ]?dir|sharedmemorymanager",
    re.IGNORECASE,
)

# Skill description logical paths wrongly glued onto workspace cwd.
_WRONG_SDK_WORKSPACE_PATH_RE = re.compile(
    r"jiuwenagent[/\\]openjiuwen|(?:^|[/\\])JiuwenAgent[/\\]openjiuwen",
    re.IGNORECASE,
)

# Workspace / runtime config the user may read before delegating.
_WORKSPACE_CONFIG_RE = re.compile(
    r"spec\.ya?ml|[^/\\]+\.ya?ml$|[^/\\]+\.json$|[^/\\]+\.toml$|"
    r"config\.|settings\.|\.clawcodex[/\\]",
    re.IGNORECASE,
)

# OPENJIUWEN_HOME runtime dirs (team workspaces, not SDK source or tool wrappers).
_RUNTIME_DATA_RE = re.compile(
    r"\.openjiuwen[/\\]|\.agent_teams[/\\]|team-workspace|team-memory[/\\]",
    re.IGNORECASE,
)

# Bash text-search stages in a pipeline (find alone is not tool-hunting).
_BASH_TEXT_SEARCH_RE = re.compile(
    r"\b(grep|rg|ripgrep)\b|xargs\s+(grep|rg)|-exec\s+(grep|rg)",
    re.IGNORECASE,
)

_PATH_CANDIDATE_RE = re.compile(
    r"(/(?:[^\s'\";|&]+)|"
    r"[A-Za-z]:[/\\][^\s'\";|&]+)",
)

# Common test/fixture directory segments under a source tree (not SDK-specific).
_SDK_TEST_TREE_SEGMENT_RE = re.compile(
    r"(?:^|[/\\])(?:tests|test|testing|fixtures|__tests__)(?:[/\\]|$)",
    re.IGNORECASE,
)

# Config/fixture discovery signals when combined with test-tree paths.
_FIXTURE_CONFIG_HUNT_RE = re.compile(
    r"\.ya?ml\b|\.json\b|\.toml\b|\bspec\.|config\.|fixture|"
    r"\*\.*\.(?:ya?ml|yml|json)|"
    r"find\b.*\.(?:ya?ml|yml|json)",
    re.IGNORECASE,
)

_DIAGNOSTIC_PATH_MARKERS = (
    "agent-tools/",
    "agent-tools\\",
    "/agent-tools/",
    "\\agent-tools\\",
)


def _current_agent_type(context: Any) -> str | None:
    agent_type = getattr(context, "agent_type", None)
    if isinstance(agent_type, str) and agent_type:
        return agent_type
    startup = getattr(context, "startup_agent", None)
    if startup is not None:
        st = getattr(startup, "agent_type", None)
        if isinstance(st, str) and st:
            return st
    return None


def _is_overview_agent(agent_type: str | None) -> bool:
    if not agent_type:
        return False
    return agent_type == "clawcodex-overview" or agent_type.endswith("-overview")


def _is_domain_agent(agent_type: str | None) -> bool:
    return bool(
        agent_type
        and agent_type.endswith("-agent")
        and not _is_overview_agent(agent_type)
    )


def _block_name(block: Any) -> str | None:
    if isinstance(block, dict):
        name = block.get("name")
        return name if isinstance(name, str) else None
    name = getattr(block, "name", None)
    return name if isinstance(name, str) else None


def _block_type(block: Any) -> str | None:
    if isinstance(block, dict):
        btype = block.get("type")
        return btype if isinstance(btype, str) else None
    btype = getattr(block, "type", None)
    return btype if isinstance(btype, str) else None


def _block_id(block: Any) -> str | None:
    if isinstance(block, dict):
        tid = block.get("id")
        return tid if isinstance(tid, str) else None
    tid = getattr(block, "id", None)
    return tid if isinstance(tid, str) else None


def _result_tool_use_id(block: Any) -> str | None:
    if isinstance(block, dict):
        tid = block.get("tool_use_id")
        return tid if isinstance(tid, str) else None
    tid = getattr(block, "tool_use_id", None)
    return tid if isinstance(tid, str) else None


def _result_is_error(block: Any) -> bool:
    if isinstance(block, dict):
        return bool(block.get("is_error"))
    return bool(getattr(block, "is_error", False))


def _skill_invoked(messages: list[Any] | None) -> bool:
    for msg in messages or []:
        content = getattr(msg, "content", None)
        if not isinstance(content, list):
            continue
        for block in content:
            if _block_type(block) == "tool_use" and _block_name(block) == "Skill":
                return True
    return False


def _sdk_tool_call_failed(messages: list[Any] | None) -> bool:
    sdk_use_ids: set[str] = set()
    for msg in messages or []:
        content = getattr(msg, "content", None)
        if not isinstance(content, list):
            continue
        for block in content:
            btype = _block_type(block)
            if btype == "tool_use":
                name = _block_name(block) or ""
                tid = _block_id(block)
                if tid and name.lower().startswith("openjiuwen-"):
                    sdk_use_ids.add(tid)
            elif btype == "tool_result":
                tid = _result_tool_use_id(block)
                if tid and tid in sdk_use_ids and _result_is_error(block):
                    return True
    return False


def _path_text(tool_name: str, tool_input: dict[str, Any]) -> str:
    if tool_name == "Read":
        return str(tool_input.get("file_path") or "")
    if tool_name == "Glob":
        parts = [str(tool_input.get("path") or ""), str(tool_input.get("pattern") or "")]
        return " ".join(parts)
    if tool_name == "Grep":
        parts = [
            str(tool_input.get("path") or ""),
            str(tool_input.get("glob") or ""),
            str(tool_input.get("pattern") or ""),
        ]
        return " ".join(parts)
    if tool_name == "Bash":
        return str(tool_input.get("command") or "")
    return ""


def _normalized_path_text(text: str) -> str:
    return text.replace("\\", "/")


def _wsl_to_windows_path(text: str) -> str | None:
    """Map ``/mnt/d/projects/...`` → ``D:/projects/...`` on Windows."""
    if sys.platform != "win32":
        return None
    norm = _normalized_path_text(text).lower()
    match = re.match(r"^/mnt/([a-z])/(.+)$", norm)
    if not match:
        return None
    return f"{match.group(1).upper()}:/{match.group(2)}"


def _fix_windows_mnt_resolution(text: str) -> str:
    """Undo ``Path('/mnt/d/...').resolve()`` → ``D:/mnt/d/...`` on Windows."""
    if sys.platform != "win32":
        return _normalized_path_text(text)
    norm = _normalized_path_text(text)
    match = re.match(r"^([A-Za-z]):/mnt/[a-z]/(.+)$", norm, re.IGNORECASE)
    if match:
        return f"{match.group(1).upper()}:/{match.group(2)}"
    return norm


def _normalize_sdk_source_dir(sdk: Path) -> Path:
    raw = _normalized_path_text(str(sdk))
    wsl = _wsl_to_windows_path(raw)
    if wsl is not None:
        return Path(wsl)
    fixed = _fix_windows_mnt_resolution(raw)
    if fixed != raw:
        return Path(fixed)
    try:
        return sdk.expanduser().resolve()
    except OSError:
        return sdk


def _sdk_root_match_prefixes(sdk_root: Path) -> tuple[str, ...]:
    """Normalized lowercase path prefixes that identify the authorized SDK root."""
    prefixes: set[str] = set()
    for candidate in (sdk_root, _normalize_sdk_source_dir(sdk_root)):
        norm = _fix_windows_mnt_resolution(_normalized_path_text(str(candidate))).lower().rstrip("/")
        if norm:
            prefixes.add(norm)
        wsl = _wsl_to_windows_path(norm)
        if wsl:
            prefixes.add(wsl.lower().rstrip("/"))
    return tuple(sorted(prefixes, key=len, reverse=True))


def _normalize_candidate_path(raw: str) -> Path:
    norm = _normalized_path_text(raw)
    wsl = _wsl_to_windows_path(norm)
    if wsl is not None:
        return Path(wsl)
    fixed = _fix_windows_mnt_resolution(norm)
    if fixed != norm:
        return Path(fixed)
    return Path(raw)


def _resolve_sdk_source_dir(context: Any) -> Path | None:
    bundle = getattr(context, "bundle_context", None)
    if bundle is None:
        try:
            from extensions.sop_converter.bundle_context import get_active_bundle

            bundle = get_active_bundle()
        except ImportError:
            bundle = None
    if bundle is None:
        return None
    sdk = getattr(bundle, "sdk_source_dir", None)
    if sdk is None:
        return None
    try:
        resolved = _normalize_sdk_source_dir(Path(sdk))
    except OSError:
        return None
    return resolved


def _path_is_under_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _candidate_paths_from_text(text: str) -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()
    for match in _PATH_CANDIDATE_RE.finditer(text):
        raw = match.group(1).strip().strip("'\"")
        raw = raw.rstrip("/\\")
        if not raw or raw in seen:
            continue
        seen.add(raw)
        try:
            candidates.append(_normalize_candidate_path(raw))
        except OSError:
            continue
    return candidates


def _path_is_under_sdk_root(path: Path, sdk_root: Path) -> bool:
    roots = (_normalize_sdk_source_dir(sdk_root), sdk_root)
    for root in roots:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except (ValueError, OSError):
            continue
    return False


def _text_targets_sdk_source(text: str, sdk_root: Path) -> bool:
    for candidate in _candidate_paths_from_text(text):
        if _path_is_under_sdk_root(candidate, sdk_root):
            return True
    text_norm = _fix_windows_mnt_resolution(_normalized_path_text(text)).lower()
    for prefix in _sdk_root_match_prefixes(sdk_root):
        if prefix and text_norm.startswith(prefix):
            return True
        if prefix and prefix in text_norm:
            return True
    return False


def _looks_like_sdk_test_tree_fixture_hunt(
    tool_name: str,
    tool_input: dict[str, Any],
    *,
    sdk_root: Path | None,
) -> bool:
    """Block config/fixture hunting under generic ``tests/`` / ``fixtures/`` in SDK source."""
    if sdk_root is None:
        return False
    text = _path_text(tool_name, tool_input)
    if not text.strip() or not _text_targets_sdk_source(text, sdk_root):
        return False
    norm = _normalized_path_text(text)
    if not _SDK_TEST_TREE_SEGMENT_RE.search(norm):
        return False
    if _FIXTURE_CONFIG_HUNT_RE.search(norm):
        return True
    if tool_name == "Bash" and re.search(r"\bfind\b", text, re.IGNORECASE):
        return True
    if tool_name == "Glob" and re.search(r"\*\.(?:ya?ml|yml|json)", text, re.IGNORECASE):
        return True
    return False


def _sdk_test_tree_block_message() -> str:
    return (
        "SOP bundle mode: do not search SDK source-tree tests/fixtures directories for "
        "user config or launcher scripts. Use workspace user config (spec.yaml, etc.) and "
        "follow 「交互式终端停损」— give the user a real-terminal command from the task guide / "
        "ToolSearch tool / wrapper _SOURCE_DIR public API."
    )


def _is_diagnostic_path(path_text: str) -> bool:
    lowered = _normalized_path_text(path_text).lower()
    return any(marker.replace("\\", "/") in lowered for marker in _DIAGNOSTIC_PATH_MARKERS)


def _looks_like_workspace_config_access(tool_name: str, tool_input: dict[str, Any]) -> bool:
    text = _path_text(tool_name, tool_input)
    if not text.strip():
        return False
    if tool_name == "Bash" and _bash_looks_like_tool_hunt(text):
        return False
    norm = _normalized_path_text(text)
    if _WORKSPACE_CONFIG_RE.search(norm):
        return True
    if tool_name == "Bash" and _looks_like_runtime_data_bash(text):
        return True
    if tool_name in {"Glob", "Read", "Grep"} and _RUNTIME_DATA_RE.search(norm):
        return True
    return False


def _looks_like_runtime_data_bash(cmd: str) -> bool:
    """``ls`` / ``find -type f`` under ``~/.openjiuwen`` — runtime data, not tool hunting."""
    if not _RUNTIME_DATA_RE.search(_normalized_path_text(cmd)):
        return False
    if re.search(r"\bls\b", cmd, re.IGNORECASE):
        return True
    if re.search(r"\bfind\b", cmd, re.IGNORECASE) and not _BASH_TEXT_SEARCH_RE.search(cmd):
        return True
    return False


def _bash_looks_like_tool_hunt(cmd: str) -> bool:
    if _TOOL_DISCOVERY_RE.search(cmd):
        return True
    if "agent-tools" in cmd.lower():
        return True
    if not _BASH_TEXT_SEARCH_RE.search(cmd):
        return False
    if _TOOL_DISCOVERY_RE.search(cmd):
        return True
    if re.search(
        r"team[-_.]?memory[-_.]?dir|ensure[-_.]?dir|sharedmemorymanager|openjiuwen-[a-z0-9-]+",
        cmd,
        re.IGNORECASE,
    ):
        return True
    return False


def _looks_like_wrong_workspace_sdk_path(
    text: str,
    context: Any,
    sdk_root: Path | None,
) -> bool:
    """Block ``<workspace>/JiuwenAgent/openjiuwen/...`` — not the manifest SDK root."""
    norm = _normalized_path_text(text)
    if not _WRONG_SDK_WORKSPACE_PATH_RE.search(norm):
        return False
    if sdk_root is not None and _text_targets_sdk_source(text, sdk_root):
        return False

    workspace = getattr(context, "workspace_root", None) or getattr(context, "cwd", None)
    if workspace is not None:
        try:
            ws = Path(str(workspace)).expanduser().resolve()
            for candidate in _candidate_paths_from_text(text):
                if _path_is_under_root(candidate, ws):
                    if _WRONG_SDK_WORKSPACE_PATH_RE.search(_normalized_path_text(str(candidate))):
                        return True
        except OSError:
            pass

    if re.search(r"(?<![:/\\])JiuwenAgent[/\\]openjiuwen", norm, re.IGNORECASE):
        return True
    return False


def _looks_like_authorized_sdk_source_access(
    tool_name: str,
    tool_input: dict[str, Any],
    sdk_root: Path | None,
) -> bool:
    """Allow Read/Glob/Grep/ls under bundle ``sdk_source_dir`` for source understanding."""
    if sdk_root is None:
        return False
    text = _path_text(tool_name, tool_input)
    if not text.strip() or not _text_targets_sdk_source(text, sdk_root):
        return False

    if _looks_like_sdk_test_tree_fixture_hunt(tool_name, tool_input, sdk_root=sdk_root):
        return False

    if tool_name == "Grep":
        pattern = str(tool_input.get("pattern") or "")
        return not _TOOL_DISCOVERY_RE.search(pattern)

    if tool_name == "Bash":
        return not _bash_looks_like_tool_hunt(text)

    return tool_name in {"Read", "Glob"}


def _looks_like_sdk_tool_discovery(
    tool_name: str,
    tool_input: dict[str, Any],
    *,
    context: Any,
    sdk_root: Path | None,
) -> bool:
    """True when exploration is trying to locate a deferred SDK tool/API by name."""
    text = _path_text(tool_name, tool_input)
    if not text.strip():
        return False
    if tool_name == "Bash":
        if _looks_like_runtime_data_bash(text):
            return False
        return _bash_looks_like_tool_hunt(text)
    if _TOOL_DISCOVERY_RE.search(text):
        return True
    if _looks_like_wrong_workspace_sdk_path(text, context, sdk_root):
        return True
    return False


def _overview_block_message(tool_name: str, agent_definitions: list[Any]) -> str:
    domain_agents = [
        getattr(a, "agent_type", "")
        for a in agent_definitions
        if isinstance(getattr(a, "agent_type", ""), str)
        and str(getattr(a, "agent_type", "")).endswith("-agent")
        and getattr(a, "agent_type", "") != "clawcodex-overview"
    ]
    domain_agents = sorted(set(domain_agents))
    examples = ", ".join(f'Agent(subagent_type="{n}", prompt="...")' for n in domain_agents[:3])
    if len(domain_agents) > 3:
        examples += ", ..."
    return (
        f"SOP bundle mode: do not use {tool_name} to hunt SDK tool names/schemas — "
        f"use Skill → ToolSearch → SDK tool, or delegate: {examples}. "
        f"Workspace config (spec.yaml), runtime data under ~/.openjiuwen, and "
        f"reads under the bundle SDK source root are still allowed."
    )


def _domain_block_message(tool_name: str, *, need_skill: bool) -> str:
    if need_skill:
        return (
            f"SOP bundle mode: for SDK API calls, call Skill(...) first, then ToolSearch. "
            f"Do not use {tool_name} to search for kebab tool names. "
            f"Reading workspace config (spec.yaml) or SDK source under sdk_source_dir is allowed."
        )
    return (
        f"SOP bundle mode: ToolSearch already identifies the SDK tool — call it directly. "
        f"Do not use {tool_name} to look up tool definitions. "
        f"If the SDK tool failed, follow the limited diagnostic steps in your system prompt."
    )


def check_bundle_source_exploration(
    tool_name: str,
    tool_input: dict[str, Any] | None,
    context: Any,
    *,
    agent_definitions: list[Any] | None = None,
) -> str | None:
    """Return an error message when exploration should be blocked."""
    try:
        from extensions.sop_converter.bundle_context import get_active_bundle
    except ImportError:
        return None

    if get_active_bundle() is None:
        return None

    if tool_name not in _EXPLORATION_TOOLS:
        return None

    tool_input = tool_input or {}
    sdk_root = _resolve_sdk_source_dir(context)

    path_text = _path_text(tool_name, tool_input)
    if _looks_like_sdk_test_tree_fixture_hunt(tool_name, tool_input, sdk_root=sdk_root):
        return _sdk_test_tree_block_message()

    if _looks_like_workspace_config_access(tool_name, tool_input):
        return None

    if _looks_like_authorized_sdk_source_access(tool_name, tool_input, sdk_root):
        return None

    agent_type = _current_agent_type(context)
    messages = getattr(context, "messages", None) or []

    if _is_diagnostic_path(_path_text(tool_name, tool_input)):
        if _sdk_tool_call_failed(messages):
            return None
        if not _is_overview_agent(agent_type):
            return (
                f"SOP bundle mode: read agent-tools specs only after an SDK tool call fails. "
                f"Complete Skill → ToolSearch → SDK tool first."
            )

    discovery = _looks_like_sdk_tool_discovery(
        tool_name,
        tool_input,
        context=context,
        sdk_root=sdk_root,
    )
    if not discovery:
        return None

    if _is_overview_agent(agent_type):
        defs = agent_definitions
        if defs is None:
            defs = _load_agent_definitions(context)
        return _overview_block_message(tool_name, defs or [])

    if _is_domain_agent(agent_type):
        if not _skill_invoked(messages):
            return _domain_block_message(tool_name, need_skill=True)
        if not _sdk_tool_call_failed(messages):
            return _domain_block_message(tool_name, need_skill=False)

    return None


def _load_agent_definitions(context: Any) -> list[Any]:
    try:
        from clawcodex_ext.agent.load_agents_dir import get_agent_definitions_with_overrides

        cwd = str(getattr(context, "cwd", None) or getattr(context, "workspace_root", ".") or ".")
        agents = list(get_agent_definitions_with_overrides(cwd))
        ad_override = getattr(context, "_agent_dir_override", None)
        if ad_override is not None:
            extra = get_agent_definitions_with_overrides(str(ad_override))
            extra_types = {a.agent_type for a in extra}
            agents = [a for a in agents if a.agent_type not in extra_types]
            agents.extend(extra)
        return agents
    except Exception:
        return []


def sop_exploration_permission_check(
    tool_name: str,
    tool_input: dict[str, Any] | None,
    context: Any,
):
    """Permission hook helper — deny when SOP exploration guard fires."""
    from clawcodex_ext.permissions.types import (
        PermissionDenyDecision,
        PermissionPassthroughResult,
    )

    message = check_bundle_source_exploration(tool_name, tool_input, context)
    if message:
        return PermissionDenyDecision(message=message)
    return PermissionPassthroughResult()
