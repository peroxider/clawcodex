from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from clawcodex_ext.debug.repl_pty_session import (
    ReplPtySession,
    Step,
    build_goal_script,
    default_repl_command,
    run_interactive_jsonl,
    run_script,
    strip_ansi,
    write_artifacts,
)


def fake_command() -> list[str]:
    return [sys.executable, str(Path(__file__).with_name('fake_repl_child.py'))]


def test_strip_ansi_removes_escape_sequences() -> None:
    assert strip_ansi('\x1b[31mGoal active\x1b[0m') == 'Goal active'


def test_default_repl_command_uses_current_python_module() -> None:
    command = default_repl_command()

    assert command[:3] == [sys.executable, '-m', 'clawcodex_ext.cli.main']
    assert '--legacy-repl' in command
    assert '--stream' in command
    assert '--agent-debug' in command


def test_session_start_send_observe_stop(tmp_path: Path) -> None:
    session = ReplPtySession(command=fake_command(), artifact_dir=tmp_path, timeout=5.0)

    ready = session.start()
    assert ready.ok is True
    assert ready.event == 'ready'
    assert ready.kind == 'ready'
    assert ready.state == 'ready'
    assert 'CLAWCODEX_AGENT_DEBUG::repl.ready::' in ready.delta

    observed = session.send('/goal verify', expect='Goal set:')
    assert observed.ok is True
    assert observed.event == 'observed'
    assert observed.kind == 'slash_command'
    assert observed.state == 'idle'
    assert 'input_echo' in observed.signals
    assert 'Goal set: verify' in observed.delta
    assert 'Goal set: verify' in observed.screen

    observed = session.send('/goal', expect='Tokens:')
    assert observed.ok is True
    assert 'Tokens: 82' in observed.delta

    stopped = session.stop()
    assert stopped.ok is True
    assert stopped.event == 'stopped'


def test_session_expect_matches_token_split_by_terminal_noise(tmp_path: Path) -> None:
    session = ReplPtySession(command=fake_command(), artifact_dir=tmp_path, timeout=5.0)
    session.start()

    observed = session.send('interleaved-token', expect='GOAL-PTY-OK')

    assert observed.ok is True
    assert 'GOAL-PTY' in observed.delta
    assert '-OK' in observed.delta
    session.stop()


def test_completed_assistant_output_with_spinner_redraw_returns_idle(tmp_path: Path) -> None:
    session = ReplPtySession(command=fake_command(), artifact_dir=tmp_path, timeout=5.0)
    session.start()

    observed = session.send('interleaved-token-with-prompt', expect='PTY-SMOKE-OK')

    assert observed.ok is True
    assert observed.kind == 'assistant_output'
    assert observed.state == 'idle'
    assert 'streaming' in observed.signals
    assert 'prompt' in observed.signals
    session.stop()


def test_session_classifies_assistant_and_error_output(tmp_path: Path) -> None:
    session = ReplPtySession(command=fake_command(), artifact_dir=tmp_path, timeout=5.0)
    session.start()

    assistant = session.send('hello', expect='echo:hello')
    assert assistant.ok is True
    assert assistant.kind == 'assistant_output'
    assert assistant.state == 'idle'
    assert 'assistant_output' in assistant.signals

    provider_error = session.send('provider-error', timeout=0.5)
    assert provider_error.ok is False
    assert provider_error.event == 'error'
    assert provider_error.kind == 'provider_error'
    assert provider_error.state == 'error'
    assert provider_error.error_kind == 'provider_error'
    assert 'ProviderError: invalid_api_key' in (provider_error.error or '')

    network_error = session.send('network-error', timeout=0.5)
    assert network_error.ok is False
    assert network_error.event == 'error'
    assert network_error.kind == 'network_error'
    assert network_error.state == 'error'
    assert network_error.error_kind == 'network_error'
    assert 'DNS lookup failed' in (network_error.error or '')

    rendered_network_error = session.send('rendered-connection-error', timeout=0.5)
    assert rendered_network_error.ok is False
    assert rendered_network_error.event == 'error'
    assert rendered_network_error.kind == 'network_error'
    assert rendered_network_error.state == 'error'
    assert rendered_network_error.error_kind == 'network_error'
    assert 'Connection error.' in (rendered_network_error.error or '')

    session.stop()


def test_session_classifies_permission_prompt(tmp_path: Path) -> None:
    session = ReplPtySession(command=fake_command(), artifact_dir=tmp_path, timeout=5.0)
    session.start()

    permission = session.send('permission-prompt', timeout=0.5)

    assert permission.ok is True
    assert permission.event == 'observed'
    assert permission.kind == 'permission_prompt'
    assert permission.state == 'awaiting_permission'
    assert permission.error_kind is None
    assert 'permission_prompt' in permission.signals
    session.stop()


def test_session_does_not_keep_resolved_permission_prompt_active(tmp_path: Path) -> None:
    session = ReplPtySession(command=fake_command(), artifact_dir=tmp_path, timeout=5.0)
    session.start()

    resolved = session.send('permission-resolved', timeout=0.5)

    assert resolved.ok is True
    assert resolved.event == 'observed'
    assert resolved.kind == 'assistant_output'
    assert resolved.state == 'idle'
    assert resolved.error_kind is None
    assert 'permission_prompt' not in resolved.signals
    session.stop()


