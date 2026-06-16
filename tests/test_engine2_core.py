"""Stage 14: Engine 2 — leveraged LEAPS/PMCC core + standing layered hedge.

Covers: LEAPS/PMCC construction + exposure multiple; SMSF fully-paid + no-borrow
assertion + covered-diagonal routing; hedge layering + severe-tail sizing (the
hedge caps modeled tail loss near budget); regime scaling of hedge weight.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from core.bs_pricing import bs_greeks
from core.chain import OptionChain, OptionQuote
from core.context import TradeContext
from core.models import Family, InstrumentClass, Right
from engines.engine2_core import Engine2Core
from strategies import core_hedge, leveraged_core

ASOF = date(2026, 6, 15)
SPOT = 100.0


def _chain(symbol="SPY", spot=SPOT, dtes=(270, 35, 75)) -> OptionChain:
    quotes = []
    for dte in dtes:
        exp = ASOF + timedelta(days=dte)
        t = dte / 365.0
        for k in range(50, 151, 5):
            for right in (Right.CALL, Right.PUT):
                g = bs_greeks(spot, float(k), t, 0.04, 0.25, right)
                price = max(g["price"], 0.01)
                quotes.append(OptionQuote(expiry=exp, strike=float(k), right=right,
                                          bid=round(price * 0.98, 2), ask=round(price * 1.02 + 0.01, 2),
                                          delta=g["delta"], iv=0.25))
    return OptionChain(symbol=symbol, spot=spot, quotes=quotes, asof=ASOF)


def _ctx(pool="trading", *, symbol="SPY", core_capital=100_000.0, available_cash=None,
         use_pmcc=False, market_regime=None) -> TradeContext:
    extras = {"pool": pool, "core_capital": core_capital, "use_pmcc": use_pmcc}
    if available_cash is not None:
        extras["available_cash"] = available_cash
    return TradeContext(
        symbol=symbol, account_id="A1", instrument_class=InstrumentClass.US_ETF_OPT,
        chain=_chain(symbol=symbol), spot=SPOT, is_etf=True, nlv=core_capital,
        market_regime=market_regime, asof=ASOF, extras=extras,
    )


# --------------------------------------------------------------------------- #
# LEAPS core construction + exposure multiple
# --------------------------------------------------------------------------- #
def test_leaps_core_targets_exposure_multiple():
    s = leveraged_core.propose(_ctx(), core_exposure_mult=1.5)
    assert s is not None and s.family is Family.CORE_LEAPS
    assert len(s.legs) == 1 and s.legs[0].contract.right is Right.CALL
    # deep-ITM ~75 delta
    assert s.entry_greeks["long_delta"] > 0.65
    # realized exposure multiple is near the 1.5x target (sizing is integer-contract)
    assert s.management["core_exposure_mult_realized"] == pytest.approx(1.5, abs=0.25)
    assert s.management["effective_exposure"] > s.management["allocated_capital"]
    assert s.max_loss == s.management["net_debit"]  # defined risk = net debit


def test_pmcc_core_adds_short_call_diagonal():
    s = leveraged_core.propose(_ctx(use_pmcc=True), use_pmcc=True)
    assert s is not None and s.family is Family.CORE_PMCC
    assert len(s.legs) == 2
    assert s.multi_expiry is True
    assert s.management["covered_diagonal"] is True
    # net debit (LEAPS - short call) is less than the LEAPS-only debit
    leaps_only = leveraged_core.propose(_ctx())
    assert s.management["net_debit"] < leaps_only.management["net_debit"]


def test_exposure_scales_with_mult():
    low = leveraged_core.propose(_ctx(), core_exposure_mult=1.3)
    high = leveraged_core.propose(_ctx(), core_exposure_mult=1.7)
    assert high.management["effective_exposure"] >= low.management["effective_exposure"]


# --------------------------------------------------------------------------- #
# SMSF: fully paid, no borrow, covered diagonal
# --------------------------------------------------------------------------- #
def test_smsf_core_is_fully_paid_and_flagged():
    s = leveraged_core.propose(_ctx(pool="investing", core_capital=100_000.0))
    assert s is not None
    assert s.management["fully_paid"] is True
    assert s.management["no_borrow"] is True
    assert s.max_loss <= s.management["available_cash"]  # premium within cash


def test_smsf_core_rejected_when_premium_exceeds_cash():
    # Tiny available cash -> the LEAPS premium can't be fully paid -> no borrow -> dropped.
    s = leveraged_core.propose(
        _ctx(pool="investing", core_capital=100_000.0, available_cash=10.0)
    )
    assert s is None


def test_smsf_pmcc_routes_covered_diagonal():
    s = leveraged_core.propose(_ctx(pool="investing", use_pmcc=True), use_pmcc=True)
    assert s is not None and s.family is Family.CORE_PMCC
    assert s.management["covered_diagonal"] is True
    assert s.management["no_borrow"] is True


# --------------------------------------------------------------------------- #
# Hedge: layering + severe-tail sizing caps loss near budget
# --------------------------------------------------------------------------- #
def test_hedge_layers_and_caps_tail_near_budget():
    ctx = _ctx()
    core_severe_loss = 60_000.0  # modeled -20% loss on the levered core
    dd_budget = 20_000.0  # 20% of 100k
    plan = core_hedge.propose_hedge(ctx, core_severe_loss=core_severe_loss,
                                    dd_budget_dollars=dd_budget)
    layers = {s.management["hedge_layer"] for s in plan.suggestions}
    assert layers == {"base", "tail"}  # both layers present
    # the hedge targets covering the excess over budget...
    assert plan.target_payoff == pytest.approx(core_severe_loss - dd_budget, rel=0.01)
    # ...and the modeled payoff brings net core loss down toward the budget
    net_after = core_severe_loss - plan.modeled_severe_payoff
    assert net_after <= dd_budget * 1.5
    assert plan.modeled_severe_payoff > 0


def test_hedge_empty_when_core_within_budget():
    ctx = _ctx()
    plan = core_hedge.propose_hedge(ctx, core_severe_loss=10_000.0, dd_budget_dollars=20_000.0)
    assert plan.suggestions == []
    assert plan.target_payoff == 0.0


def test_hedge_weight_scales_with_regime():
    class _Regime:
        def __init__(self, defensive=False, hard_skip=False):
            self.is_defensive = defensive
            self.is_hard_skip = hard_skip

    calm = core_hedge.propose_hedge(_ctx(), core_severe_loss=60_000.0, dd_budget_dollars=20_000.0)
    defensive = core_hedge.propose_hedge(
        _ctx(market_regime=_Regime(defensive=True)), core_severe_loss=60_000.0, dd_budget_dollars=20_000.0
    )
    assert defensive.regime_scale > calm.regime_scale
    assert defensive.target_payoff > calm.target_payoff
    assert core_hedge.regime_hedge_scale(_Regime(hard_skip=True)) > \
           core_hedge.regime_hedge_scale(_Regime(defensive=True))


# --------------------------------------------------------------------------- #
# Engine 2 orchestration: tag, net delta, coverage ratio
# --------------------------------------------------------------------------- #
def test_engine2_orchestrates_core_and_hedge():
    engine = Engine2Core()
    ctx = _ctx()
    core = engine.propose(ctx)
    assert core and all(s.engine == "core" for s in core)
    assert engine.net_core_delta(core) > 0  # long beta

    severe_loss = engine.modeled_core_severe_loss(core)
    assert severe_loss > 0
    plan = engine.propose_hedge(ctx, core_severe_loss=severe_loss + 30_000.0, dd_budget_dollars=20_000.0)
    assert all(s.engine == "core" for s in plan.suggestions)
    ratio = engine.hedge_coverage_ratio(severe_loss + 30_000.0, plan.modeled_severe_payoff)
    assert 0.0 < ratio <= 2.0
    assert engine.hedge_coverage_ratio(0.0, 100.0) == 0.0
