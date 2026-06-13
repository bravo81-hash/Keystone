"""Collar on an SMSF core holding — event-driven downside protection.

Triggered only when the market regime is DEFENSIVE (flag from Stage 4). Proposes
a long put ~25 delta financed by the existing covered call. Near-zero touch;
removed when the regime normalizes. Requires >= 100 core shares.
"""

from __future__ import annotations

from typing import Optional

from core.context import TradeContext
from core.models import Action, Contract, Family, Leg, Right, Suggestion

TARGET_DTE = 38
MIN_DTE = 30
MAX_DTE = 45
PUT_DELTA = 0.25
MULTIPLIER = 100


def propose(ctx: TradeContext) -> Optional[Suggestion]:
    market = ctx.market_regime
    if market is None or not market.is_defensive:
        return None  # collars are raised only in DEFENSIVE regimes
    if ctx.core_shares < 100:
        return None

    chain = ctx.chain
    asof = ctx.asof or chain.asof
    expiry = chain.nearest_expiry(TARGET_DTE, min_dte=MIN_DTE, max_dte=MAX_DTE, asof=asof)
    if expiry is None:
        return None

    put = chain.by_delta(expiry, Right.PUT, PUT_DELTA)
    if put is None or put.mid <= 0:
        return None

    contracts = ctx.core_shares // 100
    cost = put.mid * MULTIPLIER * contracts
    legs = [
        Leg(
            contract=Contract.option(ctx.symbol, expiry, put.strike, Right.PUT),
            action=Action.BUY,
            quantity=contracts,
        )
    ]
    return Suggestion(
        symbol=ctx.symbol,
        account_id=ctx.account_id,
        family=Family.COLLAR,
        legs=legs,
        dte=chain.dte(expiry, asof),
        entry_greeks={"long_put_delta": put.delta},
        max_loss=cost,  # premium paid for protection (net of the financing CC)
        rationale=(
            f"protective collar: long {put.strike}P x{contracts} @ {expiry} "
            f"(~{put.abs_delta:.2f}d), financed by existing covered call (regime DEFENSIVE)"
        ),
        instrument_class=ctx.instrument_class,
        multi_expiry=False,
        management={
            "event_driven": True,
            "remove_when": "regime normalizes",
            "financed_by": "existing covered call",
            "put_strike": put.strike,
        },
    )
