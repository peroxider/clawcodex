"""Tests for F-121 rule extraction, storage, and the orchestration hook.

Phase 1:  extract, RuleStore, exact dedup, get_rules_path
Phase 2:  RuleEmbedder (TF-IDF), semantic dedup+merge, score, prune
"""

from __future__ import annotations

import math
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import yaml

from extensions.orchestrator.rules_learner import (
    RuleEmbedder,
    RuleEngine,
    RuleStore,
    _infer_category,
    _merge_two_rules,
)

# ═══════════════════════════════════════════════════════════════════
# RuleEngine.extract()
# ═══════════════════════════════════════════════════════════════════


class TestRuleEngineExtract(unittest.TestCase):
    def test_extract_parses_single_rule(self) -> None:
        reply = """I fixed the issue.

## Extracted Rules
- [naming] Use explicit exception types instead of bare except:
  Body: When catching exceptions, always specify the exception type.
"""
        rules = RuleEngine.extract(reply)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]['category'], 'naming')
        self.assertIn('exception types', rules[0]['summary'])
        self.assertIn('specify', rules[0]['body'])

    def test_extract_parses_multiple_rules(self) -> None:
        reply = """Work done.

## Extracted Rules
- [naming] Use explicit exception types
  Body: Always specify the exception type.
- [testing] Write unit tests for all public functions
  Body: Every public function must have at least one unit test.
- [error_handling] Log exceptions before re-raising
  Body: Always log the original exception before re-raising.
"""
        rules = RuleEngine.extract(reply)
        self.assertEqual(len(rules), 3)
        self.assertEqual(rules[0]['category'], 'naming')
        self.assertEqual(rules[1]['category'], 'testing')
        self.assertEqual(rules[2]['category'], 'error_handling')

    def test_extract_parses_body_on_separate_line(self) -> None:
        reply = """Done.

## Extracted Rules
- [code_style] Use f-strings over concatenation
  Body: f-strings are more readable than + or % formatting.
"""
        rules = RuleEngine.extract(reply)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]['category'], 'code_style')
        self.assertEqual(rules[0]['summary'], 'Use f-strings over concatenation')
        self.assertIn('f-strings are more readable', rules[0]['body'])

    def test_extract_parses_inline_body(self) -> None:
        reply = """Done.

## Extracted Rules
- [boilerplate] Add license header: Every file must have the MIT license header.
"""
        rules = RuleEngine.extract(reply)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]['summary'], 'Add license header')
        self.assertIn('MIT license header', rules[0]['body'])

    def test_extract_skips_when_no_section(self) -> None:
        reply = 'I fixed all the feedback items.'
        rules = RuleEngine.extract(reply)
        self.assertEqual(rules, [])

    def test_extract_handles_empty_section(self) -> None:
        reply = '## Extracted Rules\n'
        rules = RuleEngine.extract(reply)
        self.assertEqual(rules, [])

    def test_extract_with_noise_before_section(self) -> None:
        reply = """I made the following changes.
- Fixed the import ordering
- Added error handling

## Extracted Rules
- [import_style] Group standard library imports first
  Body: stdlib, then third-party, then local.
"""
        rules = RuleEngine.extract(reply)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]['category'], 'import_style')

    def test_extract_timestamps_are_set(self) -> None:
        reply = """
## Extracted Rules
- [naming] Use explicit exception types
"""
        rules = RuleEngine.extract(reply)
        self.assertEqual(len(rules), 1)
        self.assertIn('T', rules[0]['created_at'])
        self.assertIn('T', rules[0]['updated_at'])
        self.assertIn('T', rules[0]['last_applied'])

    def test_extract_default_confidence_and_support(self) -> None:
        reply = """
## Extracted Rules
- [other] Some convention
"""
        rules = RuleEngine.extract(reply)
        self.assertEqual(rules[0]['confidence'], 'medium')
        self.assertEqual(rules[0]['support_count'], 1)

    # -----------------------------------------------------------------
    # F-121 fix: loose-format tolerance (LLM output that deviates from
    # the canonical `- [category] summary` template).
    # -----------------------------------------------------------------

    def test_extract_bold_title_instead_of_category(self) -> None:
        """Agent used `**bold title** — desc` instead of `[category] desc`."""
        reply = """## Extracted Rules
- **Quote Style Convention** — Use double quotes for string literals
  Body: The project requires double quotes for all string literals.
"""
        rules = RuleEngine.extract(reply)
        self.assertEqual(len(rules), 1)
        self.assertIn('Quote Style Convention', rules[0]['summary'])
        self.assertIn('double quotes', rules[0]['body'])
        # category inferred from "double quotes" keyword -> code_style
        self.assertEqual(rules[0]['category'], 'code_style')

    def test_extract_body_with_list_prefix(self) -> None:
        """Body line carries a leading `- ` list marker (common LLM habit)."""
        reply = """## Extracted Rules
- [code_style] Use double quotes for strings
  - Body: The project uses double quotes for all string literals.
"""
        rules = RuleEngine.extract(reply)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]['category'], 'code_style')
        self.assertIn('double quotes', rules[0]['body'])

    def test_extract_no_category_no_title(self) -> None:
        """Bare summary with no `[category]` and no `**title**`."""
        reply = """## Extracted Rules
- Use double quotes for string literals instead of single quotes
  Body: The project convention requires double quotes everywhere.
"""
        rules = RuleEngine.extract(reply)
        self.assertEqual(len(rules), 1)
        # inferred from "double quotes" keyword
        self.assertEqual(rules[0]['category'], 'code_style')
        self.assertIn('double quotes', rules[0]['summary'])

    def test_extract_real_agent_output(self) -> None:
        """Regression: the actual follow-up output that surfaced the bug.

        Reproduces the 2026-07-02 run-1-followup-1 agent reply where the
        agent used `**Quote Style Convention** — ...` + `  - Body: ...`,
        which the strict regex silently dropped (extract returned 0).
        """
        reply = (
            '## Summary\n\n'
            'Fixed single-quoted string to double quotes.\n\n'
            '---\n\n'
            '## Extracted Rules\n\n'
            '- **Quote Style Convention** — Use double quotes (`"..."`) '
            "for string literals instead of single quotes (`'...'`)\n"
            '  - Body: The project convention requires double quotes for '
            'string literals. This applies to all string values including '
            '`short_help=` text in CLI argument definitions.\n'
        )
        rules = RuleEngine.extract(reply)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]['category'], 'code_style')
        self.assertIn('double quotes', rules[0]['summary'])
        self.assertIn('double quotes', rules[0]['body'])

    def test_extract_mixed_strict_and_loose(self) -> None:
        """One canonical-format rule + one deviant-format rule in one reply."""
        reply = """## Extracted Rules
- [testing] Write unit tests for all public functions
  Body: Every public function needs at least one test.
- **Quote Style** — Use double quotes for strings
  Body: The project uses double quotes for all string literals.
"""
        rules = RuleEngine.extract(reply)
        self.assertEqual(len(rules), 2)
        self.assertEqual(rules[0]['category'], 'testing')
        self.assertEqual(rules[1]['category'], 'code_style')

    def test_extract_strict_format_unchanged(self) -> None:
        """Backward-compat: strict `[category]` format still parses as before."""
        reply = """## Extracted Rules
- [naming] Use explicit exception types instead of bare except:
  Body: Always specify the exception type.
"""
        rules = RuleEngine.extract(reply)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]['category'], 'naming')
        self.assertEqual(
            rules[0]['summary'], 'Use explicit exception types instead of bare except:'
        )
        self.assertIn('specify', rules[0]['body'])


