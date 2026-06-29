"""Tests for gateway config load/save (atomic, ChannelConfig roundtrip)."""

from __future__ import annotations

from clawcodex_ext.services.channels.models import ChannelConfig, ChannelType
from clawcodex_ext.services.im_gateway.config import (
    GatewayConfig,
    ReliabilityConfig,
    load_config,
    save_config,
)


def _cfg() -> GatewayConfig:
    return GatewayConfig(
        enabled=True,
        default_targets=['wechat-main'],
        state_dir='~/.clawcodex/im-gateway',
        reliability=ReliabilityConfig(),
        channels=[
            ChannelConfig(
                type=ChannelType.WECHAT,
                webhook_url='https://ilinkai.weixin.qq.com/dummy',
                name='wechat-main',
                enabled=True,
                extra={'account_id': 'default', 'base_url': 'https://ilinkai.weixin.qq.com'},
            ),
            ChannelConfig(
                type=ChannelType.SLACK,
                webhook_url='https://hooks.example.com/services/T/B/abcdef0123456789',
                name='slack-ops',
                enabled=False,
            ),
        ],
    )


def test_config_roundtrip(tmp_path) -> None:
    p = tmp_path / 'channels.yaml'
    save_config(_cfg(), p)
    loaded = load_config(p)
    assert loaded.enabled is True
    assert loaded.default_targets == ['wechat']
    assert len(loaded.channels) == 2
    wechat = loaded.get_channel('wechat')
    assert wechat is not None
    assert wechat.type is ChannelType.WECHAT
    assert wechat.extra['account_id'] == 'default'
    slack = loaded.get_channel('slack-ops')
    assert slack is not None
    assert slack.enabled is False


def test_load_config_normalizes_legacy_wechat_name_to_single_instance(tmp_path) -> None:
    p = tmp_path / 'channels.yaml'
    p.write_text(
        """
default_targets:
  - wechat-main
channels:
  - type: wechat
    webhook_url: https://ilinkai.weixin.qq.com/dummy
    name: wechat-main
    enabled: true
    extra:
      account_id: default
      base_url: https://ilinkai.weixin.qq.com
""",
        encoding='utf-8',
    )

    loaded = load_config(p)

    assert loaded.default_targets == ['wechat']
    assert loaded.get_channel('wechat') is not None
    assert loaded.get_channel('wechat-main') is None


def test_config_channel_replace_and_remove(tmp_path) -> None:
    cfg = _cfg()
    new = ChannelConfig(
        type=ChannelType.WECHAT,
        webhook_url='https://ilinkai.weixin.qq.com/dummy',
        name='wechat-main',
        enabled=False,
    )
    cfg.replace_channel(new)
    assert cfg.get_channel('wechat').enabled is False
    assert cfg.remove_channel('slack-ops') is True
    assert cfg.get_channel('slack-ops') is None
    assert cfg.remove_channel('nope') is False


def test_config_replace_channel_keeps_one_entry_per_type() -> None:
    cfg = _cfg()
    replacement = ChannelConfig(
        type=ChannelType.SLACK,
        webhook_url='https://hooks.example.com/services/T/B/newabcdef012345',
        name='slack-alerts',
        enabled=True,
    )
    cfg.replace_channel(replacement)

    assert cfg.get_channel('slack-ops') is None
    assert cfg.get_channel('slack-alerts') == replacement
    assert [c.type for c in cfg.channels].count(ChannelType.SLACK) == 1


def test_replace_channel_by_type_updates_default_targets_when_name_changes() -> None:
    cfg = _cfg()
    cfg.default_targets = ['slack-ops', 'wechat-main']
    replacement = ChannelConfig(
        type=ChannelType.SLACK,
        webhook_url='https://hooks.example.com/services/T/B/newabcdef012345',
        name='slack-alerts',
        enabled=True,
    )

    cfg.replace_channel(replacement)

    assert cfg.default_targets == ['slack-alerts', 'wechat']


def test_load_config_collapses_duplicate_channel_types(tmp_path) -> None:
    p = tmp_path / 'channels.yaml'
    p.write_text(
        """
channels:
  - type: slack
    webhook_url: https://hooks.example.com/services/T/B/oldabcdef012345
    name: slack-old
    enabled: true
    extra: null
  - type: slack
    webhook_url: https://hooks.example.com/services/T/B/newabcdef012345
    name: slack-new
    enabled: false
    extra: null
""",
        encoding='utf-8',
    )

    loaded = load_config(p)

    assert loaded.get_channel('slack-old') is None
    assert loaded.get_channel('slack-new') is not None
    assert len(loaded.channels) == 1


def test_save_config_collapses_duplicate_channel_types(tmp_path) -> None:
    p = tmp_path / 'channels.yaml'
    cfg = GatewayConfig(
        channels=[
            ChannelConfig(
                type=ChannelType.SLACK,
                webhook_url='https://hooks.example.com/services/T/B/oldabcdef012345',
                name='slack-old',
                enabled=True,
            ),
            ChannelConfig(
                type=ChannelType.SLACK,
                webhook_url='https://hooks.example.com/services/T/B/newabcdef012345',
                name='slack-new',
                enabled=False,
            ),
        ],
    )

    save_config(cfg, p)

    raw = p.read_text(encoding='utf-8')
    assert 'slack-old' not in raw
    assert raw.count('type: slack') == 1
    loaded = load_config(p)
    assert loaded.get_channel('slack-old') is None
    assert loaded.get_channel('slack-new') is not None
    assert len(loaded.channels) == 1


def test_config_atomic_save_uses_replace(tmp_path) -> None:
    p = tmp_path / 'channels.yaml'
    save_config(_cfg(), p)
    # no .tmp left behind
    assert not (tmp_path / 'channels.yaml.tmp').exists()
    assert p.exists()


def test_channel_config_to_dict_roundtrip_preserves_extra() -> None:
    c = ChannelConfig(
        type=ChannelType.WECHAT,
        webhook_url='https://x.example.com/dummy',
        name='w1',
        extra={'allowed_users': ['u1', 'u2'], 'max_consecutive_failures': 10},
    )
    d = c.to_dict()
    back = ChannelConfig.from_dict(d)
    assert back == c
    assert back.extra == {'allowed_users': ['u1', 'u2'], 'max_consecutive_failures': 10}


def test_load_config_missing_file_returns_default(tmp_path) -> None:
    cfg = load_config(tmp_path / 'nope.yaml')
    assert cfg.enabled is True
    assert cfg.channels == []
