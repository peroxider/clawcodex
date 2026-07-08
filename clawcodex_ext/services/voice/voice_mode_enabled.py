"""Voice-mode gating logic — F-64 P64-A.

Mirrors TS ``src/voice/voiceModeEnabled.ts``: a three-layer gate that
decides whether voice input is available and which STT backend to use.

Layers
------
1. **Feature flag** — ``FEATURE_VOICE_MODE`` env var (``"1"`` / ``"true"``).
   Off by default; the project ships the stack but the user must opt in.
2. **Kill-switch** — ``CLAWCODEX_VOICE_DISABLED`` env var. Default unset =
   not disabled. A negative gate like TS ``tengu_amber_quartz_disabled``:
   the *absence* of the env var means "available".
3. **Auth (Anthropic backend only)** — Anthropic STT requires an OAuth
   token (claude.ai subscription), not an API key. The doubao backend
   uses an independent credential file and skips this check.

Read-side
---------
* :func:`is_voice_mode_enabled` — Anthropic path: flag + kill-switch + OAuth.
* :func:`is_voice_available` — Provider-agnostic: flag + kill-switch only.
  Used by ``/voice`` to decide whether to show the command at all, and by
  the doubao path which doesn't need OAuth.
* :func:`get_voice_provider` — The persisted backend, defaulting to
  ``"anthropic"`` when unset (so a fresh install has a defined default).
* :func:`is_voice_enabled` — The master on/off switch written by ``/voice``.

The settings reads go through ``get_settings()`` (cached) and are
invalidated by ``set_voice_provider`` / ``set_voice_enabled`` so the gate
reflects mid-session changes immediately.
"""

from __future__ import annotations

import os
from typing import Literal

__all__ = [
    "VoiceProvider",
    "VOICE_PROVIDERS",
    "is_voice_feature_enabled",
    "is_voice_disabled_by_kill_switch",
    "has_voice_auth",
    "is_voice_mode_enabled",
    "is_voice_available",
    "is_voice_enabled",
    "get_voice_provider",
]

VoiceProvider = Literal["anthropic", "doubao"]
VOICE_PROVIDERS: tuple[str, ...] = ("anthropic", "doubao")


def is_voice_feature_enabled() -> bool:
    """Layer 1 — compile/runtime feature flag ``FEATURE_VOICE_MODE``.

    Accepts ``"1"`` / ``"true"`` / ``"yes"`` (case-insensitive). Empty /
    unset / any other value = disabled. This is the *only* layer that
    defaults off; layers 2 and 3 default to "available".
    """
    raw = os.environ.get("FEATURE_VOICE_MODE", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def is_voice_disabled_by_kill_switch() -> bool:
    """Layer 2 — negative kill-switch ``CLAWCODEX_VOICE_DISABLED``.

    Mirrors TS ``tengu_amber_quartz_disabled`` (default false = not
    disabled). Any truthy value here disables voice; absence = available.
    """
    raw = os.environ.get("CLAWCODEX_VOICE_DISABLED", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def has_voice_auth() -> bool:
    """Layer 3 — Anthropic OAuth check (claude.ai subscription token).

    Distinct from an API key: the Anthropic STT WebSocket endpoint
    (``voice_stream``) is gated on an OAuth bearer, not a sk-ant- key.
    Doubao bypasses this entirely (independent credentials file).

    Lazy import avoids pulling the auth stack at module-import time, and
    degrades to ``False`` if the auth module is unavailable (e.g. running
    under a stripped-down test harness) — voice simply reports unavailable
    rather than crashing the gate.
    """
    try:
        from clawcodex_ext.auth.oauth import OAuthTokens  # noqa: F401
        from clawcodex_ext.auth.auth import load_api_key  # noqa: F401
    except Exception:
        return False
    # The real OAuth-token presence check lives in the auth subsystem; we
    # delegate to a lightweight probe so the gate stays decoupled from the
    # auth internals. Implementation detail: read the persisted OAuth store
    # and confirm a non-expired token exists. Falls back to False on any
    # failure so a misconfigured auth never crashes the REPL.
    try:
        from clawcodex_ext.auth.codex_store import has_valid_oauth_token

        return has_valid_oauth_token()
    except Exception:
        # Function may not exist on all builds — treat as "no auth" rather
        # than blocking the gate. The STT connection itself will surface a
        # proper error if the user actually tries to record.
        return False


def is_voice_mode_enabled() -> bool:
    """Anthropic path gate: flag ∧ ¬kill-switch ∧ OAuth.

    Use this for the Anthropic STT backend specifically. For doubao or
    provider-agnostic availability checks use :func:`is_voice_available`.
    """
    if not is_voice_feature_enabled():
        return False
    if is_voice_disabled_by_kill_switch():
        return False
    return has_voice_auth()


def is_voice_available() -> bool:
    """Provider-agnostic gate: flag ∧ ¬kill-switch.

    OAuth is intentionally NOT checked here — the doubao backend uses an
    independent credential file. The REPL uses this to decide whether to
    show the ``/voice`` command and whether the push-to-talk hotkey should
    even be armed; the per-provider connection then enforces its own auth.
    """
    if not is_voice_feature_enabled():
        return False
    return not is_voice_disabled_by_kill_switch()


def is_voice_enabled() -> bool:
    """Master on/off switch (``settings.voice_enabled``).

    Written by ``/voice`` (no-arg toggle). When false the push-to-talk
    hotkey is inert regardless of provider configuration. Decoupled from
    :func:`get_voice_provider` — provider records the *chosen backend*,
    this records whether the user has opted in at all.
    """
    try:
        from src.settings.settings import get_settings

        return bool(get_settings().voice_enabled)
    except Exception:
        # Settings unavailable (e.g. bootstrap-before-config) → treat as
        # off. ``/voice`` will re-flip it once settings are reachable.
        return False


def get_voice_provider() -> VoiceProvider:
    """The persisted STT backend, defaulting to ``"anthropic"`` when unset.

    Reads ``settings.voice_provider``; empty string / unrecognised value /
    settings-unavailable all fall back to ``"anthropic"`` so a fresh
    install has a defined default without needing an explicit ``/voice
    anthropic`` invocation.
    """
    try:
        from src.settings.settings import get_settings

        raw = (get_settings().voice_provider or "").strip().lower()
    except Exception:
        raw = ""
    if raw in VOICE_PROVIDERS:
        return raw  # type: ignore[return-value]
    return "anthropic"
