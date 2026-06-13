"""Iron condor — neutral/range defined-risk short premium (trading sleeve).

Both short legs ~16-20 delta (default 18); symmetric long wings sized to the
WIDEST equal width whose combined defined max-loss fits the per-position budget.
IVR floor 30; favored when range-bound + elevated IVR. Same management metadata
as credit spreads. Every proposal runs american_guards.
"""

from __future__ import annotations

from typing import Optional

from core.context import TradeContext
from core.models import Action, Contract, Family, Leg, Right, Suggestion
from strategies._common import (
    ivr_floor_ok,
    net_position_delta,
    short_premium_management,
)
from strategies._guards import american_guards

TARGET_DTE = 45
MIN_DTE = 30
MAX_DTE = 60
DEFAULT_SHORT_DELTA = 0.18
MULTIPLIER = 100


def _finalize(ctx: TradeContext, suggestion: Suggestion) -> Optional[Suggestion]:
    guard = american_guards(ctx, suggestion)
    if not guard.valid:
        return None
    if guard.warnings:
        suggestion.management.setdefault("warnings", []).extend(guard.warnings)
    return suggestion


def propose(ctx: TradeContext) -> Optional[Suggestion]:
    """Build a symmetric iron condor, widest wings fitting the budget."""

    if not ivr_floor_ok(ctx):
        return None

    chain = ctx.chain
    asof = ctx.asof or chain.asof
    expiry = chain.nearest_expiry(TARGET_DTE, min_dte=MIN_DTE, max_dte=MAX_DTE, asof=asof)
    if expiry is None:
        return None

    short_put = chain.by_delta(expiry, Right.PUT, DEFAULT_SHORT_DELTA)
    short_call = chain.by_delta(expiry, Right.CALL, DEFAULT_SHORT_DELTA)
    if short_put is None or short_call is None or short_put.mid <= 0 or short_call.mid <= 0:
        return None

    # Candidate equal widths available on BOTH wings.
    put_widths = {
        round(short_put.strike - q.strike, 6)
        for q in chain.quotes_for(expiry, Right.PUT)
        if q.strike < short_put.strike
    }
    call_widths = {
        round(q.strike - short_call.strike, 6)
        for q in chain.quotes_for(expiry, Right.CALL)
        if q.strike > short_call.strike
    }
    common = sorted(put_widths & call_widths, reverse=True)  # widest first

    short_credit = short_put.mid + short_call.mid
    chosen: Optional[tuple[float, float, float, float]] = None  # (w, credit, long_put, long_call)
    for w in common:
        long_put = chain.get(expiry, short_put.strike - w, Right.PUT)
        long_call = chain.get(expiry, short_call.strike + w, Right.CALL)
        if long_put is None or long_call is None:
            continue
        credit = short_credit - (long_put.mid + long_call.mid)
        if credit <= 0:
            continue
        max_loss = (w - credit) * MULTIPLIER
        if max_loss <= ctx.per_position_budget:
            chosen = (w, credit, long_put.strike, long_call.strike)
            break

    if chosen is None:
        return None
    width, credit, long_put_strike, long_call_strike = chosen

    legs = [
        Leg(contract=Contract.option(ctx.symbol, expiry, short_put.strike, Right.PUT), action=Action.SELL),
        Leg(contract=Contract.option(ctx.symbol, expiry, long_put_strike, Right.PUT), action=Action.BUY),
        Leg(contract=Contract.option(ctx.symbol, expiry, short_call.strike, Right.CALL), action=Action.SELL),
        Leg(contract=Contract.option(ctx.symbol, expiry, long_call_strike, Right.CALL), action=Action.BUY),
    ]
    max_loss = (width - credit) * MULTIPLIER
    suggestion = Suggestion(
        symbol=ctx.symbol,
        account_id=ctx.account_id,
        family=Family.IRON_CONDOR,
        legs=legs,
        dte=chain.dte(expiry, asof),
        entry_greeks={"net_delta": net_position_delta(legs, chain)},
        max_loss=max_loss,
        rationale=(
            f"iron condor {long_put_strike}/{short_put.strike} - "
            f"{short_call.strike}/{long_call_strike} @ {expiry}, "
            f"credit {credit:.2f}, width {width:g}, IVR {ctx.ivr():.0f}"
        ),
        instrument_class=ctx.instrument_class,
        multi_expiry=False,
        management={
            **short_premium_management(credit),
            "short_put": short_put.strike,
            "long_put": long_put_strike,
            "short_call": short_call.strike,
            "long_call": long_call_strike,
            "width": width,
            "max_profit": credit * MULTIPLIER,
        },
    )
    return _finalize(ctx, suggestion)
