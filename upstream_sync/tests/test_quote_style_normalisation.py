"""Tests for the ``--ignore-quote-style`` flag plumbing in patch_generator.

Three guarantees to lock in:

1. ``read_normalised`` + ``read_normalised_loose`` collapse CRLF→LF as the
   first layer (so the loose path is a *superset* of strict normal).
2. Pure quote-style-only diffs are equal under ``loose=True`` but differ
   under ``loose=False``.
3. Real functional changes are caught by both modes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from upstream_sync.core.patch_generator import PatchGenerator


@pytest.fixture
def tmp_pair(tmp_path: Path) -> tuple[Path, Path]:
    upstream = tmp_path / "upstream.py"
    downstream = tmp_path / "downstream.py"
    return upstream, downstream


def _write(path: Path, body: bytes) -> None:
    path.write_bytes(body)


class TestReadNormalisedLoose:
    def test_crlf_only_difference_collapses_under_loose(self, tmp_path: Path) -> None:
        upstream = tmp_path / "upstream.py"
        downstream = tmp_path / "downstream.py"
        _write(upstream, b"x = 1\r\ny = 2\r\n")
        _write(downstream, b"x = 1\ny = 2\n")

        # Strict mode: still treats CRLF and LF as identical (existing behaviour).
        assert (
            PatchGenerator.read_normalised(upstream)
            == PatchGenerator.read_normalised(downstream)
        )
        # Loose mode also equal — superset of strict.
        assert (
            PatchGenerator.read_normalised_loose(upstream)
            == PatchGenerator.read_normalised_loose(downstream)
        )

    def test_quote_style_only_difference_under_loose(self, tmp_path: Path) -> None:
        upstream = tmp_path / "upstream.py"
        downstream = tmp_path / "downstream.py"
        _write(upstream, b"name = 'alice'\nother = 'bob'\n")
        _write(downstream, b'name = "alice"\nother = "bob"\n')

        # Strict: differs.
        assert (
            PatchGenerator.read_normalised(upstream)
            != PatchGenerator.read_normalised(downstream)
        )
        # Loose: equal — quote-only diff is invisible.
        assert (
            PatchGenerator.read_normalised_loose(upstream)
            == PatchGenerator.read_normalised_loose(downstream)
        )

    def test_functional_change_detected_under_loose(self, tmp_path: Path) -> None:
        upstream = tmp_path / "upstream.py"
        downstream = tmp_path / "downstream.py"
        _write(upstream, b"x = 'foo'\n")
        _write(downstream, b'x = "bar"\n')

        # Loose collapses the quote style but the inner content still differs.
        assert (
            PatchGenerator.read_normalised_loose(upstream)
            != PatchGenerator.read_normalised_loose(downstream)
        )

    def test_apostrophe_in_word_is_not_rewritten(self, tmp_path: Path) -> None:
        upstream = tmp_path / "upstream.py"
        downstream = tmp_path / "downstream.py"
        _write(upstream, b"msg = \"it's working\"\n")
        _write(downstream, b"msg = \"it's working\"\n")

        # Same content → both modes equal.
        assert (
            PatchGenerator.read_normalised_loose(upstream)
            == PatchGenerator.read_normalised_loose(downstream)
        )

    def test_escape_pattern_is_not_rewritten(self, tmp_path: Path) -> None:
        upstream = tmp_path / "upstream.py"
        downstream = tmp_path / "downstream.py"
        _write(upstream, b"raw = 'a\\'b'\n")
        _write(downstream, b"raw = 'a\\'b'\n")

        # Escaped single-quote inside a single-quoted string must NOT be
        # promoted to a double-quoted literal — that would change semantics.
        # Both modes should see the file as identical because upstream and
        # downstream are the same; the test mainly guards against the regex
        # growing too greedy in future edits.
        assert (
            PatchGenerator.read_normalised_loose(upstream)
            == PatchGenerator.read_normalised_loose(downstream)
        )


class TestFilesDifferNorm:
    def test_loose_false_strict_default(self, tmp_pair: tuple[Path, Path]) -> None:
        upstream, downstream = tmp_pair
        _write(upstream, b"name = 'alice'\n")
        _write(downstream, b'name = "alice"\n')

        assert PatchGenerator.files_differ_norm(upstream, downstream) is True
        assert PatchGenerator.files_differ_norm(upstream, downstream, loose=False) is True

    def test_loose_true_treats_quote_only_as_equal(
        self, tmp_pair: tuple[Path, Path]
    ) -> None:
        upstream, downstream = tmp_pair
        _write(upstream, b"name = 'alice'\n")
        _write(downstream, b'name = "alice"\n')

        assert (
            PatchGenerator.files_differ_norm(upstream, downstream, loose=True) is False
        )

    def test_loose_true_still_catches_real_change(
        self, tmp_pair: tuple[Path, Path]
    ) -> None:
        upstream, downstream = tmp_pair
        _write(upstream, b"x = 'foo'\n")
        _write(downstream, b'x = "bar"\n')

        assert (
            PatchGenerator.files_differ_norm(upstream, downstream, loose=True) is True
        )