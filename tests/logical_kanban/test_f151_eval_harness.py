"""Tests that wrap the F-151 offline evaluation harness.

The harness in ``eval_f151.py`` is a self-contained script intended
to be run by hand:

    python3 tests/logical_kanban/eval_f151.py

It is *also* imported here so the F-151 acceptance checks (see the
evaluation report at
``docs/feature_plan/09-logical-kanban/f-151-evaluation-report.md``)
are exercised as part of the regular test suite.  We only assert the
*platinum-tier* invariants — the in-depth per-goal metrics are
expected to drift as the scorer is tuned, and the report is the
authoritative source for those numbers.
"""

from __future__ import annotations

from tests.logical_kanban.eval_f151 import (
    GOLDEN_GOALS,
    run_evaluation,
)


def test_golden_set_has_ten_goals() -> None:
    assert len(GOLDEN_GOALS) == 10
    for entry in GOLDEN_GOALS:
        assert "goal" in entry and entry["goal"].strip()
        assert "expected" in entry and entry["expected"].startswith("M-")


def test_summary_injection_drives_method_reuse() -> None:
    """F-151 acceptance: summary injection lifts method_reuse_rate ≥ 30 %."""
    results = run_evaluation()
    with_rate = results["with_summary"]["method_reuse_rate"]
    without_rate = results["without_summary"]["method_reuse_rate"]
    assert with_rate >= 0.30, f"method_reuse_rate={with_rate:.0%} below 30 %"
    # The control arm must NOT attach method_refs — that is the
    # contrast that makes the with/without comparison meaningful.
    assert without_rate == 0.0


def test_summary_stays_within_token_budget() -> None:
    """F-151 acceptance: average summary < 1 800 tokens."""
    results = run_evaluation()
    avg = results["with_summary"]["avg_summary_tokens"]
    assert avg < 1800, f"avg_summary_tokens={avg:.0f} exceeds 1 800"


def test_summary_does_not_break_validation() -> None:
    """F-151 acceptance: validation_pass_rate must not regress."""
    results = run_evaluation()
    with_rate = results["with_summary"]["validation_pass_rate"]
    without_rate = results["without_summary"]["validation_pass_rate"]
    # Both arms must pass validation; pseudo-LLM emits clean plans.
    assert with_rate == 1.0
    assert without_rate == 1.0


def test_summary_uplift_is_positive() -> None:
    """Sanity: with/without delta on method_reuse must be strictly positive."""
    results = run_evaluation()
    uplift = results["uplift"]["method_reuse_rate"]
    assert uplift > 0.0


def test_top1_match_rate_stays_in_documented_band() -> None:
    """The 50 % top-1 rate is a *known* floor of the lightweight scorer.

    The F-151 design accounts for this by surfacing top-10 methods to
    the LLM.  We assert the rate is between 40 % and 60 % — the tight
    band is anchored on the measured 50 % and tolerates ±10 % of
    drift from future scorer tweaks (e.g. changing the description
    match weight).  A jump above 60 % means a real improvement; a drop
    below 40 % means a regression.
    """
    results = run_evaluation()
    rate = results["with_summary"]["top1_match_rate"]
    assert 0.40 <= rate <= 0.60, (
        f"top1_match_rate={rate:.0%} drifted outside the [40 %, 60 %] band — "
        "either a real improvement (relax the upper bound) or a regression "
        "(investigate the scorer)."
    )