# ═══════════════════════════════════════════════════════════════════
# _infer_category helper (F-121 fix)
# ═══════════════════════════════════════════════════════════════════


class TestInferCategory(unittest.TestCase):
    def test_quote_keyword_maps_to_code_style(self) -> None:
        self.assertEqual(_infer_category('use double quotes for strings'), 'code_style')

    def test_chinese_quote_keyword(self) -> None:
        self.assertEqual(_infer_category('字符串应使用双引号'), 'code_style')

    def test_exception_keyword_maps_to_error_handling(self) -> None:
        self.assertEqual(_infer_category('catch specific exceptions'), 'error_handling')

    def test_test_keyword_maps_to_testing(self) -> None:
        self.assertEqual(_infer_category('write pytest tests'), 'testing')

    def test_unknown_keyword_maps_to_other(self) -> None:
        self.assertEqual(_infer_category('random unrelated text'), 'other')


# ═══════════════════════════════════════════════════════════════════
# RuleStore — path resolution
# ═══════════════════════════════════════════════════════════════════


class TestRuleStoreResolvePath(unittest.TestCase):
    def test_resolve_path_default(self) -> None:
        path = RuleStore.resolve_path('/tmp/workflows/WORKFLOW.md', '')
        self.assertTrue(path.endswith('workflow.rules.yaml'))
        self.assertIn('workflows', path)

    def test_resolve_path_relative(self) -> None:
        path = RuleStore.resolve_path('/tmp/workflows/WORKFLOW.md', 'custom.yaml')
        self.assertTrue(path.endswith('workflows/custom.yaml'))

    def test_resolve_path_absolute(self) -> None:
        path = RuleStore.resolve_path('/tmp/workflows/WORKFLOW.md', '/etc/rules.yaml')
        self.assertEqual(path, '/etc/rules.yaml')


