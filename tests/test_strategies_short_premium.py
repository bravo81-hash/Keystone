"""Stage 5: credit spreads, iron condor, american guards."""

from __future__ import annotations

from datetime import date

import pytest

from core.chain import OptionChain, OptionQuote
from core.context import TradeContext
from core.models import Action, Contract, Event, EventKind, Family, InstrumentClass, Leg, Right, Suggestion
from regime.stock_regime import stock_regime
from regime.surface import Surface
from strategies import credit_spread, iron_condor
from strategies._guards import (
    american_guards,
    guard_earnings_straddle,
    guard_exdiv_assignment,
    guard_pin_risk,
)

ASOF = date(2026, 6, 15)
EXPIRY = date(2026, 7, 30)  # 45 DTE from ASOF

_PUTS = [(100, -0.50, 3.00), (95, -0.30, 1.80), (92, -0.20, 1.20), (90, -0.15, 0.90),
         (87, -0.10, 0.60), (85, -0.07, 0.40), (80, -0.04, 0.20)]
_CALLS = [(100, 0.50, 3.00), (105, 0.30, 1.80), (108, 0.20, 1.20), (110, 0.15, 0.90),
          (113, 0.10, 0.60), (115, 0.07, 0.40), (120, 0.04, 0.20)]


def make_chain(expiry=EXPIRY, asof=ASOF) -> OptionChain:
    quotes = [
        OptionQuote(expiry=expiry, strike=k, right=Right.PUT, bid=m, ask=m, delta=d, iv=0.30)
        for k, d, m in _PUTS
    ] + [
        OptionQuote(expiry=expiry, strike=k, right=Right.CALL, bid=m, ask=m, delta=d, iv=0.30)
        for k, d, m in _CALLS
    ]
    return OptionChain(symbol="AAPL", spot=100.0, quotes=quotes, asof=asof)


def make_regime(ivr: float):
    surf = Surface(ticker="AAPL", iv_9d=0.24, iv_30d=0.25, iv_90d=0.26,
                   slope_9_30=0.01, slope_30_90=0.01, inverted_front=False)
    return stock_regime("AAPL", surf, ivr=ivr, vrp_value=0.05)


def make_ctx(*, is_etf=False, ivr=50.0, next_earnings=None, next_exdiv=None, atr20=None,
             budget=500.0, instrument_class=InstrumentClass.US_EQUITY_OPT, bias=None) -> TradeContext:
    return TradeContext(
        symbol="AAPL",
        account_id="T1",
        instrument_class=instrument_class,
        chain=make_chain(),
        is_etf=is_etf,
        spot=100.0,
        stock_regime=make_regime(ivr),
        next_earnings=next_earnings,
        next_exdiv=next_exdiv,
        atr20=atr20,
        per_position_budget=budget,
        asof=ASOF,
        extras={"bias": bias} if bias else {},
    )


# --------------------------------------------------------------------------- #
# Credit spread strike / width selection
# --------------------------------------------------------------------------- #
def test_put_credit_spread_selection():
    s = credit_spread.propose_put_credit_spread(make_ctx(budget=500))
    assert s is not None
    assert s.family is Family.PUT_CREDIT_SPREAD
    assert len(s.legs) == 2
    short, long = s.legs
    assert short.action is Action.SELL and short.contract.strike == 92  # ~20 delta
    assert long.action is Action.BUY and long.contract.strike == 87  # widest width <= budget
    assert s.dte == 45
    assert s.management["credit"] == pytest.approx(0.60)
    assert s.max_loss == pytest.approx(440.0)
    assert s.multi_expiry is False


def test_put_credit_spread_width_grows_with_budget():
    # Bigger budget admits a wider wing (more premium).
    s = credit_spread.propose_put_credit_spread(make_ctx(budget=700))
    assert s.legs[1].contract.strike == 85  # width 7, max_loss 620 <= 700
    assert s.max_loss == pytest.approx(620.0)


def test_call_credit_spread_selection():
    s = credit_spread.propose_call_credit_spread(make_ctx(budget=500))
    assert s.family is Family.CALL_CREDIT_SPREAD
    short, long = s.legs
    assert short.contract.right is Right.CALL and short.contract.strike == 108
    assert long.contract.strike == 113
    assert s.max_loss == pytest.approx(440.0)


