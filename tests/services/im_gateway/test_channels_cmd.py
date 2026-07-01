"""Tests for the `clawcodex-dev channels` CLI command (config ops + wizard)."""

from __future__ import annotations

from clawcodex_ext.cli.channels_cmd import commands as ch
from clawcodex_ext.services.channels.models import ChannelConfig, ChannelType
from clawcodex_ext.services.im_gateway.models import WECHAT_DIRECT_ALL_ORIGIN


def _slack(name: str = 'slack-ops', enabled: bool = False) -> ChannelConfig:
    return ChannelConfig(
        type=ChannelType.SLACK,
        webhook_url='https://hooks.example.com/services/T/B/abcdef0123456789',
        name=name,
        enabled=enabled,
    )


def test_list_channels_empty(tmp_path) -> None:
    p = tmp_path / 'channels.yaml'
    assert ch.list_channels(str(p)) == []


def test_add_list_remove_channel(tmp_path) -> None:
    p = tmp_path / 'channels.yaml'
    ch.add_channel(str(p), _slack('s1', enabled=True))
    listed = ch.list_channels(str(p))
    assert listed == [{'name': 's1', 'type': 'slack', 'enabled': True}]
    assert ch.remove_channel(str(p), 's1') is True
    assert ch.list_channels(str(p)) == []


def test_add_channel_replaces_existing_channel_of_same_type(tmp_path) -> None:
    p = tmp_path / 'channels.yaml'
    ch.add_channel(str(p), _slack('slack-old', enabled=False))
    ch.add_channel(str(p), _slack('slack-new', enabled=True))

    assert ch.list_channels(str(p)) == [{'name': 'slack-new', 'type': 'slack', 'enabled': True}]


def test_update_channel_replaces(tmp_path) -> None:
    p = tmp_path / 'channels.yaml'
    ch.add_channel(str(p), _slack('s1', enabled=True))
    ch.update_channel(str(p), _slack('s1', enabled=False))
    listed = ch.list_channels(str(p))
    assert listed[0]['enabled'] is False
    assert ch.update_channel(str(p), _slack('renamed')) is True
    assert ch.list_channels(str(p)) == [{'name': 'renamed', 'type': 'slack', 'enabled': False}]
    missing_type = ChannelConfig(
        type=ChannelType.DISCORD,
        webhook_url='https://discord.com/api/webhooks/1/token',
        name='discord-main',
    )
    assert ch.update_channel(str(p), missing_type) is False


def test_format_status(tmp_path) -> None:
    p = tmp_path / 'channels.yaml'
    ch.add_channel(str(p), _slack('s1', enabled=True))
    out = ch.format_status(str(p))
    assert 's1' in out and 'enabled' in out
    assert 'no channels' in ch.format_status(str(p), 'nope')


def test_format_status_wechat_includes_login_and_conversation_connection(
    tmp_path,
    monkeypatch,
) -> None:
    p = tmp_path / 'channels.yaml'
    ch.add_channel(str(p), ch.build_default_channel('wechat'))
    monkeypatch.setattr(
        ch,
        'wechat_login_status',
        lambda name, state_dir=None: 'logged_in (account_id=acct, user_id=bot_user)',
    )
    monkeypatch.setattr(
        ch,
        '_read_gateway_runtime_status',
        lambda state_dir=None: {
            'bindings': [
                {
                    'origin': WECHAT_DIRECT_ALL_ORIGIN,
                    'session_id': 'repl-main',
                    'host_type': 'repl',
                    'connection_state': 'active',
                }
            ],
            'peers': [
                {
                    'session_id': 'repl-main',
                    'origin': WECHAT_DIRECT_ALL_ORIGIN,
                    'host_type': 'repl',
                    'online': True,
                }
            ],
            'channel_health': [
                {
                    'channel_id': 'wechat',
                    'healthy': True,
                    'account_status': 'logged_in',
                }
            ],
        },
        raising=False,
    )

    out = ch.format_status(str(p), 'wechat', state_dir=str(tmp_path))

    assert 'login: logged_in' in out
    assert 'conversation: connected to repl' in out
    assert 'session=repl-main' in out


def test_format_status_wechat_reports_disconnected_conversation(tmp_path, monkeypatch) -> None:
    p = tmp_path / 'channels.yaml'
    ch.add_channel(str(p), ch.build_default_channel('wechat'))
    monkeypatch.setattr(ch, 'wechat_login_status', lambda name, state_dir=None: 'unconfigured')
    monkeypatch.setattr(
        ch, '_read_gateway_runtime_status', lambda state_dir=None: {}, raising=False
    )

    out = ch.format_status(str(p), 'wechat', state_dir=str(tmp_path))

    assert 'conversation: disconnected' in out


