"""File-based reliability store.

Persists the gateway's durable state under ``state_dir`` using the
project's existing file-based conventions (small state → JSON, append
logs → NDJSON). Each file has a single-writer lock; JSON state files
are written via tmp + atomic ``os.replace``; NDJSON logs are
append-only. v1 keeps this single-process/single-account; the backend
interface is reserved so SQLite/Postgres can slot in later (P6+).

P1 ships functional basics (dedupe, outbox, dead-letter, session map,
context tokens, audit). P4 adds compaction/rotation, the retry loop,
storm aggregation, and cross-process audit/redaction hardening.
"""

from __future__ import annotations

import json
import os
import threading
import time
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import ReliabilityConfig
from .models import SessionTarget

logger = logging.getLogger(__name__)


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, path)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return default


def _append_ndjson(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + '\n')


def _read_ndjson(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


class ReliabilityStore:
    def __init__(
        self,
        state_dir: str | Path,
        reliability: ReliabilityConfig | None = None,
    ) -> None:
        self._dir = Path(state_dir).expanduser()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._reliability = reliability or ReliabilityConfig()
        self._lock = threading.RLock()
        # in-memory dedupe index: key -> first_seen_ts
        self._dedupe: dict[str, float] = {}
        self._load_dedupe()

    # -- paths -----------------------------------------------------------
    @property
    def state_dir(self) -> Path:
        return self._dir

    def _p(self, name: str) -> Path:
        return self._dir / name

    # -- inbound dedupe --------------------------------------------------
    def _load_dedupe(self) -> None:
        cutoff = time.time() - self._reliability.inbound_dedupe_ttl_seconds
        for entry in _read_ndjson(self._p('processed_inbound.ndjson')):
            key = entry.get('key')
            ts = entry.get('seen_at', 0)
            if key and ts >= cutoff:
                self._dedupe[key] = ts

    def is_duplicate(self, key: str) -> bool:
        with self._lock:
            self._purge_expired()
            return key in self._dedupe

    def record_processed(self, key: str, *, message_id: str | None = None) -> None:
        with self._lock:
            ts = time.time()
            self._dedupe[key] = ts
            _append_ndjson(
                self._p('processed_inbound.ndjson'),
                {'key': key, 'message_id': message_id, 'seen_at': ts},
            )

    def check_and_record(self, key: str, *, message_id: str | None = None) -> bool:
        """Return True if newly seen (and recorded); False if duplicate."""
        with self._lock:
            self._purge_expired()
            if key in self._dedupe:
                logger.debug('im_gateway dedupe hit: key=%s', key[:32])
                return False
            self.record_processed(key, message_id=message_id)
            return True

    def _purge_expired(self) -> None:
        cutoff = time.time() - self._reliability.inbound_dedupe_ttl_seconds
        self._dedupe = {k: v for k, v in self._dedupe.items() if v >= cutoff}

    # -- outbox ----------------------------------------------------------
    def append_outbox(self, entry: dict[str, Any]) -> None:
        with self._lock:
            _append_ndjson(self._p('outbox.ndjson'), entry)

    def outbox_entries(self) -> list[dict[str, Any]]:
        with self._lock:
            return _read_ndjson(self._p('outbox.ndjson'))

    def outbox_pending(self) -> list[dict[str, Any]]:
        """Latest status per idempotency_key where status != delivered."""
        with self._lock:
            latest: dict[str, dict[str, Any]] = {}
            for e in _read_ndjson(self._p('outbox.ndjson')):
                key = e.get('idempotency_key')
                if not key:
                    continue
                latest[key] = e
            terminal = {'delivered', 'dead', 'failed'}
            return [e for e in latest.values() if e.get('status') not in terminal]

    # -- dead letter -----------------------------------------------------
    def append_dead_letter(self, entry: dict[str, Any]) -> None:
        with self._lock:
            _append_ndjson(self._p('dead_letter.ndjson'), entry)
        logger.warning(
            'im_gateway dead-letter appended: channel=%s idem=%s category=%s',
            entry.get('channel'),
            str(entry.get('idempotency_key'))[:16],
            entry.get('error_category'),
        )

    def dead_letter_entries(self) -> list[dict[str, Any]]:
        with self._lock:
            return _read_ndjson(self._p('dead_letter.ndjson'))

    # -- session map -----------------------------------------------------
    def get_session(self, origin: str) -> SessionTarget | None:
        data = _read_json(self._p('im_session_map.json'), {})
        entry = data.get(origin)
        if not entry:
            return None
        return SessionTarget(
            session_id=entry.get('session_id', ''),
            host_type=entry.get('host_type', 'default'),
        )

    def set_session(self, origin: str, target: SessionTarget) -> None:
        with self._lock:
            data = _read_json(self._p('im_session_map.json'), {})
            data[origin] = {
                'session_id': target.session_id,
                'host_type': target.host_type,
                'updated_at': time.time(),
            }
            _atomic_write_json(self._p('im_session_map.json'), data)
        logger.debug(
            'im_gateway session map set: origin=%s session=%s',
            origin[:24],
            target.session_id[:24],
        )

    # -- context tokens --------------------------------------------------
    def get_context_token(self, account_id: str, user_id: str) -> str | None:
        data = _read_json(self._p('wechat_context_tokens.json'), {})
        return data.get(f'{account_id}:{user_id}')

    def set_context_token(self, account_id: str, user_id: str, token: str | None) -> None:
        with self._lock:
            data = _read_json(self._p('wechat_context_tokens.json'), {})
            key = f'{account_id}:{user_id}'
            if token is None:
                data.pop(key, None)
            else:
                data[key] = token
            _atomic_write_json(self._p('wechat_context_tokens.json'), data)

    def wechat_context_users(self, account_id: str) -> list[str]:
        """Return user_ids that have a persisted context token for ``account_id``.

        Used to resolve a wildcard WeChat OUTBOUND origin right after a
        gateway restart, before any new inbound arrives: the context-token
        store already survives restarts (it backs the ``context_reply``
        capability), so it doubles as the durable record of known senders
        without a separate persistence file.
        """
        data = _read_json(self._p('wechat_context_tokens.json'), {})
        prefix = f'{account_id}:'
        return [k[len(prefix) :] for k in data if isinstance(k, str) and k.startswith(prefix)]

    def get_wechat_cursor(self, account_id: str) -> str:
        """Return the saved iLink ``get_updates_buf`` cursor, or ``""``.

        iLink expects the cursor as a string on every ``getupdates`` POST;
        sending JSON ``null`` (the previous default) can cause the server to
        never deliver messages even though the session is valid. The two
        reference clients (hermes-agent, AstrBot) both default to ``""``.
        """
        data = _read_json(self._p('wechat_accounts.json'), {})
        entry = data.get(account_id)
        if not isinstance(entry, dict):
            return ''
        cursor = entry.get('get_updates_buf')
        return str(cursor) if cursor else ''

    def set_wechat_cursor(self, account_id: str, get_updates_buf: str | None) -> None:
        with self._lock:
            data = _read_json(self._p('wechat_accounts.json'), {})
            entry = data.get(account_id)
            if not isinstance(entry, dict):
                entry = {}
            entry['get_updates_buf'] = get_updates_buf
            entry['updated_at'] = time.time()
            data[account_id] = entry
            _atomic_write_json(self._p('wechat_accounts.json'), data)

    # -- unsupported inbound (P2) ----------------------------------------
    def record_unsupported_media(self, entry: dict[str, Any]) -> None:
        with self._lock:
            _append_ndjson(self._p('unsupported_inbound.ndjson'), entry)

    # -- audit -----------------------------------------------------------
    def audit(self, event_type: str, **fields: Any) -> None:
        from .audit import redact

        entry = {
            'timestamp': time.time(),
            'event_type': event_type,
            **redact(fields),
        }
        with self._lock:
            _append_ndjson(self._p('audit.ndjson'), entry)

    def audit_entries(self) -> list[dict[str, Any]]:
        with self._lock:
            return _read_ndjson(self._p('audit.ndjson'))


__all__ = ['ReliabilityStore']
