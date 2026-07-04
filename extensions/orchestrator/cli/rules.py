"""orchestrator rules — inspect and manage learned PR review conventions.

Usage (noun-verb):

  # Query
  clawcodex orchestrator rules list [--workflow PATH]
  clawcodex orchestrator rules review --id <id> [--workflow PATH]
  clawcodex orchestrator rules stats [--workflow PATH]

  # Management
  clawcodex orchestrator rules delete --id <id> [--workflow PATH]
  clawcodex orchestrator rules refresh [--workflow PATH]
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from extensions.orchestrator.rules_learner import RuleEngine, RuleStore
from extensions.orchestrator.workflow import WorkflowLoader
from extensions.orchestrator.workflow_store import get_workflow_store


# ---------------------------------------------------------------------------
# Parser registration
# ---------------------------------------------------------------------------


def add_rules_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register ``rules`` sub-subcommands."""
    rules_parser = subparsers.add_parser(
        'rules',
        help='Inspect and manage learned PR review conventions',
        description='List, review, delete, refresh, or show stats for rules '
        'automatically extracted from PR review feedback.',
    )
    rules_sub = rules_parser.add_subparsers(
        dest='rules_subcommand',
        required=True,
    )

    # --- rules list ---
    list_parser = rules_sub.add_parser(
        'list',
        help='List all rules with summary and metadata',
        description='Display all rules in the workflow rules file. Idempotent (pure read).',
    )
    list_parser.add_argument(
        '--workflow',
        type=str,
        default=None,
        metavar='PATH',
        help='Path to WORKFLOW.md (optional auto-detection override)',
    )

    # --- rules review ---
    review_parser = rules_sub.add_parser(
        'review',
        help='Show full detail for a specific rule',
        description='Display one rule with its full body, source, and metadata.',
    )
    review_parser.add_argument(
        '--id',
        type=int,
        required=True,
        metavar='RULE_ID',
        help='Rule id to review',
    )
    review_parser.add_argument(
        '--workflow',
        type=str,
        default=None,
        metavar='PATH',
        help='Path to WORKFLOW.md (optional auto-detection override)',
    )

    # --- rules delete ---
    delete_parser = rules_sub.add_parser(
        'delete',
        help='Delete a rule by id',
        description='Remove a single rule from the rules file. '
        'The orchestrator will not re-add it unless re-extracted.',
    )
    delete_parser.add_argument(
        '--id',
        type=int,
        required=True,
        metavar='RULE_ID',
        help='Rule id to delete',
    )
    delete_parser.add_argument(
        '--workflow',
        type=str,
        default=None,
        metavar='PATH',
        help='Path to WORKFLOW.md (optional auto-detection override)',
    )

    # --- rules refresh ---
    refresh_parser = rules_sub.add_parser(
        'refresh',
        help='[NOT IMPLEMENTED] Re-extract rules from previous follow-up transcripts',
        description='NOT IMPLEMENTED — re-extraction from past sessions requires '
        'the orchestrator daemon and will be available in a future release. '
        'Rules are automatically extracted after each review follow-up completes '
        'when ``rules.enabled=true`` in the workflow configuration.',
    )
    refresh_parser.add_argument(
        '--workflow',
        type=str,
        default=None,
        metavar='PATH',
        help='Path to WORKFLOW.md (optional auto-detection override)',
    )

    # --- rules stats ---
    stats_parser = rules_sub.add_parser(
        'stats',
        help='Show rule statistics',
        description='Display aggregate statistics: total count, category distribution, '
        'average confidence, recent additions.',
    )
    stats_parser.add_argument(
        '--workflow',
        type=str,
        default=None,
        metavar='PATH',
        help='Path to WORKFLOW.md (optional auto-detection override)',
    )


# ---------------------------------------------------------------------------
# Run dispatch
# ---------------------------------------------------------------------------


def run(args: argparse.Namespace) -> int:
    """Dispatch to the appropriate rules subcommand."""
    cmd = args.rules_subcommand

    workflow_path = _resolve_workflow_path(getattr(args, 'workflow', None))
    if workflow_path is None:
        print(
            'No workflow found. Specify --workflow PATH or run from a workflow directory.',
            file=sys.stderr,
        )
        return 1

    rules_path = _resolve_rules_path(workflow_path)
    if rules_path is None:
        print('Rules are not enabled in the workflow configuration.', file=sys.stderr)
        return 1

    if cmd == 'list':
        return _run_list(rules_path)
    elif cmd == 'review':
        return _run_review(rules_path, args.id)
    elif cmd == 'delete':
        return _run_delete(rules_path, args.id)
    elif cmd == 'refresh':
        return _run_refresh(workflow_path, rules_path)
    elif cmd == 'stats':
        return _run_stats(rules_path)
    else:
        print(f'Unknown rules subcommand: {cmd}', file=sys.stderr)
        return 2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_workflow_path(workflow_arg: str | None) -> str | None:
    """Resolve the WORKFLOW.md path from CLI arg or cwd."""
    if workflow_arg:
        p = Path(workflow_arg)
        if p.exists():
            return str(p.resolve())
        print(f'Workflow file not found: {workflow_arg}', file=sys.stderr)
        return None

    # Try default
    default = WorkflowLoader.default_path()
    if default.exists():
        return str(default.resolve())

    # Try workspace_locator metadata
    try:
        from extensions.orchestrator.workspace_locator import get_workflow_path

        meta = get_workflow_path(workspace_arg=None)
        if meta:
            return str(Path(meta).resolve())
    except Exception:
        pass

    return None


