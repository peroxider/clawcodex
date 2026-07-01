"""IM channel configuration helpers invoked via ``clawcodex-dev gateway``.

These functions are called from ``gateway_cmd.commands.run_gateway_command``
using the flattened verb surface::

  clawcodex-dev gateway setup                  Guided wizard (interactive menu)
  clawcodex-dev gateway status [name]          Show channel health/status
  clawcodex-dev gateway disconnect <name>      Remove REPL/orchestrator connection
  clawcodex-dev gateway restart <name>         Rebuild a channel adapter
  clawcodex-dev gateway login <name>           WeChat iLink QR login

The wizard reads/writes ``~/.clawcodex/gateway/channels.yaml``
atomically (single-writer lock + tmp+replace). WeChat-specific QR
login / login-state operations are wired through the same gateway state.

Editable fields are driven by a per-type map in P1; P2/P5 refine this
to be descriptor-driven from ``ChannelCapabilityDescriptor``.
"""

from __future__ import annotations

import sys
from typing import Any, Callable

from clawcodex_ext.services.channels.models import ChannelConfig, ChannelType
from clawcodex_ext.services.im_gateway.config import load_config, save_config

InputFn = Callable[[str], str]

_USAGE = (
    'usage: clawcodex-dev gateway {setup|status|disconnect|restart|login} [name]\n\n'
    '  setup            Guided configuration wizard.\n'
    '  status [name]    Show channel status (all if name omitted).\n'
    '  disconnect <name> Remove the active REPL/orchestrator connection.\n'
    '  restart <name>   Rebuild a channel adapter and reload its config.\n'
    '  login <name>     WeChat iLink QR login.\n'
)

# Per-type editable fields. Webhook types share webhook_url; WeChat stores
# platform fields in ChannelConfig.extra. P2 refines WeChat fields + login.
_FIELD_MAP: dict[str, list[tuple[str, str, Any]]] = {
    'feishu': [('webhook_url', 'webhook URL', ''), ('enabled', 'enabled (true/false)', True)],
    'slack': [('webhook_url', 'webhook URL', ''), ('enabled', 'enabled (true/false)', True)],
    'discord': [('webhook_url', 'webhook URL', ''), ('enabled', 'enabled (true/false)', True)],
    'wechat': [
        ('base_url', 'iLink base URL', 'https://ilinkai.weixin.qq.com'),
        ('account_id', 'account id', 'default'),
        ('enabled', 'enabled (true/false)', True),
    ],
}

_DEFAULT_CHANNEL_NAMES = {
    'discord': 'discord-main',
    'feishu': 'feishu-main',
    'slack': 'slack-main',
    'wechat': 'wechat',
}


# -- pure config ops (testable) -----------------------------------------


def list_channels(path: str | None = None) -> list[dict[str, Any]]:
    cfg = load_config(path)
    return [{'name': c.name, 'type': c.type.value, 'enabled': c.enabled} for c in cfg.channels]


def add_channel(path: str | None, channel: ChannelConfig) -> None:
    cfg = load_config(path)
    cfg.replace_channel(channel)
    save_config(cfg, path)


def update_channel(path: str | None, channel: ChannelConfig) -> bool:
    cfg = load_config(path)
    if cfg.get_channel(channel.name) is None and cfg.get_channel_by_type(channel.type) is None:
        return False
    cfg.replace_channel(channel)
    save_config(cfg, path)
    return True


def remove_channel(path: str | None, name: str) -> bool:
    cfg = load_config(path)
    if not cfg.remove_channel(name):
        return False
    save_config(cfg, path)
    return True


def _coerce(value: str, default: Any) -> Any:
    if isinstance(default, bool):
        return value.strip().lower() in ('1', 'true', 'yes', 'y', 'on')
    if isinstance(default, int):
        try:
            return int(value)
        except ValueError:
            return default
    return value


def build_channel_from_inputs(ctype: str, name: str, inputs: dict[str, str]) -> ChannelConfig:
    """Build a ChannelConfig from wizard inputs for the given type."""
    fields = _FIELD_MAP.get(ctype, [])
    enabled = True
    webhook_url = 'https://placeholder.invalid/'
    extra: dict[str, Any] = {}
    for field_name, _label, default in fields:
        raw = inputs.get(field_name, '')
        value = _coerce(raw if raw != '' else str(default), default)
        if field_name == 'webhook_url':
            webhook_url = str(value) if value else 'https://placeholder.invalid/'
        elif field_name == 'enabled':
            enabled = bool(value)
        else:
            extra[field_name] = value
    return ChannelConfig(
        type=ChannelType(ctype),
        webhook_url=webhook_url,
        name=name,
        enabled=enabled,
        extra=extra or None,
    )


