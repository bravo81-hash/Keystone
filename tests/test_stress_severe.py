"""Stage 17: severe-tail stress on the full leveraged book + DD-budget gate.

Covers: full-book stress incl. hedge offset + overlay payoff; severe-tail
pass/fail; allocator-style leverage cut when severe-tail breaches budget until it
clears; beta-mapped market + worst-name rows still correct (regression).
"""

from __future__ import annotations

import math

import pytest

from config.schema import StressCfg
from portfolio.stress import (
    StressPosition,
    market_row_pnl,
    severe_tail_row,
    severe_tail_stress,
    stress_book,
    worst_single_name,
)


def _levered_core(loss_at_severe: float) -> StressPosition:
    # A levered long-beta core: large negative delta-driven loss in the gap.
    # delta_shares chosen so beta-mapped -20% move yields ~ -loss_at_severe.
    spot = 100.0
    delta_shares = loss_at_severe / (spot * 0.20)
    return StressPosition(symbol="SPY", spot=spot, beta=1.0, delta_shares=delta_shares,
                          max_loss=None, engine="core")


def _income(loss: float) -> StressPosition:
    # Short premium: defined max-loss, fully realized in the gap.
    return StressPosition(symbol="AAPL", spot=100.0, beta=1.1, delta_shares=0.0,
                          max_loss=loss, severe_payoff=-loss, engine="income")


def _hedge(payoff: float) -> StressPosition:
    # Standing hedge: modeled positive payoff in the severe gap.
    return StressPosition(symbol="SPY", spot=100.0, severe_payoff=payoff, max_loss=2000.0,
                          engine="core")


def _overlay(payoff: float) -> StressPosition:
    return StressPosition(symbol="SPY", spot=100.0, severe_payoff=payoff, max_loss=3000.0,
                          engine="overlay")


# --------------------------------------------------------------------------- #
# Full-book severe row includes hedge offset + overlay payoff
# --------------------------------------------------------------------------- #
def test_severe_row_nets_hedge_and_overlay():
    core = _levered_core(60_000.0)  # -60k in the gap
    income = _income(15_000.0)  # -15k
    hedge = _hedge(40_000.0)  # +40k
    overlay = _overlay(20_000.0)  # +20k
    naked = severe_tail_row([core, income])
    protected = severe_tail_row([core, income, hedge, overlay])
    assert naked < protected  # hedge + overlay reduce the loss
    assert protected == pytest.approx(naked + 60_000.0)


def test_severe_payoff_overrides_greeks():
    # When severe_payoff is set it is used verbatim for the severe row.
    p = StressPosition(symbol="X", spot=100.0, delta_shares=9999.0, severe_payoff=500.0)
    assert p.pnl_severe(-0.20, 30.0) == 500.0
    # but the standard greek pnl still uses the linearization
    assert p.pnl(-0.20, 30.0) != 500.0


# --------------------------------------------------------------------------- #
# Severe-tail pass/fail against the DD budget
# --------------------------------------------------------------------------- #
def test_severe_tail_within_budget_pass():
    book = [_levered_core(50_000.0), _hedge(40_000.0)]  # net -10k
    res = severe_tail_stress(book, dd_budget=20_000.0)
    assert res.aggregate_loss == pytest.approx(10_000.0)
    assert res.within_budget is True
    assert res.implied_max_leverage > 1.0  # room to spare
    assert res.hedge_offset == pytest.approx(40_000.0)


def test_severe_tail_breaches_budget_fail():
    book = [_levered_core(60_000.0), _hedge(10_000.0)]  # net -50k
    res = severe_tail_stress(book, dd_budget=20_000.0)
    assert res.aggregate_loss == pytest.approx(50_000.0)
    assert res.within_budget is False
    assert res.implied_max_leverage == pytest.approx(20_000.0 / 50_000.0)  # 0.4


def test_severe_tail_book_gains_infinite_leverage():
    book = [_hedge(40_000.0), _overlay(20_000.0)]  # all gains
    res = severe_tail_stress(book, dd_budget=20_000.0)
    assert res.aggregate_loss == 0.0
    assert res.within_budget is True
    assert math.isinf(res.implied_max_leverage)


# --------------------------------------------------------------------------- #
# Cutting leverage clears the budget (allocator behaviour)
# --------------------------------------------------------------------------- #
def test_cutting_to_implied_leverage_clears_budget():
    book = [_levered_core(60_000.0), _income(15_000.0), _hedge(10_000.0)]
    res = severe_tail_stress(book, dd_budget=20_000.0)
    assert res.within_budget is False
    factor = res.implied_max_leverage
    assert factor < 1.0
    scaled = [p.scaled(factor) for p in book]
    res2 = severe_tail_stress(scaled, dd_budget=20_000.0)
    assert res2.within_budget is True
    assert res2.aggregate_loss == pytest.approx(20_000.0, rel=1e-6)


# --------------------------------------------------------------------------- #
# Regression: standard rows unchanged
# --------------------------------------------------------------------------- #
def test_standard_rows_still_correct():
    book = [StressPosition(symbol="AAPL", spot=100.0, beta=1.0, delta_shares=100.0,
                           max_loss=5000.0)]
    mkt = market_row_pnl(book, spot_shock=-0.05, iv_shock=10.0)
    assert mkt == pytest.approx(-0.05 * 100.0 * 100.0)  # -500
    sym, worst = worst_single_name(book, gap=-0.15, iv_shock=15.0)
    assert sym == "AAPL"
    assert worst == pytest.approx(-1500.0)  # -0.15*100*100, within max_loss


def test_severe_uses_cfg_shocks():
    book = [StressPosition(symbol="SPY", spot=100.0, beta=1.0, delta_shares=100.0)]
    cfg = StressCfg(severe_spot_shock=-0.30)
    res = severe_tail_stress(book, dd_budget=10_000.0, cfg=cfg)
    # -30% * 100 shares * $100 = -3000
    assert res.aggregate_pnl == pytest.approx(-3000.0)
