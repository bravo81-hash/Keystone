"""Composite per-stock regime.

Combines the chain/history signals — term slope (surface), IVR bucket, VRP sign,
earnings proximity (days to confirmed earnings), and skew flags — into a state
the ranker maps to selection bias and sizing. No VIX analogue per name; this is
purely bottom-up from the stock's own options.

Vocabulary (``StockRegimeState``):
  PREMIUM_RICH    elevated/high IVR with positive VRP  -> favor short premium
  PREMIUM_FAIR    middling IVR, non-negative VRP        -> short premium ok
  PREMIUM_THIN    low IVR (below the 30 floor)          -> avoid selling premium
  EARNINGS_BLACKOUT  confirmed earnings imminent        -> no new short premium
  NEUTRAL         none of the above
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel

from regime.skew import Skew
from regime.surface import Surface

IVR_FLOOR = 30.0  # design-doc short-premium IVR floor


class IVRBucket(str, Enum):
    LOW = "LOW"  # < 30 (below the floor)
    MEDIUM = "MEDIUM"  # 30-50
    ELEVATED = "ELEVATED"  # 50-70
    HIGH = "HIGH"  # >= 70


class TermState(str, Enum):
    CONTANGO = "CONTANGO"  # upward sloping front
    FLAT = "FLAT"
    INVERTED = "INVERTED"  # front above 30d


class VRPSign(str, Enum):
    POSITIVE = "POSITIVE"
    FLAT = "FLAT"
    NEGATIVE = "NEGATIVE"


class EarningsProximity(str, Enum):
    NONE = "NONE"
    UPCOMING = "UPCOMING"  # within ~10 trading sessions
    IMMINENT = "IMMINENT"  # <= 2 days


class StockRegimeState(str, Enum):
    PREMIUM_RICH = "PREMIUM_RICH"
    PREMIUM_FAIR = "PREMIUM_FAIR"
    PREMIUM_THIN = "PREMIUM_THIN"
    EARNINGS_BLACKOUT = "EARNINGS_BLACKOUT"
    NEUTRAL = "NEUTRAL"


class StockRegime(BaseModel):
    ticker: str
    ivr: float
    ivr_bucket: IVRBucket
    term_state: TermState
    vrp: float
    vrp_sign: VRPSign
    earnings_proximity: EarningsProximity
    days_to_earnings: Optional[int] = None
    extreme_call_skew: bool = False
    extreme_put_skew: bool = False
    state: StockRegimeState
    sell_premium_ok: bool  # IVR >= floor and earnings not imminent


def classify_ivr(ivr: float) -> IVRBucket:
    if ivr < IVR_FLOOR:
        return IVRBucket.LOW
    if ivr < 50.0:
        return IVRBucket.MEDIUM
    if ivr < 70.0:
        return IVRBucket.ELEVATED
    return IVRBucket.HIGH


def classify_term(slope_9_30: float, tol: float = 0.005) -> TermState:
    if slope_9_30 < -tol:
        return TermState.INVERTED
    if slope_9_30 > tol:
        return TermState.CONTANGO
    return TermState.FLAT


def classify_vrp(vrp_value: float, tol: float = 0.005) -> VRPSign:
    if vrp_value > tol:
        return VRPSign.POSITIVE
    if vrp_value < -tol:
        return VRPSign.NEGATIVE
    return VRPSign.FLAT


def classify_earnings(days_to_earnings: Optional[int]) -> EarningsProximity:
    if days_to_earnings is None:
        return EarningsProximity.NONE
    if days_to_earnings <= 2:
        return EarningsProximity.IMMINENT
    if days_to_earnings <= 10:
        return EarningsProximity.UPCOMING
    return EarningsProximity.NONE


def stock_regime(
    ticker: str,
    surface: Surface,
    ivr: float,
    vrp_value: float,
    *,
    days_to_earnings: Optional[int] = None,
    skew: Optional[Skew] = None,
) -> StockRegime:
    """Compose the per-stock regime from its signals."""

    ivr_bucket = classify_ivr(ivr)
    term_state = classify_term(surface.slope_9_30)
    vrp_sign = classify_vrp(vrp_value)
    proximity = classify_earnings(days_to_earnings)
    call_skew = bool(skew and skew.extreme_call_skew)
    put_skew = bool(skew and skew.extreme_put_skew)

    sell_premium_ok = ivr_bucket is not IVRBucket.LOW and proximity is not EarningsProximity.IMMINENT

    if proximity is EarningsProximity.IMMINENT:
        state = StockRegimeState.EARNINGS_BLACKOUT
    elif ivr_bucket in (IVRBucket.ELEVATED, IVRBucket.HIGH) and vrp_sign is VRPSign.POSITIVE:
        state = StockRegimeState.PREMIUM_RICH
    elif ivr_bucket is IVRBucket.MEDIUM and vrp_sign is not VRPSign.NEGATIVE:
        state = StockRegimeState.PREMIUM_FAIR
    elif ivr_bucket is IVRBucket.LOW:
        state = StockRegimeState.PREMIUM_THIN
    else:
        state = StockRegimeState.NEUTRAL

    return StockRegime(
        ticker=ticker,
        ivr=ivr,
        ivr_bucket=ivr_bucket,
        term_state=term_state,
        vrp=vrp_value,
        vrp_sign=vrp_sign,
        earnings_proximity=proximity,
        days_to_earnings=days_to_earnings,
        extreme_call_skew=call_skew,
        extreme_put_skew=put_skew,
        state=state,
        sell_premium_ok=sell_premium_ok,
    )
