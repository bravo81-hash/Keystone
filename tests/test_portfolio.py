"""Stage 8: budgets (trading + SMSF buckets), stress, fit filter."""

from __future__ import annotations

import pytest

from config.schema import RiskConfig, SMSFBudgetCfg, StressCfg, TradingBudgetCfg
from core.models import Family, InstrumentClass, Suggestion
from portfolio.budgets import BookItem, check_smsf_budget, check_trading_budget
from portfolio.fit import fit
from portfolio.index_book import ingest_index_book
from portfolio.stress import (
    StressPosition,
    beta_60d,
    market_row_pnl,
    stress_book,
    worst_single_name,
)
from store.db import init_db

TRADING = TradingBudgetCfg()
SMSF = SMSFBudgetCfg()
NLV = 100_000.0


def bi(symbol, sector, family, *, max_loss=0.0, sleeve="short_premium", is_etf=False,
       cash_reserved=0.0, notional=0.0) -> BookItem:
    return BookItem(symbol=symbol, sector=sector, family=family, max_loss=max_loss,
                    sleeve=sleeve, is_etf=is_etf, cash_reserved=cash_reserved, notional=notional)


# --------------------------------------------------------------------------- #
# Trading buckets
# --------------------------------------------------------------------------- #
def test_per_position_cap():
    big = bi("AAPL", "IT", Family.PUT_CREDIT_SPREAD, max_loss=1500)  # > 1% of 100k
    assert check_trading_budget(big, [], TRADING, NLV).ok is False
    small = bi("AAPL", "IT", Family.PUT_CREDIT_SPREAD, max_loss=800)
    assert check_trading_budget(small, [], TRADING, NLV).ok is True


def test_aggregate_short_premium_cap():
    book = [bi(f"N{i}", "Financials", Family.IRON_CONDOR, max_loss=900) for i in range(6)]  # 5400
    cand = bi("AAPL", "IT", Family.PUT_CREDIT_SPREAD, max_loss=900)  # -> 6300 > 6000
    check = check_trading_budget(cand, book[:5], TRADING, NLV)  # 4500 + 900 = 5400 ok
    assert check.ok is True
    over = check_trading_budget(cand, book, TRADING, NLV)  # 5400 + 900 = 6300 > 6000
    assert over.ok is False
    assert any("short-premium" in b for b in over.breaches)


def test_trend_sleeve_cap():
    book = [bi("MSFT", "IT", Family.TREND_LEAPS, max_loss=4800, sleeve="trend")]
    cand = bi("NVDA", "IT", Family.TREND_DEBIT_SPREAD, max_loss=400, sleeve="trend")  # 5200 > 5000
    # different sectors to avoid sector-cap noise
    cand.sector = "Energy"
    assert check_trading_budget(cand, book, TRADING, NLV).ok is False


def test_position_count_cap():
    book = [bi(f"N{i}", f"S{i}", Family.IRON_CONDOR, max_loss=100) for i in range(6)]
    cand = bi("AAPL", "IT", Family.PUT_CREDIT_SPREAD, max_loss=100)
    assert check_trading_budget(cand, book, TRADING, NLV).ok is False  # 7 > 6


def test_sector_cap():
    book = [bi("AAPL", "IT", Family.IRON_CONDOR, max_loss=100),
            bi("MSFT", "IT", Family.IRON_CONDOR, max_loss=100)]
    cand = bi("NVDA", "IT", Family.PUT_CREDIT_SPREAD, max_loss=100)  # 3rd IT name
    check = check_trading_budget(cand, book, TRADING, NLV)
    assert check.ok is False
    assert any("sector" in b for b in check.breaches)


def test_correlation_cap():
    book = [bi("AAPL", "IT", Family.IRON_CONDOR, max_loss=100)]
    cand = bi("MSFT", "Financials", Family.PUT_CREDIT_SPREAD, max_loss=100)
    corr = lambda a, b: 0.85  # above the 0.7 cap
    assert check_trading_budget(cand, book, TRADING, NLV, correlation_fn=corr).ok is False


# --------------------------------------------------------------------------- #
# SMSF buckets — ETF vs single-name notional branch
# --------------------------------------------------------------------------- #
def test_smsf_single_name_notional_cap():
    cand = bi("F", "Discretionary", Family.WHEEL_CSP, is_etf=False, notional=12000, cash_reserved=12000)
    assert check_smsf_budget(cand, [], SMSF, 92000.0).ok is False  # > 12% of 92k = 11040


