"""Market regime gate — the on/off switch for ALL new entries.

Two inputs, lightweight by design:
  * VIX complex term structure (VIX9D / VIX / VIX3M): contango is calm,
    backwardation (front above back) is stress.
  * Trend filter: a broad index vs its 200DMA, and whether the 200DMA is rising.

Output is one of four states with an explicit HARD_SKIP and DEFENSIVE set:
  CALM_TREND  contango + uptrend         (risk-on)
  NEUTRAL     no stress, no clean trend
  DEFENSIVE   a single stress signal     (raises the SMSF collar flag, Stage 7)
  HARD_SKIP   backwardation + trend break (vetoes all new entries, never softened)

A numeric ``score`` in [0, 1] feeds the 0.4/0.6 blend (regime.blend).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class MarketRegimeState(str, Enum):
    CALM_TREND = "CALM_TREND"
    NEUTRAL = "NEUTRAL"
    DEFENSIVE = "DEFENSIVE"
    HARD_SKIP = "HARD_SKIP"


HARD_SKIP_STATES = frozenset({MarketRegimeState.HARD_SKIP})
DEFENSIVE_STATES = frozenset({MarketRegimeState.DEFENSIVE})

MARKET_SCORES: dict[MarketRegimeState, float] = {
    MarketRegimeState.CALM_TREND: 1.0,
    MarketRegimeState.NEUTRAL: 0.6,
    MarketRegimeState.DEFENSIVE: 0.3,
    MarketRegimeState.HARD_SKIP: 0.0,
}


class MarketRegime(BaseModel):
    state: MarketRegimeState
    score: float
    is_hard_skip: bool
    is_defensive: bool
    # component flags (for transparency on the dashboard)
    term_front_backwardated: bool  # VIX9D > VIX
    term_full_backwardated: bool  # VIX > VIX3M
    above_ma: bool
    uptrend: bool
    downtrend: bool
    meta: dict = Field(default_factory=dict)


def classify_market_regime(
    vix9d: float,
    vix: float,
    vix3m: float,
    index_price: float,
    ma200: float,
    ma200_rising: bool,
) -> MarketRegime:
    """Classify the market regime from the VIX complex + index trend."""

    front_back = vix9d > vix
    full_back = vix > vix3m
    above = index_price >= ma200
    uptrend = above and ma200_rising
    downtrend = (not above) and (not ma200_rising)

    if (full_back and downtrend) or (full_back and not above):
        state = MarketRegimeState.HARD_SKIP
    elif front_back or full_back or downtrend or (not above):
        state = MarketRegimeState.DEFENSIVE
    elif uptrend and not front_back and not full_back:
        state = MarketRegimeState.CALM_TREND
    else:
        state = MarketRegimeState.NEUTRAL

    return MarketRegime(
        state=state,
        score=MARKET_SCORES[state],
        is_hard_skip=state in HARD_SKIP_STATES,
        is_defensive=state in DEFENSIVE_STATES,
        term_front_backwardated=front_back,
        term_full_backwardated=full_back,
        above_ma=above,
        uptrend=uptrend,
        downtrend=downtrend,
    )
