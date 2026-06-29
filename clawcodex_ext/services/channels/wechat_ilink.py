"""WeChat / Weixin iLink channel adapter (personal WeChat, v1).

Implements the iLink HTTP JSON contract documented by the
``@tencent-weixin/openclaw-weixin`` npm package (v2.4.6 verified):
``getupdates`` long-poll inbound, ``sendmessage`` text outbound,
``context_token`` round-trip, ``get_updates_buf`` cursor persistence.
The Python adapter does NOT embed the TS plugin runtime; it speaks the
documented HTTP JSON protocol directly through an injectable transport.

Capabilities declared on one adapter: ``outbound_text``,
``inbound_polling``, ``context_reply``, ``login_managed``. v1 supports
direct chat only; non-text inbound is classified ``unsupported_media``
(metadata only, no download/decrypt). ``bot_token`` is Fernet-encrypted
at rest. Anti-loop drops the bot's own messages. A consecutive-failure
circuit breaker stops polling on sustained errors; 401/session-expiry
pauses the account without consuming the breaker budget.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import fcntl
import hashlib
import logging
import os
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken

from .capabilities import (
    CapabilityDescriptor,
    ChannelAdapter,
    ChannelCapability,
    ChannelCapabilitySet,
)
from .models import ChannelConfig, ChannelMessage
from .results import (
    ChannelHealth,
    ChannelSendResult,
    CircuitState,
    ErrorCategory,
    SendStatus,
    ValidationResult,
)
from .retry import DEFAULT_RETRY_POLICY, RetryPolicy, classify_exception, classify_http_status
from .transport import (
    DEFAULT_TIMEOUT_SECONDS,
    ChannelTransport,
    TransportError,
    TransportResponse,
    default_headers,
    encode_json_body,
)

logger = logging.getLogger(__name__)

ILINK_CHANNEL_ID = 'openclaw-weixin'
ILINK_APP_ID = 'bot'
ILINK_APP_CLIENT_VERSION = (2 << 16) | (2 << 8) | 0
# ``base_info.channel_version`` carried on every POST. Must match the
# ``ILINK_APP_CLIENT_VERSION`` encoding above (v2.2.0 → 131584).
ILINK_CHANNEL_VERSION = '2.2.0'
# iLink body-level error codes (returned inside an HTTP 200 response, NOT
# via HTTP status). Mirrors hermes-agent ``weixin.py`` / AstrBot
# ``weixin_oc_adapter.py``: -14 == session expired (re-scan required),
# -2 == rate limit (backoff+retry) — except -2 + errmsg "unknown error"
# which is a stale-session signal treated as session-expired.
ILINK_SESSION_EXPIRED_ERRCODE = -14
ILINK_RATE_LIMIT_ERRCODE = -2
_STALE_SESSION_ERRMSG = 'unknown error'
ILINK_QR_BOT_TYPE = '3'
ILINK_QR_TIMEOUT_SECONDS = 480
ILINK_QR_REQUEST_TIMEOUT_SECONDS = 35.0
ILINK_QR_POLL_INTERVAL_SECONDS = 1.0
TEXT_CHUNK_SIZE = 4000
DEFAULT_LONG_POLL_TIMEOUT_MS = 35000
DEFAULT_MAX_CONSECUTIVE_FAILURES = 10
POLL_BACKOFF_SECONDS = 30  # after 3 consecutive failures (per package monitor.ts)
PAIRING_CODE_TTL_SECONDS = 600
EP_GET_UPDATES = '/ilink/bot/getupdates'
EP_SEND_MESSAGE = '/ilink/bot/sendmessage'
EP_GET_BOT_QR = '/ilink/bot/get_bot_qrcode'
EP_GET_QR_STATUS = '/ilink/bot/get_qrcode_status'


# -- auth record + encrypted store --------------------------------------


@dataclass
class WeChatAuthRecord:
    bot_token: str
    account_id: str
    base_url: str
    user_id: str | None = None
    saved_at: float = field(default_factory=time.time)


class WeChatIlinkAuthStore:
    """Fernet-encrypted at-rest store for the WeChat ``bot_token``.

    Key source: ``CLAWCODEX_IM_SECRET`` env (a urlsafe-base64 Fernet key).
    Fallback: a per-install random key written to a ``0o600`` key file with
    a warning that env is preferred. The token is never persisted in plain
    text either way.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        secret_env: str = 'CLAWCODEX_IM_SECRET',
    ) -> None:
        self._path = Path(path)
        self._secret_env = secret_env
        self._key_file = self._path.with_suffix('.key')
        self._lock = threading.Lock()

    def _load_key(self) -> bytes:
        env_val = os.environ.get(self._secret_env)
        if env_val:
            return env_val.encode('utf-8')
        # Fallback: per-install key file (0o600). Generate once, reuse.
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._key_file.exists():
            logger.debug(
                '%s not set; falling back to 0o600 key file at %s. '
                'Set the env var for production deployments.',
                self._secret_env,
                self._key_file,
            )
            key = Fernet.generate_key()
            self._key_file.write_bytes(key)
            os.chmod(self._key_file, 0o600)
        return self._key_file.read_bytes()

    def save(self, record: WeChatAuthRecord) -> None:
        fernet = Fernet(self._load_key())
        blob = fernet.encrypt(record.bot_token.encode('utf-8'))
        payload = {
            'bot_token_enc': blob.decode('utf-8'),
            'account_id': record.account_id,
            'base_url': record.base_url,
            'user_id': record.user_id,
            'saved_at': record.saved_at,
        }
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(self._path.suffix + '.tmp')
            tmp.write_text(_json_dumps(payload), encoding='utf-8')
            os.replace(tmp, self._path)
            os.chmod(self._path, 0o600)

    def load(self) -> WeChatAuthRecord | None:
        with self._lock:
            if not self._path.exists():
                return None
            data = _json_loads(self._path.read_text(encoding='utf-8'))
        enc = data.get('bot_token_enc')
        if not enc:
            return None
        try:
            token = Fernet(self._load_key()).decrypt(enc.encode('utf-8')).decode('utf-8')
        except InvalidToken:
            logger.error('failed to decrypt bot_token (key mismatch?)')
            return None
        return WeChatAuthRecord(
            bot_token=token,
            account_id=data.get('account_id', 'default'),
            base_url=data.get('base_url', ''),
            user_id=data.get('user_id'),
            saved_at=data.get('saved_at', 0.0),
        )

    def clear(self) -> None:
        with self._lock:
            self._path.unlink(missing_ok=True)