def test_format_status_wechat_reports_offline_binding_as_disconnected(
    tmp_path, monkeypatch
) -> None:
    p = tmp_path / 'channels.yaml'
    ch.add_channel(str(p), ch.build_default_channel('wechat'))
    monkeypatch.setattr(
        ch,
        'wechat_login_status',
        lambda name, state_dir=None: 'logged_in (account_id=acct, user_id=bot_user)',
    )
    monkeypatch.setattr(
        ch,
        '_read_gateway_runtime_status',
        lambda state_dir=None: {
            'bindings': [
                {
                    'origin': WECHAT_DIRECT_ALL_ORIGIN,
                    'session_id': 'repl-main',
                    'host_type': 'repl',
                    'connection_state': 'offline',
                }
            ],
            'peers': [
                {
                    'session_id': 'repl-main',
                    'origin': WECHAT_DIRECT_ALL_ORIGIN,
                    'host_type': 'repl',
                    'online': False,
                }
            ],
        },
        raising=False,
    )

    out = ch.format_status(str(p), 'wechat', state_dir=str(tmp_path))

    assert 'conversation: disconnected' in out
    assert 'connected to repl' not in out


def test_build_channel_from_inputs_wechat(tmp_path) -> None:
    p = tmp_path / 'channels.yaml'
    channel = ch.build_channel_from_inputs(
        'wechat',
        'wechat',
        {
            'base_url': 'https://ilinkai.weixin.qq.com',
            'account_id': 'default',
            'enabled': 'true',
        },
    )
    assert channel.type is ChannelType.WECHAT
    assert channel.enabled is True
    assert channel.extra['base_url'] == 'https://ilinkai.weixin.qq.com'
    assert 'allowed_users' not in channel.extra
    # round-trip via save/load
    ch.add_channel(str(p), channel)
    loaded = ch.list_channels(str(p))
    assert loaded == [{'name': 'wechat', 'type': 'wechat', 'enabled': True}]


def test_wizard_add_then_edit_then_remove(tmp_path) -> None:
    p = tmp_path / 'channels.yaml'
    # scripted inputs: add a slack channel, then return
    inputs = iter(
        [
            '+',  # choose new
            'slack',  # type
            'slack-ops',  # name
            'https://hooks.example.com/services/T/B/abcdef0123456789',  # webhook_url
            'true',  # enabled
            '',  # exit
        ]
    )
    rc = ch.run_wizard(str(p), input_fn=lambda _prompt: next(inputs))
    assert rc == 0
    listed = ch.list_channels(str(p))
    assert listed == [{'name': 'slack-ops', 'type': 'slack', 'enabled': True}]

    # edit: disable then remove
    inputs2 = iter(
        [
            '1',  # select channel 1
            '2',  # enable/disable toggle
            '0',  # back
            '1',  # select channel 1
            '3',  # remove
            'y',  # confirm
            '',  # exit
        ]
    )
    ch.run_wizard(str(p), input_fn=lambda _prompt: next(inputs2))
    assert ch.list_channels(str(p)) == []


def test_wechat_wizard_creates_default_config_and_runs_scan_before_options(
    tmp_path, monkeypatch, capsys
) -> None:
    p = tmp_path / 'channels.yaml'
    login_calls: list[str] = []

    def _fake_login(name: str, *, state_dir: str | None = None) -> int:
        login_calls.append(name)
        return 0

    monkeypatch.setattr(ch, 'wechat_login', _fake_login)
    inputs = iter(
        [
            '+',  # choose new
            'wechat',  # type only; no manual name/base_url/account_id prompts
            '0',  # leave the post-scan options menu
            '',  # exit wizard
        ]
    )
    prompts: list[str] = []

    def _input(prompt: str) -> str:
        prompts.append(prompt)
        return next(inputs)

    assert ch.run_wizard(str(p), input_fn=_input) == 0

    assert login_calls == ['wechat']
    assert ch.list_channels(str(p)) == [{'name': 'wechat', 'type': 'wechat', 'enabled': True}]
    text = (capsys.readouterr().out + '\n'.join(prompts)).lower()
    assert 'account id' not in text
    assert 'allowed users' not in text
    assert 'base url' not in text
    assert '编辑字段' not in text


