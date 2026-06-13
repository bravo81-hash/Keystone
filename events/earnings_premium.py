"""Earnings-premium machinery (built early; no caller in v1 — see design SS12).

Two pieces:
  * Implied earnings move — the jump the front expiry is pricing, isolated from
    ordinary diffusion by subtracting a no-event total-variance baseline.
  * Realized earnings moves — the last N quarters' |close->open| gaps around
    confirmed earnings dates, and their median.

Used only by a future EVENT family; building it now keeps that option cheap.
"""

from __future__ import annotations

import math
from datetime import date
from statistics import median
from typing import Optional

from core.models import DailyBar


def implied_move_from_ivs(iv_front: float, iv_baseline: float, tenor_years: float) -> float:
    """Implied event move (decimal, ~1 std-dev jump) from front vs baseline IV.

    Front total variance over the tenor contains the event jump; the baseline IV
    (a no-event tenor, e.g. the back month scaled in) does not. The excess total
    variance is the event's variance contribution:

        move = sqrt(max(iv_front^2 - iv_baseline^2, 0) * tenor_years)
    """

    if tenor_years <= 0:
        return 0.0
    excess = iv_front * iv_front - iv_baseline * iv_baseline
    if excess <= 0:
        return 0.0
    return math.sqrt(excess * tenor_years)


def implied_move_from_straddle(straddle_price: float, spot: float) -> float:
    """Rough implied move from the front ATM straddle price: straddle / spot."""

    if spot <= 0:
        return 0.0
    return straddle_price / spot


def realized_earnings_moves(
    bars: list[DailyBar],
    earnings_dates: list[date],
) -> list[float]:
    """|open_after / close_before - 1| for each earnings date covered by ``bars``.

    close_before = close of the latest bar on/before the earnings date;
    open_after  = open of the earliest bar strictly after it (the gap open).
    """

    if not bars:
        return []
    ordered = sorted(bars, key=lambda b: b.date)
    moves: list[float] = []
    for ed in sorted(earnings_dates):
        close_before: Optional[float] = None
        open_after: Optional[float] = None
        for bar in ordered:
            if bar.date <= ed:
                close_before = bar.close
            elif open_after is None:  # first bar strictly after ed
                open_after = bar.open
                break
        if close_before and open_after and close_before > 0:
            moves.append(abs(open_after / close_before - 1.0))
    return moves


def median_realized_move(
    bars: list[DailyBar],
    earnings_dates: list[date],
    *,
    max_quarters: int = 8,
) -> Optional[float]:
    """Median of the most recent ``max_quarters`` realized earnings moves."""

    moves = realized_earnings_moves(bars, earnings_dates)
    if not moves:
        return None
    recent = moves[-max_quarters:]
    return float(median(recent))
