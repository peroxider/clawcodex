"""Materialize oversized goal objectives under Codex attachments."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

MAX_THREAD_GOAL_OBJECTIVE_CHARS = 4000
GOAL_ATTACHMENT_DIR = "attachments"
GOAL_FILE_NAME = "goal-objective.md"
GOAL_FILE_PREFIX = "Read the Codex goal objective file at "
GOAL_FILE_SUFFIX = " before continuing."


@dataclass(frozen=True)
class MaterializedGoalObjective:
    objective: str
    attachment_dir: Path | None = None


def materialize_goal_objective(
    objective: str,
    *,
    codex_home: Path | str | None = None,
) -> MaterializedGoalObjective:
    """Write long objectives to an attachment file and return a short reference."""
    if len(objective) <= MAX_THREAD_GOAL_OBJECTIVE_CHARS:
        return MaterializedGoalObjective(objective=objective)

    home = _codex_home(codex_home)
    attachment_dir = home / GOAL_ATTACHMENT_DIR / str(uuid.uuid4())
    attachment_dir.mkdir(parents=True, exist_ok=False)
    goal_file = attachment_dir / GOAL_FILE_NAME
    reference = objective_file_reference(goal_file)
    if len(reference) > MAX_THREAD_GOAL_OBJECTIVE_CHARS:
        raise ValueError(
            "Goal objective file reference is too long: "
            f"{len(reference)} characters. Limit: {MAX_THREAD_GOAL_OBJECTIVE_CHARS}."
        )
    goal_file.write_text(objective)
    return MaterializedGoalObjective(objective=reference, attachment_dir=attachment_dir)


def objective_text_for_edit(
    objective: str,
    *,
    codex_home: Path | str | None = None,
) -> str:
    path = objective_file_path(objective, codex_home=codex_home)
    if path is None:
        return objective
    return path.read_text()


def objective_file_reference(path: Path | str) -> str:
    return f"{GOAL_FILE_PREFIX}{Path(path)}{GOAL_FILE_SUFFIX}"


def objective_file_path(
    objective: str,
    *,
    codex_home: Path | str | None = None,
) -> Path | None:
    path_text = objective.removeprefix(GOAL_FILE_PREFIX)
    if path_text == objective:
        return None
    path_text = path_text.removesuffix(GOAL_FILE_SUFFIX)
    if objective_file_reference(path_text) != objective:
        return None
    path = Path(path_text)
    if not path.is_absolute():
        return None

    home = _codex_home(codex_home)
    try:
        relative = path.relative_to(home / GOAL_ATTACHMENT_DIR)
    except ValueError:
        return None
    parts = relative.parts
    if len(parts) != 2 or parts[1] != GOAL_FILE_NAME:
        return None
    try:
        uuid.UUID(parts[0])
    except ValueError:
        return None
    if not path.is_file():
        return None
    return path


def _codex_home(codex_home: Path | str | None) -> Path:
    return Path(codex_home).expanduser() if codex_home is not None else Path.home() / ".codex"


__all__ = [
    "GOAL_ATTACHMENT_DIR",
    "GOAL_FILE_NAME",
    "GOAL_FILE_PREFIX",
    "GOAL_FILE_SUFFIX",
    "MAX_THREAD_GOAL_OBJECTIVE_CHARS",
    "MaterializedGoalObjective",
    "materialize_goal_objective",
    "objective_file_path",
    "objective_file_reference",
    "objective_text_for_edit",
]