def test_existing_wechat_wizard_options_do_not_prompt_for_internal_fields(
    tmp_path, monkeypatch, capsys
) -> None:
    p = tmp_path / 'channels.yaml'
    ch.add_channel(str(p), ch.build_default_channel('wechat'))
    monkeypatch.setattr(ch, 'wechat_login_status', lambda name, state_dir=None: 'logged_in')
    inputs = iter(
        [
            '1',  # select existing wechat
            '2',  # status
            '0',  # back
            '',  # exit
        ]
    )
    prompts: list[str] = []

    def _input(prompt: str) -> str:
        prompts.append(prompt)
        return next(inputs)

    assert ch.run_wizard(str(p), input_fn=_input) == 0

    text = capsys.readouterr().out + '\n'.join(prompts)
    assert '编辑字段' not in text
    assert 'account id' not in text.lower()
    assert 'allowed users' not in text.lower()
    assert 'base url' not in text.lower()
    assert 'logged_in' in text


def test_wechat_login_status_unconfigured(tmp_path) -> None:
    from extensions.im_gateway.server import DaemonPaths

    paths = DaemonPaths.for_state_dir(tmp_path)
    ch.add_channel(str(paths.state_dir / 'channels.yaml'), ch.build_default_channel('wechat'))
    out = ch.wechat_login_status('wechat', state_dir=str(tmp_path))
    assert 'unconfigured' in out


def test_wechat_login_status_reuses_legacy_wechat_main_auth(tmp_path) -> None:
    from extensions.im_gateway.server import DaemonPaths

    from clawcodex_ext.services.channels.wechat_ilink import WeChatAuthRecord, WeChatIlinkAuthStore

    paths = DaemonPaths.for_state_dir(tmp_path)
    ch.add_channel(str(paths.state_dir / 'channels.yaml'), ch.build_default_channel('wechat'))
    legacy_auth = paths.state_dir / 'wechat' / 'wechat-main_auth.json'
    WeChatIlinkAuthStore(legacy_auth).save(
        WeChatAuthRecord(
            bot_token='bot_tok_123',
            account_id='acct',
            base_url='https://ilinkai.weixin.qq.com',
            user_id='bot_user',
        )
    )

    out = ch.wechat_login_status('wechat', state_dir=str(tmp_path))

    assert 'logged_in' in out
    assert 'account_id=acct' in out


def test_wechat_login_reports_ilink_http_error_without_traceback(
    tmp_path, monkeypatch, capsys
) -> None:
    from extensions.im_gateway.server import DaemonPaths

    from clawcodex_ext.services.channels.wechat_ilink import (
        WeChatIlinkChannelAdapter,
        _IlinkHttpError,
    )

    paths = DaemonPaths.for_state_dir(tmp_path)
    ch.add_channel(str(paths.state_dir / 'channels.yaml'), ch.build_default_channel('wechat'))

    async def _raise_404(self, **_kwargs) -> dict:
        raise _IlinkHttpError(404, b'not found')

    monkeypatch.setattr(WeChatIlinkChannelAdapter, 'qr_login', _raise_404)

    rc = ch.wechat_login('wechat', state_dir=str(tmp_path))

    captured = capsys.readouterr()
    assert rc == 1
    assert 'iLink 登录失败' in captured.err
    assert '404' in captured.err
    assert '/getlogincode' not in captured.err


def test_wechat_login_prints_qr_before_waiting_and_reports_success(
    tmp_path, monkeypatch, capsys
) -> None:
    from extensions.im_gateway.server import DaemonPaths

    from clawcodex_ext.services.channels.wechat_ilink import WeChatIlinkChannelAdapter

    paths = DaemonPaths.for_state_dir(tmp_path)
    ch.add_channel(str(paths.state_dir / 'channels.yaml'), ch.build_default_channel('wechat'))
    monkeypatch.setattr(ch, '_print_terminal_qr', lambda scan_data: None)

    async def _fake_qr_login(self, *, on_code=None, on_status=None, **_kwargs) -> dict:
        if on_code is not None:
            on_code('https://ilinkai.weixin.qq.com/qr/abc')
        if on_status is not None:
            on_status('wait')
            on_status('scaned')
        return {
            'status': 'confirmed',
            'code_url': 'https://ilinkai.weixin.qq.com/qr/abc',
            'bot_token': 'bot_tok_123',
            'account_id': 'bot_account_1',
        }

    monkeypatch.setattr(WeChatIlinkChannelAdapter, 'qr_login', _fake_qr_login)
    # daemon is "running" so login takes the live-reload path (no subprocess)
    monkeypatch.setattr(ch, '_daemon_alive', lambda daemon: True)
    monkeypatch.setattr(ch, 'restart_channel', lambda name, state_dir=None: 0)

    rc = ch.wechat_login('wechat', state_dir=str(tmp_path))

    captured = capsys.readouterr()
    assert rc == 0
    assert 'https://ilinkai.weixin.qq.com/qr/abc' in captured.out
    assert '已扫码' in captured.out
    assert 'WeChat 登录成功 (account_id=bot_account_1)' in captured.out


