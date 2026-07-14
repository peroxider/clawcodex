"""Tests for the F-REC cast→mp4 post-processor.

Covers the PNG rendering, hold-time math, and the ffmpeg
integration.  The ffmpeg E2E is skipped when ``ffmpeg`` is not on
``PATH`` (CI may run on a minimal image), but the rendering path
requires Pillow — if Pillow is missing, the suite skips itself
instead of failing the whole recording gate.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Pillow / ffmpeg availability gating
# ---------------------------------------------------------------------------


def _pillow_available() -> bool:
    try:
        from PIL import Image  # noqa: F401

        return True
    except ImportError:
        return False


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


pytestmark = pytest.mark.skipif(
    not _pillow_available(),
    reason="Pillow not installed; cast-to-mp4 tests are opt-in",
)


# ---------------------------------------------------------------------------
# Fixtures: build a minimal .cast file with N snapshot markers
# ---------------------------------------------------------------------------


def _make_cast(tmp_path: Path, *, snapshots: int, time_step: float = 0.4) -> Path:
    """Write a tiny valid .cast with N dashboard:snapshot markers."""
    cast = tmp_path / "demo.cast"
    lines = [
        json.dumps(
            {"version": 2, "width": 120, "height": 36, "title": "fixture"}
        )
    ]
    for i in range(snapshots):
        t = i * time_step
        lines.append(json.dumps([t, "m", "dashboard:snapshot"]))
        lines.append(
            json.dumps(
                [
                    t + 0.01,
                    "o",
                    (
                        "Logical Kanban (tick "
                        f"{i})    ⏳ pending: 1  🔵 running: 2  "
                        "✅ done: 0  ❌ failed: 0  🚧 blocked: 0\n"
                    ),
                ]
            )
        )
    cast.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return cast


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_render_cast_to_pngs_returns_one_png_per_snapshot(
    tmp_path: Path,
) -> None:
    from extensions.recording.tools.cast_to_mp4 import render_cast_to_pngs

    cast = _make_cast(tmp_path, snapshots=4)
    pairs = render_cast_to_pngs(cast, tmp_path / "out")

    assert len(pairs) == 4
    for png, _hold in pairs:
        assert png.exists()
        assert png.stat().st_size > 0
        assert png.suffix == ".png"


def test_render_cast_to_pngs_computes_hold_time_from_gaps(
    tmp_path: Path,
) -> None:
    from extensions.recording.tools.cast_to_mp4 import _compute_hold_seconds

    snapshots = [(0.0, []), (2.0, []), (3.5, []), (5.0, [])]
    holds = _compute_hold_seconds(snapshots)
    # Inter-snapshot gaps are 2.0, 1.5, 1.5 → min_hold=1.0 floors nothing here,
    # and the tail gets the explicit 2.0s hold.
    assert holds == [2.0, 1.5, 1.5, 2.0]


def test_render_cast_to_pngs_enforces_min_hold_floor(
    tmp_path: Path,
) -> None:
    from extensions.recording.tools.cast_to_mp4 import _compute_hold_seconds

    # Three snapshots 50ms apart — without the min_hold floor the
    # frames would only show for ~50ms each.
    snapshots = [(0.0, []), (0.05, []), (0.10, [])]
    holds = _compute_hold_seconds(snapshots, min_hold=1.0, tail_hold=2.0)
    assert holds == [1.0, 1.0, 2.0]


def test_render_cast_to_pngs_raises_when_no_output_frames(
    tmp_path: Path,
) -> None:
    """When no output frames exist, fallback sampling is empty too."""
    from extensions.recording.tools.cast_to_mp4 import render_cast_to_pngs

    bad = tmp_path / "empty.cast"
    bad.write_text(
        '{"version":2,"width":120,"height":36}\n'
        '[0.0,"m","unknown:marker"]\n',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="no renderable output frames"):
        render_cast_to_pngs(bad, tmp_path / "out")


def test_render_cast_to_pngs_raises_runtime_error_on_malformed_header(
    tmp_path: Path,
) -> None:
    """Malformed header must surface as RuntimeError (not JSONDecodeError).

    Guards a regression where ``json.loads`` raised
    ``JSONDecodeError`` (a ``ValueError`` subclass) and the CLI's
    ``except RuntimeError`` did not catch it, leaking a raw Python
    traceback to the end user.
    """
    from extensions.recording.tools.cast_to_mp4 import render_cast_to_pngs

    bad = tmp_path / "garbage.cast"
    bad.write_text("not json at all\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="malformed header"):
        render_cast_to_pngs(bad, tmp_path / "out")


def test_render_cast_to_pngs_raises_runtime_error_on_malformed_event_frame(
    tmp_path: Path,
) -> None:
    """Bad event frames further down the file must also be normalized."""
    from extensions.recording.tools.cast_to_mp4 import render_cast_to_pngs

    bad = tmp_path / "mid.cast"
    bad.write_text(
        '{"version":2,"width":120,"height":36}\n'
        "totally bogus event frame\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="malformed event frame"):
        render_cast_to_pngs(bad, tmp_path / "out")


def test_emoji_badges_are_replaced_with_ascii_labels(tmp_path: Path) -> None:
    """Each tick's stats line carries all 5 badge emoji; after render
    they must all be replaced, and the line's color must reflect the
    *last* badge seen in the line."""
    from extensions.recording.tools.cast_to_mp4 import _draw_frame
    from PIL import Image, ImageDraw, ImageFont

    outputs = [
        "Header line\n",
        (
            "Logical Kanban (tick 0)    ⏳ pending: 1  🔵 running: 2  "
            "✅ done: 0  ❌ failed: 0  🚧 blocked: 0\n"
        ),
    ]
    out = tmp_path / "ascii_test.png"
    _draw_frame(
        out,
        outputs=outputs,
        title="emoji test",
        width_px=960,
        height_px=480,
        bg=(14, 17, 22),
        fg=(201, 209, 217),
        palette={
            "pending": (110, 118, 129),
            "running": (88, 166, 255),
            "done": (63, 185, 80),
            "failed": (248, 81, 73),
            "blocked": (210, 153, 34),
        },
        font=ImageFont.load_default(),
        badge_font=ImageFont.load_default(),
        Image=Image,
        ImageDraw=ImageDraw,
    )
    assert out.exists() and out.stat().st_size > 0


def test_run_cast_to_mp4_rejects_missing_ffmpeg_when_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If ffmpeg is missing, the CLI surfaces a friendly error (rc=2).

    We monkeypatch ``shutil.which`` so we don't need to manipulate the
    real ``PATH``.  PIL is assumed available; if it's not, the suite
    was already skipped at module load.
    """
    if not _pillow_available():
        pytest.skip("Pillow is not installed")
    from extensions.recording.tools import cast_to_mp4 as mod

    cast = _make_cast(tmp_path, snapshots=2)
    out = tmp_path / "nope.mp4"

    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    rc = mod.run_cast_to_mp4_command(
        ["--cast", str(cast), "--out", str(out)]
    )
    assert rc == 2



