"""F-REC-L end-to-end: REPL ``/dashboard`` rendered into ``.cast``.

F-156 §1.8 / F-REC-L wired a Rich-console tee + prompt_session proxy into
the default interactive REPL via ``extensions.recording.repl_source`` and
exposed ``clawcodex-dev --record <path>`` in
``clawcodex_ext/cli/parser.py``. Earlier tests in this directory only
exercised the writer/validator/registry in isolation or with synthetic
entries; none of them drove a real ``/dashboard`` invocation through the
REPL.

This module closes the gap with two complementary tests:

* ``test_headless_dashboard_argv_does_not_explode`` — guards the
  pre-existing crash in
  ``clawcodex_ext/entrypoints/headless._run_dashboard_headless``, where
  the path used to instantiate ``DashboardCommand()`` (a frozen
  ``InteractiveCommand`` dataclass whose ``name``/``description``
  fields lack defaults) and crash with "missing 2 required
  positional arguments". After the fix the same invocation produces
  the dashboard panel text on stdout.
* ``test_repl_interactive_dashboard_records_into_cast`` — drives the
  default interactive REPL via a PTY, issues ``/dashboard`` + ``/quit``
  with ``--record``, and asserts the captured ``.cast`` is a valid
  asciicast v2 file whose ``o``-frames contain the rendered dashboard
  panel. This is the explicit end-to-end smoke for F-REC-L.

The two tests cover the two real entry modes:
``-p /dashboard`` (headless print) without ``--record`` (headless
``HeadlessOptions`` deliberately drops ``record`` per F-REC-L design)
and interactive REPL with ``--record``.
"""

from __future__ import annotations

import json
import os
import pty
import subprocess
import sys
import time
from pathlib import Path

import pytest


def _read_cast(path: Path) -> tuple[dict, list[list[object]]]:
    raw = path.read_text(encoding="utf-8").splitlines()
    header = json.loads(raw[0])
    events = [json.loads(line) for line in raw[1:]]
    return header, events


@pytest.mark.timeout(60)
def test_headless_dashboard_argv_does_not_explode(tmp_path: Path) -> None:
    """``clawcodex-dev -p /dashboard`` exits 0 and prints the dashboard panel.

    Before the fix to
    ``clawcodex_ext/entrypoints/headless._run_dashboard_headless``,
    this invocation crashed with
    ``InteractiveCommand.__init__() missing 2 required positional
    arguments: 'name' and 'description'`` because the function
    instantiated a bare ``DashboardCommand()`` against a frozen
    dataclass whose ``CommandBase.name`` / ``description`` fields have
    no defaults.

    After the fix the function uses the pre-built ``DASHBOARD_COMMAND``
    singleton (which carries ``name`` and ``description``) so the
    command runs to completion and emits the dashboard panel to
    stdout. We assert on the panel's prose, not just on the exit
    code, so a future regression that drops the fix and falls back to
    a different failure mode is still caught.
    """
    env = os.environ.copy()
    env.setdefault("CLAWCODEX_DISABLE_TELEMETRY", "1")
    # Drop any local credential env so this test stays hermetic.
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "clawcodex_ext.cli.main",
            "-p",
            "/dashboard",
            "--output-format",
            "text",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(Path(__file__).resolve().parents[3]),
        env=env,
    )

    # The bug manifested as exit 1 with the "missing 2 required
    # positional arguments" traceback. The acceptance conditions are
    # rc == 0 AND no such traceback.
    assert result.returncode == 0, (
        f"headless /dashboard returned rc={result.returncode}; "
        f"stdout={result.stdout!r}; stderr={result.stderr!r}"
    )
    assert "missing 2 required positional arguments" not in result.stderr, (
        "headless /dashboard regressed to the InteractiveCommand "
        "dataclass crash; check the DASHBOARD_COMMAND singleton usage "
        "in clawcodex_ext/entrypoints/headless._run_dashboard_headless"
    )
    # Dashboard panel vocabulary the command emits. Lowercase to be
    # tolerant of Rich markup wrapping.
    combined = (result.stdout + result.stderr).lower()
    assert "dashboard" in combined, (
        f"expected 'dashboard' marker in output; got stdout={result.stdout!r}; "
        f"stderr={result.stderr!r}"
    )


