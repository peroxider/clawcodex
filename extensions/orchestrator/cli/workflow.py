"""orchestrator workflow — scaffold a workflow.md from the packaged template.

Usage (noun-verb):
  clawcodex orchestrator workflow init [--kind <tracker>] [--owner <o>] [--repo <r>]

Design:
  - Copies the workflow template from the package to the current directory.
  - Replaces ``{{PLACEHOLDER}}`` tokens with user-provided values.
  - The template path is resolved from the installed package, so users
    who installed via ``pip`` (no source tree) can still generate a
    workflow.md without manually hunting for template files.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


# ── Template resolution ──────────────────────────────────────────────

def _template_path(variant: str = "workflow") -> Path:
    """Return the path to ``{variant}.template.md`` inside the package.

    Works for both editable installs (source tree) and non-editable
    installs (site-packages zip / wheel).

    Raises ``FileNotFoundError`` if the variant does not exist.
    """
    import extensions.orchestrator.templates as tpl_mod

    # Try named variant first, fall back to "workflow" generic name
    candidates = [f"{variant}.template.md", "workflow.template.md"]

    for p in tpl_mod.__path__:  # type: ignore[attr-defined]
        for name in candidates:
            candidate = Path(p) / name
            if candidate.exists():
                return candidate

    # Python 3.9+ importlib.resources API as second resort
    try:
        from importlib.resources import files
        for name in candidates:
            ref = files("extensions.orchestrator.templates") / name  # type: ignore[arg-type]
            if hasattr(ref, "__fspath__"):
                p = Path(ref.__fspath__())
                if p.exists():
                    return p
            # MultiplexedPath
            if str(ref) and Path(str(ref)).exists():
                return Path(str(ref))
    except Exception:
        pass

    # Last resort: walk sys.modules for the orchestrator package
    import extensions.orchestrator as orch_mod
    base = Path(orch_mod.__file__).parent  # type: ignore[arg-type]
    for name in candidates:
        candidate = base / "templates" / name
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        f"Cannot locate template '{variant}' — your install may be corrupt. "
        f"Run 'clawcodex orchestrator workflow list-templates' to see available variants."
    )


def _available_templates() -> dict[str, str]:
    """Return {variant_name: template_path} for all packaged templates."""
    import extensions.orchestrator.templates as tpl_mod
    templates: dict[str, str] = {}
    for p in tpl_mod.__path__:  # type: ignore[attr-defined]
        for f in Path(p).glob("*.template.md"):
            name = f.stem  # e.g. "workflow" or "workflow-local"
            templates[name] = str(f)
    return templates


# ── Placeholder substitution ─────────────────────────────────────────

def _prompt(label: str, default: str = "", secret: bool = False) -> str:
    """Prompt interactively, or return *default* when stdin is not a TTY."""
    if not sys.stdin.isatty():
        return default
    try:
        if secret:
            import getpass
            raw = getpass.getpass(f"  {label} [{default}]: ")
        else:
            raw = input(f"  {label} [{default}]: ")
        return raw.strip() or default
    except (EOFError, KeyboardInterrupt):
        return default


def _fill_placeholders(content: str, values: dict[str, str]) -> str:
    """Replace ``{{KEY}}`` placeholders with corresponding *values*."""
    for key, val in values.items():
        content = content.replace("{{" + key + "}}", val)
        # Also replace ${{KEY}}_ENV style
        content = content.replace("${{" + key + "_ENV}}", val)
    return content


# ── Parser ───────────────────────────────────────────────────────────

def add_workflow_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register ``workflow`` sub-subcommands (init | list-templates)."""
    parser = subparsers.add_parser(
        "workflow",
        help="Scaffold and manage orchestrator workflow files",
        description="Generate ``workflow.md`` from the packaged template, "
                    "or list available template variants.",
    )
    wf_sub = parser.add_subparsers(
        dest="workflow_subcommand",
        required=True,
    )

    # --- workflow init ---
    init_parser = wf_sub.add_parser(
        "init",
        help="Generate workflow.md from template",
        description="Copy the packaged workflow template to the current directory "
                    "and replace placeholders with your values.",
    )
    init_parser.add_argument(
        "--template", "-t",
        default="workflow",
        metavar="VARIANT",
        help="Template variant: workflow (default, remote tracker), "
             "workflow-local (local file-based tracker). "
             "Run 'list-templates' to see all available variants.",
    )
    init_parser.add_argument(
        "--kind", "-k",
        default="",
        metavar="TRACKER",
        help="Tracker kind: github, gitcode, gitee, linear, local (default: prompt)",
    )
    init_parser.add_argument(
        "--owner", "-o",
        default="",
        metavar="OWNER",
        help="Repository owner (e.g. my-org)",
    )
    init_parser.add_argument(
        "--repo", "-r",
        default="",
        metavar="REPO",
        help="Repository name (e.g. my-project)",
    )
    init_parser.add_argument(
        "--endpoint",
        default="",
        metavar="URL",
        help="API endpoint for self-hosted instances",
    )
    init_parser.add_argument(
        "--assignee",
        default="",
        metavar="USER",
        help="Only process issues assigned to this user",
    )
    init_parser.add_argument(
        "--branch-prefix",
        default="clawcodex",
        metavar="PREFIX",
        help="Branch prefix for issue branches (default: clawcodex)",
    )
    init_parser.add_argument(
        "--workspace-root",
        default="/tmp/symphony_workspaces/myproject",
        metavar="PATH",
        help="Local workspace root path",
    )
    init_parser.add_argument(
        "--output", "--out",
        default="workflow.md",
        metavar="FILE",
        help="Output file path (default: ./workflow.md)",
    )
    init_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Skip prompts; use defaults for missing values",
    )

    # --- workflow list-templates ---
    list_parser = wf_sub.add_parser(
        "list-templates",
        help="List available workflow template variants",
        description="Show all packaged template files and their locations.",
    )