def test_session_expect_ignores_initial_terminal_echo(tmp_path: Path) -> None:
    session = ReplPtySession(command=fake_command(), artifact_dir=tmp_path, timeout=5.0)
    session.start()

    observed = session.send(
        'silent ECHO-ONLY-MATCH',
        expect='ECHO-ONLY-MATCH',
        timeout=0.2,
    )

    assert observed.ok is False
    assert observed.event == 'error'
    assert 'silent ECHO-ONLY-MATCH' in observed.delta
    session.stop()


def test_session_expect_does_not_match_loose_subsequence(tmp_path: Path) -> None:
    session = ReplPtySession(command=fake_command(), artifact_dir=tmp_path, timeout=5.0)
    session.start()

    observed = session.send('token-status', expect='Tokens used:', timeout=0.3)

    assert observed.ok is False
    assert 'Tokens: 0' in observed.delta
    session.stop()


def test_send_without_expect_waits_for_output_after_terminal_echo(tmp_path: Path) -> None:
    session = ReplPtySession(command=fake_command(), artifact_dir=tmp_path, timeout=5.0)
    session.start()

    observed = session.send('delayed-output', timeout=1.5)

    assert observed.ok is True
    assert 'delayed-output' in observed.delta
    assert 'late-output' in observed.delta
    session.stop()


def test_write_artifacts_writes_raw_clean_and_result(tmp_path: Path) -> None:
    result = write_artifacts(
        artifact_dir=tmp_path,
        raw_text='\x1b[32mGoal active\x1b[0m',
        command=['fake'],
        events=[{'event': 'observed', 'kind': 'slash_command', 'ok': True}],
        ok=True,
        error=None,
    )

    assert result.raw_log.read_text() == '\x1b[32mGoal active\x1b[0m'
    assert result.clean_transcript.read_text() == 'Goal active'
    payload = json.loads(result.result_json.read_text())
    assert payload['ok'] is True
    assert payload['command'] == ['fake']
    assert payload['events'][0]['kind'] == 'slash_command'


def test_build_goal_script_is_a_regression_scenario() -> None:
    assert build_goal_script(
        goal='verify',
        prompt='hello',
        expect_response='echo:hello',
    ) == [
        Step(label='start goal', send='/goal verify', expect='Goal set:'),
        Step(label='send prompt', send='hello', expect='echo:hello'),
        Step(label='inspect goal', send='/goal', expect='Tokens:'),
        Step(label='clear goal', send='/goal clear', expect='Goal cleared'),
        Step(label='exit', send='/exit', expect='Goodbye!'),
    ]


def test_run_script_executes_goal_steps(tmp_path: Path) -> None:
    result = run_script(
        command=fake_command(),
        steps=build_goal_script(
            goal='verify',
            prompt='hello',
            expect_response='echo:hello',
        ),
        artifact_dir=tmp_path,
        timeout=5.0,
    )

    assert result.ok is True
    assert 'Tokens: 82' in result.clean_transcript.read_text()
    payload = json.loads(result.result_json.read_text())
    kinds = [event['kind'] for event in payload['events']]
    assert 'slash_command' in kinds
    assert 'assistant_output' in kinds


def test_run_interactive_jsonl_supports_dynamic_turns(tmp_path: Path) -> None:
    stdin = io.StringIO(
        '\n'.join(
            [
                json.dumps({'op': 'start', 'cmd': fake_command()}),
                json.dumps({'op': 'send', 'text': '/goal verify', 'expect': 'Goal set:'}),
                json.dumps({'op': 'send', 'text': 'hello', 'expect': 'echo:hello'}),
                json.dumps({'op': 'observe', 'timeout': 0.1}),
                json.dumps({'op': 'stop'}),
            ]
        )
        + '\n'
    )
    stdout = io.StringIO()

    rc = run_interactive_jsonl(
        stdin=stdin,
        stdout=stdout,
        artifact_dir=tmp_path,
        timeout=5.0,
    )

    assert rc == 0
    lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert lines[0]['event'] == 'ready'
    assert lines[1]['ok'] is True
    assert 'Goal set: verify' in lines[1]['delta']
    assert 'echo:hello' in lines[2]['delta']
    assert lines[-1]['event'] == 'stopped'


def test_run_interactive_jsonl_exit_ends_controller_after_stop(tmp_path: Path) -> None:
    stdin = io.StringIO(
        '\n'.join(
            [
                json.dumps({'op': 'start', 'cmd': fake_command()}),
                json.dumps({'op': 'stop'}),
                json.dumps({'op': 'exit'}),
                json.dumps({'op': 'start', 'cmd': fake_command()}),
            ]
        )
        + '\n'
    )
    stdout = io.StringIO()

    rc = run_interactive_jsonl(
        stdin=stdin,
        stdout=stdout,
        artifact_dir=tmp_path,
        timeout=5.0,
    )

    assert rc == 0
    lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [line['event'] for line in lines] == ['ready', 'stopped', 'controller_exit']


def test_docs_use_current_goal_expectations() -> None:
    root = Path(__file__).resolve().parents[2]
    paths = [
        root / 'tests/skills/clawcodex-repl-pty-debug/SKILL.md',
        root / 'docs/guide/agent-pty-debugging.md',
    ]
    docs = [path.read_text() for path in paths if path.exists()]

    assert docs
    for content in docs:
        assert '"expect":"Available Commands:"' in content
        assert '"expect":"Available tools:"' in content
        assert '"expect":"No goal is currently set."' in content
        assert 'Total units:' in content
        assert 'CLAW_HEADLESS_BACKEND=stub' in content
        assert 'CLAWCODEX_HOME' in content
        assert 'fake_repl_child.py' in content
        assert 'provider_error' in content
        assert 'network_error' in content
        assert 'Reply with exactly' not in content
        assert 'Tokens used:' in content
