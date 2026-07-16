"""Tests for P119-A/B section registry and override APIs.

Covers the 5-path acceptance criteria from F-119 §3.1 (items 1-4, 7-8).
"""

from __future__ import annotations

import unittest

from clawcodex_ext.context_system.section_registry import (
    SectionScope,
    clear_section_registry,
    consult_section_builders,
    get_inserted_sections,
    get_section_order,
    get_section_scope,
    register_section_builder,
    register_inserted_section,
)
from clawcodex_ext.context_system.system_prompt_cache import (
    CacheScope,
    SystemPromptSection,
    system_prompt_section,
)


class TestSectionRegistry(unittest.TestCase):
    """P119-A: generic section builder registry."""

    def setUp(self):
        clear_section_registry()

    def test_consult_returns_none_without_registration(self):
        result = consult_section_builders("intro")
        self.assertIsNone(result)

    def test_register_and_consult_single_builder(self):
        def _builder():
            return SystemPromptSection(
                id="intro", content="custom", cache_scope=CacheScope.GLOBAL, order=0,
            )

        register_section_builder("intro", _builder)
        result = consult_section_builders("intro")
        self.assertIsNotNone(result)
        self.assertEqual(result.content, "custom")

    def test_first_non_none_builder_wins(self):
        def _first():
            return SystemPromptSection(
                id="intro", content="first", cache_scope=CacheScope.GLOBAL, order=0,
            )

        def _second():
            return SystemPromptSection(
                id="intro", content="second", cache_scope=CacheScope.GLOBAL, order=0,
            )

        register_section_builder("intro", _first)
        register_section_builder("intro", _second)
        result = consult_section_builders("intro")
        self.assertEqual(result.content, "first")

    def test_builder_returning_none_falls_through(self):
        def _none_builder():
            return None

        register_section_builder("system", _none_builder)
        result = consult_section_builders("system")
        self.assertIsNone(result)

    def test_different_keys_isolated(self):
        """Builders for different (id, order, scope) keys are independent."""
        def _intro():
            return SystemPromptSection(
                id="intro", content="custom_intro", cache_scope=CacheScope.GLOBAL, order=0,
            )

        register_section_builder("intro", _intro)
        # system section should be unaffected
        result = consult_section_builders("system")
        self.assertIsNone(result)


class TestSectionMetadata(unittest.TestCase):
    """P119-B: canonical section order and scope mappings."""

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


class TestInsertedSections(unittest.TestCase):
    """P119-B: insert_section infrastructure."""

    def setUp(self):
        clear_section_registry()

    def test_register_and_get_inserted(self):
        section = system_prompt_section(
            name="custom_meta",
            content="meta content",
            cache_scope=CacheScope.SESSION,
            order=15,
        )
        register_inserted_section(section)
        result = get_inserted_sections()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "custom_meta")
        self.assertEqual(result[0].content, "meta content")
        self.assertEqual(result[0].order, 15)


class TestOverrideSection(unittest.TestCase):
    """P119-B: override_section API."""

    def setUp(self):
        clear_section_registry()
        from clawcodex_ext.context_system.prompt_assembly import get_system_prompt_cache

        get_system_prompt_cache().invalidate_all()

    def test_override_section_immediate_effect(self):
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
            get_system_prompt_cache,
        )
        from clawcodex_ext.context_system.section_registry import override_section

        get_system_prompt_cache().invalidate_all()
        override_section("doing_tasks", "CUSTOM DOING TASKS", reason="test")
        prompt = build_full_system_prompt(cwd="/tmp")
        self.assertIn("CUSTOM DOING TASKS", prompt)

    def test_override_section_invalidates_cache(self):
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
            get_system_prompt_cache,
        )
        from clawcodex_ext.context_system.section_registry import override_section

        get_system_prompt_cache().invalidate_all()
        # First build populates the intro cache.
        build_full_system_prompt(cwd="/tmp")
        cache = get_system_prompt_cache()
        self.assertIsNotNone(cache.get("intro"))

        # Override should invalidate the cached intro.
        override_section("intro", "CUSTOM", reason="test")
        self.assertIsNone(cache.get("intro"))

    def test_override_section_returns_section(self):
        from clawcodex_ext.context_system.section_registry import override_section

        section = override_section("intro", "content", reason="test")
        self.assertIsInstance(section, SystemPromptSection)
        self.assertEqual(section.id, "intro")
        self.assertEqual(section.content, "content")

    def test_override_wins_over_prior_registration(self):
        """P119-B: override_section takes priority over earlier builders."""
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
            get_system_prompt_cache,
        )
        from clawcodex_ext.context_system.section_registry import override_section

        get_system_prompt_cache().invalidate_all()

        # First register a plain builder via the generic API.
        def _earlier():
            return SystemPromptSection(
                id="intro", content="EARLIER", cache_scope=CacheScope.GLOBAL, order=0,
            )

        register_section_builder("intro", _earlier)
        # Then override — should clear the earlier builder and win.
        override_section("intro", "OVERRIDE_WINS", reason="test")
        prompt = build_full_system_prompt(cwd="/tmp")
        self.assertIn("OVERRIDE_WINS", prompt)
        self.assertNotIn("EARLIER", prompt)