# ── Dispatch ─────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> int:
    """Dispatch to the appropriate workflow subcommand."""
    cmd = args.workflow_subcommand
    if cmd == "init":
        return _run_init(args)
    elif cmd == "list-templates":
        return _run_list_templates(args)
    print(f"error: unknown workflow subcommand '{cmd}'", file=sys.stderr)
    return 2


# ── Implementations ──────────────────────────────────────────────────

def _run_init(args: argparse.Namespace) -> int:
    """Copy and fill the workflow template."""
    variant = args.template or "workflow"

    # Locate template
    try:
        tpl = _template_path(variant)
    except FileNotFoundError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1

    # Determine output path
    out = Path(args.output).expanduser().resolve()
    if out.exists():
        print(f"✗ {out} already exists — remove it first or use --output", file=sys.stderr)
        return 1

    interactive = sys.stdin.isatty() and not args.non_interactive

    # Gather values (flag → prompt → default)
    def val(flag_val: str, label: str, default: str = "") -> str:
        if flag_val:
            return flag_val
        if interactive:
            return _prompt(label, default)
        return default

    kind = val(args.kind, "Tracker kind (github/gitcode/gitee/linear/local)", "github")
    owner = val(args.owner, "Repository owner")
    repo = val(args.repo, "Repository name")
    endpoint = val(args.endpoint, "API endpoint (leave blank for default)")
    assignee = val(args.assignee, "Issue assignee (leave blank for all)")
    branch_prefix = val(args.branch_prefix, "Branch prefix", "clawcodex")
    ws_root = val(args.workspace_root, "Workspace root", "/tmp/symphony_workspaces/myproject")

    # Build clone_url
    clone_url = ""
    push_user = ""
    if kind in ("github", "gitcode", "gitee"):
        domains = {"github": "github.com", "gitcode": "gitcode.com", "gitee": "gitee.com"}
        domain = domains.get(kind, "github.com")
        if owner and repo:
            clone_url = f"https://{domain}/{owner}/{repo}.git"
            push_user = owner

    # Determine token env var
    token_env_map = {
        "github": "GITHUB_TOKEN",
        "gitcode": "GITCODE_TOKEN",
        "gitee": "GITEE_TOKEN",
        "linear": "LINEAR_API_KEY",
    }
    token_env = token_env_map.get(kind, "TRACKER_API_KEY")

    # Determine tracker endpoint
    endpoint_defaults = {
        "gitcode": "https://api.gitcode.com/api/v5",
        "gitee": "https://gitee.com/api/v5",
    }
    if not endpoint:
        endpoint = endpoint_defaults.get(kind, "")

    # Build substitution map
    values = {
        "TRACKER_KIND": kind,
        "TRACKER_ENDPOINT": endpoint,
        "REPO_OWNER": owner,
        "REPO_NAME": repo,
        "REPO_CLONE_URL": clone_url,
        "TRACKER_API_KEY_ENV": token_env,
        "REPO_ASSIGNEE": assignee,
        "BRANCH_PREFIX": branch_prefix,
        "WORKSPACE_ROOT": ws_root,
        "GIT_PUSH_USER": push_user,
        "GIT_PUSH_TOKEN_ENV": token_env,
        "REPO_URL": clone_url.removesuffix(".git") if clone_url else "",
    }

    # Read and fill template
    raw = tpl.read_text(encoding="utf-8")
    filled = _fill_placeholders(raw, values)

    # Write
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(filled, encoding="utf-8")

    print(f"✓ Generated {out}")
    print()
    print("  Next steps:")
    print(f"    1. Edit {out.name} — check every {{PLACEHOLDER}} was replaced")
    print(f"    2. Set the required env var: export {token_env}=<your-token>")
    print(f"    3. Start: clawcodex orchestrator server start --workflow {out.name}")
    print()
    if interactive:
        print("  Hint: re-run with --non-interactive and CLI flags to skip prompts.")
    return 0


def _run_list_templates(args: argparse.Namespace) -> int:
    """List all available template files."""
    try:
        templates = _available_templates()
    except Exception as exc:
        print(f"✗ Cannot list templates: {exc}", file=sys.stderr)
        return 1

    print("Available workflow templates:")
    print()
    for name, path in sorted(templates.items()):
        print(f"  {name:30s}  {path}")
    print()
    print("Usage:  clawcodex orchestrator workflow init")
    return 0