def test_wechat_login_reloads_channel_after_success(tmp_path, monkeypatch, capsys) -> None:
    from extensions.im_gateway.server import DaemonPaths

    from clawcodex_ext.services.channels.wechat_ilink import WeChatIlinkChannelAdapter

    paths = DaemonPaths.for_state_dir(tmp_path)
    ch.add_channel(str(paths.state_dir / 'channels.yaml'), ch.build_default_channel('wechat'))
    monkeypatch.setattr(ch, '_print_terminal_qr', lambda scan_data: None)
    reload_calls: list[tuple[str, str | None]] = []

    async def _fake_qr_login(self, *, on_code=None, on_status=None, **_kwargs) -> dict:
        if on_code is not None:
            on_code('https://ilinkai.weixin.qq.com/qr/abc')
        if on_status is not None:
            on_status('confirmed')
        return {
            'status': 'confirmed',
            'bot_token': 'bot_tok_123',
            'account_id': 'bot_account_1',
        }

    def _fake_restart(name: str, *, state_dir: str | None = None) -> int:
        reload_calls.append((name, state_dir))
        return 0

    monkeypatch.setattr(WeChatIlinkChannelAdapter, 'qr_login', _fake_qr_login)
    monkeypatch.setattr(ch, 'restart_channel', _fake_restart)
    # daemon is "running" so login takes the live-reload path
    monkeypatch.setattr(ch, '_daemon_alive', lambda daemon: True)

    rc = ch.wechat_login('wechat', state_dir=str(tmp_path))

    assert rc == 0
    assert reload_calls == [('wechat', str(tmp_path))]
    assert 'WeChat 登录成功' in capsys.readouterr().out


def test_wechat_login_auto_starts_daemon_when_down(tmp_path, monkeypatch, capsys) -> None:
    """When the daemon is DOWN, login must start it (not silently succeed)."""
    from extensions.im_gateway.server import DaemonPaths

    from clawcodex_ext.services.channels.wechat_ilink import WeChatIlinkChannelAdapter

    paths = DaemonPaths.for_state_dir(tmp_path)
    ch.add_channel(str(paths.state_dir / 'channels.yaml'), ch.build_default_channel('wechat'))
    monkeypatch.setattr(ch, '_print_terminal_qr', lambda scan_data: None)

    async def _fake_qr_login(self, *, on_code=None, on_status=None, **_kwargs) -> dict:
        return {'status': 'confirmed', 'bot_token': 'bot_tok_123', 'account_id': 'bot_account_1'}

    start_calls: list[bool] = []

    class _FakeDaemon:
        def __init__(self, *a, **kw):
            pass

        def start(self):
            start_calls.append(True)
            return 0

    monkeypatch.setattr(WeChatIlinkChannelAdapter, 'qr_login', _fake_qr_login)
    monkeypatch.setattr(ch, '_daemon_alive', lambda daemon: False)
    monkeypatch.setattr('extensions.im_gateway.server.GatewayDaemon', _FakeDaemon)
    # restart_channel must NOT be called when daemon was down
    monkeypatch.setattr(ch, 'restart_channel', lambda *a, **k: 1)

    rc = ch.wechat_login('wechat', state_dir=str(tmp_path))
    assert rc == 0
    assert start_calls == [True]
    assert '守护进程已启动' in capsys.readouterr().out


def test_wechat_login_daemon_start_failure_reports_error(tmp_path, monkeypatch, capsys) -> None:
    """When daemon.start() fails, login must surface the error (not silent success)."""
    from extensions.im_gateway.server import DaemonPaths

    from clawcodex_ext.services.channels.wechat_ilink import WeChatIlinkChannelAdapter

    paths = DaemonPaths.for_state_dir(tmp_path)
    ch.add_channel(str(paths.state_dir / 'channels.yaml'), ch.build_default_channel('wechat'))
    monkeypatch.setattr(ch, '_print_terminal_qr', lambda scan_data: None)

    async def _fake_qr_login(self, *, on_code=None, on_status=None, **_kwargs) -> dict:
        return {'status': 'confirmed', 'bot_token': 'bot_tok_123', 'account_id': 'bot_account_1'}

    class _FakeDaemon:
        def __init__(self, *a, **kw):
            pass

        def start(self):
            return 1  # start failed

    monkeypatch.setattr(WeChatIlinkChannelAdapter, 'qr_login', _fake_qr_login)
    monkeypatch.setattr(ch, '_daemon_alive', lambda daemon: False)
    monkeypatch.setattr('extensions.im_gateway.server.GatewayDaemon', _FakeDaemon)

    rc = ch.wechat_login('wechat', state_dir=str(tmp_path))
    assert rc == 1
    assert '启动失败' in capsys.readouterr().err
