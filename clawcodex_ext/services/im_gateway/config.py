"""Gateway configuration: load/save ``channels.yaml`` atomically.

The YAML file is both the hand-editable file-state base and the CLI
wizard's persistence target — the wizard reads/writes the same file.
Saves are atomic (tmp file + ``os.replace``) under a single-writer
``fcntl`` lock so concurrent processes cannot interleave writes.

Channel entries are stored as :class:`ChannelConfig` objects; WeChat
platform-specific fields (``base_url``, ``account_id``, ``allowed_users``,
…) live in ``ChannelConfig.extra`` so the existing ``to_dict``/``from_dict``
round-trip is reused unchanged.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

from clawcodex_ext.services.channels.models import ChannelConfig, ChannelType

DEFAULT_STATE_DIR = '~/.clawcodex/im-gateway'
DEFAULT_CHANNELS_YAML = '~/.clawcodex/im-gateway/channels.yaml'


@dataclass
class ReliabilityConfig:
    outbox_max_attempts: int = 5
    retry_base_seconds: float = 2.0
    retry_max_seconds: float = 60.0
    inbound_dedupe_ttl_seconds: int = 600
    storm_window_seconds: int = 60
    secret_encryption_env: str = 'CLAWCODEX_IM_SECRET'
    markdown_fallback: bool = True
    long_message_threshold_chunks: int = 4

    def to_dict(self) -> dict[str, Any]:
        return {
            'outbox_max_attempts': self.outbox_max_attempts,
            'retry_base_seconds': self.retry_base_seconds,
            'retry_max_seconds': self.retry_max_seconds,
            'inbound_dedupe_ttl_seconds': self.inbound_dedupe_ttl_seconds,
            'storm_window_seconds': self.storm_window_seconds,
            'secret_encryption_env': self.secret_encryption_env,
            'markdown_fallback': self.markdown_fallback,
            'long_message_threshold_chunks': self.long_message_threshold_chunks,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ReliabilityConfig:
        if not data:
            return cls()
        known = {
            k: v
            for k, v in data.items()
            if k
            in {
                'outbox_max_attempts',
                'retry_base_seconds',
                'retry_max_seconds',
                'inbound_dedupe_ttl_seconds',
                'storm_window_seconds',
                'secret_encryption_env',
                'markdown_fallback',
                'long_message_threshold_chunks',
            }
        }
        return cls(**known)


@dataclass
class GatewayConfig:
    enabled: bool = True
    default_targets: list[str] = field(default_factory=list)
    state_dir: str = DEFAULT_STATE_DIR
    storage_backend: str = 'files'
    reliability: ReliabilityConfig = field(default_factory=ReliabilityConfig)
    channels: list[ChannelConfig] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            'enabled': self.enabled,
            'default_targets': _normalize_default_targets(self.default_targets),
            'state_dir': self.state_dir,
            'storage_backend': self.storage_backend,
            'reliability': self.reliability.to_dict(),
            'channels': [c.to_dict() for c in _unique_channels_by_type(self.channels)],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> GatewayConfig:
        if not data:
            return cls()
        cfg = cls(
            enabled=bool(data.get('enabled', True)),
            default_targets=list(data.get('default_targets') or []),
            state_dir=str(data.get('state_dir', DEFAULT_STATE_DIR)),
            storage_backend=str(data.get('storage_backend', 'files')),
            reliability=ReliabilityConfig.from_dict(data.get('reliability')),
        )
        channels_raw = data.get('channels') or []
        for entry in channels_raw:
            if not isinstance(entry, dict):
                continue
            cfg.replace_channel(ChannelConfig.from_dict(entry))
        cfg.default_targets = _normalize_default_targets(cfg.default_targets)
        return cfg

    def get_channel(self, name: str) -> ChannelConfig | None:
        for c in self.channels:
            if c.name == name:
                return c
        return None

    def get_channel_by_type(self, channel_type: ChannelType | str) -> ChannelConfig | None:
        key = channel_type.value if isinstance(channel_type, ChannelType) else str(channel_type)
        for c in self.channels:
            if c.type.value == key:
                return c
        return None

    def replace_channel(self, channel: ChannelConfig) -> None:
        """Replace an existing channel entry by type, or append.

        IM Message Gateway v1 intentionally keeps one configured channel per
        channel type. Names remain useful for status/restart display, but they
        are not a second axis of multiplicity.
        """
        channel = _normalize_channel(channel)
        self.default_targets = _normalize_default_targets(self.default_targets)
        replaced = False
        next_channels: list[ChannelConfig] = []
        for c in self.channels:
            c = _normalize_channel(c)
            if c.type == channel.type:
                if not replaced:
                    if c.name != channel.name:
                        self.default_targets = [
                            channel.name if target == c.name else target
                            for target in self.default_targets
                        ]
                    next_channels.append(channel)
                    replaced = True
                continue
            next_channels.append(c)
        if not replaced:
            next_channels.append(channel)
        self.channels = next_channels

    def remove_channel(self, name: str) -> bool:
        before = len(self.channels)
        self.channels = [c for c in self.channels if c.name != name]
        return len(self.channels) < before


def _unique_channels_by_type(channels: list[ChannelConfig]) -> list[ChannelConfig]:
    cfg = GatewayConfig()
    for channel in channels:
        cfg.replace_channel(channel)
    return cfg.channels


def _normalize_channel(channel: ChannelConfig) -> ChannelConfig:
    if channel.type is ChannelType.WECHAT and channel.name != 'wechat':
        return replace(channel, name='wechat')
    return channel


def _normalize_default_targets(default_targets: list[str]) -> list[str]:
    return ['wechat' if target == 'wechat-main' else target for target in default_targets]


_LOCK = threading.Lock()


@contextlib.contextmanager
def _file_lock(lock_path: Path):
    """Single-writer advisory lock (POSIX fcntl)."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.touch(exist_ok=True)
    fd = os.open(str(lock_path), os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def load_config(path: str | Path | None = None) -> GatewayConfig:
    """Load :class:`GatewayConfig` from ``path`` (default ``channels.yaml``)."""
    p = Path(path or DEFAULT_CHANNELS_YAML).expanduser()
    if not p.exists():
        return GatewayConfig()
    with _file_lock(_lock_path(p)):
        data = yaml.safe_load(p.read_text(encoding='utf-8')) or {}
    if not isinstance(data, dict):
        raise ValueError(f'{p}: expected a YAML mapping at the top level')
    return GatewayConfig.from_dict(data)


def save_config(config: GatewayConfig, path: str | Path | None = None) -> Path:
    """Atomically save ``config`` to ``path`` under a single-writer lock."""
    p = Path(path or DEFAULT_CHANNELS_YAML).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = yaml.safe_dump(config.to_dict(), allow_unicode=True, sort_keys=False)
    with _file_lock(_lock_path(p)):
        tmp = p.with_suffix(p.suffix + '.tmp')
        tmp.write_text(payload, encoding='utf-8')
        os.replace(tmp, p)
    return p


def _lock_path(yaml_path: Path) -> Path:
    return yaml_path.with_suffix(yaml_path.suffix + '.lock')


__all__ = [
    'DEFAULT_CHANNELS_YAML',
    'DEFAULT_STATE_DIR',
    'GatewayConfig',
    'ReliabilityConfig',
    'load_config',
    'save_config',
]
