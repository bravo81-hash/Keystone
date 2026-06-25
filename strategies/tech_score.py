"""Eight-factor technical momentum score (ported from STFS-EQ indicators.py).

Pure Python — no numpy/pandas. Called by selection.scout on daily OHLC data
fetched via yfinance; also callable in tests with fixture lists.

Factors (match STFS v2.7.pine):
  F1  EMA(8) > EMA(21) > EMA(34)                   daily EMA stack
  F2  weekly close > EMA30w AND EMA10w > EMA30w     weekly trend confirmation
  F3  HMA(15) rising bar-over-bar                   momentum
  F4  ADX(14) > 20 AND strictly rising 2 bars       trend strength
  F5  RSI(14) in [50, 75]                           momentum breadth
  F6  20-day RS > SPY 20-day RS                     relative strength
  F7  OBV > OBV_EMA(21) AND OBV > OBV 20 bars ago  accumulation
  F8  ATR% in [1.5%, 5.0%]                          healthy volatility range

STRONG_BUY: score >= 6 AND trio (F1+F2+F8).
WATCH:      score >= 5 AND F1.
SKIP:       everything else.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TechSignal(str, Enum):
    STRONG_BUY = "STRONG_BUY"
    WATCH = "WATCH"
    SKIP = "SKIP"


@dataclass
class TechScoreResult:
    ticker: str
    spot: float
    f1: bool
    f2: bool
    f3: bool
    f4: bool
    f5: bool
    f6: bool
    f7: bool
    f8: bool
    score: int           # 0-8
    trio: bool           # F1+F2+F8 all true — required for STRONG_BUY
    signal: TechSignal
    atr20: float = 0.0
    atr_pct: float = 0.0
    entry: Optional[float] = None   # close - 1.5*ATR
    stop: Optional[float] = None    # entry - 2.5*ATR
    target: Optional[float] = None  # entry + 4.0*ATR
    recommended_structure: Optional[str] = None
    factors: list[bool] = field(default_factory=list)
    adx: float = 0.0
    rsi: float = 0.0
    vrp: Optional[float] = None  # IV30 - RV20 in decimal (0.05 = 5 vol-points)


# --------------------------------------------------------------------------- #
# Primitive indicators (all return full-length series, oldest-first)
# --------------------------------------------------------------------------- #

def _ema(series: list[float], n: int) -> list[float]:
    """EMA with span=n (alpha = 2/(n+1))."""
    if not series:
        return []
    k = 2.0 / (n + 1)
    out = [series[0]]
    for x in series[1:]:
        out.append(x * k + out[-1] * (1.0 - k))
    return out


def _wilder(series: list[float], n: int) -> list[float]:
    """Wilder's smoothing (alpha = 1/n) — used for ATR, ADX, RSI."""
    if not series:
        return []
    alpha = 1.0 / n
    out = [series[0]]
    for x in series[1:]:
        out.append(x * alpha + out[-1] * (1.0 - alpha))
    return out


def _wma(series: list[float], n: int) -> list[Optional[float]]:
    """Weighted MA; first n-1 entries are None."""
    weights = list(range(1, n + 1))
    w_sum = float(sum(weights))
    out: list[Optional[float]] = [None] * (n - 1)
    for i in range(n - 1, len(series)):
        out.append(sum(w * v for w, v in zip(weights, series[i - n + 1: i + 1])) / w_sum)
    return out


def _hma(series: list[float], n: int) -> list[Optional[float]]:
    """Hull MA = WMA(2·WMA(n/2) - WMA(n), sqrt(n))."""
    half = max(1, n // 2)
    sq = max(1, int(math.sqrt(n)))
    wh = _wma(series, half)
    wf = _wma(series, n)
    combined: list[Optional[float]] = [
        2.0 * a - b if a is not None and b is not None else None
        for a, b in zip(wh, wf)
    ]
    valid: list[float] = [v for v in combined if v is not None]  # type: ignore[misc]
    if len(valid) < sq:
        return [None] * len(series)
    hull_raw = _wma(valid, sq)
    n_nones = sum(1 for v in combined if v is None)
    return [None] * n_nones + list(hull_raw)


def _rsi(closes: list[float], n: int = 14) -> list[float]:
    if len(closes) < 2:
        return [50.0] * len(closes)
    diffs = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    su = _wilder([max(0.0, d) for d in diffs], n)
    sd = _wilder([max(0.0, -d) for d in diffs], n)
    out = [50.0]
    for u, d in zip(su, sd):
        out.append(100.0 if d == 0.0 else 100.0 - 100.0 / (1.0 + u / d))
    return out


def _atr(highs: list[float], lows: list[float], closes: list[float], n: int = 14) -> list[float]:
    trs = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        trs.append(max(highs[i] - lows[i],
                       abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])))
    return _wilder(trs, n)


def _adx(highs: list[float], lows: list[float], closes: list[float], n: int = 14) -> list[float]:
    """ADX series; padded with 0.0 at index 0 to match closes length."""
    if len(closes) < 2:
        return [0.0] * len(closes)
    pdm, mdm, trs = [], [], []
    for i in range(1, len(highs)):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        pdm.append(up if up > dn and up > 0.0 else 0.0)
        mdm.append(dn if dn > up and dn > 0.0 else 0.0)
        trs.append(max(highs[i] - lows[i],
                       abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])))
    tr_s, pdm_s, mdm_s = _wilder(trs, n), _wilder(pdm, n), _wilder(mdm, n)
    dx_list = []
    for tr, p, m in zip(tr_s, pdm_s, mdm_s):
        if tr == 0.0:
            dx_list.append(0.0)
        else:
            pdi, mdi = 100.0 * p / tr, 100.0 * m / tr
            denom = pdi + mdi
            dx_list.append(100.0 * abs(pdi - mdi) / denom if denom > 0.0 else 0.0)
    return [0.0] + _wilder(dx_list, n)


