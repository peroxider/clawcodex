from types import SimpleNamespace

from clawcodex_ext.latent_memory.server.token_usage import TokenUsageTracker, suppress_token_usage


def _enable_for_test(tracker: TokenUsageTracker) -> None:
    tracker._enabled = True
    tracker._stats = tracker._empty_stats()
    tracker._stats["enabled"] = True


def test_suppress_token_usage_excludes_nested_openai_response():
    tracker = TokenUsageTracker()
    _enable_for_test(tracker)
    response = SimpleNamespace(
        model="test-model",
        usage=SimpleNamespace(
            prompt_tokens=7,
            completion_tokens=5,
            total_tokens=12,
        ),
    )

    with suppress_token_usage():
        tracker.record_response(response)

    assert tracker.snapshot()["llm_calls"] == 0

    tracker.record_response(response)
    snapshot = tracker.snapshot()
    assert snapshot["llm_calls"] == 1
    assert snapshot["total_tokens"] == 12