def build_default_channel(ctype: str) -> ChannelConfig:
    """Build the lowest-friction default config for a channel type."""
    name = _DEFAULT_CHANNEL_NAMES.get(ctype, f'{ctype}-main')
    if ctype == 'wechat':
        return ChannelConfig(
            type=ChannelType.WECHAT,
            webhook_url='https://ilinkai.weixin.qq.com/dummy',
            name=name,
            enabled=True,
            extra={
                'base_url': 'https://ilinkai.weixin.qq.com',
                'account_id': 'default',
            },
        )
    return build_channel_from_inputs(ctype, name, {})


# -- status / restart ---------------------------------------------------


def format_status(
    path: str | None = None, name: str | None = None, *, state_dir: str | None = None
) -> str:
    cfg = load_config(path)
    lines: list[str] = []
    channels = [c for c in cfg.channels if name is None or c.name == name]
    if not channels:
        return f'no channels configured{f" matching {name!r}" if name else ""}'
    resolved_state_dir = _resolve_status_state_dir(path, state_dir)
    runtime_status = _read_gateway_runtime_status(resolved_state_dir)
    for c in channels:
        dot = '●' if c.enabled else '○'
        lines.append(f'{dot} {c.name} [{c.type.value}] enabled={c.enabled}')
        if c.type is ChannelType.WECHAT:
            lines.append(f'  login: {wechat_login_status(c.name, state_dir=resolved_state_dir)}')
            lines.append(f'  {_format_wechat_conversation(runtime_status)}')
    return '\n'.join(lines)


def _resolve_status_state_dir(path: str | None, state_dir: str | None) -> str | None:
    if state_dir is not None:
        return state_dir
    if path is None:
        return None
    from pathlib import Path

    return str(Path(path).expanduser().parent)


def _read_gateway_runtime_status(state_dir: str | None = None) -> dict[str, Any]:
    import asyncio

    from extensions.im_gateway.server import DaemonPaths, GatewayDaemon

    paths = DaemonPaths.for_state_dir(state_dir)
    daemon = GatewayDaemon(paths)
    if not _daemon_alive(daemon):
        return {'gateway_running': False}

    async def _status() -> dict[str, Any]:
        from clawcodex_ext.services.im_gateway.ipc_client import GatewayIpcClient

        async with GatewayIpcClient(paths.sock_file) as client:
            return await client.status() or {}

    try:
        data = asyncio.run(_status())
    except (ConnectionError, FileNotFoundError, OSError, RuntimeError) as exc:
        return {'gateway_running': True, 'gateway_error': str(exc)}
    data['gateway_running'] = True
    return data


def _format_wechat_conversation(runtime_status: dict[str, Any]) -> str:
    if runtime_status.get('gateway_error'):
        return f'conversation: unknown (gateway error: {runtime_status["gateway_error"]})'
    bindings = [
        b
        for b in runtime_status.get('bindings', [])
        if str(b.get('origin', '')).startswith('wechat:direct:')
    ]
    if not bindings:
        return 'conversation: disconnected'
    binding = bindings[0]
    session_id = str(binding.get('session_id') or '')
    peers = {
        str(p.get('session_id') or ''): p
        for p in runtime_status.get('peers', [])
        if p.get('session_id')
    }
    peer = peers.get(session_id, {})
    host_type = str(binding.get('host_type') or peer.get('host_type') or 'unknown')
    connection_state = str(binding.get('connection_state') or 'unknown')
    online = bool(peer.get('online', connection_state == 'active'))
    if connection_state != 'active' or not online:
        state = 'offline' if not online else connection_state
        return f'conversation: disconnected (last {host_type}, session={session_id}, state={state})'
    state = 'online' if online and connection_state == 'active' else connection_state
    return f'conversation: connected to {host_type} (session={session_id}, state={state})'