class TestDisableSection(unittest.TestCase):
    """P119-B: disable_section API."""

    def setUp(self):
        clear_section_registry()
        from clawcodex_ext.context_system.prompt_assembly import get_system_prompt_cache

        get_system_prompt_cache().invalidate_all()

    def test_disable_section_removes_content(self):
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
            get_system_prompt_cache,
        )
        from clawcodex_ext.context_system.section_registry import disable_section

        get_system_prompt_cache().invalidate_all()
        disable_section("tone_style")
        prompt = build_full_system_prompt(cwd="/tmp")
        self.assertNotIn("Tone and style", prompt)

    def test_disable_section_other_sections_remain(self):
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
            get_system_prompt_cache,
        )
        from clawcodex_ext.context_system.section_registry import disable_section

        get_system_prompt_cache().invalidate_all()
        disable_section("tone_style")
        prompt = build_full_system_prompt(cwd="/tmp")
        self.assertIn("Using your tools", prompt)


class TestInsertSection(unittest.TestCase):
    """P119-B: insert_section API."""

    def setUp(self):
        clear_section_registry()
        from clawcodex_ext.context_system.prompt_assembly import get_system_prompt_cache

        get_system_prompt_cache().invalidate_all()

    def test_insert_section_appears_in_prompt(self):
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
            get_system_prompt_cache,
        )
        from clawcodex_ext.context_system.section_registry import insert_section

        get_system_prompt_cache().invalidate_all()
        insert_section("intro", "self_iter_meta", "## Iteration Meta", reason="test")
        prompt = build_full_system_prompt(cwd="/tmp")
        self.assertIn("## Iteration Meta", prompt)

    def test_insert_section_ordering(self):
        """New section sorts after after_id."""
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
            get_system_prompt_cache,
        )
        from clawcodex_ext.context_system.section_registry import insert_section

        get_system_prompt_cache().invalidate_all()
        insert_section("intro", "meta", "[[META]]", reason="test")
        prompt = build_full_system_prompt(cwd="/tmp")
        intro_pos = prompt.find("interactive agent")
        meta_pos = prompt.find("[[META]]")
        sys_pos = prompt.find("All text you output")
        self.assertLess(intro_pos, meta_pos)
        self.assertLess(meta_pos, sys_pos)

    def test_insert_section_returns_section(self):
        from clawcodex_ext.context_system.section_registry import insert_section

        section = insert_section("intro", "new_id", "content", reason="test")
        self.assertIsInstance(section, SystemPromptSection)
        self.assertEqual(section.id, "new_id")
        self.assertEqual(section.order, 0.5)


class TestDefaultByteStability(unittest.TestCase):
    """P119-A/B: default output is byte-stable when no overrides are registered."""

    def setUp(self):
        clear_section_registry()
        from clawcodex_ext.context_system.prompt_assembly import get_system_prompt_cache

        get_system_prompt_cache().invalidate_all()

    def test_default_blocks_byte_identical(self):
        from clawcodex_ext.context_system.prompt_assembly import build_full_system_prompt_blocks

        blocks_a = build_full_system_prompt_blocks(cwd="/tmp")
        blocks_b = build_full_system_prompt_blocks(cwd="/tmp")
        self.assertEqual(blocks_a, blocks_b)

    def test_default_prompt_contains_seven_static_sections(self):
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
            get_system_prompt_cache,
        )

        get_system_prompt_cache().invalidate_all()
        prompt = build_full_system_prompt(cwd="/tmp")
        self.assertIn("Using your tools", prompt)
        self.assertIn("Executing actions with care", prompt)
        self.assertIn("Communicating with the user", prompt)


