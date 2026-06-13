"""Stage 6: trend filter + long-premium convexity (LEAPS/diagonal/debit, caps)."""

from __future__ import annotations

from datetime import date

import pytest

from core.chain import OptionChain, OptionQuote
from core.context import TradeContext
from core.models import Action, Family, InstrumentClass, Right
from strategies import trend_long
from strategies.trend_filter import TrendState, trend_state

ASOF = date(2026, 6, 15)
MONTHLY = date(2026, 7, 15)  # 30 DTE
MID = date(2026, 9, 13)  # 90 DTE
LEAPS = date(2027, 3, 12)  # 270 DTE


def make_chain() -> OptionChain:
    q = []

    def add(expiry, strike, right, delta, mid):
        q.append(OptionQuote(expiry=expiry, strike=strike, right=right, bid=mid, ask=mid, delta=delta))

    for k, d, m in [(80, 0.78, 24.0), (90, 0.65, 16.0), (100, 0.55, 10.0), (110, 0.40, 6.0)]:
        add(LEAPS, k, Right.CALL, d, m)
    for k, d, m in [(120, -0.78, 24.0), (110, -0.65, 16.0), (100, -0.55, 10.0)]:
        add(LEAPS, k, Right.PUT, d, m)
    for k, d, m in [(100, 0.50, 3.0), (105, 0.30, 1.5), (110, 0.15, 0.7)]:
        add(MONTHLY, k, Right.CALL, d, m)
    for k, d, m in [(100, -0.50, 3.0), (95, -0.30, 1.5)]:
        add(MONTHLY, k, Right.PUT, d, m)
    for k, d, m in [(95, 0.62, 7.5), (100, 0.50, 5.0), (105, 0.35, 3.0), (110, 0.30, 2.2)]:
        add(MID, k, Right.CALL, d, m)
    return OptionChain(symbol="MSFT", spot=100.0, quotes=q, asof=ASOF)


def make_ctx(*, trend=TrendState.UP, nlv=1_000_000.0, sleeve_used=0.0, structure=None) -> TradeContext:
    extras = {"trend": trend}
    if structure:
        extras["trend_structure"] = structure
    return TradeContext(
        symbol="MSFT",
        account_id="T1",
        instrument_class=InstrumentClass.US_EQUITY_OPT,
        chain=make_chain(),
        spot=100.0,
        nlv=nlv,
        sleeve_usage={"trend": sleeve_used},
        asof=ASOF,
        extras=extras,
    )


# --------------------------------------------------------------------------- #
# Trend filter
# --------------------------------------------------------------------------- #
def test_trend_state_up():
    closes = [100 + 0.5 * i for i in range(260)]
    assert trend_state(closes) is TrendState.UP


def test_trend_state_down():
    closes = [200 - 0.5 * i for i in range(260)]
    assert trend_state(closes) is TrendState.DOWN


def test_trend_state_none_flat_and_short():
    assert trend_state([100.0] * 260) is TrendState.NONE
    assert trend_state([100.0] * 50) is TrendState.NONE  # insufficient history


# --------------------------------------------------------------------------- #
# Construction
# --------------------------------------------------------------------------- #
def test_leaps_construction():
    s = trend_long.propose_leaps(make_ctx())
    assert s is not None
    assert s.family is Family.TREND_LEAPS
    assert len(s.legs) == 1
    leg = s.legs[0]
    assert leg.action is Action.BUY and leg.contract.right is Right.CALL
    assert leg.contract.strike == 80  # ~75 delta deep ITM
    assert s.max_loss == pytest.approx(2400.0)
    assert s.multi_expiry is False


def test_diagonal_construction():
    s = trend_long.propose_diagonal(make_ctx())
    assert s.family is Family.TREND_DIAGONAL
    assert len(s.legs) == 2
    long_leg, short_leg = s.legs
    assert long_leg.action is Action.BUY and long_leg.contract.expiry == LEAPS and long_leg.contract.strike == 80
    assert short_leg.action is Action.SELL and short_leg.contract.expiry == MONTHLY and short_leg.contract.strike == 105
    assert s.multi_expiry is True
    assert s.max_loss == pytest.approx(2250.0)
    assert s.management["short_call_roll"]


def test_debit_spread_construction():
    s = trend_long.propose_debit_spread(make_ctx())
    assert s.family is Family.TREND_DEBIT_SPREAD
    long_leg, short_leg = s.legs
    assert long_leg.contract.strike == 95 and short_leg.contract.strike == 110
    assert long_leg.contract.expiry == short_leg.contract.expiry == MID
    assert s.max_loss == pytest.approx(530.0)
    assert s.multi_expiry is False


def test_down_trend_uses_puts():
    s = trend_long.propose_leaps(make_ctx(trend=TrendState.DOWN))
    assert s.legs[0].contract.right is Right.PUT
    assert s.legs[0].contract.strike == 120  # deep ITM put ~75 delta


def test_no_trend_no_proposal():
    assert trend_long.propose_leaps(make_ctx(trend=TrendState.NONE)) is None
    assert trend_long.propose(make_ctx(trend=TrendState.NONE)) is None


# --------------------------------------------------------------------------- #
# Sizing caps
# --------------------------------------------------------------------------- #
def test_per_position_cap_rejects_oversized():
    # NLV 100k -> 0.5% cap = $500; a $2400 LEAPS debit breaches it.
    assert trend_long.propose_leaps(make_ctx(nlv=100_000.0)) is None


def test_sleeve_ceiling_rejects():
    # NLV 1M -> 5% ceiling = $50k; 49k used + 2.4k debit = 51.4k > ceiling.
    assert trend_long.propose_leaps(make_ctx(sleeve_used=49_000.0)) is None


def test_within_caps_passes():
    assert trend_long.propose_leaps(make_ctx(sleeve_used=40_000.0)) is not None


# --------------------------------------------------------------------------- #
# Management metadata + dispatch + reuse
# --------------------------------------------------------------------------- #
def test_management_metadata():
    s = trend_long.propose_leaps(make_ctx())
    assert s.management["profit_target_long_leg"] is None  # no PT on the long leg
    assert "trend_invalidation" in s.management["alerts"]
    assert s.management["partial_scale_out"] is False


def test_propose_dispatch():
    assert trend_long.propose(make_ctx(structure="diagonal")).family is Family.TREND_DIAGONAL
    assert trend_long.propose(make_ctx(structure="debit")).family is Family.TREND_DEBIT_SPREAD
    assert trend_long.propose(make_ctx()).family is Family.TREND_LEAPS


def test_build_diagonal_reusable_for_pmcc():
    # Stage 7 PMCC reuses build_diagonal with a PMCC family tag.
    s = trend_long.build_diagonal(make_ctx(), Right.CALL, family=Family.PMCC)
    assert s.family is Family.PMCC
    assert s.multi_expiry is True
    assert len(s.legs) == 2