def _obv(closes: list[float], volumes: list[float]) -> list[float]:
    out = [0.0]
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        out.append(out[-1] + (volumes[i] if d > 0 else (-volumes[i] if d < 0 else 0.0)))
    return out


# --------------------------------------------------------------------------- #
# Structure recommendation
# --------------------------------------------------------------------------- #

def _structure_for_vrp(vrp: Optional[float]) -> str:
    """Mirrors STFS-EQ IVP quartile→structure mapping via VRP heuristic.

    VRP in decimal form: 0.08 = 8 vol-points.
    """
    if vrp is None:
        return "credit_spread"
    if vrp > 0.08:
        return "credit_spread (implied rich — sell premium)"
    if vrp > 0.02:
        return "credit_spread or debit_spread"
    return "trend_long (implied cheap — buy call/debit spread)"


# --------------------------------------------------------------------------- #
# Main scorer
# --------------------------------------------------------------------------- #

def compute_tech_score(
    ticker: str,
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    spy_closes: list[float],
    weekly_closes: list[float],
    *,
    vrp: Optional[float] = None,
) -> TechScoreResult:
    """Compute the 8-factor score for the *latest* bar.

    All series must be oldest-first. ``weekly_closes`` must be pre-resampled
    by the caller (calendar-week end prices). Minimum 35 daily bars required;
    returns SKIP on insufficient history.
    """
    spot = closes[-1] if closes else 0.0
    n = len(closes)

    if n < 35 or not highs or not lows or not volumes:
        return TechScoreResult(
            ticker=ticker, spot=spot,
            f1=False, f2=False, f3=False, f4=False,
            f5=False, f6=False, f7=False, f8=False,
            score=0, trio=False, signal=TechSignal.SKIP, factors=[False] * 8,
        )

    # F1 — EMA(8) > EMA(21) > EMA(34)
    f1 = _ema(closes, 8)[-1] > _ema(closes, 21)[-1] > _ema(closes, 34)[-1]

    # F2 — weekly: close > EMA30w AND EMA10w > EMA30w
    if len(weekly_closes) >= 30:
        ema10w = _ema(weekly_closes, 10)[-1]
        ema30w = _ema(weekly_closes, 30)[-1]
        f2 = weekly_closes[-1] > ema30w and ema10w > ema30w
    else:
        f2 = False

    # F3 — HMA(15) rising
    hull = _hma(closes, 15)
    valid_hull = [v for v in hull if v is not None]
    f3 = len(valid_hull) >= 2 and valid_hull[-1] > valid_hull[-2]  # type: ignore[operator]

    # F4 — ADX(14) > 20 and strictly rising 2 bars
    adx_s = _adx(highs, lows, closes, 14)
    adx_now = adx_s[-1] if adx_s else 0.0
    adx_p1 = adx_s[-2] if len(adx_s) >= 2 else 0.0
    adx_p2 = adx_s[-3] if len(adx_s) >= 3 else 0.0
    f4 = adx_now > 20.0 and adx_now > adx_p1 > adx_p2

    # F5 — RSI(14) in [50, 75]
    rsi_now = _rsi(closes, 14)[-1]
    f5 = 50.0 <= rsi_now <= 75.0

    # F6 — 20-day RS > SPY 20-day RS
    min_len = min(len(closes), len(spy_closes))
    if min_len >= 21:
        cl, sp = closes[-min_len:], spy_closes[-min_len:]
        rs_t = (cl[-1] / cl[-21] - 1.0) if cl[-21] > 0 else 0.0
        rs_spy = (sp[-1] / sp[-21] - 1.0) if sp[-21] > 0 else 0.0
        f6 = rs_t > rs_spy
    else:
        f6 = False

    # F7 — OBV > OBV_EMA(21) and OBV > OBV 20 bars ago
    obv_s = _obv(closes, volumes)
    obv_ema = _ema(obv_s, 21)
    f7 = len(obv_s) >= 21 and obv_s[-1] > obv_ema[-1] and obv_s[-1] > obv_s[-21]

    # F8 — ATR% in [1.5%, 5.0%]
    atr_s = _atr(highs, lows, closes, 14)
    atr_now = atr_s[-1]
    atr_pct = (atr_now / spot * 100.0) if spot > 0 else 0.0
    f8 = 1.5 <= atr_pct <= 5.0

    factors = [f1, f2, f3, f4, f5, f6, f7, f8]
    score = sum(factors)
    trio = f1 and f2 and f8

    if score >= 6 and trio:
        signal = TechSignal.STRONG_BUY
    elif score >= 5 and f1:
        signal = TechSignal.WATCH
    else:
        signal = TechSignal.SKIP

    entry = spot - 1.5 * atr_now
    stop = entry - 2.5 * atr_now
    target = entry + 4.0 * atr_now

    return TechScoreResult(
        ticker=ticker, spot=spot,
        f1=f1, f2=f2, f3=f3, f4=f4, f5=f5, f6=f6, f7=f7, f8=f8,
        score=score, trio=trio, signal=signal,
        atr20=atr_now, atr_pct=atr_pct,
        entry=entry, stop=stop, target=target,
        recommended_structure=_structure_for_vrp(vrp),
        factors=factors, adx=adx_now, rsi=rsi_now, vrp=vrp,
    )