def test_smsf_etf_notional_branch_allows_more():
    cand = bi("XLE", "Energy", Family.WHEEL_CSP, is_etf=True, notional=12000, cash_reserved=12000)
    assert check_smsf_budget(cand, [], SMSF, 92000.0).ok is True  # <= 25% of 92k = 23000
    big_etf = bi("XLE", "Energy", Family.WHEEL_CSP, is_etf=True, notional=24000, cash_reserved=24000)
    assert check_smsf_budget(big_etf, [], SMSF, 92000.0).ok is False  # > 23000


def test_smsf_csp_cash_reserve_cap():
    book = [bi("XLF", "Financials", Family.WHEEL_CSP, cash_reserved=50000, notional=4000)]
    cand = bi("XLU", "Utilities", Family.WHEEL_CSP, cash_reserved=9300, notional=4000)  # 59300 > 55200
    assert check_smsf_budget(cand, book, SMSF, 92000.0).ok is False


# --------------------------------------------------------------------------- #
# Stress
# --------------------------------------------------------------------------- #
def test_beta_60d():
    rets = [0.01, -0.01] * 35  # 70 returns, non-zero variance
    spy, name = [100.0], [100.0]
    for r in rets:
        spy.append(spy[-1] * (1 + r))
        name.append(name[-1] * (1 + 2 * r))  # exactly 2x SPY returns
    assert beta_60d(name, spy) == pytest.approx(2.0, abs=1e-6)


def test_market_row_pnl_beta_mapped():
    # long 100 share-equivalents, beta 1.0, -5% spot, no vega.
    pos = StressPosition(symbol="X", spot=100.0, beta=1.0, delta_shares=100.0)
    assert market_row_pnl([pos]) == pytest.approx(-500.0)  # 100 * (100*-0.05)


def test_worst_single_name_selection():
    a = StressPosition(symbol="AAA", spot=100.0, delta_shares=-50.0, max_loss=500.0)
    b = StressPosition(symbol="BBB", spot=100.0, delta_shares=-200.0, max_loss=2000.0)
    sym, pnl = worst_single_name([a, b])
    assert sym == "BBB"
    assert pnl == pytest.approx(-2000.0)  # floored at defined max-loss


def test_earnings_window_widens_shock():
    base = StressPosition(symbol="C", spot=100.0, delta_shares=-100.0, max_loss=5000.0)
    earn = StressPosition(symbol="C", spot=100.0, delta_shares=-100.0, max_loss=5000.0,
                          earnings_window=True, implied_move=0.20)  # 1.5*0.20 = 0.30 move
    _, base_pnl = worst_single_name([base])  # 0.15 gap -> -1500
    _, earn_pnl = worst_single_name([earn])  # 0.30 move -> -3000
    assert base_pnl == pytest.approx(-1500.0)
    assert earn_pnl == pytest.approx(-3000.0)
    assert earn_pnl < base_pnl


def test_stress_ceiling():
    pos = StressPosition(symbol="X", spot=100.0, beta=1.0, delta_shares=300.0)  # -1500 market
    res = stress_book([pos], StressCfg(weekly_pnl_ceiling=1000.0))
    assert res.market_pnl == pytest.approx(-1500.0)
    assert res.market_within_ceiling is False


# --------------------------------------------------------------------------- #
# Fit filter
# --------------------------------------------------------------------------- #
def _suggestion(max_loss: float) -> Suggestion:
    return Suggestion(
        symbol="AAPL", account_id="T1", family=Family.PUT_CREDIT_SPREAD, legs=[],
        instrument_class=InstrumentClass.US_EQUITY_OPT, max_loss=max_loss,
    )


def test_fit_filters_breach_and_logs():
    db = init_db(":memory:")
    cfg = RiskConfig()
    breach = fit(_suggestion(1500), [], cfg, NLV, pool="trading", sector="IT", db=db)
    assert breach.ok is False and breach.breaches
    rows = db.query("SELECT reason FROM blocked_structures")
    assert len(rows) == 1 and rows[0]["reason"].startswith("budget:")

    ok = fit(_suggestion(800), [], cfg, NLV, pool="trading", sector="IT", db=db)
    assert ok.ok is True and ok.breaches == []


def test_index_book_ingest_disabled():
    assert ingest_index_book(RiskConfig().index_book_ingest) == []
