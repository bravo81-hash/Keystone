"""Stage 7: SMSF wheel (CSP/CC), collar, PMCC gating, rebalance, affordability."""

from __future__ import annotations

from datetime import date

import pytest

from config.loader import load_investing
from config.schema import TargetHoldingCfg
from core.chain import OptionChain, OptionQuote
from core.context import TradeContext
from core.models import Action, Event, EventKind, Family, InstrumentClass, Right
from portfolio.rebalance import RebalanceActionType, detect_rebalance, route_to_csp
from regime.market_regime import classify_market_regime
from strategies import collar, pmcc, wheel_cc, wheel_csp

ASOF = date(2026, 6, 15)
WHEEL_EXP = date(2026, 7, 23)  # 38 DTE
MONTHLY = date(2026, 7, 15)  # 30 DTE
LEAPS = date(2027, 3, 12)  # 270 DTE

_DEFENSIVE = classify_market_regime(20, 18, 19, 110, 100, True)
_CALM = classify_market_regime(14, 15, 17, 110, 100, True)


def wheel_chain() -> OptionChain:
    q = []

    def add(strike, right, delta, mid):
        q.append(OptionQuote(expiry=WHEEL_EXP, strike=strike, right=right, bid=mid, ask=mid, delta=delta))

    for k, d, m in [(100, -0.50, 3.0), (97, -0.38, 2.2), (95, -0.30, 1.6),
                    (93, -0.25, 1.2), (90, -0.20, 0.85), (87, -0.15, 0.55)]:
        add(k, Right.PUT, d, m)
    for k, d, m in [(100, 0.50, 3.0), (105, 0.30, 1.5), (108, 0.20, 0.9), (110, 0.15, 0.6)]:
        add(k, Right.CALL, d, m)
    return OptionChain(symbol="F", spot=100.0, quotes=q, asof=ASOF)


def pmcc_chain() -> OptionChain:
    q = []

    def add(expiry, strike, delta, mid):
        q.append(OptionQuote(expiry=expiry, strike=strike, right=Right.CALL, bid=mid, ask=mid, delta=delta))

    for k, d, m in [(80, 0.78, 24.0), (90, 0.65, 16.0), (100, 0.55, 10.0)]:
        add(LEAPS, k, d, m)
    for k, d, m in [(100, 0.50, 3.0), (105, 0.25, 1.2), (110, 0.15, 0.7)]:
        add(MONTHLY, k, d, m)
    return OptionChain(symbol="F", spot=100.0, quotes=q, asof=ASOF)


def make_ctx(*, chain=None, acquire_below=None, next_earnings=None, next_exdiv=None,
             core_shares=0, market_regime=None, is_etf=False,
             instrument_class=InstrumentClass.US_EQUITY_OPT, pmcc_enabled=False) -> TradeContext:
    return TradeContext(
        symbol="F",
        account_id="SMSF",
        instrument_class=instrument_class,
        chain=chain or wheel_chain(),
        is_etf=is_etf,
        spot=100.0,
        next_earnings=next_earnings,
        next_exdiv=next_exdiv,
        core_shares=core_shares,
        market_regime=market_regime,
        acquire_below_price=acquire_below,
        nlv=92000.0,
        pmcc_enabled=pmcc_enabled,
        asof=ASOF,
    )


# --------------------------------------------------------------------------- #
# Affordability scaffold validity
# --------------------------------------------------------------------------- #
def test_investing_scaffold_passes_smsf_affordability():
    inv = load_investing()
    nlv = inv.smsf_nlv
    assert inv.target_holdings, "scaffold should ship placeholder holdings"
    for h in inv.target_holdings:
        assert h.acquire_below_price is not None
        pct = 25.0 if h.is_etf else 12.0
        assert 100 * h.acquire_below_price <= (pct / 100) * nlv, h.ticker


# --------------------------------------------------------------------------- #
# Wheel CSP
# --------------------------------------------------------------------------- #
def test_csp_default_selection_and_cash_reservation():
    s = wheel_csp.propose(make_ctx())
    assert s.family is Family.WHEEL_CSP
    assert len(s.legs) == 1 and s.legs[0].action is Action.SELL
    assert s.legs[0].contract.strike == 93  # ~25 delta
    assert s.management["cash_reserved"] == pytest.approx(9300.0)
    assert s.dte == 38