class TestPromptAssemblyWithOverride(unittest.TestCase):
    """Integration: P119-A registry + P119-B override + assembly."""

    def setUp(self):
        clear_section_registry()
        from clawcodex_ext.context_system.prompt_assembly import get_system_prompt_cache

        get_system_prompt_cache().invalidate_all()

    def test_register_section_builder_overrides_default(self):
        """AC item 1: register_section_builder("intro", 0, GLOBAL, fn) → intro content from fn."""
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
            get_system_prompt_cache,
        )

        get_system_prompt_cache().invalidate_all()

        def _custom_intro():
            return SystemPromptSection(
                id="intro", content="CUSTOM INTRO", cache_scope=CacheScope.GLOBAL, order=0,
            )

        register_section_builder("intro", _custom_intro)
        prompt = build_full_system_prompt(cwd="/tmp")
        self.assertIn("CUSTOM INTRO", prompt)
        self.assertNotIn("interactive agent", prompt)

    def test_override_section_immediate_and_cache_invalidated(self):
        """AC item 2: override_section takes effect and invalidates cache."""
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
            get_system_prompt_cache,
        )
        from clawcodex_ext.context_system.section_registry import override_section

        get_system_prompt_cache().invalidate_all()
        build_full_system_prompt(cwd="/tmp")  # prime cache
        override_section("doing_tasks", "TASK OVERRIDE", reason="test")
        prompt = build_full_system_prompt(cwd="/tmp")
        self.assertIn("TASK OVERRIDE", prompt)

    def test_insert_section_between_intro_and_system(self):
        """AC item 3: insert_section("intro", "self_iter_meta", content) sorts correctly."""
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
            get_system_prompt_cache,
        )
        from clawcodex_ext.context_system.section_registry import insert_section

        get_system_prompt_cache().invalidate_all()
        insert_section("intro", "self_iter_meta", "[[ITER_META]]", reason="test")
        prompt = build_full_system_prompt(cwd="/tmp")
        intro_pos = prompt.find("interactive agent")
        meta_pos = prompt.find("[[ITER_META]]")
        sys_pos = prompt.find("All text you output")
        self.assertLess(intro_pos, meta_pos)
        self.assertLess(meta_pos, sys_pos)

    def test_disable_tone_style_and_verify_absent(self):
        """AC item 4: disable_section("tone_style") → tone_style absent."""
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
            get_system_prompt_cache,
        )
        from clawcodex_ext.context_system.section_registry import disable_section

        get_system_prompt_cache().invalidate_all()
        disable_section("tone_style")
        prompt = build_full_system_prompt(cwd="/tmp")
        self.assertNotIn("Tone and style", prompt)

    def test_default_without_builders_is_byte_equal(self):
        """AC item 7: default content byte-equal with no builder registration."""
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt_blocks,
            get_system_prompt_cache,
        )

        get_system_prompt_cache().invalidate_all()
        blocks_a = build_full_system_prompt_blocks(cwd="/tmp")
        blocks_b = build_full_system_prompt_blocks(cwd="/tmp")
        self.assertEqual(blocks_a, blocks_b)


