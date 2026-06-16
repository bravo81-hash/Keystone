"""Stage 15: Engine 3 — trend/managed-futures + convexity overlay.

Covers: TS-momentum signal both directions; debit-spread / LEAP construction
long and short; no-short-stock invariant; load-bearing sizing; crisis-payoff
reporting; trend_long fold-in (same geometry).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from core.bs_pricing import bs_greeks
from core.chain import OptionChain, OptionQuote
from core.context import TradeContext
from core.models import Action, Family, InstrumentClass, Right
from engines.engine3_overlay import Engine3Overlay
from strategies import trend_long, trend_overlay
from strategies.trend_filter import TrendState

ASOF = date(2026, 6, 15)
SPOT = 100.0


def _chain(symbol="SPY", spot=SPOT, dtes=(90, 270)) -> OptionChain:
    quotes = []
    for dte in dtes:
        exp = ASOF + timedelta(days=dte)
        t = dte / 365.0
        for k in range(50, 151, 5):
            for right in (Right.CALL, Right.PUT):
                g = bs_greeks(spot, float(k), t, 0.04, 0.25, right)
                price = max(g["price"], 0.05)
                quotes.append(OptionQuote(expiry=exp, strike=float(k), right=right,
                                          bid=round(price * 0.98, 2), ask=round(price * 1.02 + 0.02, 2),
                                          delta=g["delta"], iv=0.25))
    return OptionChain(symbol=symbol, spot=spot, quotes=quotes, asof=ASOF)


def _rising() -> list[float]:
    return [50.0 + 0.2 * i for i in range(300)]  # up trend


def _falling() -> list[float]:
    return [150.0 - 0.2 * i for i in range(300)]  # down trend


def _ctx(closes, *, symbol="SPY", name_budget=0.0, expression="debit_spread", nlv=None) -> TradeContext:
    return TradeContext(
        symbol=symbol, account_id="A1", instrument_class=InstrumentClass.US_ETF_OPT,
        chain=_chain(symbol=symbol), spot=SPOT, is_etf=True, nlv=nlv, asof=ASOF,
        extras={"closes": closes, "overlay_name_budget": name_budget,
                "overlay_expression": expression, "pool": "trading"},
    )


# --------------------------------------------------------------------------- #
# Signals
# --------------------------------------------------------------------------- #
def test_ts_momentum_both_directions():
    assert trend_overlay.ts_momentum_signal(_rising()) == 1
    assert trend_overlay.ts_momentum_signal(_falling()) == -1
    assert trend_overlay.ts_momentum_signal([100.0] * 300) == 0


def test_ma_state_both_directions():
    assert trend_overlay.ma_state_signal(_rising()) == 1
    assert trend_overlay.ma_state_signal(_falling()) == -1


def test_overlay_signal_both_mode_requires_agreement():
    assert trend_overlay.overlay_signal(_rising(), "both") == 1
    assert trend_overlay.overlay_signal(_falling(), "both") == -1
    # flat series -> both signals 0 -> flat
    assert trend_overlay.overlay_signal([100.0] * 300, "both") == 0


# --------------------------------------------------------------------------- #
# Construction (long / short), defined risk, no short stock
# --------------------------------------------------------------------------- #
def test_long_trend_builds_call_debit_spread():
    s = trend_overlay.propose(_ctx(_rising()))
    assert s is not None and s.family is Family.OVERLAY_DEBIT_SPREAD
    assert len(s.legs) == 2
    assert all(leg.contract.right is Right.CALL for leg in s.legs)
    assert s.max_loss == pytest.approx(s.management["net_debit"])  # defined risk = debit


def test_short_trend_builds_put_debit_spread():
    s = trend_overlay.propose(_ctx(_falling()))
    assert s is not None and s.family is Family.OVERLAY_DEBIT_SPREAD
    assert all(leg.contract.right is Right.PUT for leg in s.legs)


def test_long_trend_leap_expression():
    s = trend_overlay.propose(_ctx(_rising(), expression="leap"))
    assert s is not None and s.family is Family.OVERLAY_LEAP
    assert len(s.legs) == 1 and s.legs[0].action is Action.BUY


def test_no_short_stock_invariant():
    for closes in (_rising(), _falling()):
        for expr in ("debit_spread", "leap"):
            s = trend_overlay.propose(_ctx(closes, expression=expr))
            assert s is not None
            # every leg is an option (has a right) — never short stock
            assert all(leg.contract.right is not None for leg in s.legs)


def test_flat_signal_returns_none():
    assert trend_overlay.propose(_ctx([100.0] * 300)) is None


# --------------------------------------------------------------------------- #
# Load-bearing sizing + crisis payoff
# --------------------------------------------------------------------------- #
def test_load_bearing_sizing_scales_contracts():
    small = trend_overlay.propose(_ctx(_rising(), name_budget=1_000.0))
    big = trend_overlay.propose(_ctx(_rising(), name_budget=20_000.0))
    assert big.management["contracts"] > small.management["contracts"]
    assert big.max_loss > small.max_loss


def test_crisis_payoff_positive_for_short_trend():
    # A put debit spread (short trend) pays off in the -20% crash.
    s = trend_overlay.propose(_ctx(_falling(), name_budget=10_000.0))
    assert s.management["modeled_crisis_payoff"] > 0


def test_crisis_payoff_negative_for_long_trend():
    # A long-equity call spread loses ~its debit in the crash.
    s = trend_overlay.propose(_ctx(_rising(), name_budget=10_000.0))
    assert s.management["modeled_crisis_payoff"] < 0


# --------------------------------------------------------------------------- #
# trend_long fold-in (same convexity geometry)
# --------------------------------------------------------------------------- #
def test_folds_in_trend_long_geometry():
    # The overlay's long call debit spread uses the SAME strike geometry as the
    # v1 trend_long debit spread (DEBIT_LONG_DELTA / DEBIT_SHORT_DELTA, same DTE).
    overlay = trend_overlay.propose(_ctx(_rising()))
    v1_ctx = _ctx(_rising(), nlv=10_000_000.0)
    v1_ctx.extras["trend"] = TrendState.UP
    v1 = trend_long.propose_debit_spread(v1_ctx)
    assert v1 is not None
    assert [leg.contract.strike for leg in overlay.legs] == \
           [leg.contract.strike for leg in v1.legs]


# --------------------------------------------------------------------------- #
# Engine 3 orchestration
# --------------------------------------------------------------------------- #
def test_engine3_tags_and_reports_sleeve_and_crisis():
    engine = Engine3Overlay()
    spy = engine.propose(_ctx(_falling(), symbol="SPY", name_budget=10_000.0))
    tlt = engine.propose(_ctx(_rising(), symbol="TLT", name_budget=10_000.0))
    book = spy + tlt
    assert all(s.engine == "overlay" for s in book)
    sleeves = engine.net_exposure_by_sleeve(book)
    assert "equity" in sleeves and "bonds" in sleeves
    # SPY short-trend put spread => negative equity delta
    assert sleeves["equity"] < 0
    crisis = engine.modeled_crisis_payoff(book)
    assert crisis == pytest.approx(sum(s.management["modeled_crisis_payoff"] for s in book))
