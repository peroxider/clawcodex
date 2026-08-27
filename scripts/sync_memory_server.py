#!/usr/bin/env python3
"""Safely sync the bundled memory server from memory-benchmarks.

The source package is developed as ``improved_memory_server`` while ClawCodex
embeds it as ``clawcodex_ext.latent_memory.server``.  This script rewrites that package
name and reapplies the small set of ClawCodex runtime adaptations before it
writes anything.

Usage::

    python scripts/sync_memory_server.py                 # preview
    python scripts/sync_memory_server.py --apply         # validate, confirm, apply
    python scripts/sync_memory_server.py --apply --yes   # non-interactive apply
    python scripts/sync_memory_server.py --check         # CI: fail if out of sync
"""

from __future__ import annotations

import argparse
import ast
import difflib
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = REPO_ROOT.parent / "memory-benchmarks" / "improved_memory_server"
DEFAULT_TARGET = REPO_ROOT / "clawcodex_ext" / "latent_memory" / "server"

IMPORT_SRC = "improved_memory_server"
IMPORT_DST = "clawcodex_ext.latent_memory.server"

SKIP_DIRS = {"__pycache__", "tests", ".pytest_cache", ".mypy_cache", "node_modules"}
SKIP_SUFFIXES = {".pyc", ".pyo"}

# These files belong to the embedding repository rather than the upstream
# implementation.  A colliding source file (README.md) deliberately loses.
CLAWCODEX_ONLY = {
    "README.md",
    "daemon.py",
    "memory.env.example",
    "环境配置使用说明.md",
}

# Known files removed by the authoritative implementation.  Listing these
# explicitly avoids deleting an unrecognized ClawCodex customization.
OBSOLETE_FILES = {"lib/solidification/migrate.py"}

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


class SyncError(RuntimeError):
    """Raised when a safe, complete sync cannot be produced."""


@dataclass(frozen=True)
class RenderedFile:
    relative_path: str
    content: bytes


@dataclass(frozen=True)
class SyncPlan:
    new: tuple[str, ...]
    changed: tuple[str, ...]
    unchanged: tuple[str, ...]
    target_only: tuple[str, ...]
    removed: tuple[str, ...]

    @property
    def writes(self) -> tuple[str, ...]:
        return self.new + self.changed

    @property
    def actions(self) -> tuple[str, ...]:
        return self.writes + self.removed


def _configure_console() -> None:
    """Avoid crashing on source text that the active Windows code page cannot encode."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(errors="backslashreplace")


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def collect_files(root: Path) -> set[str]:
    """Collect production files, excluding caches and source-package tests."""
    result: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name not in SKIP_DIRS)
        directory = Path(dirpath)
        for filename in filenames:
            if Path(filename).suffix in SKIP_SUFFIXES:
                continue
            result.add(_relative(directory / filename, root))
    return result


def _replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SyncError(f"{label}: expected one source pattern, found {count}")
    return text.replace(old, new, 1)


def _replace_function(text: str, name: str, replacement: str) -> str:
    """Replace one top-level function while preserving the rest of the source file."""
    tree = ast.parse(text)
    matches = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    if len(matches) != 1:
        raise SyncError(f"config.py: expected one {name}() function, found {len(matches)}")
    node = matches[0]
    lines = text.splitlines(keepends=True)
    start = node.lineno - 1
    end = node.end_lineno or node.lineno
    while end < len(lines) and not lines[end].strip():
        end += 1
    normalized = replacement.rstrip() + "\n\n\n"
    return "".join(lines[:start]) + normalized + "".join(lines[end:])


def rewrite_imports(text: str) -> str:
    return text.replace(IMPORT_SRC, IMPORT_DST)


_CLAW_CONFIG_PREAMBLE = '''def memory_state_dir() -> Path:
    """Return the persistent state directory used by the bundled service."""
    configured = os.getenv("CLAWCODEX_MEMORY_STATE_DIR")
    if configured:
        return Path(configured).expanduser()
    config_root = Path(
        os.getenv("CLAWCODEX_CONFIG_DIR", str(Path.home() / ".clawcodex"))
    ).expanduser()
    return config_root / "memory"


def configured_mem0_path() -> Path | None:
    configured = os.getenv("MEM0_CONFIG_PATH", "").strip()
    return Path(configured).expanduser() if configured else None
'''


_CLAW_DEFAULT_HISTORY = '''def default_history_db_path() -> str:
    """返回历史记录数据库路径，优先从环境变量读取。"""
    return os.getenv("HISTORY_DB_PATH", str(memory_state_dir() / "history.db"))
'''


_CLAW_VECTOR_CONFIG = '''def build_vector_store_config(config: dict[str, Any]) -> dict[str, Any]:
    """Build a remote or local Qdrant configuration for the bundled service."""
    vector_store_config: dict[str, Any] = {
        "collection_name": os.getenv("COLLECTION_NAME", "memories"),
    }
    qdrant_url = os.getenv("QDRANT_URL", "").strip()
    qdrant_host = os.getenv("QDRANT_HOST", "").strip()
    qdrant_api_key = os.getenv("QDRANT_API_KEY", "").strip()
    if qdrant_url:
        parsed = urlparse(qdrant_url)
        if not parsed.hostname:
            raise ValueError("QDRANT_URL must include a hostname")
        vector_store_config["url"] = qdrant_url
        if qdrant_api_key:
            vector_store_config["api_key"] = qdrant_api_key
    elif qdrant_host:
        vector_store_config.update(
            {"host": qdrant_host, "port": int(os.getenv("QDRANT_PORT", "6333"))}
        )
    else:
        vector_store_config.update(
            {
                "path": os.getenv("QDRANT_PATH", str(memory_state_dir() / "qdrant")),
                "on_disk": True,
            }
        )
    embedding_dims = config.get("embedder", {}).get("config", {}).get("embedding_dims")
    if embedding_dims:
        vector_store_config["embedding_model_dims"] = embedding_dims
    return {"provider": "qdrant", "config": vector_store_config}
'''


_SOURCE_CONFIG_FALLBACK = """    logger.info("未找到配置文件; 从环境变量构建默认配置")
    config = {
        "version": "v1.1",
        "vector_store": build_vector_store_config({}),
        "llm": {
            "provider": os.getenv("LLM_PROVIDER", "openai"),
            "config": {
                "model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
                "temperature": 0.1,
            },
        },
        "embedder": {
            "provider": os.getenv("EMBEDDER_PROVIDER", "openai"),
            "config": {
                "model": os.getenv("EMBEDDER_MODEL", "text-embedding-3-small"),
            },
        },
        "history_db_path": default_history_db_path(),
    }
    inject_add_retry_config(config)
    return config
