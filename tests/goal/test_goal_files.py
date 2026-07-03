"""Spec-6 goal objective materialization tests."""

from __future__ import annotations

from pathlib import Path

from clawcodex_ext.goal.files import (
    GOAL_FILE_NAME,
    MAX_THREAD_GOAL_OBJECTIVE_CHARS,
    materialize_goal_objective,
    objective_text_for_edit,
)


def test_long_goal_objective_is_materialized_under_codex_attachments(
    tmp_path: Path,
) -> None:
    objective = "ship it\n" + ("x" * MAX_THREAD_GOAL_OBJECTIVE_CHARS)

    materialized = materialize_goal_objective(objective, codex_home=tmp_path)

    assert materialized.attachment_dir is not None
    assert materialized.objective.startswith("Read the Codex goal objective file at ")
    assert materialized.objective.endswith(" before continuing.")
    goal_file = materialized.attachment_dir / GOAL_FILE_NAME
    assert goal_file.read_text() == objective
    assert goal_file.parent.parent == tmp_path / "attachments"
    assert len(materialized.objective) <= MAX_THREAD_GOAL_OBJECTIVE_CHARS
    assert objective_text_for_edit(materialized.objective, codex_home=tmp_path) == objective


def test_short_goal_objective_is_not_materialized(tmp_path: Path) -> None:
    materialized = materialize_goal_objective("short objective", codex_home=tmp_path)

    assert materialized.objective == "short objective"
    assert materialized.attachment_dir is None
    assert not (tmp_path / "attachments").exists()


def test_objective_text_for_edit_only_reads_valid_goal_objective_references(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "elsewhere" / GOAL_FILE_NAME
    outside.parent.mkdir()
    outside.write_text("secret")
    reference = f"Read the Codex goal objective file at {outside} before continuing."

    assert objective_text_for_edit(reference, codex_home=tmp_path) == reference