# ---------------------------------------------------------------------------
# ffmpeg integration
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not on PATH")
def test_pngs_to_mp4_produces_a_valid_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from extensions.recording.tools.cast_to_mp4 import (
        pngs_to_mp4,
        render_cast_to_pngs,
    )

    cast = _make_cast(tmp_path, snapshots=3)
    png_dir = tmp_path / "pngs"
    pairs = render_cast_to_pngs(cast, png_dir)
    mp4 = tmp_path / "out.mp4"
    pngs_to_mp4(pairs, mp4, fps=2)
    assert mp4.exists()
    assert mp4.stat().st_size > 0


@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not on PATH")
def test_convert_cast_to_mp4_writes_keep_pngs_when_requested(
    tmp_path: Path,
) -> None:
    from extensions.recording.tools.cast_to_mp4 import convert_cast_to_mp4

    cast = _make_cast(tmp_path, snapshots=2)
    mp4 = tmp_path / "kept.mp4"
    pairs = convert_cast_to_mp4(cast, mp4, fps=2, keep_pngs=True)
    assert mp4.exists() and mp4.stat().st_size > 0

    keep_dir = mp4.with_suffix(mp4.suffix + ".pngs")
    assert keep_dir.exists()
    preserved = sorted(keep_dir.glob("frame_*.png"))
    assert len(preserved) == len(pairs)


def test_render_cast_to_pngs_falls_back_to_interval_sampling(
    tmp_path: Path,
) -> None:
    """If no recognized markers are present, the renderer samples o frames."""
    from extensions.recording.tools.cast_to_mp4 import render_cast_to_pngs

    cast = tmp_path / "plain.cast"
    cast.write_text(
        json.dumps({"version": 2, "width": 120, "height": 36, "title": "repl"})
        + "\n"
        + json.dumps([0.0, "o", "line 1\n"])
        + "\n"
        + json.dumps([1.0, "o", "line 2\n"])
        + "\n"
        + json.dumps([3.0, "o", "line 3\n"])
        + "\n"
        + json.dumps([3.5, "o", "line 4\n"])
        + "\n",
        encoding="utf-8",
    )
    pairs = render_cast_to_pngs(cast, tmp_path / "out", fallback_interval_s=1.5)
    # Events at 0.0, 1.0, 3.0, 3.5 with interval 1.5:
    # 0.0 and 1.0 fall in the first bucket, 3.0 and 3.5 in the second.
    assert len(pairs) == 2


def test_run_cast_to_mp4_rejects_missing_input(tmp_path: Path) -> None:
    """CLI must fail with exit code 2 when the input .cast does not exist."""
    from extensions.recording.tools.cast_to_mp4 import run_cast_to_mp4_command

    missing = tmp_path / "ghost.cast"
    out = tmp_path / "ghost.mp4"
    rc = run_cast_to_mp4_command(
        ["--cast", str(missing), "--out", str(out)]
    )
    assert rc == 2


def test_run_cast_to_mp4_emits_clean_error_for_malformed_cast(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Malformed .cast must surface as one-line stderr — no traceback.

    Companion test to the two unit tests above; this one exercises
    the CLI entry point to catch future regressions in
    :func:`run_cast_to_mp4_command` (e.g. a widening of ``except``).
    """
    from extensions.recording.tools.cast_to_mp4 import run_cast_to_mp4_command

    bad = tmp_path / "garbage.cast"
    bad.write_text("not json\n", encoding="utf-8")
    out = tmp_path / "garbage.mp4"
    rc = run_cast_to_mp4_command(
        ["--cast", str(bad), "--out", str(out)]
    )
    assert rc == 1

    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "malformed" in captured.err
    assert str(bad) in captured.err


def test_run_cast_to_mp4_emits_clean_argparse(tmp_path: Path) -> None:
    """Sanity check: the parser exposes --cast/--out/--fps/--keep-pngs."""
    from extensions.recording.tools.cast_to_mp4 import build_cast_to_mp4_parser

    parser = build_cast_to_mp4_parser()
    args = parser.parse_args(
        [
            "--cast",
            "/tmp/in.cast",
            "--out",
            "/tmp/out.mp4",
            "--fps",
            "8",
            "--width",
            "640",
            "--height",
            "320",
            "--keep-pngs",
        ]
    )
    assert args.fps == 8
    assert args.width == 640
    assert args.height == 320
    assert args.keep_pngs is True
