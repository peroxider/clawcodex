"""F-121: Rule extraction, storage, and retrieval from PR review feedback.

Phase 1 — end-to-end minimal pipeline:
  - RuleStore: read/write workflow.rules.yaml with atomic write
  - RuleEngine.extract(): parse agent reply for ## Extracted Rules section

Phase 2 — intelligent processing:
  - RuleEmbedder: TF-IDF + cosine similarity for semantic dedup (Phase 1
    fallback — Phase 3 should prioritise a sentence-transformer model)
  - RuleEngine.merge(): merge similar rules (via configurable threshold)
  - RuleEngine.score(): 5-dimension quality scoring
  - RuleEngine.prune(): auto-prune when over max_rules limit
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Regex to find the ## Extracted Rules section in an agent reply.
_RULES_SECTION_RE = re.compile(
    r'^##\s+Extracted\s+Rules\s*\n(.*?)(?=\n##\s|\Z)',
    re.DOTALL | re.MULTILINE,
)

# Regex to parse individual rule items inside the section — strict form.
# Matches the canonical template format: `- [category] summary` + optional
# `Body: ...` on the next indented line. Kept for backward compatibility
# with the prompt template's documented format (F-121 §2.3).
#
# The lookahead accepts the start of ANY next list item (strict `[cat]`,
# loose `**bold**`, or bare `\w` summary) so a strict item does not
# greedily swallow a following loose-format item (F-121 fix).
#
# The Body capture tolerates an optional leading list marker (`- ` or
# `* `) since LLMs frequently write `  - Body: ...` instead of `  Body:`
# (F-121 fix).
_RULE_ITEM_RE = re.compile(
    r'^\s*[-*]\s+\[([^\]]+)\]\s+(.+?)(?:\n\s*[-*]?\s*Body:\s*(.+?))?'
    r'(?=\n\s*[-*]\s+(?:\[|\*\*|\w)|\n\s*$|\Z)',
    re.DOTALL | re.MULTILINE,
)

# F-121 fix: loose fallback regex for LLM output that deviates from the
# template. Tolerates three common deviations observed in practice:
#   (a) bold title instead of `[category]` — `- **Quote Style** — desc`
#   (b) Body line with a leading list marker — `  - Body: ...`
#   (c) bare summary with no category / title — `- Use double quotes`
# The category capture group is empty when no `[category]` prefix is
# present; `_infer_category()` then maps summary/body keywords to a
# canonical category (or falls back to `other`).
# Group layout: (1)=category-or-empty (2)=summary (3)=body-or-None
_RULE_ITEM_LOOSE_RE = re.compile(
    r'^\s*[-*]\s+(?:\[([^\]]*)\]\s+|\*\*([^*]*)\*\*\s*[-\u2014]\s+)?(.+?)'
    r'(?:\n\s*[-*]?\s*Body:\s*(.+?))?'
    r'(?=\n\s*[-*]\s+(?:\[|\*\*|\w)|\n\s*$|\Z)',
    re.DOTALL | re.MULTILINE,
)

# F-121 §2.2 canonical category enum. Used by `_infer_category()` to map
# free-form summary/body text to a category when the agent omits `[cat]`.
_RULE_CATEGORIES = (
    'naming',
    'error_handling',
    'testing',
    'import_style',
    'code_style',
    'type_annotation',
    'architecture',
    'boilerplate',
    'security',
    'performance',
    'other',
)

# Keyword → category inference map (checked in order; first hit wins).
# Keys are lowercased substrings; a rule whose summary or body contains
# any keyword is assigned the corresponding category.
_CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ('error_handling', ('except', 'exception', 'error', 'raise', 'try', 'catch', '异常')),
    ('testing', ('test', 'pytest', 'assert', 'fixture', 'mock', '测试')),
    ('import_style', ('import', '导入', '排序')),
    ('type_annotation', ('type', 'annotation', 'typing', 'mypy', '类型')),
    ('naming', ('name', 'naming', 'variable', 'function', 'class', '命名')),
    ('architecture', ('layer', 'module', 'depend', '分层', '依赖', '架构')),
    ('boilerplate', ('license', 'header', 'docstring', 'doc', '注释', '版权')),
    ('security', ('security', 'auth', 'token', 'secret', '安全', '密钥')),
    ('performance', ('perf', 'performance', 'speed', 'cache', '性能', '缓存')),
    (
        'code_style',
        (
            'quote',
            '引号',
            '双引号',
            '单引号',
            'indent',
            '缩进',
            'space',
            '空格',
            'format',
            '格式',
            'style',
            '风格',
            'bracket',
            '括号',
        ),
    ),
]


def _infer_category(text: str) -> str:
    """Map free-form rule text to a canonical category by keyword match.

    Returns the first matching category from ``_CATEGORY_KEYWORDS``, or
    ``'other'`` if no keyword hits. Used when the agent omits the
    ``[category]`` prefix (F-121 fix for loose LLM output).
    """
    lowered = text.lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(kw.lower() in lowered for kw in keywords):
            return category
    return 'other'


_AUTO_MANAGED_COMMENT = (
    '# workflow.rules.yaml \u2014 \u7531 clawcodex orchestrator \u81ea\u52a8\u7ba1\u7406'
)

# Default quality-score weights.
_W_SUPPORT = 0.30
_W_SPECIFICITY = 0.25
_W_RECENCY = 0.10
_W_AUTHORITY = 0.15
_W_CRITICALITY = 0.20


# ---------------------------------------------------------------------------
# Tokeniser
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    """Lowercase word tokens (strips punctuation)."""
    return re.findall(r'\w+', text.lower())


# ---------------------------------------------------------------------------
# RuleStore
# ---------------------------------------------------------------------------


class RuleStore:
    """Read/write ``workflow.rules.yaml`` with atomic write safety."""

    DEFAULT_FILENAME = 'workflow.rules.yaml'

    @staticmethod
    def resolve_path(workflow_path: str, rules_path: str) -> str:
        if rules_path:
            p = Path(rules_path)
            if p.is_absolute():
                return str(p)
            return str(Path(workflow_path).parent / rules_path)
        return str(Path(workflow_path).parent / RuleStore.DEFAULT_FILENAME)

    @staticmethod
    def load(path: str) -> dict:
        p = Path(path)
        if not p.exists():
            return {'version': 1, 'rules': []}
        try:
            raw = p.read_text(encoding='utf-8')
            data = yaml.safe_load(raw)
            if not isinstance(data, dict):
                return {'version': 1, 'rules': []}
            data.setdefault('version', 1)
            data.setdefault('rules', [])
            return data
        except (yaml.YAMLError, OSError) as exc:
            logger.warning('Failed to load rules file %s: %s', path, exc)
            return {'version': 1, 'rules': []}

    @staticmethod
    def save(path: str, rules: list[dict], version: int = 1) -> None:
        p = Path(path)
        content = yaml.dump(
            {'version': version, 'rules': rules},
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )
        full_content = f'{_AUTO_MANAGED_COMMENT}\n{content}'
        tmp = p.with_suffix('.yaml.tmp')
        try:
            tmp.write_text(full_content, encoding='utf-8')
            tmp.replace(p)
        except OSError as exc:
            logger.error('Failed to save rules file %s: %s', path, exc)
            raise

    @staticmethod
    def is_user_managed(path: str) -> bool:
        p = Path(path)
        if not p.exists():
            return False
        try:
            first = p.read_text(encoding='utf-8').splitlines()[0] if p.stat().st_size > 0 else ''
            return _AUTO_MANAGED_COMMENT not in first
        except (OSError, IndexError):
            return False

    @staticmethod
    def ensure_file(path: str) -> None:
        p = Path(path)
        if p.exists():
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        RuleStore.save(path, [], version=1)


# ---------------------------------------------------------------------------
# RuleEmbedder — TF-IDF + cosine similarity (no external deps)
# ---------------------------------------------------------------------------


class RuleEmbedder:
    """Phase 1 fallback text similarity using TF-IDF + cosine similarity.

    This is a lightweight pure-Python implementation (no external
    dependencies) intended as a Phase 1 fallback.  In Phase 3 this
    should be replaced with a sentence-transformer model (e.g.
    ``all-MiniLM-L6-v2``) for better semantic accuracy, with TF-IDF
    retained as a fallback when the model is unavailable.

    Builds a vocabulary from all input texts on each ``embed_many()``
    call, so the caller should batch all texts that need to be compared.
    """

    def __init__(self) -> None:
        self._vocab: dict[str, int] = {}
        self._idf: dict[str, float] = {}
        self._n_docs: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        """Vectorise a batch of texts.

        Builds a joint vocabulary and IDF across the entire batch, then
        returns a ``list[list[float]]`` where each inner list is the
        TF-IDF vector for the corresponding text.
        """
        self._n_docs = len(texts)
        self._build_vocab(texts)
        return [self._vector(t) for t in texts]

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        """Cosine similarity between two vectors (0.0 – 1.0)."""
        dot = sum(ai * bi for ai, bi in zip(a, b))
        norm_a = math.sqrt(sum(ai * ai for ai in a))
        norm_b = math.sqrt(sum(bi * bi for bi in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_vocab(self, texts: list[str]) -> None:
        """Build vocabulary and compute IDF across all texts."""
        doc_freq: Counter[str] = Counter()
        all_tokens: set[str] = set()
        for text in texts:
            tokens = set(_tokenize(text))
            doc_freq.update(tokens)
            all_tokens.update(tokens)

        self._vocab = {t: i for i, t in enumerate(sorted(all_tokens))}
        n = self._n_docs or len(texts)
        self._idf = {t: math.log((n + 1) / (doc_freq[t] + 1)) + 1.0 for t in all_tokens}

    def _vector(self, text: str) -> list[float]:
        """Compute the TF-IDF vector for one text against the current vocab."""
        tokens = _tokenize(text)
        if not tokens:
            return [0.0] * len(self._vocab)
        tf = Counter(tokens)
        max_tf = float(max(tf.values()))
        vec = [0.0] * len(self._vocab)
        for token, count in tf.items():
            if token in self._vocab:
                tf_norm = 0.5 + 0.5 * (count / max_tf)
                vec[self._vocab[token]] = tf_norm * self._idf.get(token, 1.0)
        return vec


# ---------------------------------------------------------------------------
# RuleEngine
# ---------------------------------------------------------------------------


class RuleEngine:
    """Rule extraction, deduplication, merge, quality scoring, pruning."""

    def __init__(self, store: RuleStore | None = None) -> None:
        self.store = store or RuleStore()

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    @staticmethod
    def extract(agent_reply: str) -> list[dict]:
        match = _RULES_SECTION_RE.search(agent_reply)
        if not match:
            return []
        section = match.group(1).strip()
        rules: list[dict] = []
        now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

        # Track char spans already consumed by the strict regex so the
        # loose fallback does not double-count the same rule. Spans are
        # half-open [start, end) over the stripped section text.
        strict_spans: list[tuple[int, int]] = []

        for m in _RULE_ITEM_RE.finditer(section):
            category = m.group(1).strip()
            summary = m.group(2).strip()
            body = m.group(3).strip() if m.group(3) else ''
            if not body and ':' in summary:
                parts = summary.split(':', 1)
                summary = parts[0].strip()
                body = parts[1].strip()
            rules.append(
                {
                    'category': category,
                    'summary': summary,
                    'body': body,
                    'support_count': 1,
                    'confidence': 'medium',
                    'created_at': now,
                    'updated_at': now,
                    'last_applied': now,
                }
            )
            strict_spans.append((m.start(), m.end()))

        # F-121 fix: loose fallback for LLM output that deviates from the
        # canonical `- [category] summary` template. Common deviations:
        # bold-title instead of `[cat]`, Body line with a leading `- `,
        # or a bare summary with no category prefix at all. We skip any
        # loose match whose start falls inside a strict span to avoid
        # duplicating rules the strict pass already captured.
        def _in_strict_span(pos: int) -> bool:
            for s, e in strict_spans:
                if s <= pos < e:
                    return True
            return False

        for m in _RULE_ITEM_LOOSE_RE.finditer(section):
            if _in_strict_span(m.start()):
                continue
            # Loose group layout: (1)=category-or-None (2)=bold-title-or-None
            # (3)=summary (4)=body-or-None. Exactly one of (1)/(2) is set.
            category = (m.group(1) or '').strip()
            bold_title = (m.group(2) or '').strip()
            summary = (m.group(3) or '').strip()
            body = (m.group(4).strip() if m.group(4) else '').strip()
            if not summary:
                continue
            # If the agent used a bold title instead of [category], fold
            # the title into the summary (it is usually the rule name).
            if bold_title and not category:
                summary = f'{bold_title} — {summary}' if summary else bold_title
            if not body and ':' in summary:
                parts = summary.split(':', 1)
                summary = parts[0].strip()
                body = parts[1].strip()
            if not category or category not in _RULE_CATEGORIES:
                category = _infer_category(f'{summary} {body}')
            rules.append(
                {
                    'category': category,
                    'summary': summary,
                    'body': body,
                    'support_count': 1,
                    'confidence': 'medium',
                    'created_at': now,
                    'updated_at': now,
                    'last_applied': now,
                }
            )
        return rules

    # ------------------------------------------------------------------
    # Semantic dedup + merge (Phase 2)
    # ------------------------------------------------------------------

    @staticmethod
    def _rule_text(r: dict) -> str:
        """Join summary + body for similarity comparison."""
        parts = [r.get('summary', '')]
        if r.get('body'):
            parts.append(r['body'])
        return ' '.join(parts)

    @staticmethod
    def _deduplicate_and_merge(
        candidates: list[dict],
        existing: list[dict],
        similarity_threshold: float = 0.85,
        enhancement_threshold: float = 0.70,
    ) -> list[dict]:
        """Phase 2 semantic dedup + merge.

        Three-way decision per candidate vs. each existing rule:
          - ``sim >= similarity_threshold`` → duplicate → skip, increment
            ``support_count`` on the existing rule.
          - ``enhancement_threshold <= sim < similarity_threshold`` →
            merge: combine summary/body intelligently.
          - ``sim < enhancement_threshold`` → new rule, append.

        Exact duplicate (same summary text) is still caught first as a
        fast path before semantic comparison.
        """
        # --- fast path: exact dedup ---------------------------------------------------
        merged = list(existing)
        existing_map: dict[str, dict] = {}
        for r in merged:
            key = r.get('summary', '').strip().lower()
            if key:
                existing_map[key] = r

        remaining: list[dict] = []
        now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

        for c in candidates:
            key = c.get('summary', '').strip().lower()
            if key and key in existing_map:
                existing_map[key]['support_count'] = existing_map[key].get('support_count', 1) + 1
                existing_map[key]['updated_at'] = now
            else:
                remaining.append(c)

        if not remaining:
            return merged

        # --- semantic dedup + merge ----------------------------------------------------
        # Collect all texts for embedding
        existing_texts = [RuleEngine._rule_text(r) for r in merged]
        candidate_texts = [RuleEngine._rule_text(c) for c in remaining]
        all_texts = existing_texts + candidate_texts

        embedder = RuleEmbedder()
        vectors = embedder.embed_many(all_texts)
        existing_vecs = vectors[: len(merged)]
        candidate_vecs = vectors[len(merged) :]

        next_id = len(merged) + 1
        for ci, c in enumerate(remaining):
            c_vec = candidate_vecs[ci]
            best_sim = 0.0
            best_ei = -1
            for ei, e_vec in enumerate(existing_vecs):
                sim = RuleEmbedder.cosine_similarity(c_vec, e_vec)
                if sim > best_sim:
                    best_sim = sim
                    best_ei = ei

            if best_sim >= similarity_threshold:
                # Duplicate — increment support_count on the closest existing rule
                target = merged[best_ei]
                target['support_count'] = target.get('support_count', 1) + 1
                target['updated_at'] = now
            elif best_sim >= enhancement_threshold:
                # Merge — combine candidate into the closest existing rule
                target = merged[best_ei]
                merged_rule = _merge_two_rules(target, c)
                # Replace in-place
                merged[best_ei] = merged_rule
                # Recompute vector for the merged rule so subsequent candidates
                # compare against the enriched version
                merged_text = RuleEngine._rule_text(merged_rule)
                mvecs = embedder.embed_many([merged_text])
                existing_vecs[best_ei] = mvecs[0]
            else:
                # New rule — append
                c['id'] = next_id
                next_id += 1
                c['updated_at'] = now  # ensure fresh
                merged.append(c)
                existing_vecs.append(candidate_vecs[ci])

        return merged

    # ------------------------------------------------------------------
    # Quality scoring (Phase 2)
    # ------------------------------------------------------------------

    @staticmethod
    def score(rule: dict) -> float:
        """Five-dimension quality score used for auto-pruning.

        Dimensions:
          1. ``support_count_norm``  — capped at 5
          2. ``specificity``          — has body text?
          3. ``recency``              — days since creation (90-day linear decay)
          4. ``authority``            — derived from rule ``confidence`` field
          5. ``criticality``          — default 0.7 (``comment``-level)

        Returns a float in [0.0, 1.0].
        """
        now = datetime.now(timezone.utc)

        # 1. Support count (capped at 5)
        support = rule.get('support_count', 1)
        support_norm = min(support, 5) / 5.0

        # 2. Specificity: body text → 1.0, only summary → 0.3
        body = rule.get('body', '') or ''
        specificity = 1.0 if len(body.strip()) > 20 else 0.3

        # 3. Recency: linear decay over 90 days
        created_str = rule.get('created_at', '')
        days = 999.0
        if created_str:
            try:
                created = datetime.fromisoformat(created_str)
                days = (now - created).total_seconds() / 86400.0
            except (ValueError, TypeError):
                pass
        recency = max(0.0, 1.0 - days / 90.0)

        # 4. Authority derived from confidence field
        conf_levels = {'high': 0.9, 'medium': 0.7, 'low': 0.5}
        authority = conf_levels.get(rule.get('confidence', 'medium'), 0.7)

        # 5. Criticality derived from confidence field
        crit_levels = {'high': 0.9, 'medium': 0.7, 'low': 0.5}
        criticality = crit_levels.get(rule.get('confidence', 'medium'), 0.7)

        return (
            _W_SUPPORT * support_norm
            + _W_SPECIFICITY * specificity
            + _W_RECENCY * recency
            + _W_AUTHORITY * authority
            + _W_CRITICALITY * criticality
        )

    @staticmethod
    def prune(rules: list[dict], max_rules: int) -> list[dict]:
        """Drop lowest-scoring rules when ``len(rules) > max_rules``.

        Returns a trimmed list (never exceeds ``max_rules``).
        """
        if max_rules <= 0 or len(rules) <= max_rules:
            return list(rules)

        scored = [(RuleEngine.score(r), r) for r in rules]
        # Sort descending by score, keep top max_rules
        scored.sort(key=lambda x: x[0], reverse=True)
        kept = [r for _, r in scored[:max_rules]]

        dropped = len(rules) - len(kept)
        if dropped > 0:
            logger.info('Pruned %d low-quality rule(s), kept %d', dropped, len(kept))

        return kept

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def apply(
        self,
        agent_reply: str,
        workflow_rules_path: str,
        similarity_threshold: float = 0.85,
        enhancement_threshold: float = 0.70,
        max_rules: int = 20,
        min_confidence: str | None = None,
    ) -> int:
        """Full pipeline: extract → dedup+merge → score → prune → filter → persist.

        Returns the number of new candidate rules extracted (before
        dedup), or 0 if no rules section was found or the file is
        user-managed.
        """
        candidates = self.extract(agent_reply)
        if not candidates:
            return 0

        if RuleStore.is_user_managed(workflow_rules_path):
            logger.warning(
                'Rules file %s is user-managed (no auto-managed header); skipping write-back',
                workflow_rules_path,
            )
            return 0

        RuleStore.ensure_file(workflow_rules_path)
        existing_data = RuleStore.load(workflow_rules_path)
        existing = existing_data.get('rules', [])

        merged = self._deduplicate_and_merge(
            candidates,
            existing,
            similarity_threshold=similarity_threshold,
            enhancement_threshold=enhancement_threshold,
        )

        # Assign/refresh sequential ids after dedup+merge
        for i, r in enumerate(merged, start=1):
            r['id'] = i

        merged = self.prune(merged, max_rules=max_rules)

        # Filter by min_confidence
        if min_confidence:
            conf_levels = {'low': 0, 'medium': 1, 'high': 2}
            min_level = conf_levels.get(min_confidence, 0)
            before = len(merged)
            merged = [
                r for r in merged if conf_levels.get(r.get('confidence', 'low'), 0) >= min_level
            ]
            if len(merged) < before:
                logger.info(
                    'Filtered %d rule(s) below min_confidence=%s',
                    before - len(merged),
                    min_confidence,
                )

        RuleStore.save(
            workflow_rules_path,
            merged,
            version=existing_data.get('version', 1),
        )
        logger.info(
            'Extracted %d rule(s), merged to %d total in %s',
            len(candidates),
            len(merged),
            workflow_rules_path,
        )
        return len(candidates)

    @staticmethod
    def get_rules_path(config: Any, workflow_path: str | None) -> str | None:
        rules_config = getattr(config, 'rules', None)
        if not rules_config or not getattr(rules_config, 'enabled', False):
            return None
        rules_path = getattr(rules_config, 'path', '') or ''
        if not workflow_path:
            return None
        return RuleStore.resolve_path(workflow_path, rules_path)


# ---------------------------------------------------------------------------
# Merge helper
# ---------------------------------------------------------------------------


def _merge_two_rules(a: dict, b: dict) -> dict:
    """Merge two similar rules into a single enriched rule.

    ``a`` is the existing (higher-confidence) rule; ``b`` is the
    candidate.  The merge picks the best of each field.
    """
    # Summary: pick the longer / more specific one
    summary_a = (a.get('summary') or '').strip()
    summary_b = (b.get('summary') or '').strip()
    merged_summary = summary_a if len(summary_a) >= len(summary_b) else summary_b

    # Body: pick the longer one, or concatenate if both present
    body_a = (a.get('body') or '').strip()
    body_b = (b.get('body') or '').strip()
    if body_a and body_b:
        merged_body = body_a if len(body_a) >= len(body_b) else body_b
    else:
        merged_body = body_a or body_b

    # Category: prefer the more specific one (longer string), or 'multi' if incompatible
    cat_a = (a.get('category') or '').strip()
    cat_b = (b.get('category') or '').strip()
    if cat_a and cat_b and cat_a != cat_b:
        merged_category = 'multi'
    else:
        merged_category = cat_a or cat_b or 'other'

    # Support count: sum
    support = (a.get('support_count') or 1) + (b.get('support_count') or 1)

    # Source: append if different
    source_a = (a.get('source') or '').strip()
    source_b = (b.get('source') or '').strip()
    merged_source = source_a
    if source_b and source_b not in merged_source:
        merged_source = f'{merged_source}; {source_b}' if merged_source else source_b

    # Confidence: take the higher one
    conf_order = {'low': 0, 'medium': 1, 'high': 2}
    conf_a = conf_order.get(a.get('confidence', 'medium'), 1)
    conf_b = conf_order.get(b.get('confidence', 'medium'), 1)
    merged_confidence = (
        'high' if max(conf_a, conf_b) >= 2 else 'medium' if max(conf_a, conf_b) >= 1 else 'low'
    )

    # Timestamps
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    created_a = a.get('created_at', '') or now
    created_b = b.get('created_at', '') or now
    merged_created = min(created_a, created_b)

    return {
        'summary': merged_summary,
        'body': merged_body,
        'category': merged_category,
        'support_count': support,
        'source': merged_source,
        'confidence': merged_confidence,
        'created_at': merged_created,
        'updated_at': now,
        'last_applied': now,
    }