def _disconnect_gateway_connection(name: str, *, state_dir: str | None = None) -> int:
    import asyncio

    from clawcodex_ext.services.im_gateway.ipc_client import GatewayIpcClient
    from clawcodex_ext.services.im_gateway.models import WECHAT_DIRECT_ALL_ORIGIN
    from extensions.im_gateway.server import DaemonPaths, GatewayDaemon

    try:
        channel = _require_wechat_channel(name, state_dir=state_dir)
    except ValueError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    if channel.type is not ChannelType.WECHAT:
        print(
            f'error: disconnect is only supported for wechat channels, got {name!r}',
            file=sys.stderr,
        )
        return 2
    paths = DaemonPaths.for_state_dir(state_dir)
    daemon = GatewayDaemon(paths)
    if not _daemon_alive(daemon):
        print(f'{name}: conversation already disconnected (gateway daemon not running).')
        return 0

    async def _unbind() -> int:
        try:
            async with GatewayIpcClient(paths.sock_file) as client:
                resp = await client.unbind_origin(WECHAT_DIRECT_ALL_ORIGIN)
        except (ConnectionError, FileNotFoundError, OSError) as exc:
            print(f'error: could not reach gateway daemon: {exc}', file=sys.stderr)
            return 1
        if resp is not None and resp.ack_layer == 'accepted':
            print(f'{name}: conversation connection removed.')
            return 0
        print(
            f'error: disconnect failed ({resp.reason if resp else "no response"})', file=sys.stderr
        )
        return 1

    return asyncio.run(_unbind())


def restart_channel(name: str, *, state_dir: str | None = None) -> int:
    """Rebuild a channel adapter live via the running daemon (P4).

    If the daemon is running, send a ``control.reload`` IPC frame so the
    adapter is rebuilt in-process (即时生效). Otherwise validate config and
    advise starting the daemon.
    """
    import asyncio

    from extensions.im_gateway.server import DaemonPaths, GatewayDaemon

    paths = DaemonPaths.for_state_dir(state_dir)
    cfg = load_config(paths.state_dir / 'channels.yaml' if state_dir else None)
    if cfg.get_channel(name) is None:
        print(f'error: no channel named {name!r} in config', file=sys.stderr)
        return 2
    daemon = GatewayDaemon(paths)
    if _daemon_alive(daemon):
        from clawcodex_ext.services.im_gateway.ipc_client import GatewayIpcClient

        async def _reload() -> int:
            try:
                async with GatewayIpcClient(paths.sock_file) as client:
                    resp = await client.reload_channel(name)
            except (ConnectionError, FileNotFoundError, OSError) as exc:
                print(f'error: could not reach gateway daemon: {exc}', file=sys.stderr)
                return 1
            if resp is not None and resp.ack_layer == 'accepted':
                print(
                    f'channel {name!r} reloaded live (gateway daemon PID {read_pid_value(paths)}).'
                )
                return 0
            print(
                f'channel {name!r} reload returned: {resp.ack_layer if resp else "no response"} '
                f'({resp.reason if resp else ""})'
            )
            return 1

        return asyncio.run(_reload())
    print(f'channel {name!r} config validated (gateway daemon not running).')
    print('Start the daemon with `clawcodex-dev gateway start` for live reload.')
    return 0


def read_pid_value(paths) -> int | None:
    from extensions.im_gateway.server import read_pid

    return read_pid(paths)


def _daemon_alive(daemon) -> bool:
    from extensions.im_gateway.server import is_pid_alive, read_pid

    pid = read_pid(daemon.paths)
    return pid is not None and is_pid_alive(pid)


# -- WeChat-specific ops (P2) ------------------------------------------


def _wechat_paths(name: str, *, state_dir: str | None = None):
    from pathlib import Path

    from extensions.im_gateway.server import DaemonPaths

    base = DaemonPaths.for_state_dir(state_dir).state_dir
    wechat_dir = Path(base) / 'wechat'
    wechat_dir.mkdir(parents=True, exist_ok=True)
    auth_path = wechat_dir / f'{name}_auth.json'
    if name == 'wechat' and not auth_path.exists():
        legacy_auth = wechat_dir / 'wechat-main_auth.json'
        if legacy_auth.exists():
            auth_path = legacy_auth
    return auth_path, wechat_dir / f'{name}_pairing.json'


def _wechat_config_path(*, state_dir: str | None = None):
    from extensions.im_gateway.server import DaemonPaths

    return DaemonPaths.for_state_dir(state_dir).state_dir / 'channels.yaml' if state_dir else None


