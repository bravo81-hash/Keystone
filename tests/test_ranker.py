"""Stage 9: ranker — mandate filter, candidates, tier multiplier, fit, blocked skip."""

from __future__ import annotations

from datetime import date

import pytest

from core.chain import OptionChain, OptionQuote
from core.context import TradeContext
from core.models import Family, InstrumentClass, Right, Suggestion
from portfolio.account_profiles import AccountProfile, BlockedRule, Pool
from portfolio.budgets import BookItem
from regime.market_regime import classify_market_regime
from regime.stock_regime import stock_regime
from regime.surface import Surface
from selection import ranker
from selection.ranker import SMSF_FAMILIES, TRADING_FAMILIES, mandate_ok, rank, score_candidate
from store.db import init_db
from strategies import credit_spread

ASOF = date(2026, 6, 15)
CS_EXP = date(2026, 7, 30)  # 45 DTE
WHEEL_EXP = date(2026, 7, 23)  # 38 DTE
CALM = classify_market_regime(14, 15, 17, 110, 100, True)
HARD_SKIP = classify_market_regime(32, 30, 26, 90, 100, False)

TRADING = AccountProfile("T1", "Trading 1", Pool.TRADING, nlv=100_000.0)
SMSF = AccountProfile(
    "SMSF", "SMSF", Pool.INVESTING,
    blocked_rules=[BlockedRule(InstrumentClass.EU_CASH_INDEX, multi_expiry=True)],
    nlv=92_000.0,
)


def _credit_chain() -> OptionChain:
    puts = [(100, -0.50, 3.0), (95, -0.30, 1.8), (92, -0.20, 1.2), (90, -0.15, 0.9),
            (87, -0.10, 0.6), (85, -0.07, 0.4), (80, -0.04, 0.2)]
    calls = [(100, 0.50, 3.0), (105, 0.30, 1.8), (108, 0.20, 1.2), (110, 0.15, 0.9),
             (113, 0.10, 0.6), (115, 0.07, 0.4), (120, 0.04, 0.2)]
    q = [OptionQuote(expiry=CS_EXP, strike=k, right=Right.PUT, bid=m, ask=m, delta=d) for k, d, m in puts]
    q += [OptionQuote(expiry=CS_EXP, strike=k, right=Right.CALL, bid=m, ask=m, delta=d) for k, d, m in calls]
    return OptionChain(symbol="AAPL", spot=100.0, quotes=q, asof=ASOF)


def _wheel_chain() -> OptionChain:
    puts = [(100, -0.50, 3.0), (95, -0.30, 1.6), (93, -0.25, 1.2), (90, -0.20, 0.85)]
    calls = [(100, 0.50, 3.0), (105, 0.30, 1.5), (108, 0.20, 0.9)]
    q = [OptionQuote(expiry=WHEEL_EXP, strike=k, right=Right.PUT, bid=m, ask=m, delta=d) for k, d, m in puts]
    q += [OptionQuote(expiry=WHEEL_EXP, strike=k, right=Right.CALL, bid=m, ask=m, delta=d) for k, d, m in calls]
    return OptionChain(symbol="F", spot=100.0, quotes=q, asof=ASOF)


def _regime(ivr=60.0):
    surf = Surface(ticker="AAPL", iv_9d=0.24, iv_30d=0.25, iv_90d=0.26,
                   slope_9_30=0.01, slope_30_90=0.01, inverted_front=False)
    return stock_regime("AAPL", surf, ivr=ivr, vrp_value=0.05)


def trading_ctx(*, tier="A", market=CALM) -> TradeContext:
    return TradeContext(
        symbol="AAPL", account_id="T1", instrument_class=InstrumentClass.US_EQUITY_OPT,
        chain=_credit_chain(), is_etf=False, spot=100.0, stock_regime=_regime(),
        market_regime=market, per_position_budget=500.0, asof=ASOF, extras={"tier": tier},
    )


