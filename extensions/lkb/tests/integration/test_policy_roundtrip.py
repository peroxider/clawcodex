"""Persistence regression for role-scoped force overrides."""

from __future__ import annotations

from lkb.board_resolver import board_dir
from lkb.file_lock import BoardFileLock
from lkb.graph_types import Board, BoardPolicy
from lkb.json_store import JsonBoardStore
from lkb.repository import JsonFileLkbRepository


def test_force_override_roles_survive_store_and_repository_restart(tmp_home) -> None:
    board_id = "policy-role-roundtrip"
    path = board_dir(board_id, home=tmp_home)
    board = Board(
        board_id=board_id,
        project_uri="project:policy-role-roundtrip",
        display_name="Policy roles",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        policy=BoardPolicy(
            force_override_roles=("admin", "release-manager"),
        ),
    )
    JsonBoardStore.create_board(
        path,
        board=board,
        lock=BoardFileLock(path),
        home=tmp_home,
    )

    reopened = JsonFileLkbRepository(home=tmp_home).resolve_board(explicit_id=board_id)
    assert reopened.policy.force_override_roles == ("admin", "release-manager")
    assert reopened.policy.allows_force_override("admin")
    assert not reopened.policy.allows_force_override("developer")
