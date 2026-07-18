"""Tests for P119-A/B/H section registry — unified _registry + runtime_ctx + tags.

Covers the acceptance criteria from F-119 §3.1:
  items 1-4 — register/override/insert/disable
  items 5   — dump stability (in test_prompt_dump.py)
  items 7-8 — default byte-stability and 5-path assembly
  items 11-13 — P119-H tags, runtime_ctx, collect_new_sections
"""

from __future__ import annotations

import unittest

from clawcodex_ext.context_system.section_registry import (
    SectionScope,
    clear_section_registry,
    collect_new_sections,
    consult_section_builders,
    get_section_order,
    get_section_scope,
    get_sections_by_tag,
    get_sections_by_all_tags,
    get_section_tags,
    register_section,
    override_section,
    disable_section,
    insert_section,
)
from clawcodex_ext.context_system.system_prompt_cache import (
    CacheScope,
    SystemPromptSection,
)


# ============================================================================
# P119-A: register_section + consult_section_builders
# ============================================================================

class TestRegisterSection(unittest.TestCase):
    """register_section + consult_section_builders basic behaviour."""

    def setUp(self):
        clear_section_registry()

    def test_consult_returns_none_without_registration(self):
        result = consult_section_builders("intro")
        self.assertIsNone(result)

    def test_register_and_consult(self):
        def _builder(ctx):
            return "custom"
        register_section("intro", builder=_builder)
        result = consult_section_builders("intro")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, SystemPromptSection)
        self.assertEqual(result.content, "custom")

    def test_builder_returning_none_suppresses(self):
        def _builder(ctx):
            return None
        register_section("system", builder=_builder)
        result = consult_section_builders("system")
        self.assertIsNone(result)

    def test_register_section_overrides_default_content(self):
        """AC item 1: registered section content replaces default."""
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
        )

        def _custom(ctx):
            return "CUSTOM INTRO"
        register_section("intro", builder=_custom)
        prompt = build_full_system_prompt(cwd="/tmp")
        self.assertIn("CUSTOM INTRO", prompt)
        self.assertNotIn("interactive agent", prompt)

    def test_register_new_section_appears(self):
        """Registering a non-canonical id injects a new section."""
        def _issue(ctx):
            return "## Issue\nTitle: fix bug"
        register_section("issue-context", builder=_issue, order=55)
        ctx = {"workflow_phase": "coding"}
        sections = collect_new_sections(ctx)
        ids = [s.id for s in sections]
        self.assertIn("issue-context", ids)

    def test_different_keys_isolated(self):
        def _intro(ctx):
            return "custom_intro"
        register_section("intro", builder=_intro)
        result = consult_section_builders("system")
        self.assertIsNone(result)

    def test_last_registration_wins(self):
        """Registering twice for the same id overwrites (single-builder)."""
        def _first(ctx):
            return "first"
        def _second(ctx):
            return "second"
        register_section("intro", builder=_first)
        register_section("intro", builder=_second)
        result = consult_section_builders("intro")
        self.assertEqual(result.content, "second")

    def test_builder_receives_runtime_ctx(self):
        """P119-H: builder receives the runtime_ctx passed to consult."""
        def _checker(ctx):
            return f"phase={ctx.get('workflow_phase', 'none')}"
        register_section("doing_tasks", builder=_checker)
        result = consult_section_builders("doing_tasks", {"workflow_phase": "verify"})
        self.assertIn("phase=verify", result.content)


# ============================================================================
# P119-B: override_section / disable_section / insert_section
# ============================================================================

