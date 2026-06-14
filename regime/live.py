"""Live market-regime fetch from a MarketData source (yfinance/TWS).

Pulls the VIX complex (VIX9D/VIX/VIX3M) and SPY vs its 200DMA, then runs the
pure classifier. Works from free yfinance data, so it populates the dashboard's
regime read even without TWS market-data subscriptions (and over the weekend
using Friday's closes).
"""

from __future__ import annotations

from statistics import mean
from typing import Any, Optional

from regime.market_regime import MarketRegime, classify_market_regime

VIX, VIX9D, VIX3M, SPY = "^VIX", "^VIX9D", "^VIX3M", "SPY"


def fetch_market_regime(md: Any) -> tuple[Optional[MarketRegime], dict]:
    """Return (MarketRegime | None, details). None if VIX/SPY data is unavailable."""

    def price(symbol: str) -> Optional[float]:
        dp = md.last_price(symbol)
        return dp.value if dp is not None else None

    vix = price(VIX)
    vix9d = price(VIX9D) or vix  # fall back to 30d if the 9d index is missing
    vix3m = price(VIX3M) or vix
    details: dict = {"vix9d": vix9d, "vix": vix, "vix3m": vix3m}

    spy = md.daily_bars(SPY, 260)
    if vix is None or spy is None:
        details["error"] = "VIX or SPY data unavailable"
        return None, details

    closes = [b.close for b in spy.value if b.close > 0]
    if len(closes) < 200:
        details["error"] = f"only {len(closes)} SPY closes (<200)"
        return None, details

    ma200 = mean(closes[-200:])
    prev_ma = mean(closes[-220:-20]) if len(closes) >= 220 else ma200
    ma_rising = ma200 > prev_ma
    spot = closes[-1]

    regime = classify_market_regime(vix9d, vix, vix3m, spot, ma200, ma_rising)
    details.update(spot=spot, ma200=round(ma200, 2), ma_rising=ma_rising, source=spy.source)
    return regime, details
