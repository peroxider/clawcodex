"""Behavioural tests for F-157 multi-model response aggregators."""

from __future__ import annotations

import pytest

from clawcodex_ext.providers.base import ChatResponse
from clawcodex_ext.capabilities.multimodel_protocol import AggregatorProtocol, MultiModelResult
from clawcodex_ext.multimodel.aggregators import (
    MajorityVoteAggregator,
    PassThroughAggregator,
    RankAggregator,
    ScoringAggregator,
)


def result(
    slot: str, content: str, *, error: str | None = None, cancelled: bool = False
) -> MultiModelResult:
    return MultiModelResult(
        slot_name=slot,
        response=ChatResponse(content=content, model=slot, usage={}, finish_reason="stop"),
        duration_ms=12,
        tokens={"input": 2, "output": 3},
        error=error,
        cancelled=cancelled,
    )


async def test_passthrough_uses_first_success_and_preserves_all_results() -> None:
    failed = result("failed", "", error="timeout")
    success = result("second", "answer")
    output = await PassThroughAggregator().aggregate([failed, success], {})

    assert output.chosen is success.response
    assert output.runners_up == [failed]
    assert output.provenance == [failed, success]


async def test_aggregators_reject_empty_results() -> None:
    with pytest.raises(ValueError, match="empty"):
        await PassThroughAggregator().aggregate([], {})


async def test_majority_vote_clusters_similar_text_and_excludes_failed_calls() -> None:
    first = result("one", "Python is dynamically typed.")
    second = result("two", "Python is dynamically typed!")
    third = result("three", "Rust is memory safe.")
    failed = result("four", "", error="rate limited")

    output = await MajorityVoteAggregator(tolerance=0.8).aggregate(
        [first, second, third, failed], {}
    )

    assert output.chosen is first.response
    assert output.vote_summary == {
        "total_votes": 3,
        "majority": 2,
        "clusters": {0: 2, 1: 1},
        "winning_slot": "one",
    }
    assert output.runners_up == [second, third, failed]


async def test_majority_vote_falls_back_when_too_few_valid_calls() -> None:
    failed = result("failed", "", error="timeout")
    only = result("only", "answer")
    output = await MajorityVoteAggregator(min_votes=2).aggregate([failed, only], {})

    assert output.chosen is only.response
    assert output.vote_summary is None


def test_majority_vote_validates_configuration() -> None:
    with pytest.raises(ValueError, match="min_votes"):
        MajorityVoteAggregator(min_votes=0)
    with pytest.raises(ValueError, match="tolerance"):
        MajorityVoteAggregator(tolerance=1.1)


async def test_scoring_uses_injected_evaluator_and_keeps_failed_provenance() -> None:
    async def scorer(candidate: MultiModelResult) -> dict[str, float]:
        scores = {
            "one": {"correctness": 7, "clarity": 8, "completeness": 6},
            "two": {"correctness": 9, "clarity": 8, "completeness": 10},
        }
        return scores[candidate.slot_name]

    first, second = result("one", "a"), result("two", "b")
    failed = result("failed", "", error="timeout")
    output = await ScoringAggregator(scorer=scorer).aggregate([first, second, failed], {})

    assert output.chosen is second.response
    assert output.runners_up == [first, failed]
    assert output.vote_summary["scores"]["two"]["total"] == pytest.approx(9)
    assert output.vote_summary["criteria"] == ["correctness", "clarity", "completeness"]


async def test_scoring_derives_total_and_requires_a_judge_for_competition() -> None:
    async def scorer(_candidate: MultiModelResult) -> dict[str, float]:
        return {"quality": 8}

    first, second = result("one", "a"), result("two", "b")
    output = await ScoringAggregator(criteria=["quality"], scorer=scorer).aggregate(
        [first, second], {}
    )
    assert output.vote_summary["scores"]["one"]["total"] == 8

    with pytest.raises(RuntimeError, match="needs a scorer"):
        await ScoringAggregator().aggregate([first, second], {})


async def test_rank_aggregates_peer_score_maps_into_a_stable_ranking() -> None:
    async def ranker(
        evaluator: MultiModelResult, _candidates: list[MultiModelResult], _context: dict
    ) -> dict[str, float]:
        rows = {
            "one": {"one": 6, "two": 9, "three": 7},
            "two": {"one": 7, "two": 8, "three": 6},
            "three": {"one": 8, "two": 9, "three": 5},
        }
        return rows[evaluator.slot_name]

    first, second, third = result("one", "a"), result("two", "b"), result("three", "c")
    output = await RankAggregator(ranker=ranker).aggregate([first, second, third], {})

    assert output.chosen is second.response
    assert output.vote_summary["ranking"] == ["two", "one", "three"]
    assert output.vote_summary["scores"]["two"] == pytest.approx(26 / 3)


async def test_rank_requires_a_ranker_only_when_it_has_multiple_candidates() -> None:
    only = result("only", "answer")
    assert (await RankAggregator().aggregate([only], {})).chosen is only.response
    with pytest.raises(RuntimeError, match="needs a ranker"):
        await RankAggregator().aggregate([only, result("two", "other")], {})


def test_aggregators_implement_runtime_protocol() -> None:
    assert isinstance(PassThroughAggregator(), AggregatorProtocol)
    assert isinstance(MajorityVoteAggregator(), AggregatorProtocol)
    assert isinstance(ScoringAggregator(), AggregatorProtocol)
    assert isinstance(RankAggregator(), AggregatorProtocol)
