"""Regime blend + hard-skip veto.

Stock entry score = 0.4 * market + 0.6 * stock_regime, each a [0, 1] score.

Two doctrines enforced here:
  * Market HARD_SKIP vetoes ALL new entries in both sleeves — the blended score
    is forced to 0 and ``vetoed`` is True, regardless of how good the stock
    looks. Forced cadence never overrides SKIP.
  * Market DEFENSIVE (non-skip) raises a flag the SMSF collar logic consumes
    (Stage 7); it does not veto, it just colours the score and signals defence.
"""

from __future__ import annotations

from pydantic import BaseModel

from regime.market_regime import MarketRegime, MarketRegimeState
from regime.stock_regime import StockRegime, StockRegimeState

MARKET_WEIGHT = 0.4
STOCK_WEIGHT = 0.6

STOCK_SCORES: dict[StockRegimeState, float] = {
    StockRegimeState.PREMIUM_RICH: 1.0,
    StockRegimeState.PREMIUM_FAIR: 0.7,
    StockRegimeState.NEUTRAL: 0.5,
    StockRegimeState.PREMIUM_THIN: 0.2,
    StockRegimeState.EARNINGS_BLACKOUT: 0.0,
}


class BlendResult(BaseModel):
    score: float
    vetoed: bool  # market HARD_SKIP -> no new entries
    defensive: bool  # market DEFENSIVE -> SMSF collar flag (Stage 7)
    market_state: MarketRegimeState
    stock_state: StockRegimeState


def stock_regime_score(stock: StockRegime) -> float:
    return STOCK_SCORES[stock.state]


def blended_score(market_score: float, stock_score: float) -> float:
    return MARKET_WEIGHT * market_score + STOCK_WEIGHT * stock_score


def blend(market: MarketRegime, stock: StockRegime) -> BlendResult:
    """Blend the market gate and per-stock regime into one entry decision."""

    vetoed = market.is_hard_skip
    raw = blended_score(market.score, stock_regime_score(stock))
    return BlendResult(
        score=0.0 if vetoed else raw,
        vetoed=vetoed,
        defensive=market.is_defensive,
        market_state=market.state,
        stock_state=stock.state,
    )