def _require_wechat_channel(name: str, *, state_dir: str | None = None) -> ChannelConfig:
    cfg = load_config(_wechat_config_path(state_dir=state_dir))
    channel = cfg.get_channel(name)
    if channel is None or channel.type is not ChannelType.WECHAT:
        raise ValueError(f'no configured wechat channel named {name!r}')
    return channel


def wechat_login_status(name: str, *, state_dir: str | None = None) -> str:
    from clawcodex_ext.services.channels.wechat_ilink import WeChatIlinkAuthStore

    _require_wechat_channel(name, state_dir=state_dir)
    auth_path, _ = _wechat_paths(name, state_dir=state_dir)
    record = WeChatIlinkAuthStore(auth_path).load()
    if record is None:
        return 'unconfigured (not logged in; run 扫码登录)'
    return f'logged_in (account_id={record.account_id}, user_id={record.user_id})'


def _print_terminal_qr(scan_data: str) -> None:
    """Print a terminal QR when the optional qrcode package is available."""
    import importlib

    try:
        qrcode = importlib.import_module('qrcode')
    except ImportError:
        print('（当前环境未安装 qrcode，已改为显示扫码链接。）')
        return

    try:
        qr = qrcode.QRCode(border=1)
        qr.add_data(scan_data)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except Exception as exc:  # noqa: BLE001
        print(f'（终端二维码渲染失败: {exc}，请直接打开上面的二维码链接。）')


def wechat_login(name: str, *, state_dir: str | None = None) -> int:
    """Perform iLink QR login; persists encrypted bot_token. Async/real endpoint."""
    import asyncio

    from clawcodex_ext.services.channels.transport import UrllibChannelTransport
    from clawcodex_ext.services.channels.wechat_ilink import (
        WeChatIlinkAuthStore,
        WeChatIlinkChannelAdapter,
        _IlinkHttpError,
        _IlinkPlatformError,
    )
    from clawcodex_ext.services.channels.exceptions import TransportError
    from extensions.im_gateway.server import DaemonPaths

    try:
        channel_cfg = _require_wechat_channel(name, state_dir=state_dir)
    except ValueError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    extra = channel_cfg.extra or {}
    auth_path, _ = _wechat_paths(name, state_dir=state_dir)
    adapter = WeChatIlinkChannelAdapter(
        channel_cfg,
        auth_store=WeChatIlinkAuthStore(auth_path),
        store=None,  # type: ignore[arg-type]  # not needed for login
        transport=UrllibChannelTransport(),
        account_id=extra.get('account_id', 'default'),
        base_url=extra.get('base_url', 'https://ilinkai.weixin.qq.com'),
    )

    last_status: str | None = None

    def _show_code(scan_data: str) -> None:
        print('\n请使用微信扫描以下二维码/链接：')
        print(scan_data)
        _print_terminal_qr(scan_data)
        print('等待扫码确认', end='', flush=True)

    def _show_status(status: str) -> None:
        nonlocal last_status
        if status == 'wait':
            print('.', end='', flush=True)
        elif status != last_status:
            if status == 'scaned':
                print('\n已扫码，请在微信里确认。')
            elif status == 'scaned_but_redirect':
                print('\n已扫码，正在切换 iLink 确认节点。')
            elif status == 'expired':
                print('\n二维码已过期，正在刷新。')
            else:
                print(f'\n扫码状态: {status}')
        last_status = status

    async def _do() -> dict:
        return await adapter.qr_login(on_code=_show_code, on_status=_show_status)

    try:
        data = asyncio.run(_do())
    except _IlinkHttpError as exc:
        print(
            f'iLink 登录失败: HTTP {exc.status} (base_url={extra.get("base_url", "https://ilinkai.weixin.qq.com")})',
            file=sys.stderr,
        )
        if exc.status == 404:
            print(
                '提示: 当前 iLink 地址未提供 QR 登录接口；请确认 base_url 可访问 '
                'ilink/bot/get_bot_qrcode 与 ilink/bot/get_qrcode_status。',
                file=sys.stderr,
            )
        return 1
    except _IlinkPlatformError as exc:
        print(f'iLink 登录失败: 平台错误 {exc.code}: {exc.msg}', file=sys.stderr)
        return 1
    except TransportError as exc:
        print(f'iLink 登录失败: 无法连接 iLink 服务: {exc}', file=sys.stderr)
        return 1
    if data.get('bot_token'):
        print(f'\nWeChat 登录成功 (account_id={data.get("account_id", "default")})。')
        # The bot only receives WeChat messages while the gateway daemon is
        # running its getupdates long-poll. restart_channel reloads a running
        # daemon, but if the daemon is DOWN it just prints a hint and returns
        # success — leaving the user "logged in" but with no live connection
        # (the exact "clawcodex OK, WeChat side silent" symptom). Auto-start
        # the daemon here so the poll loop actually begins.
        from extensions.im_gateway.server import GatewayDaemon

        paths = DaemonPaths.for_state_dir(state_dir)
        daemon = GatewayDaemon(paths)
        if _daemon_alive(daemon):
            return restart_channel(name, state_dir=state_dir)
        print('Gateway 守护进程未运行，正在启动以建立微信消息连接……')
        start_rc = daemon.start()
        if start_rc != 0:
            print(
                '警告: Gateway 守护进程启动失败；微信消息将无法接收。\n'
                '  请手动执行 `clawcodex-dev gateway start` 后重试 `gateway restart '
                f'{name}`。',
                file=sys.stderr,
            )
            return start_rc
        print('Gateway 守护进程已启动，微信消息轮询已就绪。\n  在微信里向 bot 发消息即可触发对话。')
        return 0
    if data.get('status') == 'timeout':
        print('\n微信登录超时，请重新执行扫码登录。', file=sys.stderr)
        return 1
    if data.get('status') == 'expired':
        print('\n二维码多次过期，请重新执行扫码登录。', file=sys.stderr)
        return 1
    if data.get('code_url'):
        print(f'\n登录未完成: {data}', file=sys.stderr)
        return 1
    print(f'登录未完成: {data}')
    return 1


