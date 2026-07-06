"""``clawcodex-dev community-radar`` subcommand.

Mirrors the existing fast-path CLI style (see ``model_cmd/commands.py``
and ``provider_cmd/commands.py``). The subcommand is registered via
``clawcodex_ext.cli.subcommand_registry.register`` so the parent
dispatcher routes ``clawcodex-dev community-radar ...`` here without
touching ``src/*``.

Subcommands:

* ``scan`` — fetch + extract + score + write a digest.
* ``source list|add|remove|show`` — manage WatchSource registry.
* ``config show|set|init`` — manage RadarConfig.
* ``status`` — summarise the last scan and current registry state.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

from .config import RadarConfig, apply_env_overrides, default_config_path
from .models import WatchSource
from .pipeline import CommunityRadarPipeline
from .registry import SourceRegistry, default_registry_path

_log = logging.getLogger(__name__)


USAGE = (
    "usage: clawcodex-dev community-radar <subcommand> [options]\n\n"
    "Subcommands:\n"
    "  scan [--period weekly|monthly] [--output DIR] [--no-write]\n"
    "                         Fetch, extract, score, and persist a digest.\n"
    "  source list            List configured WatchSources.\n"
    "  source add NAME --repo OWNER/NAME [--track-releases|--track-commits|\n"
    "                         --track-prs] [--tag-filter REGEX]\n"
    "                         [--changelog PATH] [--notes TEXT]\n"
    "                         [--roadmap-keyword KW]...\n"
    "  source remove NAME     Remove a configured source.\n"
    "  source show NAME       Print a single source's full record.\n"
    "  config show            Print the active RadarConfig.\n"
    "  config init            Write the default config to the user dir.\n"
    "  status                 Print current registry + last cache state.\n"
    "  help, --help, -h       Print this help.\n"
)


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------


def _load_registry(path: Path | None = None) -> SourceRegistry:
    """Load the registry, in-memory seeding with defaults when the file is absent.

    Unlike :func:`_maybe_load_registry`, this does **not** persist defaults
    to disk. Read-only commands (``source list``, ``source show``) use
    this so they never write a file just because the user listed sources.
    """
    target = path or default_registry_path()
    registry = SourceRegistry(target)
    if not target.exists():
        return SourceRegistry.with_defaults(target)
    registry.load()
    return registry


def _maybe_load_registry(path: Path | None) -> SourceRegistry:
    """Load the registry, seeding it with defaults if the file is absent.

    Persists the defaults to disk so subsequent invocations find a real
    config file. Used by mutating commands (``scan``, ``source add``).
    """
    target = path or default_registry_path()
    registry = SourceRegistry(target)
    if not target.exists():
        defaults = SourceRegistry.with_defaults(target)
        defaults.save()
        return defaults
    registry.load()
    return registry


# ---------------------------------------------------------------------------
# scan subcommand
# ---------------------------------------------------------------------------


def _cmd_scan(args: argparse.Namespace) -> int:
    config = apply_env_overrides(RadarConfig.from_dict(_read_config_file()))
    if args.output:
        config.output_dir = str(args.output)

    registry = _maybe_load_registry(args.registry)
    pipeline = CommunityRadarPipeline(config=config, registry=registry)
    result = pipeline.run_scan(
        period=args.period,
        write=not args.no_write,
        output_dir=config.output_dir,
        persistent_copy=not args.no_persistent,
        compare=args.compare,
        incremental=args.incremental,
    )

    summary = result.digest.to_dict()["stats"]
    print(f"Scan complete: {summary['total_features']} features from "
          f"{len(result.digest.sources_used)} sources "
          f"({summary['total_versions']} versions).")
    if result.write_result:
        print(f"  digest: {result.write_result.markdown_path}")
        print(f"  json:   {result.write_result.json_path}")
    if result.digest.errors:
        print(f"  warnings: {len(result.digest.errors)} (see digest)")
    return 0


# ---------------------------------------------------------------------------
# source subcommands
# ---------------------------------------------------------------------------


def _cmd_source_list(args: argparse.Namespace) -> int:
    registry = _load_registry(args.registry)
    if not registry.list():
        print("(no sources configured)")
        return 0
    for source in registry.list():
        flags = _format_track_flags(source)
        print(f"{source.name}\t{source.repo}\t{flags}")
    return 0


def _cmd_source_add(args: argparse.Namespace) -> int:
    registry = _load_registry(args.registry)
    data: dict[str, Any] = {
        "name": args.name,
        "repo": args.repo,
        "track_releases": args.track_releases,
        "track_commits": args.track_commits,
        "track_prs": args.track_prs,
        "track_issues": args.track_issues,
    }
    if args.domain:
        data["domain"] = args.domain
    if args.tag_filter:
        data["release_tag_filter"] = args.tag_filter
    if args.changelog:
        data["changelog_path"] = args.changelog
    if args.notes:
        data["notes"] = args.notes
    if args.roadmap_keyword:
        data["roadmap_keywords"] = list(args.roadmap_keyword)
    try:
        source = WatchSource.from_dict(data)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    registry.add(source)
    registry.save()
    print(f"Added source '{source.name}' -> {source.repo}")
    return 0


def _cmd_source_remove(args: argparse.Namespace) -> int:
    registry = _load_registry(args.registry)
    if not registry.remove(args.name):
        print(f"error: no source named '{args.name}'", file=sys.stderr)
        return 1
    registry.save()
    print(f"Removed source '{args.name}'")
    return 0


def _cmd_source_show(args: argparse.Namespace) -> int:
    registry = _load_registry(args.registry)
    source = registry.get(args.name)
    if source is None:
        print(f"error: no source named '{args.name}'", file=sys.stderr)
        return 1
    print(json.dumps(source.to_dict(), indent=2, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------------------
# config subcommands
# ---------------------------------------------------------------------------


def _cmd_config_show(args: argparse.Namespace) -> int:
    config = apply_env_overrides(RadarConfig.from_dict(_read_config_file()))
    print(json.dumps(config.to_dict(), indent=2, ensure_ascii=False))
    return 0


def _cmd_config_init(args: argparse.Namespace) -> int:
    path = args.config or default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    config = RadarConfig()
    path.write_text(
        json.dumps(config.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Default config written to {path}")
    return 0


# ---------------------------------------------------------------------------
# status subcommand
# ---------------------------------------------------------------------------


def _cmd_status(args: argparse.Namespace) -> int:
    registry_path = args.registry or default_registry_path()
    config_path = args.config or default_config_path()
    registry = _load_registry(registry_path)
    print(f"Registry path: {registry_path}")
    print(f"  sources:    {len(registry)}")
    if registry.list():
        print(f"  names:      {', '.join(registry.names())}")
    print(f"Config path:  {config_path}  (exists={config_path.exists()})")
    cache_dir = os.environ.get(
        "CLAWCODEX_RADAR_CACHE_DIR",
        str(Path.home() / ".cache" / "community-radar"),
    )
    cache = Path(cache_dir)
    print(f"Cache dir:    {cache}  (exists={cache.exists()})")
    return 0


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_track_flags(source: WatchSource) -> str:
    flags = []
    if source.track_releases:
        flags.append("releases")
    if source.track_commits:
        flags.append("commits")
    if source.track_prs:
        flags.append("prs")
    if source.track_issues:
        flags.append("issues")
    return ",".join(flags) or "(none)"


def _read_config_file() -> dict[str, Any]:
    """Load the YAML/JSON RadarConfig file from disk (or empty dict)."""
    path = default_config_path()
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        _log.warning("failed to read config %s: %s", path, exc)
        return {}
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError:
            return {}
        try:
            data = yaml.safe_load(text)
        except Exception:  # noqa: BLE001
            return {}
        if isinstance(data, dict):
            inner = data.get("community_radar") or data.get("radar") or data
            return inner if isinstance(inner, dict) else {}
    else:
        try:
            data = json.loads(text)
        except Exception:  # noqa: BLE001
            return {}
        if isinstance(data, dict):
            inner = data.get("community_radar") or data.get("radar") or data
            return inner if isinstance(inner, dict) else {}
    return {}


# ---------------------------------------------------------------------------
# Argument parsing + dispatcher
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clawcodex-dev community-radar",
        description="SR-5.1 开源社区新特性雷达",
        add_help=False,
    )
    parser.add_argument("--registry", type=Path, default=None)
    sub = parser.add_subparsers(dest="subcommand")

    sub.add_parser("help")

    # scan
    scan_p = sub.add_parser("scan")
    scan_p.add_argument(
        "--period", choices=("weekly", "monthly"), default="weekly"
    )
    scan_p.add_argument("--output", type=Path, default=None)
    scan_p.add_argument("--no-write", action="store_true")
    scan_p.add_argument("--no-persistent", action="store_true")
    scan_p.add_argument(
        "--compare", action="store_true", default=False,
        help="Compare against the previous digest in the output directory.",
    )
    scan_p.add_argument(
        "--incremental", action="store_true", default=False,
        help="Incremental fetch (use cursors/ETags for speed, suitable for cron).",
    )
    # source
    source_p = sub.add_parser("source")
    source_sub = source_p.add_subparsers(dest="source_cmd", required=True)

    source_sub.add_parser("list")

    add_p = source_sub.add_parser("add")
    add_p.add_argument("name")
    add_p.add_argument("--repo", required=True)
    add_p.add_argument("--domain", choices=("software_engineering", "embodied_ai",
                        "spatial_intelligence", "general"), default=None,
                       help="Source domain for cross-domain classification guard.")
    add_p.add_argument("--track-releases", dest="track_releases", action="store_true", default=True)
    add_p.add_argument("--no-track-releases", dest="track_releases", action="store_false")
    add_p.add_argument("--track-commits", dest="track_commits", action="store_true", default=False)
    add_p.add_argument("--track-prs", dest="track_prs", action="store_true", default=False)
    add_p.add_argument("--track-issues", dest="track_issues", action="store_true", default=False)
    add_p.add_argument("--tag-filter", dest="tag_filter", default=None)
    add_p.add_argument("--changelog", dest="changelog", default=None)
    add_p.add_argument("--notes", dest="notes", default=None)
    add_p.add_argument("--roadmap-keyword", dest="roadmap_keyword", action="append", default=[])

    rm_p = source_sub.add_parser("remove")
    rm_p.add_argument("name")

    show_p = source_sub.add_parser("show")
    show_p.add_argument("name")

    # config
    cfg_p = sub.add_parser("config")
    cfg_sub = cfg_p.add_subparsers(dest="config_cmd", required=True)
    cfg_sub.add_parser("show")
    init_p = cfg_sub.add_parser("init")
    init_p.add_argument("--config", type=Path, default=None)

    # status
    status_p = sub.add_parser("status")
    status_p.add_argument("--config", type=Path, default=None)

    return parser


_DISPATCH: dict[str, Callable[[argparse.Namespace], int]] = {
    "scan": _cmd_scan,
    "source_list": _cmd_source_list,
    "source_add": _cmd_source_add,
    "source_remove": _cmd_source_remove,
    "source_show": _cmd_source_show,
    "config_show": _cmd_config_show,
    "config_init": _cmd_config_init,
    "status": _cmd_status,
}


def _route(args: argparse.Namespace) -> int:
    sub = args.subcommand
    if sub is None or sub == "help":
        print(USAGE)
        return 0
    if sub == "source":
        key = f"source_{args.source_cmd}"
        handler = _DISPATCH.get(key)
        if handler is None:
            print(USAGE)
            return 2
        return handler(args)
    if sub == "config":
        key = f"config_{args.config_cmd}"
        handler = _DISPATCH.get(key)
        if handler is None:
            print(USAGE)
            return 2
        return handler(args)
    handler = _DISPATCH.get(sub)
    if handler is None:
        print(USAGE)
        return 2
    return handler(args)


def run(argv: Sequence[str] | None = None) -> int:
    """Parse ``argv`` (defaulting to ``sys.argv[1:]``) and dispatch."""
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] in {"help", "--help", "-h"}:
        print(USAGE)
        return 0
    parser = _build_parser()
    args = parser.parse_args(list(argv))
    return _route(args)


# ---------------------------------------------------------------------------
# Subcommand registration
# ---------------------------------------------------------------------------


def register_community_radar_subcommand() -> None:
    """Register ``community-radar`` with the downstream CLI dispatcher.

    Mirrors the registration style in
    ``clawcodex_ext/cli/session_migrate_cmd.py`` — we import the
    registry lazily to avoid a circular import.
    """
    from clawcodex_ext.cli.subcommand_registry import register

    @register("community-radar")
    def _handler(args: list[str]) -> int:
        try:
            return run(args)
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"community-radar: {exc}", file=sys.stderr)
            return 1

    return None