"""A transparent :class:`BaseProvider` wrapper for multi-model turns."""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from typing import Any, Generator, Optional

from clawcodex_ext.capabilities.multimodel_protocol import AggregatedOutput, AggregatorProtocol, MultiModelResult, MultiModelStrategy
from clawcodex_ext.providers.base import BaseProvider, ChatResponse, MessageInput

from .slots import ProviderSlot


@dataclass(frozen=True)
class RouterConfig:
    """Execution limits shared by all router strategies."""

    max_concurrent: int = 5

    def __post_init__(self) -> None:
        if self.max_concurrent <= 0:
            raise ValueError("max_concurrent must be greater than zero")


class MultiModelRouter(BaseProvider):
    """Expose an ensemble as one ordinary provider to the query engine."""

    def __init__(
        self,
        slots: list[ProviderSlot],
        strategy: MultiModelStrategy,
        aggregator: AggregatorProtocol | None = None,
        *,
        config: RouterConfig | None = None,
        session_bridge: Any | None = None,
    ) -> None:
        if not slots:
            raise ValueError("MultiModelRouter needs at least one provider slot")
        if len({slot.name for slot in slots}) != len(slots):
            raise ValueError("provider slot names must be unique")
        super().__init__(api_key="", model=None)
        self.slots = list(slots)
        self.strategy = strategy
        self._aggregator = aggregator
        self.config = config or RouterConfig()
        self.session_bridge = session_bridge
        self._last_result: list[MultiModelResult] | None = None
        self._last_aggregated: AggregatedOutput | None = None

    @property
    def last_result(self) -> list[MultiModelResult] | None:
        return self._last_result

    @property
    def last_aggregated(self) -> AggregatedOutput | None:
        return self._last_aggregated

    async def _call_slot(
        self, slot: ProviderSlot, messages: list[MessageInput], **kwargs: Any
    ) -> MultiModelResult:
        started = time.monotonic()
        call_kwargs = dict(kwargs)
        # A slot's explicit model is a group policy and deliberately wins over
        # the model selected by the enclosing single-provider runtime.
        if slot.model:
            call_kwargs["model"] = slot.model
        try:
            response = await asyncio.wait_for(
                slot.provider.chat_async(messages, **call_kwargs),
                timeout=slot.timeout_ms / 1000,
            )
            duration_ms = int((time.monotonic() - started) * 1000)
            usage = response.usage if isinstance(response.usage, dict) else {}
            return MultiModelResult(slot.name, response, duration_ms, self._tokens(usage))
        except asyncio.CancelledError:
            duration_ms = int((time.monotonic() - started) * 1000)
            return MultiModelResult(slot.name, self._empty_response(slot), duration_ms, {}, cancelled=True)
        except asyncio.TimeoutError:
            return MultiModelResult(slot.name, self._empty_response(slot), slot.timeout_ms, {}, error=f"Timeout after {slot.timeout_ms}ms")
        except Exception as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            return MultiModelResult(slot.name, self._empty_response(slot), duration_ms, {}, error=str(exc))

    @staticmethod
    def _empty_response(slot: ProviderSlot) -> ChatResponse:
        return ChatResponse("", slot.model or slot.provider.model or "", {}, "error")

    @staticmethod
    def _tokens(usage: dict[str, Any]) -> dict[str, int]:
        """Normalise provider-specific usage payloads to the public contract."""
        def integer(value: Any) -> int:
            return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0

        return {
            "input": integer(usage.get("input", usage.get("input_tokens", 0))),
            "output": integer(usage.get("output", usage.get("output_tokens", 0))),
        }

    async def _execute(self, messages: list[MessageInput], **kwargs: Any) -> ChatResponse:
        results = await self.strategy.execute(self, messages, **kwargs)
        self._last_result = results
        if not results:
            raise RuntimeError("No enabled providers in multi-model router")
        aggregator = self._aggregator or getattr(self.strategy, "aggregator", None)
        if aggregator is not None:
            aggregated = await aggregator.aggregate(results, {})
            self._last_aggregated = aggregated
            chosen = aggregated.chosen
        else:
            successful = next((item for item in results if item.error is None and not item.cancelled), None)
            if successful is None:
                raise RuntimeError(f"All {len(results)} providers failed")
            chosen = successful.response
            self._last_aggregated = None
        if self.session_bridge is not None:
            self.session_bridge.record(results, self._last_aggregated)
        return chosen

    def chat_stream_response(self, messages: list[MessageInput], tools: Optional[list[dict[str, Any]]] = None, on_text_chunk: Any = None, on_thinking_chunk: Any = None, **kwargs: Any) -> ChatResponse:
        response = self._run_sync(self._execute(messages, tools=tools, **kwargs))
        # The child calls are intentionally non-streaming so all candidates can
        # be scheduled uniformly. Preserve BaseProvider's final-response
        # streaming compatibility for callers that supplied callbacks.
        if on_thinking_chunk is not None and response.reasoning_content:
            on_thinking_chunk(response.reasoning_content)
        if on_text_chunk is not None and response.content:
            on_text_chunk(response.content)
        return response

    def chat(self, messages: list[MessageInput], tools: Optional[list[dict[str, Any]]] = None, **kwargs: Any) -> ChatResponse:
        return self._run_sync(self._execute(messages, tools=tools, **kwargs))

    def chat_stream(self, messages: list[MessageInput], tools: Optional[list[dict[str, Any]]] = None, **kwargs: Any) -> Generator[str, None, None]:
        response = self.chat(messages, tools=tools, **kwargs)
        if response.content:
            yield response.content

    def get_available_models(self) -> list[str]:
        models: list[str] = []
        for slot in self.slots:
            if slot.model:
                models.append(slot.model)
            else:
                models.extend(slot.provider.get_available_models())
        return list(dict.fromkeys(models))

    @staticmethod
    def _run_sync(coro: Any) -> Any:
        """Run a coroutine even if an embedding UI already owns an event loop."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        outcome: dict[str, Any] = {}
        error: dict[str, BaseException] = {}

        def runner() -> None:
            try:
                outcome["value"] = asyncio.run(coro)
            except BaseException as exc:  # propagate exact provider exception
                error["error"] = exc

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        thread.join()
        if "error" in error:
            raise error["error"]
        return outcome["value"]