# -- wizard -------------------------------------------------------------


def run_wizard(path: str | None = None, *, input_fn: InputFn = input) -> int:
    cfg = load_config(path)
    while True:
        print('\nClawCodex 消息渠道配置')
        print('已配置渠道：')
        channels = list(cfg.channels)
        for idx, c in enumerate(channels, 1):
            dot = '●' if c.enabled else '○'
            print(
                f'  {idx}) {c.name}   [{c.type.value}]   {dot} {"enabled" if c.enabled else "disabled"}'
            )
        print('  +) 新增渠道')
        choice = input_fn('选择要编辑的渠道 / 新增 (输入序号或 +，留空退出): ').strip()
        if choice == '':
            break
        if choice == '+':
            _wizard_add(cfg, path, input_fn)
            continue
        try:
            idx = int(choice) - 1
        except ValueError:
            print('无效输入')
            continue
        if 0 <= idx < len(channels):
            _wizard_edit(cfg, path, channels[idx], input_fn)
        else:
            print('序号超出范围')
    return 0


def _wizard_add(cfg, path, input_fn: InputFn) -> None:
    print('可用渠道类型: ' + ', '.join(sorted(_FIELD_MAP.keys())))
    ctype = input_fn('渠道类型: ').strip().lower()
    if ctype not in _FIELD_MAP:
        print(f'未知类型 {ctype!r}')
        return
    existing = cfg.get_channel_by_type(ctype)
    if existing is not None:
        print(f'{ctype} 渠道已配置为 {existing.name!r}；同一类型只保留一个配置。')
        _wizard_edit(cfg, path, existing, input_fn)
        return
    if ctype == 'wechat':
        _wizard_add_wechat(cfg, path, input_fn)
        return
    default_name = _DEFAULT_CHANNEL_NAMES.get(ctype, f'{ctype}-main')
    name = input_fn(f'渠道名称 [{default_name}]: ').strip() or default_name
    if not name:
        print('名称不能为空')
        return
    inputs: dict[str, str] = {}
    for field_name, label, default in _FIELD_MAP[ctype]:
        inputs[field_name] = input_fn(f'{label} [{default}]: ').strip()
    channel = build_channel_from_inputs(ctype, name, inputs)
    cfg.replace_channel(channel)
    save_config(cfg, path)
    print(f'已保存渠道 {name!r}。执行 `clawcodex-dev gateway restart {name}` 生效。')


def _wizard_add_wechat(cfg, path, input_fn: InputFn) -> None:
    channel = build_default_channel('wechat')
    cfg.replace_channel(channel)
    save_config(cfg, path)
    print(f'已创建 WeChat 渠道 {channel.name!r}。')
    print('接下来进行微信扫码登录；扫码完成后可继续配置授权/启停等选项。')
    wechat_login(channel.name)
    refreshed = cfg.get_channel(channel.name) or channel
    _wizard_edit(cfg, path, refreshed, input_fn)


