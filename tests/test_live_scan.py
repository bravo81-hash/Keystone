"""Live scan: market-regime fetch, yfinance->chain transform, run_checkpoint."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from core.bs_pricing import bs_price
from core.market_data import DataPoint
from core.models import DailyBar, Right
from core.yf_chain import atm_iv_points, build_chain_from_rows
from portfolio.account_profiles import AccountProfile, BlockedRule, Pool
from core.models import InstrumentClass
from regime.live import fetch_market_regime
from selection.live_scan import build_scan_targets, run_checkpoint
from selection.ranker import TRADING_FAMILIES

ASOF = date.today()


def _bars(closes: list[float]) -> list[DailyBar]:
    base = ASOF - timedelta(days=len(closes))
    return [DailyBar(date=base + timedelta(days=i), open=c, high=c, low=c, close=c, volume=0)
            for i, c in enumerate(closes)]


class FakeMD:
    def __init__(self, prices: dict, bars: dict):
        self._prices = prices
        self._bars = bars

    def last_price(self, symbol):
        v = self._prices.get(symbol)
        return DataPoint(v, "fake") if v is not None else None

    def daily_bars(self, symbol, days=300):
        b = self._bars.get(symbol)
        return DataPoint(b, "fake") if b else None


def _dense_chain(symbol="AAPL", spot=100.0, dte=45):
    exp = ASOF + timedelta(days=dte)
    t = dte / 365.0
    rows = []
    for k in range(80, 121):
        for right in (Right.CALL, Right.PUT):
            mid = bs_price(spot, float(k), t, 0.04, 0.30, right)
            rows.append({"expiry": exp, "strike": float(k), "right": right,
                         "bid": round(max(mid * 0.97, 0.01), 2), "ask": round(mid * 1.03 + 0.02, 2),
                         "iv": 0.30})
    return build_chain_from_rows(symbol, spot, rows, ASOF)


# --------------------------------------------------------------------------- #
# Market regime fetch
# --------------------------------------------------------------------------- #
def test_fetch_market_regime_calm():
    closes = [100 + 0.2 * i for i in range(260)]  # rising -> above rising 200DMA
    md = FakeMD({"^VIX": 15.0, "^VIX9D": 14.0, "^VIX3M": 17.0}, {"SPY": _bars(closes)})
    regime, details = fetch_market_regime(md)
    assert regime is not None
    assert regime.state.value == "CALM_TREND"
    assert details["ma_rising"] is True


def test_fetch_market_regime_missing_data():
    regime, details = fetch_market_regime(FakeMD({}, {}))
    assert regime is None
    assert "error" in details


# --------------------------------------------------------------------------- #
# yfinance -> chain transform (BS greeks)
# --------------------------------------------------------------------------- #
def test_build_chain_from_rows_computes_greeks():
    exp = ASOF + timedelta(days=45)
    rows = [
        {"expiry": exp, "strike": 105, "right": Right.CALL, "bid": 1.0, "ask": 1.2, "iv": 0.30},
        {"expiry": exp, "strike": 95, "right": Right.PUT, "bid": 1.0, "ask": 1.2, "iv": 0.30},
        {"expiry": exp, "strike": 0, "right": Right.PUT, "bid": 0, "ask": 0, "iv": 0.30},  # skipped
        {"expiry": exp, "strike": 100, "right": Right.PUT, "bid": 1, "ask": 1.2, "iv": 0.0},  # skipped (no iv)
    ]
    chain = build_chain_from_rows("AAPL", 100.0, rows, ASOF)
    assert len(chain.quotes) == 2
    call = next(q for q in chain.quotes if q.right is Right.CALL)
    put = next(q for q in chain.quotes if q.right is Right.PUT)
    assert call.delta > 0 and put.delta < 0
    assert 0.0 < abs(put.delta) < 0.5


def test_atm_iv_points():
    chain = _dense_chain()
    points = atm_iv_points(chain, ASOF)
    assert len(points) == 1
    days, iv = points[0]
    assert days == 45 and iv == pytest.approx(0.30, abs=1e-6)


# --------------------------------------------------------------------------- #
# run_checkpoint orchestration
# --------------------------------------------------------------------------- #
def _high_vol_closes() -> list[float]:
    calm = [100 + 0.03 * i for i in range(240)]
    swing = []
    base = calm[-1]
    for i in range(25):
        swing.append(round(base * (1.06 if i % 2 == 0 else 0.95), 2))
    return calm + swing


def test_run_checkpoint_produces_cards():
    spy = [100 + 0.2 * i for i in range(260)]
    md = FakeMD(
        {"^VIX": 15.0, "^VIX9D": 14.0, "^VIX3M": 17.0},
        {"SPY": _bars(spy), "AAPL": _bars(_high_vol_closes())},
    )
    trading = AccountProfile("T1", "Trading 1", Pool.TRADING, nlv=100_000.0)
    smsf = AccountProfile("SMSF", "SMSF", Pool.INVESTING,
                          blocked_rules=[BlockedRule(InstrumentClass.EU_CASH_INDEX, multi_expiry=True)],
                          nlv=92_000.0)

    result = run_checkpoint(
        [trading, smsf], [("T1", "AAPL")],
        market_data=md, chain_provider=lambda s: _dense_chain(s) if s == "AAPL" else None,
        get_earnings=None, asof=ASOF,
    )
    assert result.market_regime is not None and result.market_regime.state.value == "CALM_TREND"
    assert result.screened["AAPL"]["passed"] is True
    assert result.cards.get("T1"), "expected trading candidates"
    assert all(c.family in TRADING_FAMILIES for c in result.cards["T1"])


def test_run_checkpoint_handles_no_chain():
    md = FakeMD({"^VIX": 15.0, "^VIX3M": 17.0}, {"SPY": _bars([100 + 0.2 * i for i in range(260)])})
    trading = AccountProfile("T1", "Trading 1", Pool.TRADING, nlv=100_000.0)
    result = run_checkpoint([trading], [("T1", "ZZZZ")], market_data=md,
                            chain_provider=lambda s: None, get_earnings=None, asof=ASOF)
    assert result.screened["ZZZZ"]["passed"] is False
    assert result.errors


def test_build_scan_targets():
    trading = AccountProfile("T1", "T", Pool.TRADING, nlv=100_000.0)
    smsf = AccountProfile("S1", "S", Pool.INVESTING, nlv=92_000.0)
    targets = build_scan_targets([trading, smsf], trading_watchlist=["SPY", "AAPL"], smsf_watchlist=["XLE"])
    assert ("T1", "SPY") in targets and ("T1", "AAPL") in targets
    assert ("S1", "XLE") in targets