# ═══════════════════════════════════════════════════════════════════
# RuleStore — file IO
# ═══════════════════════════════════════════════════════════════════


class TestRuleStoreIO(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.rules_path = str(self.root / 'workflow.rules.yaml')

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_save_and_load(self) -> None:
        rules = [
            {'id': 1, 'summary': 'Rule one', 'category': 'naming'},
            {'id': 2, 'summary': 'Rule two', 'category': 'testing'},
        ]
        RuleStore.save(self.rules_path, rules, version=1)
        data = RuleStore.load(self.rules_path)
        self.assertEqual(data['version'], 1)
        self.assertEqual(len(data['rules']), 2)
        self.assertEqual(data['rules'][0]['summary'], 'Rule one')

    def test_load_missing_file(self) -> None:
        data = RuleStore.load(str(self.root / 'nonexistent.yaml'))
        self.assertEqual(data, {'version': 1, 'rules': []})

    def test_save_atomic_write(self) -> None:
        rules = [{'id': 1, 'summary': 'Test', 'category': 'other'}]
        RuleStore.save(self.rules_path, rules, version=1)
        tmp_files = list(self.root.glob('*.yaml.tmp'))
        self.assertEqual(len(tmp_files), 0)
        self.assertTrue(Path(self.rules_path).exists())
        with open(self.rules_path, encoding='utf-8') as f:
            content = f.read()
        parsed = yaml.safe_load(content)
        self.assertEqual(len(parsed['rules']), 1)

    def test_auto_managed_comment(self) -> None:
        rules = [{'id': 1, 'summary': 'Rule', 'category': 'other'}]
        RuleStore.save(self.rules_path, rules, version=1)
        with open(self.rules_path, encoding='utf-8') as f:
            first_line = f.readline()
        self.assertIn('clawcodex', first_line)
        self.assertFalse(RuleStore.is_user_managed(self.rules_path))

    def test_user_managed_detection(self) -> None:
        Path(self.rules_path).write_text('version: 1\nrules: []\n', encoding='utf-8')
        self.assertTrue(RuleStore.is_user_managed(self.rules_path))

    def test_ensure_file_creates(self) -> None:
        self.assertFalse(Path(self.rules_path).exists())
        RuleStore.ensure_file(self.rules_path)
        self.assertTrue(Path(self.rules_path).exists())
        data = RuleStore.load(self.rules_path)
        self.assertEqual(data['rules'], [])

    def test_ensure_file_exists(self) -> None:
        RuleStore.save(self.rules_path, [{'id': 1, 'summary': 'X', 'category': 'other'}])
        RuleStore.ensure_file(self.rules_path)
        data = RuleStore.load(self.rules_path)
        self.assertEqual(len(data['rules']), 1)

    def test_load_malformed_yaml(self) -> None:
        Path(self.rules_path).write_text('---\nnot: : valid yaml [[[\n', encoding='utf-8')
        data = RuleStore.load(self.rules_path)
        self.assertEqual(data, {'version': 1, 'rules': []})


# ═══════════════════════════════════════════════════════════════════
# RuleEmbedder (Phase 2)
# ═══════════════════════════════════════════════════════════════════


class TestRuleEmbedder(unittest.TestCase):
    def test_embed_many_returns_correct_count(self) -> None:
        e = RuleEmbedder()
        vecs = e.embed_many(['hello world', 'foo bar baz'])
        self.assertEqual(len(vecs), 2)

    def test_identical_texts_have_similarity_one(self) -> None:
        e = RuleEmbedder()
        vecs = e.embed_many(['use explicit exception types', 'use explicit exception types'])
        sim = RuleEmbedder.cosine_similarity(vecs[0], vecs[1])
        self.assertAlmostEqual(sim, 1.0, places=6)

    def test_orthogonal_texts_have_low_similarity(self) -> None:
        e = RuleEmbedder()
        vecs = e.embed_many(['use explicit exception types', 'paint the wall blue'])
        sim = RuleEmbedder.cosine_similarity(vecs[0], vecs[1])
        self.assertLess(sim, 0.5)

    def test_similar_phrasing_has_high_similarity(self) -> None:
        e = RuleEmbedder()
        vecs = e.embed_many(
            [
                'always specify the exception type when catching',
                'you should specify the exception type in except blocks',
            ]
        )
        sim = RuleEmbedder.cosine_similarity(vecs[0], vecs[1])
        self.assertGreater(sim, 0.3)

    def test_cosine_similarity_zero_for_empty_vector(self) -> None:
        e = RuleEmbedder()
        vecs = e.embed_many(['', 'hello'])
        sim = RuleEmbedder.cosine_similarity(vecs[0], vecs[1])
        self.assertEqual(sim, 0.0)

    def test_symmetry(self) -> None:
        e = RuleEmbedder()
        vecs = e.embed_many(['hello world', 'world hello'])
        sim_ab = RuleEmbedder.cosine_similarity(vecs[0], vecs[1])
        sim_ba = RuleEmbedder.cosine_similarity(vecs[1], vecs[0])
        self.assertAlmostEqual(sim_ab, sim_ba, places=10)


# ═══════════════════════════════════════════════════════════════════
# _merge_two_rules helper (Phase 2)
# ═══════════════════════════════════════════════════════════════════


class TestMergeTwoRules(unittest.TestCase):
    def test_merge_keeps_longer_summary(self) -> None:
        a = {
            'summary': 'short',
            'body': '',
            'category': 'naming',
            'support_count': 2,
            'source': '',
            'confidence': 'medium',
        }
        b = {
            'summary': 'longer and more specific summary',
            'body': '',
            'category': 'naming',
            'support_count': 1,
            'source': '',
            'confidence': 'medium',
        }
        merged = _merge_two_rules(a, b)
        self.assertEqual(merged['summary'], 'longer and more specific summary')

    def test_merge_sums_support_count(self) -> None:
        a = {
            'summary': 'rule',
            'body': '',
            'category': 'naming',
            'support_count': 3,
            'source': '',
            'confidence': 'medium',
        }
        b = {
            'summary': 'rule',
            'body': '',
            'category': 'naming',
            'support_count': 2,
            'source': '',
            'confidence': 'medium',
        }
        merged = _merge_two_rules(a, b)
        self.assertEqual(merged['support_count'], 5)

    def test_merge_picks_higher_confidence(self) -> None:
        a = {
            'summary': 'rule',
            'body': '',
            'category': 'naming',
            'support_count': 1,
            'source': '',
            'confidence': 'medium',
        }
        b = {
            'summary': 'rule',
            'body': '',
            'category': 'naming',
            'support_count': 1,
            'source': '',
            'confidence': 'high',
        }
        merged = _merge_two_rules(a, b)
        self.assertEqual(merged['confidence'], 'high')

    def test_merge_concatenates_sources(self) -> None:
        a = {
            'summary': 'rule',
            'body': '',
            'category': 'naming',
            'support_count': 1,
            'source': 'PR #1',
            'confidence': 'medium',
        }
        b = {
            'summary': 'rule',
            'body': '',
            'category': 'naming',
            'support_count': 1,
            'source': 'PR #2',
            'confidence': 'medium',
        }
        merged = _merge_two_rules(a, b)
        self.assertIn('PR #1', merged['source'])
        self.assertIn('PR #2', merged['source'])

    def test_merge_marks_multi_category(self) -> None:
        a = {
            'summary': 'rule',
            'body': '',
            'category': 'naming',
            'support_count': 1,
            'source': '',
            'confidence': 'medium',
        }
        b = {
            'summary': 'rule',
            'body': '',
            'category': 'testing',
            'support_count': 1,
            'source': '',
            'confidence': 'medium',
        }
        merged = _merge_two_rules(a, b)
        self.assertEqual(merged['category'], 'multi')

    def test_merge_takes_earliest_created_at(self) -> None:
        now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        earlier = '2025-01-01T00:00:00Z'
        a = {
            'summary': 'r',
            'body': '',
            'category': 'naming',
            'support_count': 1,
            'source': '',
            'confidence': 'medium',
            'created_at': earlier,
        }
        b = {
            'summary': 'r',
            'body': '',
            'category': 'naming',
            'support_count': 1,
            'source': '',
            'confidence': 'medium',
            'created_at': now,
        }
        merged = _merge_two_rules(a, b)
        self.assertEqual(merged['created_at'], earlier)


# ═══════════════════════════════════════════════════════════════════
# RuleEngine._deduplicate_and_merge() — semantic (Phase 2)
# ═══════════════════════════════════════════════════════════════════


class TestRuleEngineDedupMerge(unittest.TestCase):
    """Semantic dedup + merge via _deduplicate_and_merge."""

    def test_dedup_new_rule(self) -> None:
        candidates = [{'summary': 'New rule', 'category': 'naming'}]
        merged = RuleEngine._deduplicate_and_merge(candidates, [])
        self.assertEqual(len(merged), 1)

    def test_dedup_exact_duplicate(self) -> None:
        existing = [{'summary': 'Use f-strings', 'category': 'code_style', 'support_count': 1}]
        candidates = [{'summary': 'Use f-strings', 'category': 'code_style'}]
        merged = RuleEngine._deduplicate_and_merge(candidates, existing)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['support_count'], 2)

    def test_dedup_case_insensitive(self) -> None:
        existing = [{'summary': 'Use f-strings', 'category': 'code_style', 'support_count': 1}]
        candidates = [{'summary': 'USE F-STRINGS', 'category': 'code_style'}]
        merged = RuleEngine._deduplicate_and_merge(candidates, existing)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['support_count'], 2)

    def test_dedup_mixed_new_and_dup(self) -> None:
        existing = [{'summary': 'Existing rule', 'support_count': 1}]
        candidates = [
            {'summary': 'Existing rule'},
            {'summary': 'Brand new rule'},
        ]
        merged = RuleEngine._deduplicate_and_merge(candidates, existing)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]['support_count'], 2)
        self.assertEqual(merged[1]['summary'], 'Brand new rule')

    def test_dedup_updates_timestamp(self) -> None:
        existing = [
            {'summary': 'Old rule', 'support_count': 1, 'updated_at': '2020-01-01T00:00:00Z'}
        ]
        candidates = [{'summary': 'Old rule'}]
        merged = RuleEngine._deduplicate_and_merge(candidates, existing)
        self.assertNotEqual(merged[0]['updated_at'], '2020-01-01T00:00:00Z')

    def test_dedup_empty_candidates(self) -> None:
        merged = RuleEngine._deduplicate_and_merge([], [{'summary': 'X', 'support_count': 1}])
        self.assertEqual(len(merged), 1)

    def test_dedup_empty_existing(self) -> None:
        merged = RuleEngine._deduplicate_and_merge([{'summary': 'X'}], [])
        self.assertEqual(len(merged), 1)

    def test_semantic_dedup_high_similarity_skips(self) -> None:
        """Semantically similar rules with high word overlap are deduped."""
        existing = [
            {
                'summary': 'Use explicit exception types when catching errors',
                'body': 'Always specify the exception type like ValueError instead of bare except',
                'support_count': 1,
            }
        ]
        candidates = [
            {
                'summary': 'Use explicit exception type in catch blocks',
                'body': 'Always specify the exception type like ValueError instead of bare except',
            }
        ]
        merged = RuleEngine._deduplicate_and_merge(
            candidates,
            existing,
            similarity_threshold=0.50,
            enhancement_threshold=0.30,
        )
        # Low thresholds guarantee the merge path is exercised
        self.assertEqual(len(merged), 1)
        self.assertGreaterEqual(merged[0]['support_count'], 2)

    def test_semantic_merge_enhances(self) -> None:
        """Partially similar rules are merged with enriched fields."""
        existing = [
            {
                'summary': 'Write unit tests for functions',
                'body': 'Add tests for functions in the test directory',
                'support_count': 1,
            }
        ]
        candidates = [
            {
                'summary': 'Write unit tests for all public functions',
                'body': 'Add tests for all public functions in the test directory',
            }
        ]
        merged = RuleEngine._deduplicate_and_merge(
            candidates,
            existing,
            similarity_threshold=0.90,
            enhancement_threshold=0.50,
        )
        # Lowered thresholds ensure merge path is exercised
        self.assertEqual(len(merged), 1)
        self.assertGreaterEqual(merged[0]['support_count'], 2)

    def test_low_similarity_adds_new_rule(self) -> None:
        """Completely different topics are added as new rules."""
        existing = [
            {
                'summary': 'Use explicit exception types',
                'support_count': 1,
            }
        ]
        candidates = [
            {
                'summary': 'Paint kitchen walls with light blue color',
            }
        ]
        merged = RuleEngine._deduplicate_and_merge(
            candidates,
            existing,
            similarity_threshold=0.85,
            enhancement_threshold=0.70,
        )
        self.assertEqual(len(merged), 2)


