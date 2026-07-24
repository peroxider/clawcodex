"""Resolve diff3 conflict artifacts with an explicit per-hunk policy."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Literal

Choice = Literal["ours", "theirs", "both"]


def resolve_diff3(text: str, choices: list[Choice]) -> str:
    lines = text.splitlines(keepends=True)
    output: list[str] = []
    index = 0
    hunk = 0

    while index < len(lines):
        if not lines[index].startswith("<<<<<<< "):
            output.append(lines[index])
            index += 1
            continue

        if hunk >= len(choices):
            raise ValueError(f"missing choice for conflict hunk {hunk + 1}")
        index += 1
        ours: list[str] = []
        while index < len(lines) and not lines[index].startswith("||||||| "):
            ours.append(lines[index])
            index += 1
        if index >= len(lines):
            raise ValueError(f"hunk {hunk + 1} has no diff3 base marker")

        index += 1
        while index < len(lines) and lines[index] != "=======\n":
            index += 1
        if index >= len(lines):
            raise ValueError(f"hunk {hunk + 1} has no separator")

        index += 1
        theirs: list[str] = []
        while index < len(lines) and not lines[index].startswith(">>>>>>> "):
            theirs.append(lines[index])
            index += 1
        if index >= len(lines):
            raise ValueError(f"hunk {hunk + 1} has no closing marker")
        index += 1

        choice = choices[hunk]
        if choice in ("ours", "both"):
            output.extend(ours)
        if choice in ("theirs", "both"):
            output.extend(theirs)
        hunk += 1

    if hunk != len(choices):
        raise ValueError(f"received {len(choices)} choices for {hunk} conflict hunks")
    return "".join(output)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--choices",
        required=True,
        help="Comma-separated per-hunk choices: ours,theirs,both",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    raw_choices = [item.strip() for item in args.choices.split(",") if item.strip()]
    invalid = [item for item in raw_choices if item not in {"ours", "theirs", "both"}]
    if invalid:
        raise ValueError(f"invalid choices: {', '.join(invalid)}")
    choices: list[Choice] = raw_choices  # type: ignore[assignment]
    resolved = resolve_diff3(args.input.read_text(encoding="utf-8"), choices)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(resolved, encoding="utf-8", newline="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