def smsf_ctx() -> TradeContext:
    return TradeContext(
        symbol="F", account_id="SMSF", instrument_class=InstrumentClass.US_EQUITY_OPT,
        chain=_wheel_chain(), is_etf=False, spot=100.0, core_shares=100, nlv=92_000.0,
        asof=ASOF, extras={"tier": "A"},
    )


def _sugg(family, instrument_class, multi_expiry=False):
    return Suggestion(symbol="X", account_id="A", family=family,
                      legs=[], instrument_class=instrument_class, multi_expiry=multi_expiry)


# --------------------------------------------------------------------------- #
# Mandate filter (both directions)
# --------------------------------------------------------------------------- #
def test_mandate_blocks_wheel_in_trading():
    assert mandate_ok(TRADING, _sugg(Family.WHEEL_CSP, InstrumentClass.US_EQUITY_OPT)) is False


def test_mandate_blocks_trading_family_in_smsf():
    assert mandate_ok(SMSF, _sugg(Family.PUT_CREDIT_SPREAD, InstrumentClass.US_EQUITY_OPT)) is False


def test_mandate_blocks_eu_cash_index_multi_expiry_in_smsf():
    assert mandate_ok(SMSF, _sugg(Family.PMCC, InstrumentClass.EU_CASH_INDEX, multi_expiry=True)) is False
    # American-style PMCC is fine for the SMSF.
    assert mandate_ok(SMSF, _sugg(Family.PMCC, InstrumentClass.US_EQUITY_OPT, multi_expiry=True)) is True


def test_mandate_allows_trading_family_in_trading():
    assert mandate_ok(TRADING, _sugg(Family.PUT_CREDIT_SPREAD, InstrumentClass.US_EQUITY_OPT)) is True


# --------------------------------------------------------------------------- #
# Candidate generation per sleeve
# --------------------------------------------------------------------------- #
def test_candidates_route_to_correct_sleeve():
    cards = rank([TRADING, SMSF], [trading_ctx(), smsf_ctx()])
    assert cards["T1"] and all(c.family in TRADING_FAMILIES for c in cards["T1"])
    assert cards["SMSF"] and all(c.family in SMSF_FAMILIES for c in cards["SMSF"])
    # SMSF generated the wheel legs.
    smsf_families = {c.family for c in cards["SMSF"]}
    assert Family.WHEEL_CSP in smsf_families


# --------------------------------------------------------------------------- #
# Scoring / tier multiplier
# --------------------------------------------------------------------------- #
def test_tier_multiplier():
    a = score_candidate(trading_ctx(tier="A"))
    b = score_candidate(trading_ctx(tier="B"))
    assert a == pytest.approx(1.0)  # CALM (1.0) + PREMIUM_RICH (1.0)
    assert b == pytest.approx(0.6 * a)


def test_hard_skip_vetoes_all_candidates():
    cards = rank([TRADING], [trading_ctx(market=HARD_SKIP)])
    assert cards.get("T1", []) == []


# --------------------------------------------------------------------------- #
# Fit integration
# --------------------------------------------------------------------------- #
def test_fit_filters_when_book_full():
    full_book = [
        BookItem(symbol=f"N{i}", sector=f"S{i}", family=Family.IRON_CONDOR, max_loss=100)
        for i in range(6)
    ]
    cards = rank([TRADING], [trading_ctx()], books={"T1": full_book})
    assert cards.get("T1", []) == []  # position-count cap breached -> all filtered


# --------------------------------------------------------------------------- #
# blocked_structures skip round-trip
# --------------------------------------------------------------------------- #
def test_blocked_structure_skip():
    db = init_db(":memory:")
    blocked = credit_spread.propose(trading_ctx())  # the put credit spread it would emit
    db.insert("blocked_structures", signature=blocked.signature(), reason="whatIf rejected")
    cards = rank([TRADING], [trading_ctx()], db=db)
    assert all(c.signature() != blocked.signature() for c in cards.get("T1", []))