class TestOverrideSection(unittest.TestCase):
    def setUp(self):
        clear_section_registry()
        from clawcodex_ext.context_system.prompt_assembly import get_system_prompt_cache
        get_system_prompt_cache().invalidate_all()

    def test_override_section_immediate_effect(self):
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
        )
        override_section("doing_tasks", "CUSTOM DOING TASKS", reason="test")
        prompt = build_full_system_prompt(cwd="/tmp")
        self.assertIn("CUSTOM DOING TASKS", prompt)

    def test_override_section_invalidates_cache(self):
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
            get_system_prompt_cache,
        )
        cache = get_system_prompt_cache()
        cache.invalidate_all()
        build_full_system_prompt(cwd="/tmp")
        self.assertIsNotNone(cache.get("intro"))
        override_section("intro", "CUSTOM", reason="test")
        self.assertIsNone(cache.get("intro"))

    def test_override_section_returns_section(self):
        section = override_section("intro", "content", reason="test")
        self.assertIsInstance(section, SystemPromptSection)
        self.assertEqual(section.id, "intro")
        self.assertEqual(section.content, "content")

    def test_override_wins(self):
        """override_section overwrites any prior registration."""
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
            get_system_prompt_cache,
        )
        cache = get_system_prompt_cache()
        cache.invalidate_all()
        # Register a plain builder first.
        register_section("intro", builder=lambda ctx: "EARLIER")
        # Then override.
        override_section("intro", "OVERRIDE_WINS", reason="test")
        prompt = build_full_system_prompt(cwd="/tmp")
        self.assertIn("OVERRIDE_WINS", prompt)
        self.assertNotIn("EARLIER", prompt)


class TestDisableSection(unittest.TestCase):
    def setUp(self):
        clear_section_registry()
        from clawcodex_ext.context_system.prompt_assembly import get_system_prompt_cache
        get_system_prompt_cache().invalidate_all()

    def test_disable_section_removes_content(self):
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
        )
        disable_section("tone_style")
        prompt = build_full_system_prompt(cwd="/tmp")
        self.assertNotIn("Tone and style", prompt)

    def test_disable_section_other_sections_remain(self):
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
        )
        disable_section("tone_style")
        prompt = build_full_system_prompt(cwd="/tmp")
        self.assertIn("Using your tools", prompt)


class TestInsertSection(unittest.TestCase):
    def setUp(self):
        clear_section_registry()
        from clawcodex_ext.context_system.prompt_assembly import get_system_prompt_cache
        get_system_prompt_cache().invalidate_all()

    def test_insert_section_appears_in_prompt(self):
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
        )
        insert_section("intro", "self_iter_meta", "## Iteration Meta", reason="test")
        prompt = build_full_system_prompt(cwd="/tmp")
        self.assertIn("## Iteration Meta", prompt)

    def test_insert_section_ordering(self):
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
        )
        insert_section("intro", "meta", "[[META]]", reason="test")
        prompt = build_full_system_prompt(cwd="/tmp")
        intro_pos = prompt.find("interactive agent")
        meta_pos = prompt.find("[[META]]")
        sys_pos = prompt.find("All text you output")
        self.assertLess(intro_pos, meta_pos)
        self.assertLess(meta_pos, sys_pos)

    def test_insert_section_no_invalidate(self):
        """insert_section does NOT invalidate existing cache entries."""
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt_blocks,
            get_system_prompt_cache,
        )
        cache = get_system_prompt_cache()
        cache.invalidate_all()
        build_full_system_prompt_blocks(cwd="/tmp", tools=[{"name": "test"}])
        self.assertIsNotNone(cache.get("intro"))
        insert_section("intro", "meta", "[[META]]", cache_scope=CacheScope.SESSION, reason="test")
        self.assertIsNotNone(cache.get("intro"))

    def test_insert_section_returns_section(self):
        section = insert_section("intro", "new_id", "content", reason="test")
        self.assertIsInstance(section, SystemPromptSection)
        self.assertEqual(section.id, "new_id")
        self.assertEqual(section.order, 0.5)


# ============================================================================
# P119-H: tags + runtime_ctx + collect_new_sections
# ============================================================================

