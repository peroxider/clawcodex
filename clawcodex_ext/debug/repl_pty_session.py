"""Interactive PTY controller for debugging the real ClawCodex REPL."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence, TextIO


ANSI_RE = re.compile(r'(?:\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)|\x1b[@-_])')
READY_MARKER_RE = r'CLAWCODEX_AGENT_DEBUG::repl\.ready::[^\r\n]*(?:\r?\n)?'
PROVIDER_ERROR_RE = re.compile(
    r'('
    r'ProviderError|API\s*Error|AuthenticationError|RateLimitError|'
    r'invalid[_ -]?api[_ -]?key|API key .*not configured|litellm\.exceptions'
    r')',
    re.IGNORECASE,
)
NETWORK_ERROR_RE = re.compile(
    r'('
    r'NetworkError|Connection\s*Error|ConnectTimeout|ReadTimeout|'
    r'NameResolutionError|DNS lookup|Temporary failure in name resolution|'
    r'nodename nor servname|SSL:'
    r')',
    re.IGNORECASE,
)
STREAMING_RE = re.compile(
    r'(Thinking|Streaming|Waiting for model|[\u2800-\u28ff])',
    re.IGNORECASE,
)
PERMISSION_PROMPT_RE = re.compile(
    r'Permission Required.*?(Allow\?|allow this action|Enter select|quick select)',
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class Observation:
    ok: bool
    event: str
    delta: str
    screen: str
    artifact_dir: str
    step: int
    error: str | None = None
    kind: str = 'unknown'
    state: str = 'unknown'
    error_kind: str | None = None
    signals: tuple[str, ...] = ()


@dataclass(frozen=True)
class ObservationClassification:
    kind: str
    state: str
    signals: tuple[str, ...]
    error_kind: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class Step:
    label: str
    send: str
    expect: str
    timeout: float = 30.0


@dataclass(frozen=True)
class ArtifactResult:
    ok: bool
    artifact_dir: Path
    raw_log: Path
    clean_transcript: Path
    result_json: Path


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub('', text)


def _compact_for_expect(text: str) -> str:
    text = strip_ansi(text)
    text = re.sub(r'[\u2800-\u28ff]', '', text)
    text = re.sub(r'Thinking[^\r\n]*', '', text)
    text = text.replace('❯', '')
    return re.sub(r'\s+', '', text)


def _matches_expected_text(expected: str, rendered_text: str) -> bool:
    if expected in rendered_text:
        return True
    compact_expected = _compact_for_expect(expected)
    if not compact_expected:
        return True
    return compact_expected in _compact_for_expect(rendered_text)


def _has_non_echo_output(delta: str, sent_text: str | None) -> bool:
    if sent_text is None:
        return bool(strip_ansi(delta).strip())
    for line in strip_ansi(delta).replace('\r', '\n').split('\n'):
        candidate = line.strip()
        if not candidate:
            continue
        if candidate == sent_text:
            continue
        if candidate.endswith(sent_text) and candidate[: -len(sent_text)].strip() in {'>', '❯'}:
            continue
        return True
    return False


def _has_initial_terminal_echo(delta: str, sent_text: str | None) -> bool:
    if sent_text is None:
        return False
    for line in delta.replace('\r', '\n').split('\n'):
        if not line.strip():
            continue
        return _line_is_terminal_echo(line, sent_text)
    return False


def _line_is_terminal_echo(line: str, sent_text: str) -> bool:
    candidate = strip_ansi(line).strip()
    if not candidate:
        return False
    if candidate == sent_text:
        return True
    return candidate.endswith(sent_text) and candidate[: -len(sent_text)].strip() in {
        '>',
        '❯',
    }


def _without_initial_terminal_echo(delta: str, sent_text: str | None) -> str:
    if sent_text is None:
        return delta
    lines = delta.replace('\r', '\n').split('\n')
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        if _line_is_terminal_echo(line, sent_text):
            return '\n'.join(lines[index + 1 :])
        return delta
    return ''


def _first_non_empty_line(text: str) -> str | None:
    for line in strip_ansi(text).replace('\r', '\n').split('\n'):
        candidate = line.strip()
        if candidate:
            return candidate
    return None


def _detect_rendered_error(text: str) -> tuple[str, str] | None:
    clean = strip_ansi(text)
    for line in clean.replace('\r', '\n').split('\n'):
        candidate = line.strip()
        if not candidate:
            continue
        if NETWORK_ERROR_RE.search(candidate):
            return 'network_error', candidate
        if PROVIDER_ERROR_RE.search(candidate):
            return 'provider_error', candidate
    return None


def _has_permission_prompt(text: str) -> bool:
    clean = strip_ansi(text)
    matches = list(PERMISSION_PROMPT_RE.finditer(clean))
    if not matches:
        return False

    # Terminal redraws often keep the old permission menu visible in the same
    # delta that also contains the approved tool result and a fresh prompt.
    # Classify only an active permission prompt as awaiting input.
    tail = clean[matches[-1].end() :]
    if 'Tool result:' in tail or 'Tool error:' in tail or 'Goodbye!' in tail:
        return False
    return True


def _classify_observation(
    *,
    delta: str,
    sent_text: str | None,
    ok: bool,
    event: str,
    error: str | None,
) -> ObservationClassification:
    clean_delta = strip_ansi(delta)
    non_echo_delta = strip_ansi(_without_initial_terminal_echo(delta, sent_text))
    signals: list[str] = []

    if _has_initial_terminal_echo(delta, sent_text):
        signals.append('input_echo')
    if STREAMING_RE.search(clean_delta):
        signals.append('streaming')
    if 'CLAWCODEX_AGENT_DEBUG::repl.ready::' in clean_delta:
        signals.append('ready_marker')
    if '❯' in delta or re.search(r'(^|\n)\s*[>❯]\s*$', clean_delta):
        signals.append('prompt')

    if event == 'ready':
        return ObservationClassification('ready', 'ready', tuple(signals or ['ready_marker']))
    if event == 'stopped':
        return ObservationClassification('stopped', 'stopped', tuple(signals))

    if _has_permission_prompt(non_echo_delta or clean_delta):
        signals.append('permission_prompt')
        return ObservationClassification(
            'permission_prompt',
            'awaiting_permission',
            tuple(dict.fromkeys(signals)),
        )

    rendered_error = _detect_rendered_error(non_echo_delta or clean_delta)
    if rendered_error is not None:
        error_kind, summary = rendered_error
        signals.append(error_kind)
        return ObservationClassification(
            kind=error_kind,
            state='error',
            signals=tuple(dict.fromkeys(signals)),
            error_kind=error_kind,
            error=f'{error_kind}: {summary}',
        )

    if error is not None or not ok:
        error_kind = 'timeout' if error and 'Timeout exceeded' in error else 'controller_error'
        signals.append(error_kind)
        return ObservationClassification(
            kind=error_kind,
            state='error',
            signals=tuple(dict.fromkeys(signals)),
            error_kind=error_kind,
        )

    has_non_echo = _has_non_echo_output(delta, sent_text)
    if sent_text and sent_text.lstrip().startswith('/') and has_non_echo:
        signals.append('slash_command')
        return ObservationClassification('slash_command', 'idle', tuple(dict.fromkeys(signals)))
    if has_non_echo:
        signals.append('assistant_output')
        state = 'streaming' if 'streaming' in signals and 'prompt' not in signals else 'idle'
        return ObservationClassification('assistant_output', state, tuple(dict.fromkeys(signals)))
    if 'input_echo' in signals:
        return ObservationClassification('input_echo', 'prompt', tuple(dict.fromkeys(signals)))

    line = _first_non_empty_line(clean_delta)
    if line:
        signals.append('terminal_output')
        return ObservationClassification('terminal_output', 'idle', tuple(dict.fromkeys(signals)))

    return ObservationClassification('prompt', 'prompt', tuple(dict.fromkeys(signals)))


def default_repl_command() -> list[str]:
    return [
        sys.executable,
        '-m',
        'clawcodex_ext.cli.main',
        '--legacy-repl',
        '--stream',
        '--agent-debug',
    ]


def default_artifact_dir(root: Path | None = None) -> Path:
    base = root or Path(tempfile.gettempdir()) / 'clawcodex-repl-pty'
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    return base / stamp


def build_goal_script(*, goal: str, prompt: str, expect_response: str) -> list[Step]:
    return [
        Step(label='start goal', send=f'/goal {goal}', expect='Goal set:'),
        Step(label='send prompt', send=prompt, expect=expect_response),
        Step(label='inspect goal', send='/goal', expect='Tokens:'),
        Step(label='clear goal', send='/goal clear', expect='Goal cleared'),
        Step(label='exit', send='/exit', expect='Goodbye!'),
    ]


def write_artifacts(
    *,
    artifact_dir: Path,
    raw_text: str,
    command: Sequence[str],
    events: list[dict[str, object]],
    ok: bool,
    error: str | None,
) -> ArtifactResult:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    raw_log = artifact_dir / 'raw.log'
    clean_transcript = artifact_dir / 'clean.txt'
    result_json = artifact_dir / 'result.json'

    raw_log.write_text(raw_text, encoding='utf-8')
    clean_transcript.write_text(strip_ansi(raw_text), encoding='utf-8')
    result_json.write_text(
        json.dumps(
            {
                'artifacts': {
                    'clean_transcript': str(clean_transcript),
                    'raw_log': str(raw_log),
                    'result_json': str(result_json),
                },
                'command': list(command),
                'error': error,
                'events': events,
                'ok': ok,
            },
            indent=2,
            sort_keys=True,
        )
        + '\n',
        encoding='utf-8',
    )
    return ArtifactResult(ok, artifact_dir, raw_log, clean_transcript, result_json)


class ReplPtySession:
    def __init__(
        self,
        *,
        command: Sequence[str],
        artifact_dir: Path,
        timeout: float = 30.0,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.command = list(command)
        self.artifact_dir = artifact_dir
        self.timeout = timeout
        self.env = {str(key): str(value) for key, value in (env or {}).items()}
        self._child = None
        self._raw_chunks: list[str] = []
        self._events: list[dict[str, object]] = []
        self._step = 0

    def start(self) -> Observation:
        try:
            import pexpect
        except ModuleNotFoundError as exc:
            raise SystemExit(
                'pexpect is required. Run with `uv run --extra dev --frozen ...`.'
            ) from exc

        from clawcodex_ext.debug.agent_debug import apply_agent_debug_environment

        child_env = os.environ.copy()
        child_env.update(self.env)
        debug_dir_raw = str(child_env.get('CLAWCODEX_AGENT_DEBUG_DIR', '')).strip()
        debug_dir = (
            Path(debug_dir_raw).expanduser() if debug_dir_raw else self.artifact_dir / 'state'
        )
        apply_agent_debug_environment(child_env, debug_dir=debug_dir)

        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self._child = pexpect.spawn(
            self.command[0],
            self.command[1:],
            dimensions=(40, 120),
            encoding='utf-8',
            env=child_env,
            timeout=self.timeout,
        )
        return self._expect_regex(READY_MARKER_RE, event='ready')

    def send(
        self,
        text: str,
        *,
        expect: str | None = None,
        timeout: float | None = None,
    ) -> Observation:
        self._require_child().sendline(text)
        if expect:
            return self.expect(
                expect,
                timeout=timeout,
                event='observed',
                ignored_initial_echo=text,
            )
        return self._observe(timeout=timeout, ignored_initial_echo=text)

    def key(self, text: str, *, timeout: float | None = None) -> Observation:
        self._require_child().send(text)
        return self._observe(timeout=timeout, ignored_initial_echo=text)

    def expect(
        self,
        pattern: str,
        *,
        timeout: float | None = None,
        event: str = 'observed',
        ignored_initial_echo: str | None = None,
    ) -> Observation:
        return self._expect_exact(
            pattern,
            timeout=timeout,
            event=event,
            ignored_initial_echo=ignored_initial_echo,
        )

    def observe(self, *, timeout: float | None = None) -> Observation:
        return self._observe(timeout=timeout, ignored_initial_echo=None)

    def _observe(
        self,
        *,
        timeout: float | None,
        ignored_initial_echo: str | None,
    ) -> Observation:
        child = self._require_child()
        before_len = len(self.raw_text)
        total_timeout = self.timeout if timeout is None else timeout
        deadline = time.monotonic() + total_timeout
        idle_deadline: float | None = None
        saw_substantive_output = False

        while time.monotonic() < deadline:
            read_timeout = 0.05
            if idle_deadline is not None:
                read_timeout = max(0.0, min(read_timeout, idle_deadline - time.monotonic()))
            try:
                chunk = child.read_nonblocking(size=4096, timeout=read_timeout)
            except Exception:
                if hasattr(child, 'isalive') and not child.isalive():
                    break
                if saw_substantive_output and idle_deadline is not None:
                    if time.monotonic() >= idle_deadline:
                        break
                    continue
                if not saw_substantive_output:
                    time.sleep(0.01)
                    continue
                break
            if not chunk:
                if saw_substantive_output:
                    break
                continue
            self._collect(chunk)
            delta = self.raw_text[before_len:]
            if _has_non_echo_output(delta, ignored_initial_echo):
                saw_substantive_output = True
                idle_deadline = time.monotonic() + min(0.2, total_timeout)

        return self._observation(
            True,
            'observed',
            before_len,
            sent_text=ignored_initial_echo,
        )

    def stop(self) -> Observation:
        before_len = len(self.raw_text)
        child = self._child
        if child is not None and child.isalive():
            try:
                child.sendline('/exit')
                child.expect_exact('Goodbye!', timeout=2)
                self._collect(str(child.before))
                self._collect(str(child.after))
            except Exception:
                child.close(force=True)
        self._child = None
        return self._observation(True, 'stopped', before_len)

    @property
    def raw_text(self) -> str:
        return ''.join(self._raw_chunks)

    @property
    def screen(self) -> str:
        return strip_ansi(self.raw_text)

    def write_artifacts(self, *, ok: bool, error: str | None = None) -> ArtifactResult:
        return write_artifacts(
            artifact_dir=self.artifact_dir,
            command=self.command,
            error=error,
            events=self._events,
            ok=ok,
            raw_text=self.raw_text,
        )

    def _require_child(self):
        if self._child is None:
            raise RuntimeError('REPL PTY session has not been started')
        return self._child

    def _expect_exact(
        self,
        pattern: str,
        *,
        timeout: float | None,
        event: str,
        ignored_initial_echo: str | None,
    ) -> Observation:
        child = self._require_child()
        before_len = len(self.raw_text)
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while time.monotonic() < deadline:
            try:
                chunk = child.read_nonblocking(size=4096, timeout=0.05)
            except Exception:
                if hasattr(child, 'isalive') and not child.isalive():
                    break
                time.sleep(0.01)
                continue
            self._collect(str(chunk))
            clean_delta = strip_ansi(
                _without_initial_terminal_echo(
                    self.raw_text[before_len:],
                    ignored_initial_echo,
                )
            )
            rendered_error = _detect_rendered_error(clean_delta)
            if rendered_error is not None:
                error_kind, summary = rendered_error
                return self._observation(
                    False,
                    'error',
                    before_len,
                    f'{error_kind}: {summary}',
                    sent_text=ignored_initial_echo,
                )
            if _matches_expected_text(pattern, clean_delta):
                self._drain_available()
                return self._observation(
                    True,
                    event,
                    before_len,
                    sent_text=ignored_initial_echo,
                )
        clean_delta = strip_ansi(
            _without_initial_terminal_echo(
                self.raw_text[before_len:],
                ignored_initial_echo,
            )
        )
        if _matches_expected_text(pattern, clean_delta):
            self._drain_available()
            return self._observation(
                True,
                event,
                before_len,
                sent_text=ignored_initial_echo,
            )
        error = f'Timeout exceeded while waiting for {pattern!r}'
        return self._observation(
            False,
            'error',
            before_len,
            error,
            sent_text=ignored_initial_echo,
        )

    def _expect_regex(self, pattern: str, *, event: str) -> Observation:
        child = self._require_child()
        before_len = len(self.raw_text)
        try:
            child.expect(pattern, timeout=self.timeout)
            self._collect(str(child.before))
            self._collect(str(child.after))
            self._drain_available()
            return self._observation(True, event, before_len)
        except Exception as exc:
            self._collect(str(getattr(child, 'before', '')))
            return self._observation(False, 'error', before_len, f'{type(exc).__name__}: {exc}')

    def _collect(self, text: str) -> None:
        if text:
            self._raw_chunks.append(text)

    def _drain_available(self, *, max_wait: float = 0.2) -> None:
        child = self._require_child()
        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            try:
                chunk = child.read_nonblocking(size=4096, timeout=0.02)
            except Exception:
                if hasattr(child, 'isalive') and not child.isalive():
                    break
                time.sleep(0.01)
                continue
            if not chunk:
                break
            self._collect(str(chunk))

    def _observation(
        self,
        ok: bool,
        event: str,
        before_len: int,
        error: str | None = None,
        sent_text: str | None = None,
    ) -> Observation:
        self._step += 1
        delta = self.raw_text[before_len:]
        classification = _classify_observation(
            delta=delta,
            sent_text=sent_text,
            ok=ok,
            event=event,
            error=error,
        )
        final_error = error or classification.error
        final_ok = ok and classification.state != 'error'
        final_event = 'error' if classification.state == 'error' else event
        obs = Observation(
            ok=final_ok,
            event=final_event,
            delta=strip_ansi(delta),
            screen=self.screen,
            artifact_dir=str(self.artifact_dir),
            step=self._step,
            error=final_error,
            kind=classification.kind,
            state=classification.state,
            error_kind=classification.error_kind,
            signals=classification.signals,
        )
        self._events.append(asdict(obs))
        return obs


def _write_json(stdout: TextIO, payload: Mapping[str, object]) -> None:
    stdout.write(json.dumps(dict(payload), ensure_ascii=False, sort_keys=True) + '\n')
    stdout.flush()


def run_script(
    *,
    command: Sequence[str],
    steps: Iterable[Step],
    artifact_dir: Path,
    timeout: float,
) -> ArtifactResult:
    session = ReplPtySession(command=command, artifact_dir=artifact_dir, timeout=timeout)
    ok = True
    error = None
    ready = session.start()
    if not ready.ok:
        ok = False
        error = ready.error
    for step in steps:
        if not ok:
            break
        observed = session.send(step.send, expect=step.expect, timeout=step.timeout)
        if not observed.ok:
            ok = False
            error = observed.error
            break
    if ok:
        session.stop()
    return session.write_artifacts(ok=ok, error=error)


def run_interactive_jsonl(
    *,
    stdin: TextIO,
    stdout: TextIO,
    artifact_dir: Path,
    timeout: float,
) -> int:
    session: ReplPtySession | None = None
    ok = True
    error = None
    for raw_line in stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            op = request.get('op')
            if op == 'start':
                command = request.get('cmd') or default_repl_command()
                if not isinstance(command, list) or not all(isinstance(x, str) for x in command):
                    _write_json(
                        stdout,
                        {
                            'error': 'start.cmd must be a list of strings',
                            'event': 'error',
                            'ok': False,
                        },
                    )
                    ok = False
                    continue
                env = request.get('env')
                session = ReplPtySession(
                    command=command,
                    artifact_dir=artifact_dir,
                    env=env if isinstance(env, dict) else None,
                    timeout=float(request.get('timeout', timeout)),
                )
                obs = session.start()
                _write_json(stdout, asdict(obs))
                ok = ok and obs.ok
                error = obs.error or error
                continue
            if op in {'exit', 'quit'}:
                if session is not None:
                    obs = session.stop()
                    _write_json(stdout, asdict(obs))
                    session.write_artifacts(ok=ok, error=error)
                    session = None
                _write_json(
                    stdout,
                    {
                        'event': 'controller_exit',
                        'ok': True,
                    },
                )
                return 0 if ok else 1
            if session is None:
                _write_json(
                    stdout,
                    {
                        'error': 'session has not been started',
                        'event': 'error',
                        'ok': False,
                    },
                )
                ok = False
                continue
            if op == 'send':
                text = request.get('text')
                if not isinstance(text, str):
                    _write_json(
                        stdout,
                        {
                            'error': 'send.text must be a string',
                            'event': 'error',
                            'ok': False,
                        },
                    )
                    ok = False
                    continue
                expect = request.get('expect')
                obs = session.send(
                    text,
                    expect=expect if isinstance(expect, str) else None,
                    timeout=float(request.get('timeout', timeout)),
                )
                _write_json(stdout, asdict(obs))
                ok = ok and obs.ok
                error = obs.error or error
                continue
            if op in {'key', 'raw'}:
                text = request.get('text')
                if not isinstance(text, str):
                    _write_json(
                        stdout,
                        {
                            'error': f'{op}.text must be a string',
                            'event': 'error',
                            'ok': False,
                        },
                    )
                    ok = False
                    continue
                obs = session.key(
                    text,
                    timeout=float(request.get('timeout', timeout)),
                )
                _write_json(stdout, asdict(obs))
                ok = ok and obs.ok
                error = obs.error or error
                continue
            if op == 'observe':
                obs = session.observe(timeout=float(request.get('timeout', timeout)))
                _write_json(stdout, asdict(obs))
                ok = ok and obs.ok
                error = obs.error or error
                continue
            if op == 'stop':
                obs = session.stop()
                _write_json(stdout, asdict(obs))
                session.write_artifacts(ok=ok, error=error)
                session = None
                continue
            _write_json(
                stdout,
                {
                    'error': f'unknown op: {op!r}',
                    'event': 'error',
                    'ok': False,
                },
            )
            ok = False
        except Exception as exc:
            _write_json(
                stdout,
                {
                    'error': f'{type(exc).__name__}: {exc}',
                    'event': 'error',
                    'ok': False,
                },
            )
            ok = False
    if session is not None:
        session.stop()
        session.write_artifacts(ok=ok, error=error)
    return 0 if ok else 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Control the real ClawCodex REPL through a PTY.')
    sub = parser.add_subparsers(dest='mode', required=True)

    interactive = sub.add_parser('interactive', help='Run JSONL controller over stdin/stdout.')
    interactive.add_argument('--timeout', type=float, default=30.0)
    interactive.add_argument(
        '--artifact-root',
        type=Path,
        default=Path(tempfile.gettempdir()) / 'clawcodex-repl-pty',
    )

    script = sub.add_parser('run-script', help='Run the built-in goal smoke script.')
    script.add_argument('--goal', default='Verify REPL PTY debug harness')
    script.add_argument(
        '--prompt',
        default='Return the exact token named goal pty ok using hyphens and uppercase.',
    )
    script.add_argument('--expect-response', default='GOAL-PTY-OK')
    script.add_argument('--timeout', type=float, default=60.0)
    script.add_argument(
        '--artifact-root',
        type=Path,
        default=Path(tempfile.gettempdir()) / 'clawcodex-repl-pty',
    )
    script.add_argument('--cmd', nargs=argparse.REMAINDER)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    artifact_dir = default_artifact_dir(args.artifact_root)
    if args.mode == 'interactive':
        return run_interactive_jsonl(
            stdin=sys.stdin,
            stdout=sys.stdout,
            artifact_dir=artifact_dir,
            timeout=args.timeout,
        )
    if args.mode == 'run-script':
        command = args.cmd if args.cmd else default_repl_command()
        result = run_script(
            command=command,
            steps=build_goal_script(
                goal=args.goal,
                prompt=args.prompt,
                expect_response=args.expect_response,
            ),
            artifact_dir=artifact_dir,
            timeout=args.timeout,
        )
        print(f'ok={result.ok}')
        print(f'artifacts={result.artifact_dir}')
        return 0 if result.ok else 1
    raise SystemExit(f'unknown mode: {args.mode}')


if __name__ == '__main__':
    raise SystemExit(main())
