"""Trend state per underlying (for the long-premium convexity sleeve).

UP    : price above a RISING 200DMA + positive momentum  -> calls
DOWN  : price below a FALLING 200DMA                      -> puts
NONE  : neither (no trend convexity entry)
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

MA_WINDOW = 200
SLOPE_LOOKBACK = 20  # bars used to judge whether the MA is rising/falling
MOMENTUM_LOOKBACK = 20


class TrendState(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    NONE = "NONE"


def sma(closes: list[float], window: int) -> Optional[float]:
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def trend_state(
    closes: list[float],
    *,
    ma_window: int = MA_WINDOW,
    slope_lookback: int = SLOPE_LOOKBACK,
    momentum_lookback: int = MOMENTUM_LOOKBACK,
) -> TrendState:
    """Classify the trend from a daily close series."""

    if len(closes) < ma_window + slope_lookback or len(closes) <= momentum_lookback:
        return TrendState.NONE

    ma_now = sma(closes, ma_window)
    ma_prev = sma(closes[:-slope_lookback], ma_window)
    if ma_now is None or ma_prev is None:
        return TrendState.NONE

    price = closes[-1]
    ma_rising = ma_now > ma_prev
    ma_falling = ma_now < ma_prev
    momentum_up = price > closes[-1 - momentum_lookback]

    if price > ma_now and ma_rising and momentum_up:
        return TrendState.UP
    if price < ma_now and ma_falling:
        return TrendState.DOWN
    return TrendState.NONE