class TestTags(unittest.TestCase):
    """P119-H: tags filtering APIs."""

    def setUp(self):
        clear_section_registry()

    def test_register_with_tags(self):
        register_section("issue-ctx", builder=lambda ctx: "issue", tags=["workflow", "tracker"])
        register_section("ci-status", builder=lambda ctx: "ci", tags=["ci"])
        register_section("untagged", builder=lambda ctx: "plain")

        workflow = get_sections_by_tag("workflow")
        self.assertEqual(len(workflow), 1)
        self.assertEqual(workflow[0].id, "issue-ctx")

        ci_or_workflow = get_sections_by_tag("ci", "workflow")
        self.assertEqual(len(ci_or_workflow), 2)

        all_tags = get_sections_by_tag()
        self.assertEqual(len(all_tags), 3)

    def test_get_sections_by_all_tags(self):
        register_section("both", builder=lambda ctx: "x", tags=["ci", "workflow"])
        register_section("ci-only", builder=lambda ctx: "y", tags=["ci"])

        result = get_sections_by_all_tags("ci", "workflow")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "both")

    def test_get_section_tags(self):
        register_section("x", builder=lambda ctx: "x", tags=["ci", "workflow"])
        tags = get_section_tags("x")
        self.assertEqual(tags, {"ci", "workflow"})

    def test_get_section_tags_unregistered(self):
        self.assertEqual(get_section_tags("nonexistent"), set())

    def test_collect_new_sections_filters_by_tags(self):
        register_section("issue", builder=lambda ctx: "issue", tags=["workflow"])
        register_section("ci", builder=lambda ctx: "ci-status", tags=["ci"])
        register_section("plain", builder=lambda ctx: "plain")

        workflow_only = collect_new_sections({}, tags=["workflow"])
        ids = {s.id for s in workflow_only}
        self.assertIn("issue", ids)
        self.assertNotIn("ci", ids)
        self.assertNotIn("plain", ids)


class TestCollectNewSections(unittest.TestCase):
    """P119-H: collect_new_sections filters out canonical IDs."""

    def setUp(self):
        clear_section_registry()

    def test_known_sections_excluded(self):
        register_section("intro", builder=lambda ctx: "custom intro")
        register_section("new-section", builder=lambda ctx: "brand new", order=55)
        results = collect_new_sections({})
        ids = {s.id for s in results}
        self.assertNotIn("intro", ids, "known sections must be excluded")
        self.assertIn("new-section", ids)

    def test_sorted_by_order(self):
        register_section("z", builder=lambda ctx: "z", order=90)
        register_section("a", builder=lambda ctx: "a", order=10)
        results = collect_new_sections({})
        orders = [s.order for s in results]
        self.assertEqual(orders, sorted(orders))

    def test_builder_returning_none_excluded(self):
        register_section("skip", builder=lambda ctx: None)
        register_section("keep", builder=lambda ctx: "content", order=55)
        results = collect_new_sections({})
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, "keep")