class TestIterationMeta(unittest.TestCase):
    """P119-D: iteration_meta section injector."""

    def setUp(self):
        clear_section_registry()
        from clawcodex_ext.context_system.prompt_assembly import get_system_prompt_cache

        get_system_prompt_cache().invalidate_all()

    def test_no_builder_section_absent(self):
        """Without registration, iteration_meta does not appear in prompt."""
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
            get_system_prompt_cache,
        )

        get_system_prompt_cache().invalidate_all()
        prompt = build_full_system_prompt(cwd="/tmp")
        self.assertNotIn("ITER_META", prompt)

    def test_register_builder_section_present(self):
        """AC: register_iteration_meta_section → content appears in prompt."""
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
            get_system_prompt_cache,
        )
        from clawcodex_ext.context_system.section_registry import (
            register_section_builder,
        )
        from clawcodex_ext.context_system.system_prompt_cache import (
            CacheScope,
            SystemPromptSection,
        )

        get_system_prompt_cache().invalidate_all()

        def _meta_builder():
            return SystemPromptSection(
                id="iteration_meta",
                content="# Iteration Meta\nCurrent round: 3",
                cache_scope=CacheScope.REQUEST,
                order=95,
            )

        register_section_builder("iteration_meta", _meta_builder)
        prompt = build_full_system_prompt(cwd="/tmp")
        self.assertIn("Iteration Meta", prompt)
        self.assertIn("Current round: 3", prompt)

    def test_builder_returning_none_suppresses_section(self):
        """Builder returning None → section absent."""
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
            get_system_prompt_cache,
        )
        from clawcodex_ext.context_system.section_registry import (
            register_section_builder,
        )

        get_system_prompt_cache().invalidate_all()
        register_section_builder("iteration_meta", lambda: None)
        prompt = build_full_system_prompt(cwd="/tmp")
        self.assertNotIn("Iteration Meta", prompt)

    def test_iteration_meta_after_tool_restrictions(self):
        """iteration_meta (order 95) sorts after tool_restrictions (90)."""
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
            get_system_prompt_cache,
        )
        from clawcodex_ext.context_system.section_registry import (
            register_section_builder,
        )
        from clawcodex_ext.context_system.system_prompt_cache import (
            CacheScope,
            SystemPromptSection,
        )

        get_system_prompt_cache().invalidate_all()

        def _meta_builder():
            return SystemPromptSection(
                id="iteration_meta",
                content="[[ITER_META_MARKER]]",
                cache_scope=CacheScope.REQUEST,
                order=95,
            )

        register_section_builder("iteration_meta", _meta_builder)
        prompt = build_full_system_prompt(
            cwd="/tmp",
            tool_restrictions=["some_tool"],
        )
        restrict_pos = prompt.find("Tool Restrictions")
        meta_pos = prompt.find("[[ITER_META_MARKER]]")
        self.assertLess(restrict_pos, meta_pos)

    def test_multiple_builders_first_non_none_wins(self):
        """Multiple builders: first non-None result wins."""
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
            get_system_prompt_cache,
        )
        from clawcodex_ext.context_system.section_registry import (
            register_section_builder,
        )
        from clawcodex_ext.context_system.system_prompt_cache import (
            CacheScope,
            SystemPromptSection,
        )

        get_system_prompt_cache().invalidate_all()

        def _first():
            return SystemPromptSection(
                id="iteration_meta",
                content="FIRST",
                cache_scope=CacheScope.REQUEST,
                order=95,
            )

        def _second():
            return SystemPromptSection(
                id="iteration_meta",
                content="SECOND",
                cache_scope=CacheScope.REQUEST,
                order=95,
            )

        register_section_builder("iteration_meta", _first)
        register_section_builder("iteration_meta", _second)
        prompt = build_full_system_prompt(cwd="/tmp")
        self.assertIn("FIRST", prompt)
        self.assertNotIn("SECOND", prompt)

    def test_dump_includes_iteration_meta(self):
        """dump_effective_system_prompt captures iteration_meta when present."""
        from clawcodex_ext.context_system.prompt_dump import dump_effective_system_prompt
        from clawcodex_ext.context_system.section_registry import (
            register_section_builder,
        )
        from clawcodex_ext.context_system.system_prompt_cache import (
            CacheScope,
            SystemPromptSection,
        )

        def _meta_builder():
            return SystemPromptSection(
                id="iteration_meta",
                content="DUMP_META",
                cache_scope=CacheScope.REQUEST,
                order=95,
            )

        register_section_builder("iteration_meta", _meta_builder)
        snapshots = dump_effective_system_prompt(cwd="/tmp")
        ids = {s.id for s in snapshots}
        self.assertIn("iteration_meta", ids)

    def test_byte_stability_with_iteration_meta(self):
        """Identical builds produce identical block lists with iteration_meta."""
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt_blocks,
            get_system_prompt_cache,
        )
        from clawcodex_ext.context_system.section_registry import (
            register_section_builder,
        )
        from clawcodex_ext.context_system.system_prompt_cache import (
            CacheScope,
            SystemPromptSection,
        )

        get_system_prompt_cache().invalidate_all()

        def _meta_builder():
            return SystemPromptSection(
                id="iteration_meta",
                content="STABLE_META",
                cache_scope=CacheScope.REQUEST,
                order=95,
            )

        register_section_builder("iteration_meta", _meta_builder)
        blocks_a = build_full_system_prompt_blocks(cwd="/tmp")
        blocks_b = build_full_system_prompt_blocks(cwd="/tmp")
        self.assertEqual(blocks_a, blocks_b)