def test_csp_respects_acquire_below_price():
    s = wheel_csp.propose(make_ctx(acquire_below=92))
    assert s.legs[0].contract.strike == 90  # highest strike <= 92, nearest 25d
    assert s.management["cash_reserved"] == pytest.approx(9000.0)


def test_csp_blocks_on_earnings_straddle_name_allows_etf():
    earnings = date(2026, 7, 10)  # before the 38-DTE expiry
    assert wheel_csp.propose(make_ctx(next_earnings=earnings)) is None
    etf = wheel_csp.propose(
        make_ctx(next_earnings=earnings, is_etf=True, instrument_class=InstrumentClass.US_ETF_OPT)
    )
    assert etf is not None


# --------------------------------------------------------------------------- #
# Wheel CC
# --------------------------------------------------------------------------- #
def test_cc_requires_shares():
    assert wheel_cc.propose(make_ctx(core_shares=50)) is None
    s = wheel_cc.propose(make_ctx(core_shares=100))
    assert s.family is Family.WHEEL_CC
    assert s.legs[0].contract.strike == 108  # ~20 delta
    assert s.management["contracts"] == 1
    assert s.management["roll"] == "at 21 DTE or 80% profit"


def test_cc_skips_on_earnings():
    s = wheel_cc.propose(make_ctx(core_shares=100, next_earnings=date(2026, 7, 10)))
    assert s is None


def test_cc_skips_on_exdiv_assignment_window():
    exdiv = Event(symbol="F", date=date(2026, 7, 1), kind=EventKind.DIV,
                  confirmed=True, meta={"amount": 1.50})
    s = wheel_cc.propose(make_ctx(core_shares=100, next_exdiv=exdiv))
    assert s is None  # short call extrinsic 0.90 < dividend 1.50


# --------------------------------------------------------------------------- #
# Collar
# --------------------------------------------------------------------------- #
def test_collar_only_in_defensive_regime():
    assert collar.propose(make_ctx(core_shares=100, market_regime=_CALM)) is None
    assert collar.propose(make_ctx(core_shares=100, market_regime=None)) is None
    s = collar.propose(make_ctx(core_shares=100, market_regime=_DEFENSIVE))
    assert s is not None
    assert s.family is Family.COLLAR
    assert s.legs[0].action is Action.BUY and s.legs[0].contract.right is Right.PUT
    assert s.management["event_driven"] is True


def test_collar_requires_shares():
    assert collar.propose(make_ctx(core_shares=0, market_regime=_DEFENSIVE)) is None


# --------------------------------------------------------------------------- #
# PMCC (default OFF)
# --------------------------------------------------------------------------- #
def test_pmcc_off_by_default():
    assert pmcc.propose(make_ctx(chain=pmcc_chain(), pmcc_enabled=False)) is None


def test_pmcc_when_enabled():
    s = pmcc.propose(make_ctx(chain=pmcc_chain(), pmcc_enabled=True))
    assert s is not None
    assert s.family is Family.PMCC
    assert s.multi_expiry is True
    assert len(s.legs) == 2


# --------------------------------------------------------------------------- #
# Rebalance hook
# --------------------------------------------------------------------------- #
def test_rebalance_routes_underweight_to_csp():
    targets = [
        TargetHoldingCfg(ticker="XLE", target_weight=0.15, acquire_below_price=85, is_etf=True),
        TargetHoldingCfg(ticker="XLF", target_weight=0.15, acquire_below_price=42, is_etf=True),
        TargetHoldingCfg(ticker="TLT", target_weight=0.10, acquire_below_price=95, is_etf=True),
    ]
    nlv = 92000.0
    current = {
        "XLE": 0.0,  # fully underweight -> ACQUIRE_CSP
        "XLF": 0.15 * nlv,  # on target -> HOLD
        "TLT": 0.30 * nlv,  # overweight -> TRIM
    }
    actions = {a.ticker: a for a in detect_rebalance(current, targets, nlv)}
    assert actions["XLE"].action is RebalanceActionType.ACQUIRE_CSP
    assert actions["XLF"].action is RebalanceActionType.HOLD
    assert actions["TLT"].action is RebalanceActionType.TRIM
    assert route_to_csp(list(actions.values())) == ["XLE"]