def test_management_metadata():
    s = credit_spread.propose_put_credit_spread(make_ctx())
    m = s.management
    assert m["profit_target_pct"] == 0.5
    assert m["stop_loss_mult"] == 2.0
    assert m["must_touch_by_dte"] == 21
    assert "short_strike_test" in m["alerts"]
    assert m["max_profit"] == pytest.approx(60.0)


def test_ivr_floor_skip():
    assert credit_spread.propose_put_credit_spread(make_ctx(ivr=20)) is None
    assert iron_condor.propose(make_ctx(ivr=20)) is None


def test_budget_too_small_returns_none():
    # Even the narrowest wing (width 2, max_loss 170) exceeds a tiny budget.
    assert credit_spread.propose_put_credit_spread(make_ctx(budget=50)) is None


def test_propose_dispatch_bias():
    assert credit_spread.propose(make_ctx(bias="bearish")).family is Family.CALL_CREDIT_SPREAD
    assert credit_spread.propose(make_ctx(bias="bullish")).family is Family.PUT_CREDIT_SPREAD


# --------------------------------------------------------------------------- #
# Iron condor
# --------------------------------------------------------------------------- #
def test_iron_condor_construction():
    s = iron_condor.propose(make_ctx(budget=500))
    assert s is not None
    assert s.family is Family.IRON_CONDOR
    assert len(s.legs) == 4
    assert s.management["short_put"] == 92
    assert s.management["short_call"] == 108
    assert s.management["long_put"] == 87  # width 5 (max_loss 380 <= 500)
    assert s.management["long_call"] == 113
    assert s.max_loss == pytest.approx(380.0)
    assert s.management["credit"] == pytest.approx(1.20)
    assert s.multi_expiry is False


# --------------------------------------------------------------------------- #
# Guards (individually)
# --------------------------------------------------------------------------- #
def _put_spread_suggestion(ctx) -> Suggestion:
    return Suggestion(
        symbol="AAPL", account_id="T1", family=Family.PUT_CREDIT_SPREAD,
        legs=[
            Leg(contract=Contract.option("AAPL", EXPIRY, 92, Right.PUT), action=Action.SELL),
            Leg(contract=Contract.option("AAPL", EXPIRY, 87, Right.PUT), action=Action.BUY),
        ],
        instrument_class=InstrumentClass.US_EQUITY_OPT,
    )


def test_guard_earnings_straddle_name_blocks_etf_allowed():
    earnings = date(2026, 7, 20)  # before the 7/30 short expiry, after ASOF
    name_ctx = make_ctx(next_earnings=earnings)
    assert guard_earnings_straddle(name_ctx, _put_spread_suggestion(name_ctx)) is not None
    etf_ctx = make_ctx(is_etf=True, next_earnings=earnings)
    assert guard_earnings_straddle(etf_ctx, _put_spread_suggestion(etf_ctx)) is None


def test_propose_refuses_earnings_straddle_for_name_allows_etf():
    earnings = date(2026, 7, 20)
    assert credit_spread.propose_put_credit_spread(make_ctx(next_earnings=earnings)) is None
    etf = credit_spread.propose_put_credit_spread(
        make_ctx(is_etf=True, next_earnings=earnings, instrument_class=InstrumentClass.US_ETF_OPT)
    )
    assert etf is not None


def test_guard_exdiv_assignment_blocks_short_call():
    exdiv = Event(symbol="AAPL", date=date(2026, 7, 1), kind=EventKind.DIV,
                  confirmed=True, meta={"amount": 1.50})
    ctx = make_ctx(next_exdiv=exdiv)
    # call credit spread: short call 108, extrinsic 1.20 < dividend 1.50 -> block
    assert credit_spread.propose_call_credit_spread(ctx) is None


def test_guard_pin_risk_is_warning_not_block():
    near_expiry = date(2026, 6, 16)  # 1 DTE
    ctx = make_ctx(atr20=5.0)  # band = 2.5
    sugg = Suggestion(
        symbol="AAPL", account_id="T1", family=Family.PUT_CREDIT_SPREAD,
        legs=[Leg(contract=Contract.option("AAPL", near_expiry, 101, Right.PUT), action=Action.SELL)],
        instrument_class=InstrumentClass.US_EQUITY_OPT,
    )
    assert guard_pin_risk(ctx, sugg) is not None
    result = american_guards(ctx, sugg)
    assert result.valid is True  # pin risk warns, does not block
    assert result.warnings


def test_guards_clean_pass():
    ctx = make_ctx()
    result = american_guards(ctx, _put_spread_suggestion(ctx))
    assert result.valid is True
    assert result.blocks == []
