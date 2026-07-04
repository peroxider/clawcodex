"""Tests for the ``orchestrator rules`` CLI subcommands.

Verifies list/review/delete/stats/refresh dispatch and output.
"""

from __future__ import annotations

import argparse
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from extensions.orchestrator.cli.rules import run as rules_run
from extensions.orchestrator.rules_learner import RuleStore


def _make_workflow(root: Path, rules_enabled: bool = True) -> Path:
    """Write a minimal WORKFLOW.md with optional rules config."""
    rules_block = (
        (f'rules:\n  enabled: {str(rules_enabled).lower()}\n  path: workflow.rules.yaml\n')
        if rules_enabled
        else ''
    )
    content = (
        '---\n'
        f'{rules_block}'
        'agent:\n'
        '  model: test-model\n'
        '  provider: test\n'
        '---\n'
        'Fix the issue: {{ issue.description }}'
    )
    p = root / 'WORKFLOW.md'
    p.write_text(content, encoding='utf-8')
    return p


def _make_rules(root: Path) -> list[dict]:
    """Write sample rules into the rules file and return them."""
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    rules = [
        {
            'id': 1,
            'category': 'naming',
            'summary': 'Use explicit exception types',
            'body': 'Always specify the exception type when catching.',
            'confidence': 'high',
            'support_count': 3,
            'source': 'PR #1',
            'created_at': now,
            'updated_at': now,
            'last_applied': now,
        },
        {
            'id': 2,
            'category': 'style',
            'summary': 'Use double quotes for strings',
            'body': '',
            'confidence': 'medium',
            'support_count': 1,
            'source': 'PR #2',
            'created_at': now,
            'updated_at': now,
            'last_applied': now,
        },
    ]
    rules_path = root / 'workflow.rules.yaml'
    RuleStore.save(str(rules_path), rules)
    return rules


class TestRulesCliList(unittest.TestCase):
    """``rules list`` subcommand."""

    def test_list_shows_all_rules(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _make_workflow(root, rules_enabled=True)
            _make_rules(root)
            args = argparse.Namespace(
                rules_subcommand='list',
                workflow=str(root / 'WORKFLOW.md'),
            )
            rc = rules_run(args)
            self.assertEqual(rc, 0)

    def test_list_no_rules_shows_message(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            wf = _make_workflow(root, rules_enabled=True)
            rules_path = root / 'workflow.rules.yaml'
            RuleStore.save(str(rules_path), [])
            args = argparse.Namespace(
                rules_subcommand='list',
                workflow=str(wf),
            )
            rc = rules_run(args)
            self.assertEqual(rc, 0)

    def test_list_rules_disabled_shows_error(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            wf = _make_workflow(root, rules_enabled=False)
            args = argparse.Namespace(
                rules_subcommand='list',
                workflow=str(wf),
            )
            rc = rules_run(args)
            self.assertEqual(rc, 1)


class TestRulesCliReview(unittest.TestCase):
    """``rules review --id`` subcommand."""

    def test_review_existing_rule(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _make_workflow(root, rules_enabled=True)
            _make_rules(root)
            args = argparse.Namespace(
                rules_subcommand='review',
                id=1,
                workflow=str(root / 'WORKFLOW.md'),
            )
            rc = rules_run(args)
            self.assertEqual(rc, 0)

    def test_review_nonexistent_rule_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _make_workflow(root, rules_enabled=True)
            _make_rules(root)
            args = argparse.Namespace(
                rules_subcommand='review',
                id=999,
                workflow=str(root / 'WORKFLOW.md'),
            )
            rc = rules_run(args)
            self.assertEqual(rc, 1)


class TestRulesCliDelete(unittest.TestCase):
    """``rules delete --id`` subcommand."""

    def test_delete_existing_rule(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _make_workflow(root, rules_enabled=True)
            _make_rules(root)
            args = argparse.Namespace(
                rules_subcommand='delete',
                id=1,
                workflow=str(root / 'WORKFLOW.md'),
            )
            rc = rules_run(args)
            self.assertEqual(rc, 0)
            data = RuleStore.load(str(root / 'workflow.rules.yaml'))
            self.assertEqual(len(data['rules']), 1)
            self.assertEqual(data['rules'][0]['id'], 2)

    def test_delete_nonexistent_rule_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _make_workflow(root, rules_enabled=True)
            _make_rules(root)
            args = argparse.Namespace(
                rules_subcommand='delete',
                id=999,
                workflow=str(root / 'WORKFLOW.md'),
            )
            rc = rules_run(args)
            self.assertEqual(rc, 1)


class TestRulesCliStats(unittest.TestCase):
    """``rules stats`` subcommand."""

    def test_stats_with_rules(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _make_workflow(root, rules_enabled=True)
            _make_rules(root)
            args = argparse.Namespace(
                rules_subcommand='stats',
                workflow=str(root / 'WORKFLOW.md'),
            )
            rc = rules_run(args)
            self.assertEqual(rc, 0)

    def test_stats_no_rules(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            wf = _make_workflow(root, rules_enabled=True)
            rules_path = root / 'workflow.rules.yaml'
            RuleStore.save(str(rules_path), [])
            args = argparse.Namespace(
                rules_subcommand='stats',
                workflow=str(wf),
            )
            rc = rules_run(args)
            self.assertEqual(rc, 0)


class TestRulesCliRefresh(unittest.TestCase):
    """``rules refresh`` subcommand (stub)."""

    def test_refresh_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            wf = _make_workflow(root, rules_enabled=True)
            args = argparse.Namespace(
                rules_subcommand='refresh',
                workflow=str(wf),
            )
            rc = rules_run(args)
            self.assertEqual(rc, 0)


class TestRulesCliWorkflowNotFound(unittest.TestCase):
    """Error path: workflow file does not exist."""

    def test_missing_workflow_returns_error(self) -> None:
        args = argparse.Namespace(
            rules_subcommand='list',
            workflow='/nonexistent/WORKFLOW.md',
        )
        rc = rules_run(args)
        self.assertEqual(rc, 1)


if __name__ == '__main__':
    unittest.main()
