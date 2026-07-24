from __future__ import annotations

import pytest

from scripts.resolve_conflict_markers import resolve_diff3


ARTIFACT = """before
<<<<<<< ours
our line
||||||| base
base line
=======
their line
>>>>>>> theirs
after
"""


@pytest.mark.parametrize(
    ("choice", "expected"),
    [
        ("ours", "before\nour line\nafter\n"),
        ("theirs", "before\ntheir line\nafter\n"),
        ("both", "before\nour line\ntheir line\nafter\n"),
    ],
)
def test_resolve_diff3_choices(choice: str, expected: str) -> None:
    assert resolve_diff3(ARTIFACT, [choice]) == expected


def test_resolve_diff3_rejects_choice_count_mismatch() -> None:
    with pytest.raises(ValueError, match="received 2 choices"):
        resolve_diff3(ARTIFACT, ["ours", "theirs"])