class TestRuntimeCtx(unittest.TestCase):
    """P119-H: runtime_ctx threaded through build chain."""

    def setUp(self):
        clear_section_registry()
        from clawcodex_ext.context_system.prompt_assembly import get_system_prompt_cache
        get_system_prompt_cache().invalidate_all()

    def test_consult_receives_runtime_ctx(self):
        captured: list[dict] = []

        def _capture(ctx):
            captured.append(dict(ctx))
            return f"phase={ctx.get('workflow_phase')}"
        register_section("intro", builder=_capture)

        consult_section_builders("intro", {"workflow_phase": "verify", "task_id": "T-1"})
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].get("workflow_phase"), "verify")
        self.assertEqual(captured[0].get("task_id"), "T-1")

    def test_build_forward_runtime_ctx_to_builder(self):
        """build_full_system_prompt_blocks(runtime_ctx=...) reaches builders."""
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
            build_full_system_prompt_blocks,
        )

        captured: list[dict] = []

        def _capture(ctx):
            captured.append(dict(ctx))
            return f"phase={ctx.get('workflow_phase')}"
        register_section("doing_tasks", builder=_capture)

        build_full_system_prompt(cwd="/tmp", runtime_ctx={"workflow_phase": "coding"})
        self.assertGreaterEqual(len(captured), 1)
        ctx = captured[0]
        self.assertEqual(ctx.get("workflow_phase"), "coding")
        # cwd should be auto-injected into runtime_ctx
        self.assertEqual(ctx.get("cwd"), "/tmp")

    def test_blocks_path_same_as_str_path(self):
        """Both build paths produce same content with runtime_ctx."""
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
            build_full_system_prompt_blocks,
        )

        capture_str = []
        capture_blk = []

        def _str_builder(ctx):
            capture_str.append(dict(ctx))
            return "marker-str"
        def _blk_builder(ctx):
            capture_blk.append(dict(ctx))
            return "marker-blk"

        register_section("new-section-a", builder=_str_builder, order=55)
        register_section("new-section-b", builder=_blk_builder, order=56)

        ctx = {"workflow_phase": "test"}
        str_prompt = build_full_system_prompt(cwd="/tmp", runtime_ctx=ctx)
        blk_prompt = build_full_system_prompt_blocks(cwd="/tmp", runtime_ctx=ctx)

        self.assertIn("marker-str", str_prompt)
        self.assertIn("marker-blk", str_prompt)
        block_text = "\n\n".join(b.get("text", "") for b in blk_prompt)
        self.assertIn("marker-str", block_text)
        self.assertIn("marker-blk", block_text)

    def test_default_runtime_ctx_empty_dict(self):
        """Without runtime_ctx, builders receive an empty dict (plus cwd)."""
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
        )
        captured = []

        def _capture(ctx):
            captured.append(dict(ctx))
            return "ok"
        register_section("new-section", builder=_capture, order=55)

        build_full_system_prompt(cwd="/tmp")
        self.assertGreaterEqual(len(captured), 1)
        # Should have at least cwd injected
        self.assertEqual(captured[0].get("cwd"), "/tmp")


# ============================================================================
# Canonical metadata
# ============================================================================

class TestSectionMetadata(unittest.TestCase):
    def test_known_section_orders(self):
        self.assertEqual(get_section_order("intro"), 0)
        self.assertEqual(get_section_order("system"), 1)
        self.assertEqual(get_section_order("tool_docs"), 10)
        self.assertEqual(get_section_order("memory"), 25)
        self.assertEqual(get_section_order("tool_restrictions"), 90)

    def test_unknown_section_returns_zero(self):
        self.assertEqual(get_section_order("nonexistent"), 0)

    def test_known_section_scopes(self):
        self.assertEqual(get_section_scope("intro"), SectionScope.GLOBAL)
        self.assertEqual(get_section_scope("tool_docs"), SectionScope.SESSION)
        self.assertEqual(get_section_scope("environment"), SectionScope.REQUEST)

    def test_unknown_section_returns_session(self):
        self.assertEqual(get_section_scope("nonexistent"), SectionScope.SESSION)


# ============================================================================
# Iteration meta (P119-D via new API)
# ============================================================================

class TestIterationMeta(unittest.TestCase):
    """P119-D: iteration_meta section injector via register_section."""

    def setUp(self):
        clear_section_registry()
        from clawcodex_ext.context_system.prompt_assembly import get_system_prompt_cache
        get_system_prompt_cache().invalidate_all()

    def test_no_builder_section_absent(self):
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
        )
        prompt = build_full_system_prompt(cwd="/tmp")
        self.assertNotIn("ITER_META", prompt)

    def test_register_builder_section_present(self):
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
        )
        register_section(
            "iteration_meta",
            builder=lambda ctx: "# Iteration Meta\nCurrent round: 3",
        )
        prompt = build_full_system_prompt(cwd="/tmp")
        self.assertIn("Iteration Meta", prompt)
        self.assertIn("Current round: 3", prompt)

    def test_builder_returning_none_suppresses_section(self):
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
        )
        register_section("iteration_meta", builder=lambda ctx: None)
        prompt = build_full_system_prompt(cwd="/tmp")
        self.assertNotIn("Iteration Meta", prompt)

    def test_iteration_meta_after_tool_restrictions(self):
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
        )
        register_section("iteration_meta", builder=lambda ctx: "[[ITER_META_MARKER]]")
        prompt = build_full_system_prompt(
            cwd="/tmp",
            tool_restrictions=["some_tool"],
        )
        restrict_pos = prompt.find("Tool Restrictions")
        meta_pos = prompt.find("[[ITER_META_MARKER]]")
        self.assertLess(restrict_pos, meta_pos)

    def test_dump_includes_iteration_meta(self):
        from clawcodex_ext.context_system.prompt_dump import dump_effective_system_prompt
        register_section("iteration_meta", builder=lambda ctx: "DUMP_META")
        snapshots = dump_effective_system_prompt(cwd="/tmp")
        ids = {s.id for s in snapshots}
        self.assertIn("iteration_meta", ids)

    def test_byte_stability_with_iteration_meta(self):
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt_blocks,
        )
        register_section("iteration_meta", builder=lambda ctx: "STABLE_META")
        blocks_a = build_full_system_prompt_blocks(cwd="/tmp")
        blocks_b = build_full_system_prompt_blocks(cwd="/tmp")
        self.assertEqual(blocks_a, blocks_b)


