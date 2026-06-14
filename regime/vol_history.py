"""IV history (IVR / IV percentile), realized vol, and per-stock VRP.

Data (one request per ticker per week, TTL-cached):
  * IV history: reqHistoricalData ``OPTION_IMPLIED_VOLATILITY``, 1yr daily.
  * Daily TRADES history: 1yr daily — the SAME fetch feeds 20d realized vol AND
    the Stage 2 earnings realized-moves (callers fetch once, use twice).

Metrics:
  * IVR (rank) = 100 * (iv - min) / (max - min) over the window.
  * IV percentile = 100 * fraction of days with iv below current.
  * RV20 = annualized stdev of the last 20 close-to-close log returns.
  * VRP = IV30 - RV20 (vol points; positive => implied richer than realized).

Pacing math (the Stage 3 audit; see tests/test_pacing.py):
  Weekly refresh of N names costs, per name and ONCE per week given the caches:
    1 chain (Fridays-only)  +  1 IV-history  +  1 daily-history  = 3 metadata reqs.
  For N=80 that is 80 CHAIN + 160 HISTORICAL = 240 metadata requests/week, plus
  ATM+25D quote snapshots issued via fetch_quotes (batched 40-and-cancel). TWS
  pacing (~60 identical historical/10min, 50 simultaneous, 100 market-data lines)
  is never approached at a weekly cadence with caches warm.
"""

from __future__ import annotations

import math
from statistics import stdev
from typing import Any, Optional

from core.ib_client import ReqKind
from core.models import Contract, DailyBar

TRADING_DAYS = 252
RV_WINDOW = 20

#: Documented per-name weekly metadata request budget (chain + iv-hist + daily).
WEEKLY_METADATA_PER_NAME = 3


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def iv_rank(series: list[float], current: Optional[float] = None) -> float:
    """IV rank in [0, 100]: where ``current`` sits between the window min and max."""

    if not series:
        return 0.0
    cur = series[-1] if current is None else current
    lo, hi = min(series), max(series)
    if hi <= lo:
        return 0.0
    return 100.0 * (cur - lo) / (hi - lo)


def iv_percentile(series: list[float], current: Optional[float] = None) -> float:
    """IV percentile in [0, 100]: fraction of window days with IV below current."""

    if not series:
        return 0.0
    cur = series[-1] if current is None else current
    below = sum(1 for v in series if v < cur)
    return 100.0 * below / len(series)


def realized_vol(closes: list[float], window: int = RV_WINDOW, trading_days: int = TRADING_DAYS) -> Optional[float]:
    """Annualized close-to-close realized vol over the last ``window`` returns."""

    if len(closes) < window + 1:
        return None
    rets = [
        math.log(closes[i] / closes[i - 1])
        for i in range(len(closes) - window, len(closes))
        if closes[i - 1] > 0 and closes[i] > 0
    ]
    if len(rets) < 2:
        return None
    return stdev(rets) * math.sqrt(trading_days)


def realized_vol_from_bars(bars: list[DailyBar], window: int = RV_WINDOW) -> Optional[float]:
    closes = [b.close for b in sorted(bars, key=lambda b: b.date)]
    return realized_vol(closes, window)


def vrp(iv30: float, rv20: float) -> float:
    """Volatility risk premium in vol points: IV30 - RV20 (positive = implied rich)."""

    return iv30 - rv20


def realized_vol_series(closes: list[float], window: int = RV_WINDOW) -> list[float]:
    """Rolling annualized realized vol across the close series."""

    out: list[float] = []
    for i in range(window, len(closes)):
        rv = realized_vol(closes[i - window : i + 1], window)
        if rv is not None:
            out.append(rv)
    return out


def realized_vol_rank(closes: list[float], window: int = RV_WINDOW) -> Optional[float]:
    """0-100 rank of the latest realized vol within its own history.

    A free-data proxy for IVR when 1yr OPTION_IMPLIED_VOLATILITY history isn't
    available (yfinance mode). High = realized vol is elevated vs its own year.
    """

    series = realized_vol_series(closes, window)
    if len(series) < 2:
        return None
    cur, lo, hi = series[-1], min(series), max(series)
    if hi <= lo:
        return 50.0
    return 100.0 * (cur - lo) / (hi - lo)


# --------------------------------------------------------------------------- #
# Cached fetchers (one request/ticker/week)
# --------------------------------------------------------------------------- #
def fetch_iv_history(
    ib_client: Any,
    symbol: str,
    *,
    cache: Any = None,
    duration: str = "1 Y",
    bar_size: str = "1 day",
) -> list[float]:
    """1yr daily ATM IV series (OPTION_IMPLIED_VOLATILITY). Charges HISTORICAL."""

    key = ("iv_hist", symbol.upper())
    if cache is not None:
        cached = cache.get(key)
        if cached is not None:
            return cached
    bars = ib_client.ib.reqHistoricalData(
        Contract.stock(symbol),
        endDateTime="",
        durationStr=duration,
        barSizeSetting=bar_size,
        whatToShow="OPTION_IMPLIED_VOLATILITY",
        useRTH=True,
    )
    ib_client.budget.charge(ReqKind.HISTORICAL)
    series = [float(b.close) for b in bars]
    if cache is not None:
        cache.put(key, series)
    return series


def fetch_daily_history(
    ib_client: Any,
    symbol: str,
    *,
    cache: Any = None,
    duration: str = "1 Y",
    bar_size: str = "1 day",
) -> list[DailyBar]:
    """1yr daily TRADES bars. Shared by RV20 and earnings realized-moves.

    Cached under one key so realized vol and realized earnings-moves reuse a
    single request (no duplicate fetch).
    """

    key = ("daily_trades", symbol.upper())
    if cache is not None:
        cached = cache.get(key)
        if cached is not None:
            return cached
    raw = ib_client.ib.reqHistoricalData(
        Contract.stock(symbol),
        endDateTime="",
        durationStr=duration,
        barSizeSetting=bar_size,
        whatToShow="TRADES",
        useRTH=True,
    )
    ib_client.budget.charge(ReqKind.HISTORICAL)
    bars = [b if isinstance(b, DailyBar) else DailyBar(**b) for b in raw]
    if cache is not None:
        cache.put(key, bars)
    return bars
