"""Whole-book volatility estimate + measured cross-engine correlation.

The portfolio vol estimate blends:
  * realized — annualized close-to-close vol of the book's NLV return series
    (20-60d window), via ``regime.vol_history.realized_vol``.
  * implied  — VIX-complex level (decimalized) optionally nudged by the book's
    net vega so a vega-heavy book reads richer/cheaper than the index alone.

Diversification is MEASURED, not assumed: ``correlation_matrix`` builds the
pairwise correlation of the engines' return streams from cached returns, so the
allocator can see how much the engines actually co-move.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from regime.vol_history import realized_vol

DEFAULT_REALIZED_WEIGHT = 0.5


def implied_vol_from_vix(vix_level: float, *, net_vega_dollars: float = 0.0,
                         nlv: float = 0.0) -> float:
    """Annualized implied vol from the VIX level (decimalized), nudged by net vega.

    Long net vega (positive) shaves the implied estimate slightly (the book gains
    when vol rises); short net vega lifts it. The nudge is bounded to +/-20%.
    """

    base = max(0.0, vix_level / 100.0)
    if nlv > 0 and net_vega_dollars != 0.0:
        # vega per NLV, scaled into a bounded multiplicative nudge
        nudge = max(-0.2, min(0.2, -(net_vega_dollars / nlv)))
        base *= (1.0 + nudge)
    return base


def blend_vol(realized_v: Optional[float], implied_v: Optional[float],
              w_realized: float = DEFAULT_REALIZED_WEIGHT) -> float:
    """Weighted blend of realized + implied vol. Falls back to whichever exists."""

    if realized_v is None and implied_v is None:
        return 0.0
    if realized_v is None:
        return float(implied_v)
    if implied_v is None:
        return float(realized_v)
    w = max(0.0, min(1.0, w_realized))
    return w * realized_v + (1.0 - w) * implied_v


@dataclass
class PortfolioVol:
    realized: Optional[float]
    implied: Optional[float]
    blended: float


def portfolio_vol_estimate(
    nlv_returns: list[float],
    vix_level: float,
    *,
    window: int = 20,
    w_realized: float = DEFAULT_REALIZED_WEIGHT,
    net_vega_dollars: float = 0.0,
    nlv: float = 0.0,
) -> PortfolioVol:
    """Blend realized (from the NLV return series) + implied (VIX) vol.

    ``nlv_returns`` are daily fractional returns of the book; they are converted
    to a synthetic close series for the realized-vol helper.
    """

    realized_v: Optional[float] = None
    if len(nlv_returns) >= window + 1:
        closes = [100.0]
        for r in nlv_returns:
            closes.append(closes[-1] * (1.0 + r))
        realized_v = realized_vol(closes, window)
    implied_v = implied_vol_from_vix(vix_level, net_vega_dollars=net_vega_dollars, nlv=nlv)
    return PortfolioVol(realized_v, implied_v, blend_vol(realized_v, implied_v, w_realized))


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = min(len(xs), len(ys))
    if n < 2:
        return 0.0
    xs, ys = xs[-n:], ys[-n:]
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    vx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    vy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if vx == 0 or vy == 0:
        return 0.0
    return cov / (vx * vy)


def correlation_matrix(returns_by_engine: dict[str, list[float]]) -> dict[str, dict[str, float]]:
    """Pairwise Pearson correlation of the engines' return streams (measured
    diversification). Diagonal is 1.0; symmetric."""

    names = list(returns_by_engine)
    out: dict[str, dict[str, float]] = {a: {} for a in names}
    for i, a in enumerate(names):
        for b in names[i:]:
            corr = 1.0 if a == b else _pearson(returns_by_engine[a], returns_by_engine[b])
            out[a][b] = corr
            out[b][a] = corr
    return out