# -- pairing -----------------------------------------------------------


@dataclass
class PairingCode:
    code: str
    created_at: float
    consumed_at: float | None = None
    bound_user_id: str | None = None

    @property
    def expired(self) -> bool:
        return (time.time() - self.created_at) > PAIRING_CODE_TTL_SECONDS


class WeChatPairingStore:
    """128-bit one-time pairing codes (10min TTL, constant-time consume)."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else None
        self._lock = threading.Lock()
        self._codes: dict[str, PairingCode] = {}
        self._allowed: set[str] = set()
        if self._path and self._path.exists():
            self._load()

    def generate(self) -> str:
        with self._lock, self._exclusive_file_lock():
            self._reload_unlocked()
            code = secrets.token_urlsafe(16)  # 128 bits
            self._codes[code] = PairingCode(code=code, created_at=time.time())
            self._persist()
        return code

    def consume(self, candidate: str, *, user_id: str) -> bool:
        """Constant-time validate + single-consume bind to ``user_id``."""
        with self._lock, self._exclusive_file_lock():
            self._reload_unlocked()
            matched = None
            for code in self._codes:
                if secrets.compare_digest(code, candidate):
                    matched = code
            if matched is None:
                return False
            entry = self._codes[matched]
            if entry.consumed_at is not None or entry.expired:
                return False
            if user_id in self._allowed:
                return False  # already bound
            entry.consumed_at = time.time()
            entry.bound_user_id = user_id
            self._allowed.add(user_id)
            self._persist()
            return True

    def is_allowed(self, user_id: str) -> bool:
        with self._lock:
            self._reload_unlocked()
            return user_id in self._allowed

    def add_allowed(self, user_id: str) -> None:
        with self._lock, self._exclusive_file_lock():
            self._reload_unlocked()
            self._allowed.add(user_id)
            self._persist()

    @contextlib.contextmanager
    def _exclusive_file_lock(self):
        if not self._path:
            yield
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self._path.with_suffix(self._path.suffix + '.lock')
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _reload_unlocked(self) -> None:
        if self._path and self._path.exists():
            self._load()

    def _persist(self) -> None:
        if not self._path:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            'codes': [
                {
                    'code': c.code,
                    'created_at': c.created_at,
                    'consumed_at': c.consumed_at,
                    'bound_user_id': c.bound_user_id,
                }
                for c in self._codes.values()
            ],
            'allowed': sorted(self._allowed),
        }
        tmp = self._path.with_suffix(self._path.suffix + '.tmp')
        tmp.write_text(_json_dumps(payload), encoding='utf-8')
        os.replace(tmp, self._path)
        os.chmod(self._path, 0o600)

    def _load(self) -> None:
        assert self._path is not None
        data = _json_loads(self._path.read_text(encoding='utf-8'))
        self._codes.clear()
        for c in data.get('codes', []):
            self._codes[c['code']] = PairingCode(
                code=c['code'],
                created_at=c.get('created_at', 0.0),
                consumed_at=c.get('consumed_at'),
                bound_user_id=c.get('bound_user_id'),
            )
        self._allowed = set(data.get('allowed', []))


# -- client -------------------------------------------------------------


def _extract_text_item_list(item_list: Any) -> str | None:
    if not isinstance(item_list, list):
        return None
    for item in item_list:
        if not isinstance(item, dict):
            continue
        item_type = item.get('type')
        if item_type not in (1, '1', 'TEXT', 'text'):
            continue
        text_item = item.get('text_item') or {}
        if isinstance(text_item, dict):
            text = text_item.get('text')
            if text:
                return str(text)
    return None


def _message_type_from_item_list(item_list: Any) -> str:
    if not isinstance(item_list, list):
        return 'TEXT'
    for item in item_list:
        if not isinstance(item, dict):
            continue
        item_type = item.get('type')
        if item_type in (1, '1', 'TEXT', 'text'):
            return 'TEXT'
        if item_type is not None:
            return str(item_type)
    return 'TEXT'


@dataclass
class WeixinMessage:
    """One normalized iLink inbound message."""

    message_id: str
    from_user_id: str
    to_user_id: str
    msg_type: str  # TEXT | IMAGE | FILE | VIDEO | ...
    text: str | None
    context_token: str | None
    seq: int | None
    create_time_ms: int | None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_text(self) -> bool:
        return self.msg_type.upper() == 'TEXT'

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> WeixinMessage:
        item_list = payload.get('item_list') or []
        text = payload.get('text') or payload.get('content') or _extract_text_item_list(item_list)
        msg_type = payload.get('msg_type') or payload.get('type')
        if not msg_type:
            msg_type = 'TEXT' if text else _message_type_from_item_list(item_list)
        return cls(
            message_id=str(payload.get('msg_id') or payload.get('message_id') or ''),
            from_user_id=str(payload.get('from_user_id') or ''),
            to_user_id=str(payload.get('to_user_id') or ''),
            msg_type=str(msg_type or 'TEXT').upper(),
            text=text,
            context_token=payload.get('context_token'),
            seq=payload.get('seq'),
            create_time_ms=payload.get('create_time_ms'),
            raw=payload,
        )


def _random_wechat_uin() -> str:
    """Per-request ``X-WECHAT-UIN``: base64 of a random 32-bit int.

    Mirrors the iLink reference clients (hermes-agent, AstrBot), which
    send a fresh random UIN on every request. The server requires it on
    authenticated POSTs (``getupdates``/``sendmessage``); omitting it
    causes the post-login message stream to never establish even though
    QR login already issued a valid ``bot_token``.
    """
    value = secrets.randbits(32)
    return base64.b64encode(str(value).encode('utf-8')).decode('ascii')


class WeChatIlinkClient:
    """HTTP JSON client for the iLink contract (transport-injectable)."""

    def __init__(
        self,
        *,
        base_url: str,
        bot_token: str,
        account_id: str = 'default',
        bot_agent: str = 'ClawCodex/1.0',
        transport: ChannelTransport | None = None,
        long_poll_timeout_ms: int = DEFAULT_LONG_POLL_TIMEOUT_MS,
    ) -> None:
        self._base_url = base_url.rstrip('/')
        self._bot_token = bot_token
        self._account_id = account_id
        self._bot_agent = bot_agent
        self._transport = transport
        self._long_poll_timeout_ms = long_poll_timeout_ms

    def set_transport(self, transport: ChannelTransport) -> None:
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        h = default_headers()
        h['AuthorizationType'] = 'ilink_bot_token'
        h['Authorization'] = f'Bearer {self._bot_token}'
        h['Bot-Agent'] = self._bot_agent
        h['iLink-App-Id'] = ILINK_APP_ID
        h['iLink-App-ClientVersion'] = str(ILINK_APP_CLIENT_VERSION)
        h['X-WECHAT-UIN'] = _random_wechat_uin()
        return h

    def _url(self, path: str, *, base_url: str | None = None) -> str:
        return f'{(base_url or self._base_url).rstrip("/")}{path}'

    def _qr_headers(self) -> dict[str, str]:
        return {
            'User-Agent': default_headers().get('User-Agent', 'clawcodex-channels/0.1'),
            'iLink-App-Id': ILINK_APP_ID,
            'iLink-App-ClientVersion': str(ILINK_APP_CLIENT_VERSION),
        }

    async def _get(
        self,
        path: str,
        *,
        timeout: float,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        assert self._transport is not None, 'transport not set'
        resp: TransportResponse = await self._transport.get(
            self._url(path, base_url=base_url),
            headers=self._qr_headers(),
            timeout=timeout,
        )
        return _parse_ilink_response(resp)

    async def _post(self, path: str, body: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        assert self._transport is not None, 'transport not set'
        # The iLink contract requires ``base_info.channel_version`` on every
        # POST (getupdates/sendmessage). Without it the server rejects the
        # request, so the bot never establishes a live message stream even
        # though QR login already issued a bot_token — clawcodex would report
        # "logged_in" while the WeChat side shows no connection.
        body = {**body, 'base_info': {'channel_version': ILINK_CHANNEL_VERSION}}
        resp: TransportResponse = await self._transport.post(
            self._url(path), encode_json_body(body), headers=self._headers(), timeout=timeout
        )
        return _parse_ilink_response(resp)

    async def getupdates(
        self, get_updates_buf: str | None
    ) -> tuple[list[WeixinMessage], str | None]:
        # iLink requires get_updates_buf as a string; JSON null makes the
        # server silently drop the session's message stream. Normalize None
        # → "" at the wire boundary so every caller is safe.
        body: dict[str, Any] = {
            'get_updates_buf': get_updates_buf if get_updates_buf is not None else '',
        }
        data = await self._post(EP_GET_UPDATES, body, timeout=self._long_poll_timeout_ms / 1000 + 5)
        items = data.get('msgs') or []
        messages = [WeixinMessage.from_payload(m) for m in items if isinstance(m, dict)]
        new_buf = data.get('get_updates_buf')
        return messages, new_buf

    async def sendmessage(
        self,
        *,
        to_user_id: str,
        text: str,
        context_token: str | None = None,
    ) -> ChannelSendResult:
        client_id = f'local-{uuid.uuid4()}'
        msg: dict[str, Any] = {
            'from_user_id': '',
            'to_user_id': to_user_id,
            'client_id': client_id,
            'message_type': 2,
            'message_state': 2,
            'item_list': [{'type': 1, 'text_item': {'text': text}}],
        }
        if context_token:
            msg['context_token'] = context_token
        body = {'msg': msg}
        try:
            data = await self._post(EP_SEND_MESSAGE, body, timeout=DEFAULT_TIMEOUT_SECONDS)
        except TransportError as exc:
            cat = classify_exception(exc)
            return ChannelSendResult.retryable_error(
                ILINK_CHANNEL_ID, message=str(exc), category=cat
            )
        except _IlinkPlatformError as exc:
            # Session-expired errors are re-raised so the adapter can
            # strip the context_token and retry tokenless — iLink accepts
            # tokenless sendmessage calls as a degraded fallback, which
            # keeps proactive push messages working past the 48-hour
            # customer-service window. Mirrors hermes-agent weixin.py.
            if exc.is_session_expired:
                raise
            # Rate-limit is retryable; anything else is a terminal platform error.
            if exc.is_rate_limited:
                return ChannelSendResult.retryable_error(
                    ILINK_CHANNEL_ID,
                    message=f'rate limited: {exc.errmsg or exc.msg}',
                    category=ErrorCategory.RATE_LIMIT,
                )
            return ChannelSendResult.nonretryable_error(
                ILINK_CHANNEL_ID, message=str(exc), category=ErrorCategory.UNKNOWN
            )
        receipt = data.get('message_id') or data.get('client_id') or client_id
        logger.info(
            'wechat sendmessage ok: to=%s receipt=%s',
            _safe_id(to_user_id),
            _safe_id(receipt),
        )
        return ChannelSendResult.success(ILINK_CHANNEL_ID, provider_receipt=receipt, raw=data)

    async def get_bot_qrcode(self, *, bot_type: str = ILINK_QR_BOT_TYPE) -> dict[str, Any]:
        return await self._get(
            f'{EP_GET_BOT_QR}?bot_type={quote(bot_type)}',
            timeout=ILINK_QR_REQUEST_TIMEOUT_SECONDS,
        )

    async def get_qrcode_status(
        self,
        qrcode: str,
        *,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        return await self._get(
            f'{EP_GET_QR_STATUS}?qrcode={quote(qrcode)}',
            timeout=ILINK_QR_REQUEST_TIMEOUT_SECONDS,
            base_url=base_url,
        )


def _parse_ilink_response(resp: TransportResponse) -> dict[str, Any]:
    import json

    if resp.status >= 400:
        raise _IlinkHttpError(resp.status, resp.body)
    if not resp.body:
        return {}
    try:
        data = json.loads(resp.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise TransportError(f'ilink returned non-JSON: {exc}') from exc
    if isinstance(data, dict) and _is_ilink_payload_error(data):
        # iLink signals errors via ret/errcode inside an HTTP 200 body.
        ret = data.get('ret')
        errcode = data.get('errcode')
        errmsg = str(data.get('errmsg') or data.get('msg') or data.get('message') or '')
        code = str(
            ret
            if ret not in (None, 0, '0')
            else (errcode if errcode not in (None, 0, '0') else data.get('code'))
        )
        raise _IlinkPlatformError(code, errmsg, ret=ret, errcode=errcode, errmsg=errmsg)
    return data or {}


class _IlinkHttpError(Exception):
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.body = body
        super().__init__(f'ilink HTTP {status}')


class _IlinkPlatformError(Exception):
    """An iLink body-level error (non-zero ``ret``/``errcode`` on HTTP 200).

    ``code``/``msg`` are kept for backward-compatible display and for the
    QR-flow's synthetic codes (e.g. ``"missing_qrcode"``). When raised from
    a parsed response, ``ret``/``errcode``/``errmsg`` carry the real iLink
    fields and the ``is_session_expired`` / ``is_rate_limited`` flags drive
    retry vs. pause decisions.
    """

    def __init__(
        self,
        code: str,
        msg: str,
        *,
        ret: Any = None,
        errcode: Any = None,
        errmsg: str | None = None,
    ) -> None:
        self.code = code
        self.msg = msg
        self.ret = _ilink_int(ret)
        self.errcode = _ilink_int(errcode)
        self.errmsg = errmsg
        super().__init__(f'ilink platform error {code}: {msg}')

    @property
    def is_session_expired(self) -> bool:
        if (
            self.ret == ILINK_SESSION_EXPIRED_ERRCODE
            or self.errcode == ILINK_SESSION_EXPIRED_ERRCODE
        ):
            return True
        # ret/errcode == -2 with errmsg "unknown error" is a stale-session
        # signal, not a genuine rate limit (mirrors hermes _is_stale_session_ret).
        if (self.ret == ILINK_RATE_LIMIT_ERRCODE or self.errcode == ILINK_RATE_LIMIT_ERRCODE) and (
            self.errmsg or ''
        ).lower() == _STALE_SESSION_ERRMSG:
            return True
        return False

    @property
    def is_rate_limited(self) -> bool:
        if self.is_session_expired:
            return False
        return self.ret == ILINK_RATE_LIMIT_ERRCODE or self.errcode == ILINK_RATE_LIMIT_ERRCODE


def _ilink_int(value: Any) -> int | None:
    """Coerce an iLink ``ret``/``errcode`` to int; None for absent/invalid."""
    if value is None or value == '':
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_ilink_payload_error(data: dict[str, Any]) -> bool:
    """True when an iLink 200-response body signals an error.

    Success is ``ret``/``errcode`` absent or 0 (mirrors hermes
    ``ret not in {0, None}`` and AstrBot ``int(ret or 0) == 0``). The legacy
    ``code`` field is also honored for non-iLink-shaped errors.
    """
    ret = _ilink_int(data.get('ret'))
    errcode = _ilink_int(data.get('errcode'))
    if ret not in (None, 0) or errcode not in (None, 0):
        return True
    # Legacy envelope (not used by the iLink bot contract today, but kept so
    # unexpected server shapes still surface as errors rather than silently
    # being treated as success).
    code = data.get('code')
    if code not in (None, 0, '0'):
        return True
    return False


# -- adapter ------------------------------------------------------------


InboundHandler = Callable[[Any], Awaitable[None]]  # InboundMessage


class WeChatIlinkChannelAdapter(ChannelAdapter):
    def __init__(
        self,
        config: ChannelConfig,
        *,
        auth_store: WeChatIlinkAuthStore,
        store,  # ReliabilityStore
        pairing: WeChatPairingStore | None = None,
        transport: ChannelTransport | None = None,
        retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
        long_poll_timeout_ms: int = DEFAULT_LONG_POLL_TIMEOUT_MS,
        max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES,
        allowed_users: list[str] | None = None,
        account_id: str = 'default',
        base_url: str = 'https://ilinkai.weixin.qq.com',
        bot_agent: str = 'ClawCodex/1.0',
    ) -> None:
        self._config = config
        self._auth_store = auth_store
        self._store = store
        self._pairing = pairing or WeChatPairingStore()
        self._transport = transport
        self._retry_policy = retry_policy
        self._long_poll_timeout_ms = long_poll_timeout_ms
        self._max_consecutive_failures = max_consecutive_failures
        # Kept as a constructor-compatible field for existing configs, but
        # direct/private WeChat text is open by default: any sender can drive
        # the bot once the channel is logged in and the gateway is bound.
        self._allowed_users = set(allowed_users or [])
        self._account_id = account_id
        self._base_url = base_url
        self._bot_agent = bot_agent

        self._client: WeChatIlinkClient | None = None
        # iLink requires get_updates_buf as a string ("") on the first poll;
        # null makes the server silently drop the session's message stream.
        self._get_updates_buf: str = ''
        self._bot_user_id: str | None = None
        self._circuit_state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._last_error: str | None = None
        self._last_poll_at: float | None = None
        self._last_inbound_at: float | None = None
        self._last_outbound_at: float | None = None
        # Most recent real inbound sender (current lifetime). Used to
        # resolve wildcard OUTBOUND origins; falls back to persisted
        # context tokens via ``last_known_sender`` after a restart.
        self._last_from_user_id: str | None = None
        self._account_status = 'unconfigured'  # unconfigured|logged_in|paused|circuit_open
        self._poll_task: asyncio.Task[None] | None = None
        self._on_inbound: InboundHandler | None = None

    # -- ChannelAdapter contract ----------------------------------------
    @property
    def channel_id(self) -> str:
        return self._config.name

    @property
    def capabilities(self) -> ChannelCapabilitySet:
        return ChannelCapabilitySet.of(
            ChannelCapability.OUTBOUND_TEXT,
            ChannelCapability.INBOUND_POLLING,
            ChannelCapability.CONTEXT_REPLY,
            ChannelCapability.LOGIN_MANAGED,
            descriptors={
                ChannelCapability.OUTBOUND_TEXT: CapabilityDescriptor(
                    ChannelCapability.OUTBOUND_TEXT,
                    supports_markdown=False,
                    max_text_length=TEXT_CHUNK_SIZE,
                ),
            },
        )

    @property
    def retry_policy(self) -> RetryPolicy:
        return self._retry_policy

    def validate_config(self) -> ValidationResult:
        errors: list[str] = []
        if not self._base_url:
            errors.append('base_url must be non-empty')
        if not self._config.name:
            errors.append('name must be non-empty')
        return ValidationResult.fail(errors) if errors else ValidationResult.ok_result()

    async def health_check(self) -> ChannelHealth:
        return ChannelHealth(
            healthy=self._circuit_state is CircuitState.CLOSED
            and self._account_status == 'logged_in',
            channel_id=self.channel_id,
            circuit_state=self._circuit_state.value,
            last_error=self._last_error,
            last_poll_at=self._last_poll_at,
            last_inbound_at=self._last_inbound_at,
            last_outbound_at=self._last_outbound_at,
            consecutive_failures=self._consecutive_failures,
            account_status=self._account_status,
        )

    # -- login_managed --------------------------------------------------
    def load_credentials(self) -> WeChatAuthRecord | None:
        record = self._auth_store.load()
        if record is None:
            self._account_status = 'unconfigured'
            return None
        self._bot_user_id = record.user_id
        self._account_id = record.account_id
        self._base_url = record.base_url or self._base_url
        self._client = WeChatIlinkClient(
            base_url=self._base_url,
            bot_token=record.bot_token,
            account_id=self._account_id,
            bot_agent=self._bot_agent,
            transport=self._transport,
            long_poll_timeout_ms=self._long_poll_timeout_ms,
        )
        if self._store is not None:
            self._get_updates_buf = self._store.get_wechat_cursor(self._account_id)
        self._account_status = 'logged_in'
        return record

    async def qr_login(
        self,
        *,
        on_code: Callable[[str], None] | None = None,
        on_status: Callable[[str], None] | None = None,
        timeout_seconds: int = ILINK_QR_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        """Perform QR login; on success persist encrypted bot_token."""
        if self._transport is None:
            raise RuntimeError('transport not set')
        # Bootstrap a temp client without a token to fetch and poll the QR code.
        boot = WeChatIlinkClient(
            base_url=self._base_url,
            bot_token='',
            account_id=self._account_id,
            bot_agent=self._bot_agent,
            transport=self._transport,
            long_poll_timeout_ms=self._long_poll_timeout_ms,
        )
        qr_data = await boot.get_bot_qrcode()
        qrcode_value = str(qr_data.get('qrcode') or '')
        code_url = str(qr_data.get('qrcode_img_content') or qr_data.get('code_url') or '')
        if not qrcode_value:
            raise _IlinkPlatformError('missing_qrcode', 'QR response missing qrcode')
        scan_data = code_url or qrcode_value
        if on_code is not None:
            on_code(scan_data)

        deadline = time.monotonic() + timeout_seconds
        current_base_url = self._base_url
        refresh_count = 0
        while time.monotonic() < deadline:
            try:
                status_data = await boot.get_qrcode_status(qrcode_value, base_url=current_base_url)
            except TransportError as exc:
                logger.debug('wechat QR poll transient transport error: %s', exc)
                if on_status is not None:
                    on_status('wait')
                await asyncio.sleep(ILINK_QR_POLL_INTERVAL_SECONDS)
                continue
            status = str(status_data.get('status') or 'wait')
            if on_status is not None:
                on_status(status)
            if status == 'confirmed':
                account_id = str(status_data.get('ilink_bot_id') or self._account_id or 'default')
                bot_token = str(status_data.get('bot_token') or '')
                base_url = str(status_data.get('baseurl') or current_base_url or self._base_url)
                user_id = str(status_data.get('ilink_user_id') or '') or None
                if not account_id or not bot_token:
                    raise _IlinkPlatformError(
                        'incomplete_qr_credentials',
                        'QR confirmed but credential payload was incomplete',
                    )
                record = WeChatAuthRecord(
                    bot_token=bot_token,
                    account_id=account_id,
                    base_url=base_url.rstrip('/'),
                    user_id=user_id,
                )
                self._auth_store.save(record)
                self.load_credentials()
                return {
                    'status': 'confirmed',
                    'qrcode': qrcode_value,
                    'code_url': scan_data,
                    'bot_token': bot_token,
                    'account_id': account_id,
                    'base_url': record.base_url,
                    'user_id': user_id,
                }
            if status == 'scaned_but_redirect':
                redirect_host = str(status_data.get('redirect_host') or '')
                if redirect_host:
                    current_base_url = (
                        redirect_host.rstrip('/')
                        if redirect_host.startswith(('http://', 'https://'))
                        else f'https://{redirect_host}'
                    )
            elif status == 'expired':
                refresh_count += 1
                if refresh_count > 3:
                    return {'status': 'expired', 'qrcode': qrcode_value, 'code_url': scan_data}
                qr_data = await boot.get_bot_qrcode()
                qrcode_value = str(qr_data.get('qrcode') or '')
                code_url = str(qr_data.get('qrcode_img_content') or qr_data.get('code_url') or '')
                if not qrcode_value:
                    raise _IlinkPlatformError('missing_qrcode', 'QR refresh missing qrcode')
                scan_data = code_url or qrcode_value
                current_base_url = self._base_url
                if on_code is not None:
                    on_code(scan_data)
            await asyncio.sleep(ILINK_QR_POLL_INTERVAL_SECONDS)

        return {'status': 'timeout', 'qrcode': qrcode_value, 'code_url': scan_data}

    # -- inbound_polling ------------------------------------------------
    def set_inbound_handler(self, handler: InboundHandler) -> None:
        self._on_inbound = handler

    def last_known_sender(self) -> str | None:
        """Most recent concrete WeChat sender, for wildcard OUTBOUND resolution.

        Returns the in-memory last inbound sender (most recent, current
        lifetime). If none — e.g. right after a gateway restart with no new
        inbound — falls back to any persisted context-token user for this
        account, so a wildcard OUTBOUND can still reach the operator. The
        context-token store already survives restarts (it backs
        ``context_reply``), so no separate persistence is needed.
        """
        if self._last_from_user_id:
            return self._last_from_user_id
        if self._store is not None:
            users = self._store.wechat_context_users(self._account_id)
            if users:
                return users[0]
        return None

    async def start(self) -> None:
        if self._poll_task is not None:
            return
        if self._client is None:
            self.load_credentials()
        if self._client is None:
            logger.warning('wechat adapter %s has no credentials; not polling', self.channel_id)
            return
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None

    async def _poll_loop(self) -> None:
        logger.info(
            'wechat poll loop START channel=%s account=%s base=%s cursor=%r',
            self.channel_id,
            _safe_id(self._account_id),
            self._base_url,
            (self._get_updates_buf or '')[:24],
        )
        while True:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception('wechat poll loop error')
            await asyncio.sleep(0.1)

    async def _poll_once(self) -> None:
        if self._circuit_state is CircuitState.OPEN:
            return
        if self._client is None:
            return
        try:
            messages, new_buf = await self._client.getupdates(self._get_updates_buf)
        except _IlinkHttpError as exc:
            logger.warning('wechat getupdates HTTP %s', exc.status)
            await self._handle_poll_http_error(exc.status, exc.body)
            return
        except _IlinkPlatformError as exc:
            logger.warning(
                'wechat getupdates platform error ret=%s errcode=%s errmsg=%s session_expired=%s',
                exc.ret,
                exc.errcode,
                exc.errmsg,
                exc.is_session_expired,
            )
            # iLink returns session-expiry as a body-level ret/errcode=-14
            # inside an HTTP 200 (not as a 401). Pause without consuming the
            # circuit-breaker budget, mirroring the 401 path.
            if exc.is_session_expired:
                self._pause_account(
                    f'session expired (ret={exc.ret} errcode={exc.errcode}); re-scan required',
                    audit_event='wechat_auth_paused',
                    audit_reason='session_expired',
                )
                return
            self._record_failure(str(exc))
            return
        except TransportError as exc:
            logger.warning('wechat getupdates transport error: %s', exc)
            self._record_failure(str(exc))
            return
        # success — only advance the cursor when the server returns a real
        # value; an empty/absent get_updates_buf must NOT overwrite a valid
        # cursor (hermes guards the same way), or the stream position is lost.
        if new_buf:
            self._get_updates_buf = new_buf
            if self._store is not None:
                self._store.set_wechat_cursor(self._account_id, new_buf)
        self._consecutive_failures = 0
        self._last_poll_at = time.time()
        logger.debug(
            'wechat getupdates ok: %d message(s), cursor_advanced=%s',
            len(messages),
            bool(new_buf),
        )
        for msg in messages:
            await self._handle_inbound(msg)

    async def _handle_poll_http_error(self, status: int, body: bytes) -> None:
        category = classify_http_status(status)
        if category is ErrorCategory.AUTH:
            # session expired / 401 → pause account, do NOT consume breaker
            self._pause_account(
                f'HTTP {status}: session expired; re-scan required',
                audit_event='wechat_auth_paused',
                audit_reason='http_401',
                audit_status=status,
            )
            return
        self._record_failure(f'HTTP {status}: {body[:120]!r}')

    def _pause_account(
        self,
        message: str,
        *,
        audit_event: str,
        audit_reason: str,
        audit_status: int | None = None,
    ) -> None:
        """Pause the account (session expired) without consuming the breaker."""
        self._account_status = 'paused'
        self._last_error = message
        self._store.audit(
            audit_event,
            channel=self.channel_id,
            account_id=self._account_id,
            reason=audit_reason,
            **({'status': audit_status} if audit_status is not None else {}),
        )

    def _record_failure(self, message: str) -> None:
        self._consecutive_failures += 1
        self._last_error = message
        self._last_poll_at = time.time()
        if self._consecutive_failures >= self._max_consecutive_failures:
            self._circuit_state = CircuitState.OPEN
            self._account_status = 'circuit_open'
            self._store.audit(
                'wechat_circuit_open',
                channel=self.channel_id,
                account_id=self._account_id,
                consecutive_failures=self._consecutive_failures,
            )

    def reset_circuit(self) -> None:
        """Manual recovery via `clawcodex channels restart wechat`."""
        self._circuit_state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._last_error = None
        if self._account_status == 'circuit_open':
            self._account_status = 'logged_in' if self._client is not None else 'unconfigured'

    async def _handle_inbound(self, msg: WeixinMessage) -> None:
        logger.info(
            'wechat inbound: msg_id=%s from=%s to=%s account=%s bot_user=%s '
            'msg_type=%s text=%r context_token=%s',
            msg.message_id,
            _safe_id(msg.from_user_id),
            _safe_id(msg.to_user_id),
            _safe_id(self._account_id),
            _safe_id(self._bot_user_id),
            msg.msg_type,
            (msg.text or '')[:80],
            'yes' if msg.context_token else 'no',
        )
        # anti-loop: drop the bot's own messages. iLink marks a bot-originated
        # message with from_user_id == the bot's account_id (...@im.bot), NOT
        # the bot's wechat user_id (...@im.wechat). Comparing against user_id
        # (the previous behavior) wrongly dropped real user DMs because iLink
        # fills the bot's @im.wechat id into from_user_id for inbound DMs.
        # Mirrors hermes-agent (_process_message: sender_id == self._account_id).
        if msg.from_user_id and msg.from_user_id == self._account_id:
            logger.info('wechat anti-loop drop (from==account_id): msg_id=%s', msg.message_id)
            self._store.audit(
                'wechat_self_message_dropped',
                channel=self.channel_id,
                account_id=self._account_id,
                message_id=msg.message_id,
            )
            return
        # Track the most recent real sender for wildcard OUTBOUND resolution.
        if msg.from_user_id:
            self._last_from_user_id = msg.from_user_id
        # persist context_token
        if msg.context_token:
            self._store.set_context_token(self._account_id, msg.from_user_id, msg.context_token)
        # unsupported media
        if not msg.is_text:
            self._store.record_unsupported_media(
                {
                    'channel': self.channel_id,
                    'account_id': self._account_id,
                    'message_id': msg.message_id,
                    'from_user_hash': _hash_user(msg.from_user_id),
                    'media_type': msg.msg_type,
                    'size': _media_size(msg.raw),
                    'received_at': time.time(),
                    'raw_type': msg.msg_type,
                }
            )
            await self._reply_unsupported(msg)
            return
        self._last_inbound_at = time.time()
        logger.info(
            'wechat inbound → dispatcher: from=%s msg_id=%s',
            _safe_id(msg.from_user_id),
            msg.message_id,
        )
        if self._on_inbound is not None:
            from clawcodex_ext.services.im_gateway.models import InboundMessage, OriginKey

            inbound = InboundMessage(
                origin=str(OriginKey.wechat(self._account_id, msg.from_user_id)),
                text=msg.text or '',
                message_id=msg.message_id,
                channel=self.channel_id,
                context_token=msg.context_token,
                from_user_id=msg.from_user_id,
                raw=msg.raw,
            )
            await self._on_inbound(inbound)

    async def _reply_unsupported(self, msg: WeixinMessage) -> None:
        await self.send(
            ChannelMessage(
                text='当前 WeChat v1 仅支持文本消息，请改用文字描述或等待媒体能力开启。'
            ),
            target=msg.from_user_id,
            context_token=msg.context_token,
        )

    # -- outbound_text --------------------------------------------------
    async def send(
        self,
        message: ChannelMessage,
        *,
        target: str | None = None,
        context_token: str | None = None,
    ) -> ChannelSendResult:
        if self._client is None:
            self.load_credentials()
        if self._client is None:
            return ChannelSendResult.nonretryable_error(
                self.channel_id, message='wechat not logged in', category=ErrorCategory.AUTH
            )
        if target is None:
            return ChannelSendResult.nonretryable_error(
                self.channel_id,
                message='target (to_user_id) required for wechat send',
                category=ErrorCategory.CLIENT_ERROR,
            )
        # load saved context_token if not provided
        if context_token is None:
            context_token = self._store.get_context_token(self._account_id, target)
        text = message.text or ''
        chunks = [text[i : i + TEXT_CHUNK_SIZE] for i in range(0, len(text), TEXT_CHUNK_SIZE)] or [
            ''
        ]
        last: ChannelSendResult | None = None
        for chunk in chunks:
            # Per-chunk retry: on session-expired (errcode -14), strip the
            # context_token and retry once tokenless. iLink accepts
            # tokenless sendmessage calls as a degraded fallback — this
            # keeps proactive/cron push messages working even when the
            # 48-hour customer-service window has expired and no recent
            # user message has refreshed the session. Mirrors hermes-agent
            # weixin.py:_send_text_chunk_locked.
            retried_without_token = False
            while True:
                try:
                    result = await self._client.sendmessage(
                        to_user_id=target, text=chunk, context_token=context_token
                    )
                except _IlinkHttpError as exc:
                    cat = classify_http_status(exc.status)
                    if cat in self._retry_policy.retryable_categories:
                        last = ChannelSendResult.retryable_error(
                            self.channel_id, message=f'HTTP {exc.status}', category=cat
                        )
                    else:
                        last = ChannelSendResult.nonretryable_error(
                            self.channel_id, message=f'HTTP {exc.status}', category=cat
                        )
                    break
                except (_IlinkPlatformError, TransportError) as exc:
                    # Session expired: strip token and retry tokenless once.
                    if (
                        isinstance(exc, _IlinkPlatformError)
                        and exc.is_session_expired
                        and context_token is not None
                        and not retried_without_token
                    ):
                        retried_without_token = True
                        context_token = None
                        self._store.set_context_token(self._account_id, target, None)
                        logger.warning(
                            'wechat session expired for %s; retrying without context_token',
                            _safe_id(target),
                        )
                        continue
                    last = ChannelSendResult.nonretryable_error(
                        self.channel_id, message=str(exc), category=ErrorCategory.UNKNOWN
                    )
                    break
                last = result
                break
            if last is not None and not last.ok:
                break
        self._last_outbound_at = time.time()
        return (
            self._adapter_result(last)
            if last is not None
            else ChannelSendResult.success(self.channel_id)
        )

    def _adapter_result(self, result: ChannelSendResult) -> ChannelSendResult:
        if result.channel_id == self.channel_id:
            return result
        return ChannelSendResult(
            ok=result.ok,
            status=result.status,
            channel_id=self.channel_id,
            error_category=result.error_category,
            provider_receipt=result.provider_receipt,
            message=result.message,
            attempts=result.attempts,
            raw=result.raw,
        )


# -- helpers ------------------------------------------------------------


def _hash_user(user_id: str) -> str:
    return hashlib.sha256(user_id.encode('utf-8')).hexdigest()[:16]


def _safe_id(value: str | None, keep: int = 16) -> str:
    """Truncate an id for log readability (full ids are noisy and PII-ish)."""
    raw = str(value or '').strip()
    if not raw:
        return '<empty>'
    return raw if len(raw) <= keep else raw[:keep] + '…'


def _media_size(raw: dict[str, Any]) -> int | None:
    for key in ('size', 'file_size'):
        value = raw.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    media = raw.get('media') or raw.get('file') or raw.get('image')
    if isinstance(media, dict):
        value = media.get('size') or media.get('file_size')
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


def _json_loads(s: str) -> dict[str, Any]:
    import json

    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return {}


__all__ = [
    'DEFAULT_LONG_POLL_TIMEOUT_MS',
    'DEFAULT_MAX_CONSECUTIVE_FAILURES',
    'ILINK_CHANNEL_ID',
    'PAIRING_CODE_TTL_SECONDS',
    'TEXT_CHUNK_SIZE',
    'WeChatAuthRecord',
    'WeChatIlinkAuthStore',
    'WeChatIlinkChannelAdapter',
    'WeChatIlinkClient',
    'WeChatPairingStore',
    'WeixinMessage',
]
