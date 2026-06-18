"""Cancel-latency-fixed Minimax provider — clawcodex_ext extension.

Subclasses :class:`src.providers.minimax_provider.MinimaxProvider` and
overrides :meth:`chat_stream_response` to use the worker-thread +
100ms queue-poll drain from
:mod:`clawcodex_ext.providers._stream_drain`.

The body otherwise mirrors the parent method (``get_final_message()``,
the abort translation in the ``except`` block, the post-abort recheck).
The only behavior change is cancel latency: bounded to ~100ms instead
of the worst-case HTTP read timeout (~60s on platforms where
``response.close()`` from another thread does not interrupt the
blocking httpx read).

Registered in :mod:`clawcodex_ext.providers` via
``register_provider("minimax", …)``; the hook in
``src.providers.get_provider_class`` makes the override win over the
upstream hardcoded branch.
"""

from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

from src.providers.minimax_provider import MinimaxProvider
from src.providers.base import ChatResponse, MessageInput, TextChunkCallback

from clawcodex_ext.providers._stream_drain import drain_text_stream_with_abort_poll

if TYPE_CHECKING:
    from src.utils.abort_controller import AbortSignal


class ClawcodexMinimaxProvider(MinimaxProvider):
    """Minimax AI provider (Anthropic-compatible) with cancel-latency fix.

    Inherits ``__init__``, ``_ensure_client``, ``_get_model``,
    ``_prepare_messages``, ``_build_chat_response``, and ``chat`` from
    the parent. Overrides ``chat_stream_response`` to route the
    synchronous ``text_stream`` iteration through
    :func:`drain_text_stream_with_abort_poll`.
    """

    def chat_stream_response(
        self,
        messages: list[MessageInput],
        tools: Optional[list[dict[str, Any]]] = None,
        on_text_chunk: TextChunkCallback | None = None,
        abort_signal: "AbortSignal | None" = None,
        **kwargs,
    ) -> ChatResponse:
        from src.providers._stream_abort import StreamAbortGuard

        guard = StreamAbortGuard(abort_signal)
        guard.raise_if_pre_aborted()

        model = self._get_model(**kwargs)
        max_tokens = kwargs.get("max_tokens", 4096)
        system = kwargs.pop("system", None)
        minimax_messages = self._prepare_messages(messages)

        client = self._ensure_client()
        extra_kwargs: dict[str, Any] = {}
        if tools:
            extra_kwargs["tools"] = tools

        streamed_text_parts: list[str] = []

        def _on_text(text: str) -> None:
            streamed_text_parts.append(text)
            if on_text_chunk is not None:
                on_text_chunk(text)

        final_message: Any = None
        try:
            with (
                client.messages.stream(
                    model=model,
                    max_tokens=max_tokens,
                    messages=minimax_messages,
                    **({"system": system} if system else {}),
                    **extra_kwargs,
                    **{
                        k: v for k, v in kwargs.items() if k not in ["model", "max_tokens", "tools"]
                    },
                ) as stream,
                guard.attach(stream),
            ):
                # The only behavioral change vs. the parent: route
                # the synchronous ``text_stream`` iteration through
                # the worker-thread + 100ms queue-poll drain so a
                # user cancel lands within ~100ms instead of the
                # worst-case HTTP read timeout.
                drain_text_stream_with_abort_poll(
                    stream,
                    guard=guard,
                    on_text=_on_text,
                    stream_name="minimax-stream",
                )
                try:
                    final_message = stream.get_final_message()
                except Exception:
                    final_message = None
        except Exception as streaming_exc:
            guard.reraise_if_aborted(streaming_exc)
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


__all__ = ["ClawcodexMinimaxProvider"]
