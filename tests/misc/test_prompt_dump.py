"""Tests for P119-C prompt dump / observability interface.

Covers dump_effective_system_prompt across all formats and edge cases
per §3.1 acceptance criteria item 5.
"""

from __future__ import annotations

import unittest

from clawcodex_ext.context_system.section_registry import clear_section_registry


class TestPromptDumpStructured(unittest.TestCase):
    """P119-C: structured format — list[SectionSnapshot]."""

    def setUp(self):
        clear_section_registry()
        from clawcodex_ext.context_system.prompt_assembly import get_system_prompt_cache

        get_system_prompt_cache().invalidate_all()

    def test_structured_mode_returns_section_snapshots(self):
        from clawcodex_ext.context_system.prompt_dump import (
            SectionSnapshot,
            dump_effective_system_prompt,
        )

        snapshots = dump_effective_system_prompt(cwd="/tmp")
        self.assertGreater(len(snapshots), 5)
        for s in snapshots:
            self.assertIsInstance(s, SectionSnapshot)

    def test_known_section_ids_present(self):
        from clawcodex_ext.context_system.prompt_dump import dump_effective_system_prompt

        snapshots = dump_effective_system_prompt(cwd="/tmp")
        ids = {s.id for s in snapshots}
        self.assertIn("intro", ids)
        self.assertIn("system", ids)
        self.assertIn("doing_tasks", ids)
        self.assertIn("actions", ids)
        self.assertIn("using_tools", ids)
        self.assertIn("tone_style", ids)
        self.assertIn("output_efficiency", ids)

    def test_sha256_stable_across_calls(self):
        """AC item 5: sha256 stable on identical inputs."""
        from clawcodex_ext.context_system.prompt_dump import dump_effective_system_prompt

        snapshots_a = dump_effective_system_prompt(cwd="/tmp")
        snapshots_b = dump_effective_system_prompt(cwd="/tmp")
        self.assertEqual(len(snapshots_a), len(snapshots_b))
        for sa, sb in zip(snapshots_a, snapshots_b):
            self.assertEqual(sa.id, sb.id)
            self.assertEqual(sa.sha256, sb.sha256,
                             f"sha256 mismatch for section '{sa.id}'")

    def test_include_content_default_false(self):
        from clawcodex_ext.context_system.prompt_dump import dump_effective_system_prompt

        snapshots = dump_effective_system_prompt(cwd="/tmp")
        for s in snapshots:
            self.assertEqual(s.content, "",
                             f"content should be empty for '{s.id}'")

    def test_include_content_true(self):
        from clawcodex_ext.context_system.prompt_dump import dump_effective_system_prompt

        snapshots = dump_effective_system_prompt(cwd="/tmp", include_content=True)
        intro = next(s for s in snapshots if s.id == "intro")
        self.assertGreater(len(intro.content), 100)
        self.assertEqual(intro.byte_len, len(intro.content.encode("utf-8")))

    def test_boundary_marker_present(self):
        from clawcodex_ext.context_system.prompt_dump import dump_effective_system_prompt

        snapshots = dump_effective_system_prompt(cwd="/tmp")
        boundaries = [s for s in snapshots if s.id == "__boundary__"]
        self.assertEqual(len(boundaries), 1)
        self.assertEqual(boundaries[0].source, "boundary")

    def test_append_system_prompt_captured(self):
        from clawcodex_ext.context_system.prompt_dump import dump_effective_system_prompt

        snapshots = dump_effective_system_prompt(
            cwd="/tmp", append_system_prompt="EXTRA APPEND", include_content=True
        )
        appended = [s for s in snapshots if s.source == "appended"]
        self.assertEqual(len(appended), 1)
        self.assertEqual(appended[0].id, "__appended__")
        self.assertIn("EXTRA APPEND", appended[0].content)

    def test_byte_len_matches_utf8_encoding(self):
        from clawcodex_ext.context_system.prompt_dump import dump_effective_system_prompt

        snapshots = dump_effective_system_prompt(cwd="/tmp", include_content=True)
        for s in snapshots:
            self.assertEqual(s.byte_len, len(s.content.encode("utf-8")),
                             f"byte_len mismatch for '{s.id}'")


class TestPromptDumpFormats(unittest.TestCase):
    """P119-C: blocks and str formats."""

    def test_format_blocks_returns_raw_list(self):
        from clawcodex_ext.context_system.prompt_dump import dump_effective_system_prompt

        blocks = dump_effective_system_prompt(cwd="/tmp", format="blocks")
        self.assertIsInstance(blocks, list)
        self.assertGreater(len(blocks), 5)
        for b in blocks:
            self.assertIsInstance(b, dict)
            self.assertEqual(b["type"], "text")

    def test_format_str_returns_plain_text(self):
        from clawcodex_ext.context_system.prompt_dump import dump_effective_system_prompt

        prompt = dump_effective_system_prompt(cwd="/tmp", format="str")
        self.assertIsInstance(prompt, str)
        self.assertGreater(len(prompt), 5000)

    def test_custom_system_prompt_branch(self):
        from clawcodex_ext.context_system.prompt_dump import dump_effective_system_prompt

        snapshots = dump_effective_system_prompt(
            custom_system_prompt="You are a custom assistant.",
        )
        # custom prompt branch returns a single block, no sections
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].source, "default")


class TestPromptDumpEdgeCases(unittest.TestCase):
    """P119-C: edge cases — missing sections, extra kwargs forwarding."""

    def setUp(self):
        clear_section_registry()
        from clawcodex_ext.context_system.prompt_assembly import get_system_prompt_cache

        get_system_prompt_cache().invalidate_all()

    def test_missing_section_does_not_panic(self):
        """dump should not panic when a section builder returns None."""
        from clawcodex_ext.context_system.prompt_dump import dump_effective_system_prompt

        # tool_restrictions is optional; dump without it should still work.
        snapshots = dump_effective_system_prompt(cwd="/tmp")
        ids = {s.id for s in snapshots}
        # tool_restrictions may or may not be present — the key is no crash.
        self.assertIsInstance(snapshots, list)

    def test_extra_kwargs_forwarded(self):
        """Extra kwargs are forwarded to build_full_system_prompt_blocks."""
        from clawcodex_ext.context_system.prompt_dump import dump_effective_system_prompt

        # tool_restrictions and output_style are forwarded via **extra.
        snapshots = dump_effective_system_prompt(
            cwd="/tmp",
            tool_restrictions=["some_tool"],
            output_style="compact",
        )
        self.assertIsInstance(snapshots, list)
        self.assertGreater(len(snapshots), 0)

    def test_sha256_different_for_different_content(self):
        """Different inputs produce different sha256 for affected sections."""
        from clawcodex_ext.context_system.prompt_dump import dump_effective_system_prompt
        from clawcodex_ext.context_system.section_registry import override_section

        clear_section_registry()
        from clawcodex_ext.context_system.prompt_assembly import get_system_prompt_cache
        get_system_prompt_cache().invalidate_all()

        snapshots_a = dump_effective_system_prompt(cwd="/tmp")

        clear_section_registry()
        get_system_prompt_cache().invalidate_all()
        override_section("intro", "OVERRIDDEN INTRO", reason="test")
        snapshots_b = dump_effective_system_prompt(cwd="/tmp")

        # intro should differ; other sections may or may not.
        intro_a = next(s for s in snapshots_a if s.id == "intro")
        intro_b = next(s for s in snapshots_b if s.id == "intro")
        self.assertNotEqual(intro_a.sha256, intro_b.sha256)


if __name__ == "__main__":
    unittest.main()