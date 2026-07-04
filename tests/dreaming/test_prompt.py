"""Tests for ``clawcodex_ext.dreaming.prompt`` — F-100.

Covers the 4-phase consolidation prompt builder. The body is largely
prose; we assert the structural shape (sections, key terms, mode
flag) without coupling to the exact wording.
"""

from __future__ import annotations

from clawcodex_ext.dreaming.prompt import (
    DREAM_PROMPT_PREFIX,
    build_consolidation_prompt,
)
from src.memdir.memdir import (
    ENTRYPOINT_NAME,
    MAX_ENTRYPOINT_LINES,
)


def test_build_consolidation_prompt_contains_4_phases() -> None:
    prompt = build_consolidation_prompt(
        memory_root="/tmp/mem",
        transcript_dir="/tmp/transcripts",
    )
    assert "Phase 1 — Orient" in prompt
    assert "Phase 2 — Gather recent signal" in prompt
    assert "Phase 3 — Consolidate" in prompt
    assert "Phase 4 — Prune and index" in prompt


def test_build_consolidation_prompt_includes_paths() -> None:
    prompt = build_consolidation_prompt(
        memory_root="/tmp/mem-root",
        transcript_dir="/tmp/transcripts",
    )
    assert "Memory directory: `/tmp/mem-root`" in prompt
    assert "Session transcripts: `/tmp/transcripts`" in prompt


def test_build_consolidation_prompt_uses_memdir_constants() -> None:
    """The prompt must cite the live ENTRYPOINT_NAME + MAX_ENTRYPOINT_LINES
    constants so a change in src/memdir flows through automatically."""
    prompt = build_consolidation_prompt(
        memory_root="/tmp/mem",
        transcript_dir="/tmp/transcripts",
    )
    assert ENTRYPOINT_NAME in prompt
    assert str(MAX_ENTRYPOINT_LINES) in prompt


def test_build_consolidation_prompt_appends_extra_section() -> None:
    prompt = build_consolidation_prompt(
        memory_root="/tmp/mem",
        transcript_dir="/tmp/transcripts",
        extra="**Tool constraints**: read-only bash only",
    )
    assert "## Additional context" in prompt
    assert "read-only bash only" in prompt


def test_build_consolidation_prompt_manual_mode_includes_prefix() -> None:
    auto_prompt = build_consolidation_prompt(
        memory_root="/tmp/mem",
        transcript_dir="/tmp/transcripts",
    )
    manual_prompt = build_consolidation_prompt(
        memory_root="/tmp/mem",
        transcript_dir="/tmp/transcripts",
        manual=True,
    )
    assert DREAM_PROMPT_PREFIX in manual_prompt
    assert DREAM_PROMPT_PREFIX not in auto_prompt


def test_build_consolidation_prompt_manual_with_extra() -> None:
    prompt = build_consolidation_prompt(
        memory_root="/tmp/mem",
        transcript_dir="/tmp/transcripts",
        extra="User context: focus on auth changes",
        manual=True,
    )
    assert DREAM_PROMPT_PREFIX in prompt
    assert "User context: focus on auth changes" in prompt


def test_dream_prompt_prefix_is_manual_marker() -> None:
    assert "manual dream" in DREAM_PROMPT_PREFIX.lower()
