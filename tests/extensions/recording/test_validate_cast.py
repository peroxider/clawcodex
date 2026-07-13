"""Tests for the self-contained asciicast v2 validator (F-REC).

The validator must run without any external dependency (no asciinema
CLI), so these tests pin its semantics and reject-only-the-bad
behaviour.
"""

from __future__ import annotations

import json
from pathlib import Path

from extensions.capabilities.recorder import AsciicastEvent, AsciicastHeader
from extensions.recording.asciicast_writer import AsciicastWriter
from extensions.recording.validate_cast import validate_cast


def _cast(tmp_path: Path, *, header_kwargs: dict | None = None, frames: list[AsciicastEvent] | None = None) -> Path:
    header = AsciicastHeader(
        width=(header_kwargs or {}).get("width", 120),
        height=(header_kwargs or {}).get("height", 36),
        version=(header_kwargs or {}).get("version", 2),
    )
    path = tmp_path / "demo.cast"
    writer = AsciicastWriter(path, header)
    with writer as capture:
        for event in frames or [AsciicastEvent(t=0.1, kind="m", data="ok")]:
            capture.emit(event)
    return path


def test_validate_cast_accepts_minimal_valid_file(tmp_path: Path) -> None:
    path = _cast(tmp_path)
    assert validate_cast(path) == []


def test_validate_cast_rejects_missing_file(tmp_path: Path) -> None:
    errs = validate_cast(tmp_path / "nope.cast")
    assert errs and "file not found" in errs[0]


def test_validate_cast_rejects_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.cast"
    path.write_text("", encoding="utf-8")
    errs = validate_cast(path)
    assert errs and "empty file" in errs[0]


def test_validate_cast_rejects_bad_header_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.cast"
    path.write_text("not json\n", encoding="utf-8")
    errs = validate_cast(path)
    assert errs
    assert any("header is not valid JSON" in e for e in errs)


def test_validate_cast_rejects_wrong_version(tmp_path: Path) -> None:
    path = _cast(tmp_path, header_kwargs={"version": 1})
    errs = validate_cast(path)
    assert any("version must be 2" in e for e in errs)


def test_validate_cast_rejects_missing_width_or_height(tmp_path: Path) -> None:
    path = tmp_path / "no_w.cast"
    # Build a header JSON by hand, dropping width.
    header = {"version": 2, "height": 36}
    path.write_text(json.dumps(header) + "\n[0.0, \"m\", \"ok\"]\n", encoding="utf-8")
    errs = validate_cast(path)
    assert any("missing required fields" in e for e in errs)


def test_validate_cast_rejects_non_positive_dimensions(tmp_path: Path) -> None:
    path = _cast(tmp_path, header_kwargs={"width": 0, "height": 0})
    errs = validate_cast(path)
    assert any("width must be a positive int" in e for e in errs)
    assert any("height must be a positive int" in e for e in errs)


def test_validate_cast_rejects_malformed_event_tuple(tmp_path: Path) -> None:
    path = _cast(tmp_path)
    # Append a deliberately broken event.
    with path.open("a", encoding="utf-8") as fp:
        fp.write("[0.1, \"x\", \"bad\"]\n")
        fp.write("[0.2]\n")
        fp.write("[\"o\", 0.3, \"bad\"]\n")
        fp.write("not-json\n")
    errs = validate_cast(path)
    # Expect errors for each of the 4 broken lines.
    assert any("event code must be one of" in e for e in errs)
    assert any("event must be [time:number" in e for e in errs)
    assert any("invalid JSON" in e for e in errs)


def test_validate_cast_rejects_negative_timestamps(tmp_path: Path) -> None:
    path = _cast(tmp_path)
    with path.open("a", encoding="utf-8") as fp:
        fp.write("[-0.1, \"m\", \"back-in-time\"]\n")
    errs = validate_cast(path)
    assert any("event time must be >= 0" in e for e in errs)


def test_validate_cast_tolerates_blank_lines(tmp_path: Path) -> None:
    path = _cast(tmp_path)
    with path.open("a", encoding="utf-8") as fp:
        fp.write("\n")
        fp.write("   \n")
    assert validate_cast(path) == []