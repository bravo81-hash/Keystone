"""25-delta risk reversal (skew) per ticker.

RR = IV(25-delta call) - IV(25-delta put), expressed in **vol points**. Positive
=> calls richer (call skew); negative => puts richer (put skew, the equity norm).
Built from the existing 25-delta chain pass — no new requests.

Sanity flags on extremes (the design-doc thresholds):
  * extreme call skew: RR > +4 vol points
  * extreme put  skew: RR < -12 vol points
"""

from __future__ import annotations

from pydantic import BaseModel

CALL_SKEW_THRESHOLD = 4.0  # vol points
PUT_SKEW_THRESHOLD = -12.0  # vol points


class Skew(BaseModel):
    ticker: str
    rr_25d: float  # vol points
    extreme_call_skew: bool
    extreme_put_skew: bool


def risk_reversal(call_iv: float, put_iv: float) -> float:
    """25-delta risk reversal in vol points. Inputs are decimal IVs (0.25 = 25%)."""

    return (call_iv - put_iv) * 100.0


def build_skew(ticker: str, call_iv: float, put_iv: float) -> Skew:
    rr = risk_reversal(call_iv, put_iv)
    return Skew(
        ticker=ticker,
        rr_25d=rr,
        extreme_call_skew=rr > CALL_SKEW_THRESHOLD,
        extreme_put_skew=rr < PUT_SKEW_THRESHOLD,
    )
