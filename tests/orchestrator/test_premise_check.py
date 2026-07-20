"""Tests for the premise check + honest-exit channel (defect R3)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from extensions.orchestrator.premise_check import (
    CANNOT_PROCEED_MARKER,
    build_premise_block,
    check_issue_premise,
    extract_referenced_paths,
    find_missing_paths,
    format_cannot_proceed_comment,
    read_cannot_proceed,
)


class TestExtractReferencedPaths(unittest.TestCase):
    def test_extracts_nested_source_path(self) -> None:
        text = (
            "Crash in src/click/_network.py: timeout=0 causes ZeroDivisionError\n"
            "src/click/_network.py line 88 divides self.window / self.timeout"
        )
        self.assertEqual(extract_referenced_paths(text), ["src/click/_network.py"])

    def test_extracts_bare_filename_with_source_extension(self) -> None:
        self.assertEqual(
            extract_referenced_paths("please fix utils.py to handle None"),
            ["utils.py"],
        )

    def test_ignores_prose_slashes_and_versions(self) -> None:
        text = "and/or the TCP/IP stack breaks on python 3.11.5 sometimes"
        self.assertEqual(extract_referenced_paths(text), [])

    def test_ignores_urls(self) -> None:
        text = "see https://example.test/docs/setup.py for details"
        self.assertEqual(extract_referenced_paths(text), [])

    def test_windows_separators_are_normalized(self) -> None:
        self.assertEqual(
            extract_referenced_paths(r"broken file: src\pkg\mod.py"),
            ["src/pkg/mod.py"],
        )

    def test_deduplicates_and_caps(self) -> None:
        text = "\n".join(f"src/m{i}.py and src/m{i}.py again" for i in range(40))
        result = extract_referenced_paths(text)
        self.assertEqual(len(result), len(set(result)))
        self.assertLessEqual(len(result), 20)

    def test_empty_input(self) -> None:
        self.assertEqual(extract_referenced_paths(None), [])
        self.assertEqual(extract_referenced_paths(""), [])


class TestFindMissingPaths(unittest.TestCase):
    def test_reports_only_absent_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "real.py").write_text("x = 1\n", encoding="utf-8")
            missing = find_missing_paths(root, ["src/real.py", "src/ghost.py"])
            self.assertEqual(missing, ["src/ghost.py"])

    def test_skips_escaping_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = find_missing_paths(Path(tmp), ["../outside.py", "~/home.py"])
            self.assertEqual(missing, [])

    def test_bare_filename_resolved_by_basename_search(self) -> None:
        """Issues cite files by bare name or stale directory all the
        time; both must resolve via basename search instead of being
        reported as fabricated (observed live: a bare
        ``base_profiling_parser.py`` reference froze an obedient model
        with a false "file does not exist" warning)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deep = root / "pkg" / "sub" / "parsers"
            deep.mkdir(parents=True)
            (deep / "real_parser.py").write_text("x = 1\n", encoding="utf-8")
            missing = find_missing_paths(
                root,
                ["real_parser.py", "old_dir/real_parser.py", "fabricated.py"],
            )
            self.assertEqual(missing, ["fabricated.py"])

    def test_basename_search_ignores_git_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git_hooks = root / ".git" / "hooks"
            git_hooks.mkdir(parents=True)
            (git_hooks / "shadow.py").write_text("x = 1\n", encoding="utf-8")
            missing = find_missing_paths(root, ["shadow.py"])
            self.assertEqual(missing, ["shadow.py"])


class TestCheckIssuePremise(unittest.TestCase):
    def test_flags_fabrication_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            issue = {
                "title": "Crash in src/click/_network.py: timeout=0",
                "description": "guard timeout=0 in _backoff_delay of src/click/_network.py",
            }
            self.assertEqual(check_issue_premise(issue, tmp), ["src/click/_network.py"])

    def test_quiet_when_paths_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "utils.py").write_text("pass\n", encoding="utf-8")
            issue = {"title": "fix src/utils.py", "description": None}
            self.assertEqual(check_issue_premise(issue, tmp), [])

    def test_no_workspace_is_quiet(self) -> None:
        issue = {"title": "fix src/ghost.py", "description": ""}
        self.assertEqual(check_issue_premise(issue, None), [])


class TestHonestExitMarker(unittest.TestCase):
    def test_absent_marker_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(read_cannot_proceed(tmp))

    def test_valid_marker_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / CANNOT_PROCEED_MARKER
            marker.parent.mkdir(parents=True)
            marker.write_text(
                json.dumps(
                    {
                        "reason": "premise_not_met",
                        "details": "src/click/_network.py does not exist",
                        "checked": ["src/click/_network.py", "grep _RetryStrategy"],
                    }
                ),
                encoding="utf-8",
            )
            payload = read_cannot_proceed(tmp)
            assert payload is not None
            self.assertEqual(payload["reason"], "premise_not_met")

    def test_malformed_marker_still_honored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / CANNOT_PROCEED_MARKER
            marker.parent.mkdir(parents=True)
            marker.write_text("file does not exist, stopping", encoding="utf-8")
            payload = read_cannot_proceed(tmp)
            assert payload is not None
            self.assertEqual(payload["reason"], "cannot_proceed")
            self.assertIn("file does not exist", payload["details"])

    def test_comment_includes_reason_details_and_checked(self) -> None:
        class _Issue:
            identifier = "PROBE-19"
            id = "19"

        comment = format_cannot_proceed_comment(
            _Issue(),
            {
                "reason": "premise_not_met",
                "details": "referenced file absent",
                "checked": ["src/x.py"],
            },
        )
        self.assertIn("PROBE-19", comment)
        self.assertIn("premise_not_met", comment)
        self.assertIn("referenced file absent", comment)
        self.assertIn("src/x.py", comment)
        self.assertIn("No merge request was opened", comment)


class TestPremiseBlock(unittest.TestCase):
    def test_block_names_paths_and_marker(self) -> None:
        block = build_premise_block(["src/ghost.py"])
        self.assertIn("src/ghost.py", block)
        self.assertIn(CANNOT_PROCEED_MARKER, block)
        self.assertIn("Do NOT create the missing file", block)


class TestPromptInjection(unittest.TestCase):
    def test_render_appends_premise_block_for_missing_path(self) -> None:
        from extensions.orchestrator.prompt_builder import PromptBuilder

        with tempfile.TemporaryDirectory() as tmp:
            class _Workspace:
                path = Path(tmp)

            class _Session:
                workspace = _Workspace()
                workspace_strategy = "isolated"

            issue = {
                "identifier": "PROBE-19",
                "title": "Crash in src/click/_network.py",
                "description": "fix _backoff_delay in src/click/_network.py",
                "priority": None,
                "state": "open",
            }
            rendered = PromptBuilder.render(issue, session=_Session())
            self.assertIn("Premise Check", rendered)
            self.assertIn("src/click/_network.py", rendered)
            self.assertIn(CANNOT_PROCEED_MARKER, rendered)

    def test_render_quiet_when_paths_exist(self) -> None:
        from extensions.orchestrator.prompt_builder import PromptBuilder

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "utils.py").write_text("pass\n", encoding="utf-8")

            class _Workspace:
                path = root

            class _Session:
                workspace = _Workspace()
                workspace_strategy = "isolated"

            issue = {
                "identifier": "OK-1",
                "title": "improve src/utils.py",
                "description": None,
                "priority": None,
                "state": "open",
            }
            rendered = PromptBuilder.render(issue, session=_Session())
            self.assertNotIn("Premise Check", rendered)


if __name__ == "__main__":
    unittest.main()