# ═══════════════════════════════════════════════════════════════════
# RuleEngine.score() — quality scoring (Phase 2)
# ═══════════════════════════════════════════════════════════════════


class TestRuleEngineScore(unittest.TestCase):
    def test_score_with_body_is_higher_than_without(self) -> None:
        with_body = {
            'summary': 'rule',
            'body': 'A long detailed body with enough characters to pass the threshold.',
            'support_count': 1,
            'created_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        }
        without_body = {
            'summary': 'rule',
            'body': '',
            'support_count': 1,
            'created_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        }
        self.assertGreater(RuleEngine.score(with_body), RuleEngine.score(without_body))

    def test_score_increases_with_support_count(self) -> None:
        low = {
            'summary': 'rule',
            'body': '',
            'support_count': 1,
            'created_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        }
        high = {
            'summary': 'rule',
            'body': '',
            'support_count': 5,
            'created_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        }
        self.assertGreater(RuleEngine.score(high), RuleEngine.score(low))

    def test_score_caps_at_five_support(self) -> None:
        s5 = {
            'summary': 'rule',
            'body': '',
            'support_count': 5,
            'created_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        }
        s10 = {
            'summary': 'rule',
            'body': '',
            'support_count': 10,
            'created_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        }
        # Capped at 5 → both get same support_norm
        self.assertAlmostEqual(RuleEngine.score(s5) - RuleEngine.score(s10), 0.0, places=6)

    def test_old_rule_scores_lower(self) -> None:
        new_rule = {
            'summary': 'rule',
            'body': '',
            'support_count': 1,
            'created_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        }
        old_rule = {
            'summary': 'rule',
            'body': '',
            'support_count': 1,
            'created_at': '2025-01-01T00:00:00Z',
        }
        self.assertGreater(RuleEngine.score(new_rule), RuleEngine.score(old_rule))

    def test_score_returns_between_zero_and_one(self) -> None:
        r = {
            'summary': 'rule',
            'body': '',
            'support_count': 1,
            'created_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        }
        s = RuleEngine.score(r)
        self.assertGreaterEqual(s, 0.0)
        # Max with support=1, no body, today, confidence=medium → authority=0.7:
        # 0.30*(1/5) + 0.25*0.3 + 0.10*1.0 + 0.15*0.7 + 0.20*0.7 = 0.06+0.075+0.10+0.105+0.14 = 0.48
        # So it should be ≤ ~0.5 for this case
        self.assertLessEqual(s, 0.6)


# ═══════════════════════════════════════════════════════════════════
# RuleEngine.prune() — auto-prune (Phase 2)
# ═══════════════════════════════════════════════════════════════════


class TestRuleEnginePrune(unittest.TestCase):
    def test_prune_noop_when_under_limit(self) -> None:
        rules = [
            {
                'summary': f'Rule {i}',
                'body': '',
                'support_count': 1,
                'created_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            }
            for i in range(3)
        ]
        pruned = RuleEngine.prune(rules, max_rules=5)
        self.assertEqual(len(pruned), 3)

    def test_prune_discards_lowest_scored(self) -> None:
        now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        rules = [
            {
                'summary': f'Good rule {i}',
                'body': 'A detailed body with sufficient text content.',
                'support_count': 5,
                'created_at': now,
            }
            for i in range(3)
        ]
        # Add one deliberately low-quality rule
        rules.append(
            {
                'summary': 'bad rule',
                'body': '',
                'support_count': 1,
                'created_at': '2025-01-01T00:00:00Z',
            }
        )
        pruned = RuleEngine.prune(rules, max_rules=3)
        self.assertEqual(len(pruned), 3)
        # The bad rule should have been dropped
        summaries = [r['summary'] for r in pruned]
        self.assertNotIn('bad rule', summaries)

    def test_prune_discards_when_exactly_at_limit(self) -> None:
        now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        rules = [
            {'summary': f'R{i}', 'body': '', 'support_count': 1, 'created_at': now}
            for i in range(5)
        ]
        pruned = RuleEngine.prune(rules, max_rules=5)
        self.assertEqual(len(pruned), 5)

    def test_prune_zero_max_keeps_all(self) -> None:
        now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        rules = [
            {'summary': f'R{i}', 'body': '', 'support_count': 1, 'created_at': now}
            for i in range(10)
        ]
        pruned = RuleEngine.prune(rules, max_rules=0)
        self.assertEqual(len(pruned), 10)


# ═══════════════════════════════════════════════════════════════════
# RuleEngine.apply() — full pipeline (Phase 1 + 2)
# ═══════════════════════════════════════════════════════════════════


class TestRuleEngineApply(unittest.TestCase):
    """Full pipeline: extract → dedup+merge → score → prune → persist."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.rules_path = str(self.root / 'workflow.rules.yaml')
        self.engine = RuleEngine()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_apply_full_pipeline(self) -> None:
        import asyncio

        reply = """Done.

## Extracted Rules
- [naming] Use explicit exception types
  Body: Always specify the exception type.
- [testing] Write unit tests
  Body: Every public function needs a test.
"""
        count = asyncio.run(self.engine.apply(reply, self.rules_path))
        self.assertEqual(count, 2)
        data = RuleStore.load(self.rules_path)
        self.assertEqual(len(data['rules']), 2)

    def test_apply_skips_when_no_rules(self) -> None:
        import asyncio

        count = asyncio.run(self.engine.apply('Just regular text.', self.rules_path))
        self.assertEqual(count, 0)
        self.assertFalse(Path(self.rules_path).exists())

    def test_apply_dedup_on_existing(self) -> None:
        import asyncio

        reply1 = '## Extracted Rules\n- [naming] My rule\n'
        asyncio.run(self.engine.apply(reply1, self.rules_path))
        data1 = RuleStore.load(self.rules_path)
        self.assertEqual(len(data1['rules']), 1)

        reply2 = '## Extracted Rules\n- [naming] My rule\n'
        asyncio.run(self.engine.apply(reply2, self.rules_path))
        data2 = RuleStore.load(self.rules_path)
        self.assertEqual(len(data2['rules']), 1)
        self.assertEqual(data2['rules'][0]['support_count'], 2)

    def test_apply_skips_user_managed(self) -> None:
        import asyncio

        Path(self.rules_path).write_text('version: 1\nrules: []\n', encoding='utf-8')
        reply = '## Extracted Rules\n- [naming] My rule\n'
        count = asyncio.run(self.engine.apply(reply, self.rules_path))
        self.assertEqual(count, 0)
        data = RuleStore.load(self.rules_path)
        self.assertEqual(len(data['rules']), 0)

    def test_apply_prunes_when_over_max(self) -> None:
        import asyncio

        # Add 5 rules in first run
        reply1 = '\n'.join(
            f'- [naming] Rule {i}\n  Body: Detailed body with enough text to score well.'
            for i in range(5)
        )
        reply1 = f'## Extracted Rules\n{reply1}\n'
        asyncio.run(self.engine.apply(reply1, self.rules_path, max_rules=3))
        data = RuleStore.load(self.rules_path)
        # With TF-IDF, all 5 are semantically different → 5 candidates
        # But max_rules=3 → prune to 3
        self.assertLessEqual(len(data['rules']), 3)

    def test_apply_assigns_sequential_ids(self) -> None:
        import asyncio

        reply = '## Extracted Rules\n- [naming] First\n- [testing] Second\n'
        asyncio.run(self.engine.apply(reply, self.rules_path))
        data = RuleStore.load(self.rules_path)
        ids = [r['id'] for r in data['rules']]
        self.assertEqual(ids, [1, 2])

    def test_apply_filters_by_min_confidence(self) -> None:
        import asyncio

        now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        # Pre-populate with a low-confidence rule
        existing = [
            {
                'id': 1,
                'category': 'style',
                'summary': 'Old low quality rule',
                'body': '',
                'confidence': 'low',
                'support_count': 1,
                'created_at': now,
                'updated_at': now,
                'last_applied': now,
            },
        ]
        RuleStore.save(self.rules_path, existing)

        reply = '## Extracted Rules\n- [naming] New high quality rule\n'
        asyncio.run(self.engine.apply(reply, self.rules_path, min_confidence='medium'))
        data = RuleStore.load(self.rules_path)
        for r in data['rules']:
            self.assertIn(r.get('confidence', ''), ('medium', 'high'))
        self.assertGreater(len(data['rules']), 0)

    def test_apply_min_confidence_low_keeps_all(self) -> None:
        import asyncio

        reply = '## Extracted Rules\n- [naming] Rule one\n- [style] Rule two\n'
        asyncio.run(self.engine.apply(reply, self.rules_path, min_confidence='low'))
        data = RuleStore.load(self.rules_path)
        self.assertEqual(len(data['rules']), 2)

    def test_apply_min_confidence_high_filters_new_medium(self) -> None:
        import asyncio

        reply = '## Extracted Rules\n- [naming] Medium confidence rule\n'
        asyncio.run(self.engine.apply(reply, self.rules_path, min_confidence='high'))
        data = RuleStore.load(self.rules_path)
        # New rules get confidence='medium' by default → filtered by high threshold
        self.assertEqual(len(data['rules']), 0)


# ═══════════════════════════════════════════════════════════════════
# Workflow isolation
# ═══════════════════════════════════════════════════════════════════


class TestWorkflowIsolation(unittest.TestCase):
    """Rules files for different workflows do not interfere with each other."""

    def test_independent_rules_files_do_not_interfere(self) -> None:
        import asyncio

        with tempfile.TemporaryDirectory() as d1:
            with tempfile.TemporaryDirectory() as d2:
                path1 = Path(d1) / 'workflow.rules.yaml'
                path2 = Path(d2) / 'workflow.rules.yaml'

                engine = RuleEngine()
                reply1 = '## Extracted Rules\n- [naming] Workflow-A rule\n'
                reply2 = '## Extracted Rules\n- [style] Workflow-B rule\n'

                asyncio.run(engine.apply(reply1, str(path1)))
                asyncio.run(engine.apply(reply2, str(path2)))

                data1 = RuleStore.load(str(path1))
                data2 = RuleStore.load(str(path2))

                self.assertEqual(len(data1['rules']), 1)
                self.assertEqual(data1['rules'][0]['category'], 'naming')
                self.assertEqual(len(data2['rules']), 1)
                self.assertEqual(data2['rules'][0]['category'], 'style')


# ═══════════════════════════════════════════════════════════════════
# RuleEngine.get_rules_path()
# ═══════════════════════════════════════════════════════════════════


class TestRuleEngineGetRulesPath(unittest.TestCase):
    def _make_config(self, enabled: bool, path: str = '') -> object:
        return type(
            'FakeConfig',
            (),
            {
                'rules': type(
                    'FakeRules',
                    (),
                    {'enabled': enabled, 'path': path},
                )()
            },
        )()

    def test_get_rules_path_disabled(self) -> None:
        result = RuleEngine.get_rules_path(self._make_config(False), '/tmp/WORKFLOW.md')
        self.assertIsNone(result)

    def test_get_rules_path_enabled_default(self) -> None:
        result = RuleEngine.get_rules_path(self._make_config(True), '/tmp/WORKFLOW.md')
        self.assertIsNotNone(result)
        self.assertTrue(result.endswith('workflow.rules.yaml'))

    def test_get_rules_path_enabled_custom(self) -> None:
        result = RuleEngine.get_rules_path(
            self._make_config(True, 'my-rules.yaml'), '/tmp/WORKFLOW.md'
        )
        self.assertTrue(result.endswith('my-rules.yaml'))

    def test_get_rules_path_no_workflow_path(self) -> None:
        result = RuleEngine.get_rules_path(self._make_config(True), None)
        self.assertIsNone(result)

    def test_get_rules_path_no_rules_attr(self) -> None:
        config = type('FakeConfig', (), {})()
        result = RuleEngine.get_rules_path(config, '/tmp/WORKFLOW.md')
        self.assertIsNone(result)
