"""Cancel-latency-fixed Anthropic provider — clawcodex_ext extension.

Subclasses :class:`src.providers.anthropic_provider.AnthropicProvider`
and overrides :meth:`chat_stream_response` to use the worker-thread +
100ms queue-poll drain from :mod:`clawcodex_ext.providers._stream_drain`.

The body otherwise mirrors the parent method (watchdog,
``get_final_message()``, WI-5.2 non-streaming fallback) so the
subclass is a drop-in replacement. The only behavior change is
cancel latency: bounded to ~100ms instead of the worst-case HTTP
read timeout (~60s on platforms where ``response.close()`` from
another thread does not interrupt the blocking httpx read).

Registered in :mod:`clawcodex_ext.providers` via
``register_provider("anthropic", …)``; the hook in
``src.providers.get_provider_class`` makes the override win over
the upstream hardcoded branch.
"""

from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

from src.providers.anthropic_provider import AnthropicProvider
from clawcodex_ext.providers.base import ChatResponse, MessageInput, TextChunkCallback

from clawcodex_ext.providers._stream_drain import drain_text_stream_with_abort_poll

if TYPE_CHECKING:
    from src.utils.abort_controller import AbortSignal


class ClawcodexAnthropicProvider(AnthropicProvider):
    """Anthropic Claude provider with cancel-latency fix.

    Inherits ``__init__``, ``_ensure_client``, ``_get_model``,
    ``_prepare_messages``, ``_build_chat_response``, ``has_custom_endpoint``,
    and ``chat`` from the parent. Overrides ``chat_stream_response`` to
    route the synchronous ``text_stream`` iteration through
    :func:`drain_text_stream_with_abort_poll` so a user cancel (Shift+Tab,
    Ctrl+C) lands within ~100ms regardless of platform-level
    ``response.close()`` semantics.
    """

    def chat_stream_response(
        self,
        messages: list[MessageInput],
        tools: Optional[list[dict[str, Any]]] = None,
        on_text_chunk: TextChunkCallback | None = None,
        abort_signal: "AbortSignal | None" = None,
        **kwargs,
    ) -> ChatResponse:
        # Import inside the method to avoid the heavy ``anthropic`` SDK
        # import at module load time (WI-4.4) and to break the
        # clawcodex_ext → src → clawcodex_ext circular import risk
        # the lazy provider pattern guards against.
        from src.providers._stream_abort import StreamAbortGuard
        from src.utils.stream_watchdog import StreamWatchdog

        guard = StreamAbortGuard(abort_signal)
        # Fast-path: if abort fired before we even build the request,
        # raise directly so the caller's cancel boundary unwinds at
        # the same place the mid-stream path lands.
        guard.raise_if_pre_aborted()

        model = self._get_model(**kwargs)
        max_tokens = kwargs.get("max_tokens", 4096)
        system = kwargs.pop("system", None)
        anthropic_messages = self._prepare_messages(messages)

        client = self._ensure_client()
        extra_kwargs: dict[str, Any] = {}
        if tools:
            extra_kwargs["tools"] = tools

        def _fallback_to_chat() -> ChatResponse:
            """Re-issue the request without streaming (WI-5.2 recovery path).

            Mirrors the parent class's fallback verbatim — kept inline
            (not factored into a shared helper) so the subclass
            ``chat_stream_response`` body is self-contained for code
            review and future upstream sync.
            """
            forwarded = {
                k: v for k, v in kwargs.items() if k not in ["model", "max_tokens", "tools"]
            }
            return self.chat(
                messages,
                tools=tools,
                **({"system": system} if system else {}),
                **forwarded,
                model=model,
                max_tokens=max_tokens,
            )

        # The drain helper calls ``on_text`` once per non-empty chunk.
        # We accumulate the chunks here and call the user's
        # ``on_text_chunk`` callback from the same place the parent
        # does, preserving the exact same callback contract.
        streamed_text_parts: list[str] = []

        def _on_text(text: str) -> None:
            streamed_text_parts.append(text)
            if on_text_chunk is not None:
                on_text_chunk(text)

        watchdog_fired = False
        final_message: Any = None
        try:
            with (
                client.messages.stream(
                    model=model,
                    max_tokens=max_tokens,
                    messages=anthropic_messages,
                    **({"system": system} if system else {}),
                    **extra_kwargs,
                    **{
                        k: v for k, v in kwargs.items() if k not in ["model", "max_tokens", "tools"]
                    },
                ) as stream,
                guard.attach(stream),
            ):
                # ``guard.attach`` registered the close-on-abort listener
                # (see ``_stream_abort.py`` for the race-safe ordering
                # and the close-via-stream.response.close mechanism).
                # The provider keeps the watchdog and fallback logic
                # local: they aren't abort-related.
                watchdog = StreamWatchdog(stream, abort_signal=abort_signal)
                watchdog.arm()
                try:
                    # The only behavioral change vs. the parent: this
                    # helper bounds cancel latency to ~100ms. The
                    # parent iterated ``stream.text_stream`` directly,
                    # which on some platforms blocks for the full HTTP
                    # read timeout when ``response.close()`` from
                    # another thread is not honored.
                    drain_text_stream_with_abort_poll(
                        stream,
                        guard=guard,
                        on_text=_on_text,
                        watchdog=watchdog,
                        stream_name="anthropic-stream",
                    )
                    try:
                        final_message = stream.get_final_message()
                    except Exception:
                        final_message = None
                finally:
                    # Snapshot watchdog state INSIDE the finally so it
                    # survives an exception propagating through the
                    # iterator (close() raises mid-stream). Critic B1
                    # caught this — otherwise the assignment was on a
                    # line never reached during the exception path and
                    # the fallback branch below ran with
                    # ``watchdog_fired`` still False.
                    watchdog_fired = watchdog.fired
                    watchdog.disarm()
        except Exception as streaming_exc:
            # Abort path FIRST: a user cancel must win over the
            # watchdog fallback (the abort listener may also have
            # tripped the watchdog's race, so we'd otherwise route a
            # user cancel through non-streaming recovery and burn
            # another round-trip).
            guard.reraise_if_aborted(streaming_exc)

            # WI-5.2 fallback path: stream interrupted by the idle
            # watchdog. Fall back to non-streaming so the user still
            # gets an answer. If the failure is something else
            # (network/auth/etc.), re-raise the original.
            if watchdog_fired:
                try:
                    return _fallback_to_chat()
                except Exception as fallback_exc:
                    # Recovery itself failed — surface BOTH causes so
                    # observers see the original streaming error AND
                    # the fallback failure that prevented recovery.
                    raise streaming_exc from fallback_exc
            raise

        # Stream exited normally but abort may have fired between
        # ``__exit__`` and here.
        guard.raise_if_post_aborted()

        streamed_text = "".join(streamed_text_parts)

        if final_message is not None:
            return self._build_chat_response(final_message)

        return ChatResponse(
            content=streamed_text,
            model=model,
            usage={},
            finish_reason="stop",
            tool_uses=None,
        )


__all__ = ["ClawcodexAnthropicProvider"]
