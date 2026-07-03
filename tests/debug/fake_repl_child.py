from __future__ import annotations

import json
import time


def main() -> int:
    print(
        'CLAWCODEX_AGENT_DEBUG::repl.ready::'
        + json.dumps({'session_id': 'fake-session', 'surface': 'repl', 'stream': True}),
        flush=True,
    )
    while True:
        try:
            line = input('> ')
        except EOFError:
            print('Goodbye!', flush=True)
            return 0

        if line == '/exit':
            print('Goodbye!', flush=True)
            return 0
        if line.startswith('/goal clear'):
            print('Goal cleared', flush=True)
            continue
        if line.startswith('/goal '):
            print(f'Goal set: {line.removeprefix("/goal ")}', flush=True)
            continue
        if line == '/goal':
            print('Status: active\nTokens: 82/inf', flush=True)
            continue
        if line == 'token-status':
            print('Tokens: 0/inf\nTurns executed: 1', flush=True)
            continue
        if line == 'interleaved-token':
            print('GOAL-PTY', flush=True)
            print('Thinking status redraw', flush=True)
            print('❯', flush=True)
            print('-OK', flush=True)
            continue
        if line == 'interleaved-token-with-prompt':
            print('Assistant', flush=True)
            print('PTY-S', flush=True)
            print(
                '⠋ Thinking…  (esc to interrupt · ctrl+b background · enter to queue)', flush=True
            )
            print('❯', flush=True)
            print('MOKE-OK', flush=True)
            print('❯', flush=True)
            continue
        if line == 'delayed-output':
            time.sleep(0.4)
            print('late-output', flush=True)
            continue
        if line == 'provider-error':
            print('ProviderError: invalid_api_key from fake provider', flush=True)
            continue
        if line == 'network-error':
            print('NetworkError: DNS lookup failed for fake provider', flush=True)
            continue
        if line == 'rendered-connection-error':
            print('Assistant', flush=True)
            print('Query error: Connection error.', flush=True)
            print('Connection error.', flush=True)
            continue
        if line == 'permission-prompt':
            print(
                'Permission Required\n\n'
                '  ▸   1. [y] Yes, allow this action\n'
                '      2. [n] No, deny this action\n\n'
                '  ↑↓ navigate · Enter select · 1-9 quick select · Esc cancel\n'
                '⚠ Permission Required\n'
                '  Claude wants to use Bash. Allow?',
                flush=True,
            )
            continue
        if line == 'permission-resolved':
            print(
                'Permission Required\n\n'
                '  ▸   1. [y] Yes, allow this action\n'
                '      2. [n] No, deny this action\n\n'
                '  ↑↓ navigate · Enter select · 1-9 quick select · Esc cancel\n\n'
                'Tool result:\n'
                '{"stdout": "SC5-PERMISSION-OK"}\n\n'
                '❯ ',
                flush=True,
            )
            continue
        if line.startswith('silent '):
            time.sleep(0.4)
            continue
        if 'goal pty ok' in line.lower():
            print('GOAL-PTY-OK', flush=True)
            continue
        print(f'echo:{line}', flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
