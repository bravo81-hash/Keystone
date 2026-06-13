"""Stage 12: end-to-end smoke (MockIB) — the whole chain, transmit=False.

screened universe -> regimes -> ranker (account mandates) -> cards exclude
impermissible structures -> budgets enforced -> stage_to_tws (transmit=False) ->
store rows + an alert cycle producing INFO / WARN / CRITICAL on seeded positions.
"""

from __future__ import annotations

from datetime import date, timedelta

from config.schema import RiskConfig, UniverseConfig
from core.chain import OptionChain, OptionQuote
from core.context import TradeContext
from core.ib_client import IBClient, MockIB
from core.models import Event, EventKind, InstrumentClass, Right
from portfolio.account_profiles import AccountProfile, BlockedRule, Pool
from regime.market_regime import classify_market_regime
from regime.stock_regime import stock_regime
from regime.surface import Surface
from selection.ranker import SMSF_FAMILIES, TRADING_FAMILIES, rank
from store.db import init_db
from universe.screen import TickerSnapshot, run_screen
from universe.seed import by_ticker
from execution.stage import stage_to_tws
from alerts.monitor import run_eod_monitor
from alerts.triggers import PositionSnapshot, Severity

ASOF = date(2026, 6, 15)
CS_EXP = date(2026, 7, 30)
WHEEL_EXP = date(2026, 7, 23)
CONFIRMED = lambda t: Event(symbol=t, date=date(2026, 12, 1), kind=EventKind.EARNINGS, confirmed=True)


def _credit_chain() -> OptionChain:
    puts = [(100, -0.50, 3.0), (95, -0.30, 1.8), (92, -0.20, 1.2), (90, -0.15, 0.9),
            (87, -0.10, 0.6), (85, -0.07, 0.4), (80, -0.04, 0.2)]
    calls = [(100, 0.50, 3.0), (108, 0.20, 1.2), (113, 0.10, 0.6)]
    q = [OptionQuote(expiry=CS_EXP, strike=k, right=Right.PUT, bid=m, ask=m, delta=d) for k, d, m in puts]
    q += [OptionQuote(expiry=CS_EXP, strike=k, right=Right.CALL, bid=m, ask=m, delta=d) for k, d, m in calls]
    return OptionChain(symbol="AAPL", spot=100.0, quotes=q, asof=ASOF)


def _wheel_chain() -> OptionChain:
    puts = [(100, -0.50, 3.0), (95, -0.30, 1.6), (93, -0.25, 1.2), (90, -0.20, 0.85)]
    calls = [(100, 0.50, 3.0), (108, 0.20, 0.9)]
    q = [OptionQuote(expiry=WHEEL_EXP, strike=k, right=Right.PUT, bid=m, ask=m, delta=d) for k, d, m in puts]
    q += [OptionQuote(expiry=WHEEL_EXP, strike=k, right=Right.CALL, bid=m, ask=m, delta=d) for k, d, m in calls]
    return OptionChain(symbol="F", spot=100.0, quotes=q, asof=ASOF)


def _passing_snapshot(ticker: str) -> TickerSnapshot:
    return TickerSnapshot(
        ticker=ticker, last_price=100.0,
        atm_bid_front=1.00, atm_ask_front=1.04, atm_bid_back=2.00, atm_ask_back=2.12,
        weekly_expiries=[ASOF + timedelta(days=7 * i) for i in range(1, 5)],
        option_adv=10000.0, open_interest_atm=5000,
    )


def _trading_regime():
    surf = Surface(ticker="AAPL", iv_9d=0.24, iv_30d=0.25, iv_90d=0.26,
                   slope_9_30=0.01, slope_30_90=0.01, inverted_front=False)
    return stock_regime("AAPL", surf, ivr=60.0, vrp_value=0.05)


def test_end_to_end_smoke():
    db = init_db(":memory:")
    ib = IBClient(ib=MockIB())

    # 1. Screened universe (fixture chains, no live TWS).
    report = run_screen(
        {"AAPL": _passing_snapshot("AAPL"), "F": _passing_snapshot("F")},
        UniverseConfig(),
        get_earnings=CONFIRMED,
    )
    passed = [t for t, e in report["entries"].items() if e["passed"]]
    assert "AAPL" in passed and "F" in passed

    # 2. Profiles + regimes + contexts for the passing universe.
    trading = AccountProfile("T1", "Trading 1", Pool.TRADING, nlv=100_000.0)
    smsf = AccountProfile(
        "SMSF", "SMSF", Pool.INVESTING,
        blocked_rules=[BlockedRule(InstrumentClass.EU_CASH_INDEX, multi_expiry=True)], nlv=92_000.0,
    )
    market = classify_market_regime(14, 15, 17, 110, 100, True)  # CALM
    trading_ctx = TradeContext(
        symbol="AAPL", account_id="T1", instrument_class=InstrumentClass.US_EQUITY_OPT,
        chain=_credit_chain(), spot=100.0, stock_regime=_trading_regime(), market_regime=market,
        per_position_budget=500.0, asof=ASOF, extras={"tier": "A"},
    )
    smsf_ctx = TradeContext(
        symbol="F", account_id="SMSF", instrument_class=InstrumentClass.US_EQUITY_OPT,
        chain=_wheel_chain(), spot=100.0, core_shares=100, nlv=92_000.0,
        market_regime=market, asof=ASOF, extras={"tier": "A"},
    )

    # 3-5. Ranker with mandates -> cards exclude impermissible -> budgets enforced.
    cards = rank([trading, smsf], [trading_ctx, smsf_ctx], cfg=RiskConfig(), db=db)
    assert cards["T1"] and all(c.family in TRADING_FAMILIES for c in cards["T1"])
    assert cards["SMSF"] and all(c.family in SMSF_FAMILIES for c in cards["SMSF"])
    # mandate exclusion: the SMSF never receives a trading family.
    assert all(c.family not in TRADING_FAMILIES for c in cards["SMSF"])

    # 6. Stage the top trading card (transmit=False) and persist whatIf.
    top = cards["T1"][0]
    staged = stage_to_tws(ib, top, db=db)
    assert staged.accepted is True
    assert staged.staged_order.transmit is False
    assert staged.optionstrat_url.startswith("https://optionstrat.com/")
    assert len(db.query("SELECT * FROM whatif_results")) >= 1

    # 7. Alert cycle on seeded positions -> at least one of each severity.
    seeded = [
        PositionSnapshot("AAPL", "T1", entry_credit=1.0, current_mark=0.4),   # INFO  (profit target)
        PositionSnapshot("MSFT", "T1", dte=20),                               # WARN  (must-touch-by)
        PositionSnapshot("NVDA", "T1", entry_credit=1.0, current_mark=2.5),   # CRITICAL (stop)
    ]
    alerts = run_eod_monitor(seeded, db=db)
    severities = {a.severity for a in alerts}
    assert {Severity.INFO, Severity.WARN, Severity.CRITICAL} <= severities
    assert len(db.query("SELECT * FROM alerts")) >= 3


def test_seed_lookup_available_for_e2e():
    # The e2e universe names resolve in the seed (sector/tier for fit + cards).
    assert by_ticker("AAPL") is not None
    assert by_ticker("F") is not None