def _wizard_edit(cfg, path, channel: ChannelConfig, input_fn: InputFn) -> None:
    if channel.type.value == 'wechat':
        _wizard_edit_wechat(cfg, path, channel, input_fn)
        return
    while True:
        print(f'\n编辑 {channel.name} [{channel.type.value}]')
        print('  1) 编辑字段')
        print('  2) 启用 / 停用')
        print('  3) 移除该渠道')
        print('  0) 返回')
        choice = input_fn('选择: ').strip()
        if choice == '0':
            return
        if choice == '1':
            _edit_fields(cfg, path, channel, input_fn)
        elif choice == '2':
            channel = ChannelConfig(
                type=channel.type,
                webhook_url=channel.webhook_url,
                name=channel.name,
                enabled=not channel.enabled,
                extra=channel.extra,
            )
            cfg.replace_channel(channel)
            save_config(cfg, path)
            print(f'{channel.name} → {"enabled" if channel.enabled else "disabled"}')
        elif choice == '3':
            confirm = input_fn(f'确认移除 {channel.name}? (y/N): ').strip().lower()
            if confirm in ('y', 'yes'):
                cfg.remove_channel(channel.name)
                save_config(cfg, path)
                print(f'已移除 {channel.name}')
                return
        else:
            print('无效选择')


def _wizard_edit_wechat(cfg, path, channel: ChannelConfig, input_fn: InputFn) -> None:
    while True:
        print(f'\n编辑 {channel.name} [wechat]')
        print('  1) 扫码登录')
        print('  2) 查看登录态 / conversation 连接')
        print('  3) 移除 REPL/orchestrator 连接')
        print('  4) 启用 / 停用')
        print('  5) 移除该渠道')
        print('  0) 返回')
        choice = input_fn('选择: ').strip()
        if choice == '0':
            return
        if choice == '1':
            wechat_login(channel.name)
        elif choice == '2':
            print(format_status(path, channel.name))
        elif choice == '3':
            _disconnect_gateway_connection(
                channel.name, state_dir=_resolve_status_state_dir(path, None)
            )
        elif choice == '4':
            channel = ChannelConfig(
                type=channel.type,
                webhook_url=channel.webhook_url,
                name=channel.name,
                enabled=not channel.enabled,
                extra=channel.extra,
            )
            cfg.replace_channel(channel)
            save_config(cfg, path)
            print(f'{channel.name} → {"enabled" if channel.enabled else "disabled"}')
        elif choice == '5':
            confirm = input_fn(f'确认移除 {channel.name}? (y/N): ').strip().lower()
            if confirm in ('y', 'yes'):
                cfg.remove_channel(channel.name)
                save_config(cfg, path)
                print(f'已移除 {channel.name}')
                return
        else:
            print('无效选择')


def _edit_fields(cfg, path, channel: ChannelConfig, input_fn: InputFn) -> None:
    fields = _FIELD_MAP.get(channel.type.value, [])
    extra = dict(channel.extra or {})
    webhook_url = channel.webhook_url
    enabled = channel.enabled
    for field_name, label, _default in fields:
        current = (
            extra.get(field_name)
            if field_name in extra
            else (
                webhook_url
                if field_name == 'webhook_url'
                else ('true' if field_name == 'enabled' and enabled else 'false')
            )
        )
        raw = input_fn(f'{label} [{current}] (回车保留): ').strip()
        if raw == '':
            continue
        if field_name == 'webhook_url':
            webhook_url = raw
        elif field_name == 'enabled':
            enabled = raw.lower() in ('1', 'true', 'yes', 'y', 'on')
        else:
            extra[field_name] = raw
    updated = ChannelConfig(
        type=channel.type,
        webhook_url=webhook_url,
        name=channel.name,
        enabled=enabled,
        extra=extra or None,
    )
    cfg.replace_channel(updated)
    save_config(cfg, path)
    print('字段已保存。')


__all__ = [
    'add_channel',
    'build_channel_from_inputs',
    'format_status',
    'list_channels',
    'remove_channel',
    'restart_channel',
    'run_wizard',
    'update_channel',
    'wechat_login',
    'wechat_login_status',
]