# ============================================================================
# Default byte-stability (acceptance criteria 7 & 8)
# ============================================================================

class TestDefaultByteStability(unittest.TestCase):
    def setUp(self):
        clear_section_registry()
        from clawcodex_ext.context_system.prompt_assembly import get_system_prompt_cache
        get_system_prompt_cache().invalidate_all()

    def test_default_blocks_byte_identical(self):
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt_blocks,
        )
        blocks_a = build_full_system_prompt_blocks(cwd="/tmp")
        blocks_b = build_full_system_prompt_blocks(cwd="/tmp")
        self.assertEqual(blocks_a, blocks_b)

    def test_default_prompt_contains_seven_static_sections(self):
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
        )
        prompt = build_full_system_prompt(cwd="/tmp")
        self.assertIn("Using your tools", prompt)
        self.assertIn("Executing actions with care", prompt)
        self.assertIn("Communicating with the user", prompt)

    def test_default_without_builders_is_byte_equal(self):
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt_blocks,
        )
        blocks_a = build_full_system_prompt_blocks(cwd="/tmp")
        blocks_b = build_full_system_prompt_blocks(cwd="/tmp")
        self.assertEqual(blocks_a, blocks_b)


# ============================================================================
# Cache invalidation (P119-F)
# ============================================================================

class TestCacheInvalidation(unittest.TestCase):
    def setUp(self):
        clear_section_registry()
        from clawcodex_ext.context_system.prompt_assembly import get_system_prompt_cache
        get_system_prompt_cache().invalidate_all()

    def test_override_invalidates_section_only(self):
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt_blocks,
            get_system_prompt_cache,
        )
        cache = get_system_prompt_cache()
        cache.invalidate_all()
        build_full_system_prompt_blocks(cwd="/tmp", tools=[{"name": "test_tool"}])
        self.assertIsNotNone(cache.get("intro"))
        self.assertIsNotNone(cache.get("tool_docs"))
        override_section("intro", "CUSTOM_INTRO", reason="test")
        self.assertIsNone(cache.get("intro"))
        self.assertIsNotNone(cache.get("tool_docs"))

    def test_override_next_build_sees_new_content(self):
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
            get_system_prompt_cache,
        )
        cache = get_system_prompt_cache()
        cache.invalidate_all()
        build_full_system_prompt(cwd="/tmp")
        self.assertIsNotNone(cache.get("intro"))
        override_section("intro", "CUSTOM_INTRO", reason="test")
        prompt = build_full_system_prompt(cwd="/tmp")
        self.assertIn("CUSTOM_INTRO", prompt)

    def test_disable_invalidates_section_only(self):
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt_blocks,
            get_system_prompt_cache,
        )
        cache = get_system_prompt_cache()
        cache.invalidate_all()
        build_full_system_prompt_blocks(cwd="/tmp", tools=[{"name": "test_tool"}])
        self.assertIsNotNone(cache.get("intro"))
        self.assertIsNotNone(cache.get("tool_docs"))
        disable_section("tool_docs")
        self.assertIsNone(cache.get("tool_docs"))
        self.assertIsNotNone(cache.get("intro"))


if __name__ == "__main__":
    unittest.main()