def _resolve_rules_path(workflow_path: str) -> str | None:
    """Load the workflow config and resolve the rules file path."""
    try:
        config, _ = WorkflowLoader.load(workflow_path)
    except Exception as exc:
        print(f'Failed to load workflow: {exc}', file=sys.stderr)
        return None

    if not getattr(config, 'rules', None) or not config.rules.enabled:
        return None

    return RuleStore.resolve_path(workflow_path, config.rules.path or '')


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------


def _run_list(rules_path: str) -> int:
    data = RuleStore.load(rules_path)
    rules = data.get('rules', [])
    if not rules:
        print(f'No rules in {rules_path}')
        return 0

    print(f'Rules file: {rules_path}')
    print(f'Total: {len(rules)} rule(s)\n')
    for r in rules:
        rid = r.get('id', '?')
        summary = r.get('summary', '')
        conf = r.get('confidence', '?')
        support = r.get('support_count', 0)
        cat = r.get('category', '?')
        print(f'  [{rid}] ({cat}) [{conf}] (x{support}) {summary}')
    return 0


def _run_review(rules_path: str, rule_id: int) -> int:
    data = RuleStore.load(rules_path)
    rules = data.get('rules', [])
    for r in rules:
        if r.get('id') == rule_id:
            _print_rule(r)
            return 0

    print(f'Rule #{rule_id} not found in {rules_path}', file=sys.stderr)
    return 1


def _run_delete(rules_path: str, rule_id: int) -> int:
    data = RuleStore.load(rules_path)
    rules = data.get('rules', [])
    before = len(rules)
    rules = [r for r in rules if r.get('id') != rule_id]
    removed = before - len(rules)
    if removed == 0:
        print(f'Rule #{rule_id} not found — nothing to delete', file=sys.stderr)
        return 1
    RuleStore.save(rules_path, rules, version=data.get('version', 1))
    print(f'Deleted rule #{rule_id} from {rules_path}')
    return 0


def _run_refresh(workflow_path: str, rules_path: str) -> int:
    print(
        'NOT IMPLEMENTED — re-extraction from past sessions requires '
        'the orchestrator daemon and will be available in a future release.',
        file=sys.stderr,
    )
    return 0


def _run_stats(rules_path: str) -> int:
    data = RuleStore.load(rules_path)
    rules = data.get('rules', [])
    if not rules:
        print(f'No rules in {rules_path}')
        return 0

    total = len(rules)
    cats: dict[str, int] = {}
    confs: dict[str, int] = {}
    recent_7d = 0
    now = datetime.now(timezone.utc)

    for r in rules:
        cat = r.get('category', 'other')
        cats[cat] = cats.get(cat, 0) + 1

        conf = r.get('confidence', 'low')
        confs[conf] = confs.get(conf, 0) + 1

        created_str = r.get('created_at', '')
        if created_str:
            try:
                created = datetime.fromisoformat(created_str)
                if (now - created).total_seconds() < 7 * 86400:
                    recent_7d += 1
            except (ValueError, TypeError):
                pass

    # Average score
    scores = [RuleEngine.score(r) for r in rules]
    avg_score = sum(scores) / len(scores) if scores else 0.0

    print(f'Rules file: {rules_path}')
    print(f'  Total rules:    {total}')
    print(f'  Avg quality:    {avg_score:.3f}')
    print(f'  Added (7d):     {recent_7d}')
    print()
    print('  Category distribution:')
    for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
        pct = count / total * 100
        print(f'    {cat:25s} {count:3d} ({pct:5.1f}%)')
    print()
    print('  Confidence distribution:')
    for level in ('high', 'medium', 'low'):
        count = confs.get(level, 0)
        pct = count / total * 100
        print(f'    {level:10s} {count:3d} ({pct:5.1f}%)')

    return 0


def _print_rule(r: dict[str, Any]) -> None:
    """Pretty-print a single rule dict."""
    rid = r.get('id', '?')
    summary = r.get('summary', '')
    body = r.get('body', '')
    cat = r.get('category', '?')
    conf = r.get('confidence', '?')
    support = r.get('support_count', 0)
    source = r.get('source', '')
    created = r.get('created_at', '')
    updated = r.get('updated_at', '')
    applied = r.get('last_applied', '')

    print(f'Rule #{rid}')
    print(f'  Category:   {cat}')
    print(f'  Confidence: {conf}')
    print(f'  Support:    x{support}')
    print(f'  Summary:    {summary}')
    if body:
        print(f'  Body:')
        for line in body.splitlines():
            print(f'    {line}')
    if source:
        print(f'  Source:     {source}')
    print(f'  Created:    {created}')
    print(f'  Updated:    {updated}')
    print(f'  Applied:    {applied}')