@pytest.mark.timeout(90)
def test_repl_interactive_dashboard_records_into_cast(tmp_path: Path) -> None:
    """Interactive REPL + ``/dashboard`` + ``--record`` → valid ``.cast``.

    Drives the default prompt_toolkit + Rich REPL via a child PTY,
    feeds ``/dashboard`` followed by ``/quit``, and waits for the
    child to flush and exit cleanly. F-REC-L's
    ``install_repl_capture`` should mirror every Rich ``console.print``
    call into an ``"o"`` frame and emit ``"m"`` markers on prompt
    submit / start. The user-typed ``/dashboard`` is captured as an
    ``"i"`` frame.

    Acceptance conditions:

    * process exit code is 0 (clean ``/quit``)
    * ``.cast`` file exists and is valid asciicast v2 (header has
      ``version == 2``)
    * there is at least one ``"i"`` frame containing ``"/dashboard"``
    * there is at least one ``"m"`` marker identifying the prompt
    * the merged ``"o"`` frames contain the word "Dashboard"
      (rendered panel content captured)
    * the unified validator accepts the file

    Each clause locks down a different layer: process teardown,
    header schema, user input tee, prompt session proxy, Rich console
    tee, structural integrity.
    """
    cast_path = tmp_path / "repl-dashboard.cast"
    cli_argv = [
        "clawcodex-dev",
        "--record",
        str(cast_path),
        "--record-width",
        "120",
        "--record-height",
        "36",
    ]

    env = os.environ.copy()
    env.setdefault("CLAWCODEX_DISABLE_TELEMETRY", "1")
    # Run the CLI as a child with a real PTY so Rich + prompt_toolkit
    # behave the same way they do for a human operator. Killing the
    # child mid-flight would truncate the .cast; ``/quit`` lets the
    # REPL flush its ``atexit``-registered writer cleanly.
    pid, fd = pty.fork()
    if pid == 0:
        # Child: replace with the CLI. Match TERM so Rich doesn't fall
        # back to the "no color" rendering.
        env["TERM"] = env.get("TERM", "xterm-256color")
        os.execvpe(cli_argv[0], cli_argv, env)

    try:
        # Wait for the REPL splash + prompt to render.
        time.sleep(6)
        os.write(fd, b"/dashboard\n")
        time.sleep(4)
        # /quit is the REPL's clean-exit command. After we wait for
        # the child to exit on its own we never need to SIGKILL it.
        os.write(fd, b"/quit\n")
        try:
            _waited_pid, status = os.waitpid(pid, 0)
        except ChildProcessError:
            status = 0
    except Exception:
        # Make sure we don't leak a zombie on test failure.
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
        raise

    assert cast_path.exists(), (
        f"REPL never wrote {cast_path} before exiting; pid={pid}, status={status}"
    )

    from extensions.recording.validate_cast import validate_cast

    errors = validate_cast(cast_path)
    assert errors == [], (
        f"validator rejected the captured .cast: {errors!r}"
    )

    header, events = _read_cast(cast_path)
    assert header["version"] == 2
    assert "record" in header.get("command", ""), (
        f"header.command does not mention --record: {header!r}"
    )

    markers = [e[2] for e in events if e[1] == "m"]
    inputs = [e[2] for e in events if e[1] == "i"]
    output_frames = [e for e in events if e[1] == "o"]

    assert any("/dashboard" in payload for payload in inputs), (
        f"expected /dashboard in i-frames; got inputs={inputs!r}"
    )
    assert any(m == "repl:prompt:submit" for m in markers), (
        f"missing repl:prompt:submit markers; got {markers!r}"
    )
    assert any(m == "repl:prompt:start" for m in markers), (
        f"missing repl:prompt:start markers; got {markers!r}"
    )

    body = "".join(str(e[2]) for e in output_frames)
    assert "Dashboard" in body or "dashboard" in body.lower(), (
        f"merged o-frames do not contain 'Dashboard'; "
        f"first o-frame payload (truncated) = {str(output_frames[0][2])[:200]!r}"
    )