"""


_CLAW_CONFIG_FALLBACK = """    logger.info("未找到配置文件; 从环境变量构建默认配置")
    llm_provider = os.getenv("LLM_PROVIDER", "openai")
    embedder_provider = os.getenv("EMBEDDER_PROVIDER", "openai")
    llm_config: dict[str, Any] = {
        "model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
        "temperature": 0.1,
    }
    embedder_config: dict[str, Any] = {
        "model": os.getenv("EMBEDDER_MODEL", "text-embedding-3-small"),
    }
    ollama_base_url = os.getenv("OLLAMA_BASE_URL") or os.getenv("OLLAMA_HOST")
    if ollama_base_url and llm_provider == "ollama":
        llm_config["ollama_base_url"] = ollama_base_url
    if ollama_base_url and embedder_provider == "ollama":
        embedder_config["ollama_base_url"] = ollama_base_url
    embedding_dims = os.getenv("EMBEDDING_DIMS", "").strip()
    if embedding_dims:
        embedder_config["embedding_dims"] = int(embedding_dims)

    provider_config = {
        "llm": {"provider": llm_provider, "config": llm_config},
        "embedder": {"provider": embedder_provider, "config": embedder_config},
    }
    config = {
        "version": "v1.1",
        "vector_store": build_vector_store_config(provider_config),
        **provider_config,
        "history_db_path": default_history_db_path(),
    }
    inject_add_retry_config(config)
    return config
