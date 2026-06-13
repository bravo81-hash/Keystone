"""Mock-mode demo state — a populated AppState with no TWS required.

Runs the real ranker + alert pipeline against fixture chains/regimes (via the
same code paths as live) so the panels show authentic cards, alerts, and stress.
Lets you explore the whole UI before wiring TWS.
"""

from __future__ import annotations

from datetime import date, timedelta

from core.chain import OptionChain, OptionQuote
from core.context import TradeContext
from core.models import InstrumentClass, Right
from portfolio.account_profiles import AccountProfile, BlockedRule, Pool
from regime.market_regime import classify_market_regime
from regime.stock_regime import stock_regime
from regime.surface import Surface
from selection.ranker import rank
from ui.state import AppState

MOCK_ACCOUNTS = [
    {"account": "MOCK-TRADING", "nlv": 100_000.0},
    {"account": "MOCK-SMSF", "nlv": 92_000.0},
]


def _credit_chain(asof: date) -> OptionChain:
    exp = asof + timedelta(days=45)
    puts = [(100, -0.50, 3.0), (95, -0.30, 1.8), (92, -0.20, 1.2), (90, -0.15, 0.9),
            (87, -0.10, 0.6), (85, -0.07, 0.4), (80, -0.04, 0.2)]
    calls = [(100, 0.50, 3.0), (108, 0.20, 1.2), (113, 0.10, 0.6), (115, 0.07, 0.4)]
    q = [OptionQuote(expiry=exp, strike=k, right=Right.PUT, bid=m, ask=m, delta=d) for k, d, m in puts]
    q += [OptionQuote(expiry=exp, strike=k, right=Right.CALL, bid=m, ask=m, delta=d) for k, d, m in calls]
    return OptionChain(symbol="AAPL", spot=100.0, quotes=q, asof=asof)


def _wheel_chain(asof: date) -> OptionChain:
    exp = asof + timedelta(days=38)
    puts = [(100, -0.50, 3.0), (95, -0.30, 1.6), (93, -0.25, 1.2), (90, -0.20, 0.85)]
    calls = [(100, 0.50, 3.0), (108, 0.20, 0.9)]
    q = [OptionQuote(expiry=exp, strike=k, right=Right.PUT, bid=m, ask=m, delta=d) for k, d, m in puts]
    q += [OptionQuote(expiry=exp, strike=k, right=Right.CALL, bid=m, ask=m, delta=d) for k, d, m in calls]
    return OptionChain(symbol="F", spot=100.0, quotes=q, asof=asof)


def _cards():
    asof = date.today()
    market = classify_market_regime(14, 15, 17, 110, 100, True)  # CALM_TREND
    surf = Surface(ticker="AAPL", iv_9d=0.24, iv_30d=0.25, iv_90d=0.26,
                   slope_9_30=0.01, slope_30_90=0.01, inverted_front=False)
    trading = AccountProfile("MOCK-TRADING", "Trading 1 (mock)", Pool.TRADING, nlv=100_000.0)
    smsf = AccountProfile("MOCK-SMSF", "SMSF (mock)", Pool.INVESTING,
                          blocked_rules=[BlockedRule(InstrumentClass.EU_CASH_INDEX, multi_expiry=True)],
                          nlv=92_000.0)
    aapl = TradeContext(
        symbol="AAPL", account_id="MOCK-TRADING", instrument_class=InstrumentClass.US_EQUITY_OPT,
        chain=_credit_chain(asof), spot=100.0, market_regime=market,
        stock_regime=stock_regime("AAPL", surf, ivr=60.0, vrp_value=0.05),
        per_position_budget=500.0, asof=asof, extras={"tier": "A"},
    )
    smsf_ctx = TradeContext(
        symbol="F", account_id="MOCK-SMSF", instrument_class=InstrumentClass.US_EQUITY_OPT,
        chain=_wheel_chain(asof), spot=100.0, core_shares=100, nlv=92_000.0,
        market_regime=market, asof=asof, extras={"tier": "A"},
    )
    cards = rank([trading, smsf], [aapl, smsf_ctx])
    return market, cards, {"MOCK-TRADING": "Trading 1 (mock)", "MOCK-SMSF": "SMSF (mock)"}


def _alerts():
    from alerts.monitor import run_eod_monitor
    from alerts.triggers import PositionSnapshot

    return run_eod_monitor([
        PositionSnapshot("AAPL", "MOCK-TRADING", entry_credit=1.0, current_mark=0.4),  # INFO
        PositionSnapshot("XLE", "MOCK-TRADING", dte=20),                               # WARN
        PositionSnapshot("F", "MOCK-SMSF", short_right=Right.PUT, short_strike=95,
                         underlying_price=94, atr20=2.0),                              # CRITICAL
    ])


def _stress():
    from config.schema import StressCfg
    from portfolio.stress import StressPosition, stress_book

    book = [
        StressPosition("AAPL", spot=100.0, beta=1.1, delta_shares=-40.0, vega_dollars_per_volpt=-12.0, max_loss=440.0),
        StressPosition("XLE", spot=85.0, beta=0.9, delta_shares=-30.0, vega_dollars_per_volpt=-8.0, max_loss=380.0),
        StressPosition("F", spot=11.0, beta=1.2, delta_shares=22.0, max_loss=900.0,
                       earnings_window=True, implied_move=0.08),
    ]
    return stress_book(book, StressCfg(weekly_pnl_ceiling=2500.0))


def _smsf_holdings():
    from config.loader import load_investing

    out = []
    try:
        for h in load_investing().target_holdings:
            out.append({"ticker": h.ticker, "target_weight": h.target_weight,
                        "current_weight": round(h.target_weight * 0.6, 3), "wheel_state": "CSP open"})
    except Exception:  # noqa: BLE001
        pass
    return out


def build_mock_state() -> AppState:
    """Assemble a fully populated demo AppState (no TWS / network)."""

    market, cards, labels = _cards()
    return AppState(
        market_regime=market,
        screened={
            "AAPL": {"passed": True, "tier": "A", "sector": "Information Technology"},
            "MSFT": {"passed": True, "tier": "A", "sector": "Information Technology"},
            "XLE": {"passed": True, "tier": "A", "sector": "Energy"},
            "PLTR": {"passed": False, "tier": "B", "sector": "Information Technology"},
        },
        cards=cards,
        account_labels=labels,
        book=[
            {"account_id": "MOCK-TRADING", "symbol": "AAPL", "family": "put_credit_spread", "dte": 38, "delta": 0.06, "pnl": 85.0},
            {"account_id": "MOCK-TRADING", "symbol": "XLE", "family": "iron_condor", "dte": 42, "delta": -0.01, "pnl": -40.0},
            {"account_id": "MOCK-SMSF", "symbol": "F", "family": "wheel_csp", "dte": 33, "delta": 0.22, "pnl": 60.0},
        ],
        alerts=_alerts(),
        optionstrat_urls={"AAPL": "https://optionstrat.com/build/custom/AAPL/-.AAPL260730P92,.AAPL260730P87"},
        smsf_holdings=_smsf_holdings(),
        collars=[{"ticker": "XLU", "detail": "long 70P financed by CC (regime DEFENSIVE)"}],
        stress=_stress(),
    )