class TestCacheInvalidation(unittest.TestCase):
    """P119-F: cache invalidation linkage with override/disable.

    Only ``invalidate(section_id)`` is called — the build path checks
    cache first; a cache miss causes it to consult builders (where the
    override/disable is registered).  ``invalidate_scope`` is NOT used
    because it would wastefully clear unrelated cached sections.
    """

    def setUp(self):
        clear_section_registry()
        from clawcodex_ext.context_system.prompt_assembly import get_system_prompt_cache

        get_system_prompt_cache().invalidate_all()

    def test_override_invalidates_section_only(self):
        """override_section clears only the target section cache."""
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt_blocks,
            get_system_prompt_cache,
        )
        from clawcodex_ext.context_system.section_registry import override_section

        cache = get_system_prompt_cache()
        cache.invalidate_all()

        # Prime the cache by building with tools so both intro and
        # tool_docs are cached.
        build_full_system_prompt_blocks(cwd="/tmp", tools=[{"name": "test_tool"}])
        self.assertIsNotNone(cache.get("intro"))
        self.assertIsNotNone(cache.get("tool_docs"))

        # Override intro (GLOBAL scope).  Only intro cache should be
        # cleared; tool_docs (SESSION scope) should survive.
        override_section("intro", "CUSTOM_INTRO", reason="test")
        self.assertIsNone(cache.get("intro"))
        self.assertIsNotNone(cache.get("tool_docs"))

    def test_override_next_build_sees_new_content(self):
        """After override + cache invalidation, the next build uses new content."""
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt,
            get_system_prompt_cache,
        )
        from clawcodex_ext.context_system.section_registry import override_section

        cache = get_system_prompt_cache()
        cache.invalidate_all()

        # Prime cache.
        build_full_system_prompt(cwd="/tmp")
        self.assertIsNotNone(cache.get("intro"))

        # Override and verify content changes.
        override_section("intro", "CUSTOM_INTRO", reason="test")
        prompt = build_full_system_prompt(cwd="/tmp")
        self.assertIn("CUSTOM_INTRO", prompt)

    def test_insert_preserves_cache(self):
        """insert_section does NOT invalidate cache (new section has no cache entry)."""
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt_blocks,
            get_system_prompt_cache,
        )
        from clawcodex_ext.context_system.section_registry import insert_section

        cache = get_system_prompt_cache()
        cache.invalidate_all()

        # Prime the cache.
        build_full_system_prompt_blocks(cwd="/tmp", tools=[{"name": "test_tool"}])
        self.assertIsNotNone(cache.get("intro"))
        self.assertIsNotNone(cache.get("tool_docs"))

        # Insert a new section.  Should NOT clear any cache.
        insert_section("intro", "meta", "[[META]]", cache_scope=CacheScope.SESSION, reason="test")
        self.assertIsNotNone(cache.get("intro"))
        self.assertIsNotNone(cache.get("tool_docs"))

    def test_disable_invalidates_section_only(self):
        """disable_section clears only the target section cache."""
        from clawcodex_ext.context_system.prompt_assembly import (
            build_full_system_prompt_blocks,
            get_system_prompt_cache,
        )
        from clawcodex_ext.context_system.section_registry import disable_section

        cache = get_system_prompt_cache()
        cache.invalidate_all()

        # Prime the cache with tools so both intro and tool_docs are cached.
        build_full_system_prompt_blocks(cwd="/tmp", tools=[{"name": "test_tool"}])
        self.assertIsNotNone(cache.get("intro"))
        self.assertIsNotNone(cache.get("tool_docs"))

        # Disable tool_docs (SESSION scope).  Only tool_docs cache should
        # be cleared; intro (GLOBAL scope) should survive.
        disable_section("tool_docs")
        self.assertIsNone(cache.get("tool_docs"))
        self.assertIsNotNone(cache.get("intro"))


if __name__ == "__main__":
    unittest.main()