"""


def _adapt_config(text: str) -> str:
    text = _replace_once(
        text,
        "from typing import Any\n",
        "from typing import Any\nfrom urllib.parse import urlparse\n",
        label="config.py urllib import",
    )
    text = _replace_once(
        text,
        'CONFIG_PATH = Path(os.getenv("MEM0_CONFIG_PATH", "/app/config.yaml"))',
        _CLAW_CONFIG_PREAMBLE.rstrip(),
        label="config.py state-directory preamble",
    )
    text = _replace_function(text, "default_history_db_path", _CLAW_DEFAULT_HISTORY)
    text = _replace_function(text, "build_vector_store_config", _CLAW_VECTOR_CONFIG)
    text = _replace_once(
        text,
        "    path = config_path or CONFIG_PATH",
        "    path = config_path or configured_mem0_path()",
        label="config.py optional config path",
    )
    text = _replace_once(
        text,
        "    if path.exists():",
        "    if path is not None and path.exists():",
        label="config.py missing optional config",
    )
    text = _replace_once(
        text,
        _SOURCE_CONFIG_FALLBACK,
        _CLAW_CONFIG_FALLBACK,
        label="config.py provider fallback",
    )
    text = _replace_once(
        text,
        '"SALIENCE_GATE_OLLAMA_MODEL", "qwen2.5:1.5b"',
        '"SALIENCE_GATE_OLLAMA_MODEL", "none"',
        label="config.py salience default",
    )
    text = _replace_once(
        text,
        '            "local_mem0/crystallize_state.json",',
        '            str(memory_state_dir() / "crystallize_state.json"),',
        label="config.py crystallization state path",
    )
    text = _replace_once(
        text,
        '            "local_mem0/crystallize_audit.jsonl",',
        '            str(memory_state_dir() / "crystallize_audit.jsonl"),',
        label="config.py crystallization audit path",
    )
    text = _replace_once(
        text,
        '"db_path": os.getenv("SOLIDIFY_DB_PATH", "local_mem0/solidification.db")',
        '"db_path": os.getenv(\n'
        '            "SOLIDIFY_DB_PATH", str(memory_state_dir() / "solidification.db")\n'
        "        )",
        label="config.py solidification database path",
    )
    text = _replace_once(
        text,
        '"doc_repo_path": os.getenv("SOLIDIFY_DOC_REPO_PATH", "local_mem0/crystal_docs")',
        '"doc_repo_path": os.getenv(\n'
        '            "SOLIDIFY_DOC_REPO_PATH", str(memory_state_dir() / "crystal_docs")\n'
        "        )",
        label="config.py solidification document path",
    )
    return text


def _adapt_mcp_server(text: str) -> str:
    text = _replace_once(
        text,
        'DEFAULT_MEM0_HOST = "http://localhost:8888"',
        'DEFAULT_MEM0_HOST = "http://127.0.0.1:8888"',
        label="mcp_server.py IPv4 default",
    )
    text = _replace_once(
        text,
        '            raise MemoryServerError(f"{method} {url} failed: {exc}") from exc',
        "            raise MemoryServerError(\n"
        '                f"{method} {url} failed: {exc}. "\n'
        '                "Enable the bundled service with `clawcodex-dev memory enable`."\n'
        "            ) from exc",
        label="mcp_server.py startup hint",
    )
    text = _replace_once(
        text,
        'parser = argparse.ArgumentParser(description="MCP stdio adapter for '
        'clawcodex_ext.latent_memory.server")',
        "parser = argparse.ArgumentParser(\n"
        '        description="MCP stdio adapter for clawcodex_ext.latent_memory.server"\n'
        "    )",
        label="mcp_server.py parser description",
    )
    text = _replace_once(
        text,
        'default=os.getenv("MEMORY_MCP_ENV_FILE", "local_mem0.env")',
        'default=os.getenv("MEMORY_MCP_ENV_FILE")',
        label="mcp_server.py env-file default",
    )
    text = _replace_once(
        text,
        "Defaults to MEM0_HOST or http://localhost:8888.",
        "Defaults to MEM0_HOST or http://127.0.0.1:8888.",
        label="mcp_server.py host help",
    )
    return text


def _adapt_projection(text: str) -> str:
    return _replace_once(
        text,
        '    cfg = vector_store.get("config", {}) or {}\n    kwargs: dict[str, Any] = {}',
        '    cfg = dict(vector_store.get("config", {}) or {})\n'
        "    # Qdrant local mode only allows one client per storage path.\n"
        "    # Keep this projection separate from mem0's own local client.\n"
        '    if "path" in cfg and cfg["path"]:\n'
        "        from pathlib import Path\n\n"
        '        cfg["path"] = str(Path(cfg["path"]) / "solidification")\n'
        "    kwargs: dict[str, Any] = {}",
        label="projection.py local Qdrant isolation",
    )


ADAPTERS: dict[str, Callable[[str], str]] = {
    "config.py": _adapt_config,
    "mcp_server.py": _adapt_mcp_server,
    "lib/solidification/projection.py": _adapt_projection,
}


def render_source(source: Path) -> dict[str, RenderedFile]:
    """Render the complete desired production payload in memory."""
    rendered: dict[str, RenderedFile] = {}
    for relative_path in sorted(collect_files(source) - CLAWCODEX_ONLY):
        path = source / relative_path
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            rendered[relative_path] = RenderedFile(relative_path, path.read_bytes())
            continue
        if path.suffix == ".py":
            text = rewrite_imports(text)
            adapter = ADAPTERS.get(relative_path)
            if adapter is not None:
                text = adapter(text)
        rendered[relative_path] = RenderedFile(relative_path, text.encode("utf-8"))
    return rendered


def make_plan(rendered: dict[str, RenderedFile], target: Path) -> SyncPlan:
    target_files = collect_files(target) if target.exists() else set()
    new: list[str] = []
    changed: list[str] = []
    unchanged: list[str] = []
    for relative_path, item in rendered.items():
        destination = target / relative_path
        if not destination.exists():
            new.append(relative_path)
        elif destination.read_bytes() == item.content:
            unchanged.append(relative_path)
        else:
            changed.append(relative_path)
    return SyncPlan(
        new=tuple(new),
        changed=tuple(changed),
        unchanged=tuple(unchanged),
        target_only=tuple(sorted(target_files - rendered.keys() - OBSOLETE_FILES)),
        removed=tuple(sorted(target_files & OBSOLETE_FILES)),
    )


def _module_name(relative_path: str) -> str:
    path = relative_path.removesuffix(".py").replace("/", ".")
    if path.endswith(".__init__"):
        path = path[: -len(".__init__")]
    return f"{IMPORT_DST}.{path}" if path else IMPORT_DST


def _defined_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
    return names


def validate_tree(root: Path) -> None:
    """Compile Python and verify all static imports within the embedded package."""
    trees: dict[str, ast.Module] = {}
    names: dict[str, set[str]] = {}
    errors: list[str] = []
    for relative_path in sorted(collect_files(root)):
        if not relative_path.endswith(".py"):
            continue
        path = root / relative_path
        try:
            text = path.read_text(encoding="utf-8")
            if IMPORT_SRC in text:
                errors.append(f"{relative_path}: contains stale {IMPORT_SRC!r} reference")
            tree = ast.parse(text, filename=str(path))
            compile(tree, str(path), "exec")
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            errors.append(f"{relative_path}: {exc}")
            continue
        module = _module_name(relative_path)
        trees[module] = tree
        names[module] = _defined_names(tree)

    modules = set(trees)
    for importer, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(IMPORT_DST) and alias.name not in modules:
                        errors.append(f"{importer}: missing internal module {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
                if not module.startswith(IMPORT_DST):
                    continue
                if module not in modules:
                    errors.append(f"{importer}: missing internal module {module}")
                    continue
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    submodule = f"{module}.{alias.name}"
                    if alias.name not in names[module] and submodule not in modules:
                        errors.append(f"{importer}: {module} has no exported name {alias.name}")

    if errors:
        joined = "\n  - ".join(errors)
        raise SyncError(f"rendered package validation failed:\n  - {joined}")


def stage_tree(rendered: dict[str, RenderedFile], target: Path, temporary_root: Path) -> Path:
    """Create and validate a target-shaped tree without modifying the worktree."""
    staged = temporary_root / "server"
    staged.mkdir(parents=True)
    if target.exists():
        for relative_path in sorted(collect_files(target)):
            if relative_path in OBSOLETE_FILES:
                continue
            source_path = target / relative_path
            destination = staged / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)
    for relative_path, item in rendered.items():
        destination = staged / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(item.content)
    validate_tree(staged)
    return staged


def _safe_console_text(value: str) -> str:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return value.encode(encoding, errors="backslashreplace").decode(encoding, errors="replace")


def _print_diff(relative_path: str, rendered: RenderedFile, target: Path) -> None:
    if not relative_path.endswith(".py"):
        return
    try:
        old = (target / relative_path).read_text(encoding="utf-8").splitlines()
        new = rendered.content.decode("utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return
    diff = list(
        difflib.unified_diff(
            old,
            new,
            fromfile=f"clawcodex/{relative_path}",
            tofile=f"memory-benchmarks/{relative_path}",
            lineterm="",
            n=2,
        )
    )
    for line in diff[:20]:
        print("    " + _safe_console_text(line))
    if len(diff) > 20:
        print(f"    {DIM}... ({len(diff) - 20} more lines){RESET}")


def print_plan(
    plan: SyncPlan,
    rendered: dict[str, RenderedFile],
    source: Path,
    target: Path,
    *,
    show_diff: bool,
) -> None:
    print(f"\n{BOLD}=== Memory Server Sync: memory-benchmarks -> clawcodex ==={RESET}")
    print(f"Source: {CYAN}{source}{RESET}")
    print(f"Target: {CYAN}{target}{RESET}")
    print(f"Import rewrite: {DIM}{IMPORT_SRC} -> {IMPORT_DST}{RESET}\n")
    if plan.new:
        print(f"{GREEN}New production files ({len(plan.new)}):{RESET}")
        for relative_path in plan.new:
            print(f"  + {relative_path}")
    if plan.changed:
        print(f"{YELLOW}Changed production files ({len(plan.changed)}):{RESET}")
        for relative_path in plan.changed:
            adapter = " [adapted]" if relative_path in ADAPTERS else ""
            print(f"  ~ {relative_path}{adapter}")
            if show_diff:
                _print_diff(relative_path, rendered[relative_path], target)
    preserved = [path for path in plan.target_only if path in CLAWCODEX_ONLY]
    other_target_only = [path for path in plan.target_only if path not in CLAWCODEX_ONLY]
    if preserved:
        print(f"{CYAN}Preserved ClawCodex-only files ({len(preserved)}):{RESET}")
        for relative_path in preserved:
            print(f"  = {relative_path}")
    if other_target_only:
        print(f"{YELLOW}Target-only files retained for review ({len(other_target_only)}):{RESET}")
        for relative_path in other_target_only:
            print(f"  ? {relative_path}")
    if plan.removed:
        print(f"{RED}Obsolete files to remove ({len(plan.removed)}):{RESET}")
        for relative_path in plan.removed:
            print(f"  - {relative_path}")
    print(
        f"\nSummary: {len(plan.new)} new, {len(plan.changed)} changed, "
        f"{len(plan.removed)} removed, {len(plan.unchanged)} unchanged"
    )


def apply_plan(rendered: dict[str, RenderedFile], plan: SyncPlan, target: Path) -> None:
    """Apply validated writes with per-file rollback if an unexpected write fails."""
    backups: dict[str, bytes | None] = {}
    written: list[str] = []
    try:
        for relative_path in plan.writes:
            destination = target / relative_path
            backups[relative_path] = destination.read_bytes() if destination.exists() else None
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(f".{destination.name}.sync-tmp")
            temporary.write_bytes(rendered[relative_path].content)
            os.replace(temporary, destination)
            written.append(relative_path)
        for relative_path in plan.removed:
            destination = target / relative_path
            backups[relative_path] = destination.read_bytes()
            destination.unlink()
            written.append(relative_path)
        validate_tree(target)
    except Exception:
        for relative_path in reversed(written):
            destination = target / relative_path
            previous = backups[relative_path]
            if previous is None:
                destination.unlink(missing_ok=True)
            else:
                destination.write_bytes(previous)
        raise


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply the validated sync")
    parser.add_argument("--yes", action="store_true", help="Do not prompt with --apply")
    parser.add_argument(
        "--check", action="store_true", help="Exit non-zero when production files differ"
    )
    parser.add_argument("--show-diff", action="store_true", help="Show abbreviated diffs")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_console()
    args = parse_args(argv)
    source = args.source.expanduser().resolve()
    target = args.target.expanduser().resolve()
    if not source.is_dir():
        print(f"{RED}ERROR: source package not found: {source}{RESET}", file=sys.stderr)
        return 2
    if not target.is_dir():
        print(f"{RED}ERROR: target package not found: {target}{RESET}", file=sys.stderr)
        return 2

    try:
        rendered = render_source(source)
        plan = make_plan(rendered, target)
        with tempfile.TemporaryDirectory(prefix="memory-server-sync-") as temporary:
            stage_tree(rendered, target, Path(temporary))
    except SyncError as exc:
        print(f"{RED}ERROR: {exc}{RESET}", file=sys.stderr)
        return 2

    print_plan(plan, rendered, source, target, show_diff=args.show_diff)
    if not plan.actions:
        print(f"{GREEN}[OK] Production code is in sync and validation passed.{RESET}")
        return 0
    if args.check:
        print(f"{RED}[OUT OF SYNC] Run with --apply after reviewing the plan.{RESET}")
        return 1
    if not args.apply:
        print("\nPreview only. Re-run with --apply to migrate these files.")
        return 0
    if not args.yes:
        answer = (
            input(f"Apply {len(plan.actions)} validated file action(s)? [y/N] ").strip().lower()
        )
        if answer not in {"y", "yes"}:
            print("Aborted.")
            return 0

    try:
        apply_plan(rendered, plan, target)
    except (OSError, SyncError) as exc:
        print(f"{RED}ERROR: apply failed and completed writes were rolled back: {exc}{RESET}")
        return 2
    print(f"{GREEN}[OK] Synced and validated {len(plan.actions)} production action(s).{RESET}")
    print("Next: run tests/memory/server and a memory service startup smoke test.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
