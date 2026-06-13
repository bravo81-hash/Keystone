"""Put / call credit spreads — defined-risk short premium (trading sleeve).

Put credit spread (bullish/neutral), call credit spread (bearish/neutral).
Entry 30-60 DTE (target 45). Short strike ~16-30 delta (default 20). The long
wing is the WIDEST width whose defined max-loss still fits the per-position
budget (most premium within the risk budget). Per-stock IVR floor 30. Every
proposal runs american_guards. Management: PT 50% / stop 2x credit /
must-touch-by 21 DTE / short-strike-test alert.
"""

from __future__ import annotations

from typing import Optional

from core.chain import OptionChain
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
DEFAULT_SHORT_DELTA = 0.20
MULTIPLIER = 100


def _finalize(ctx: TradeContext, suggestion: Suggestion) -> Optional[Suggestion]:
    guard = american_guards(ctx, suggestion)
    if not guard.valid:
        return None
    if guard.warnings:
        suggestion.management.setdefault("warnings", []).extend(guard.warnings)
    return suggestion


def _select_wing(
    chain: OptionChain,
    expiry,
    right: Right,
    short_strike: float,
    short_mid: float,
    budget: float,
) -> Optional[tuple[float, float, float]]:
    """Return (long_strike, width, credit) for the widest wing fitting the budget."""

    legs = chain.quotes_for(expiry, right)
    if right is Right.PUT:
        candidates = [q for q in legs if q.strike < short_strike]
    else:
        candidates = [q for q in legs if q.strike > short_strike]
    # widest first
    candidates.sort(key=lambda q: abs(q.strike - short_strike), reverse=True)

    for long_q in candidates:
        width = abs(short_strike - long_q.strike)
        credit = short_mid - long_q.mid
        if credit <= 0 or width <= 0:
            continue
        max_loss = (width - credit) * MULTIPLIER
        if max_loss <= budget:
            return long_q.strike, width, credit
    return None


def _build_credit_spread(ctx: TradeContext, right: Right, family: Family) -> Optional[Suggestion]:
    chain = ctx.chain
    asof = ctx.asof or chain.asof
    expiry = chain.nearest_expiry(TARGET_DTE, min_dte=MIN_DTE, max_dte=MAX_DTE, asof=asof)
    if expiry is None:
        return None

    short_q = chain.by_delta(expiry, right, DEFAULT_SHORT_DELTA)
    if short_q is None or short_q.mid <= 0:
        return None

    wing = _select_wing(chain, expiry, right, short_q.strike, short_q.mid, ctx.per_position_budget)
    if wing is None:
        return None
    long_strike, width, credit = wing

    legs = [
        Leg(
            contract=Contract.option(ctx.symbol, expiry, short_q.strike, right),
            action=Action.SELL,
        ),
        Leg(
            contract=Contract.option(ctx.symbol, expiry, long_strike, right),
            action=Action.BUY,
        ),
    ]
    max_loss = (width - credit) * MULTIPLIER
    side = "put" if right is Right.PUT else "call"
    suggestion = Suggestion(
        symbol=ctx.symbol,
        account_id=ctx.account_id,
        family=family,
        legs=legs,
        dte=chain.dte(expiry, asof),
        entry_greeks={"net_delta": net_position_delta(legs, chain), "short_delta": short_q.delta},
        max_loss=max_loss,
        rationale=(
            f"{side} credit spread {short_q.strike}/{long_strike} @ {expiry} "
            f"(short ~{short_q.abs_delta:.2f}d), credit {credit:.2f}, "
            f"width {width:g}, IVR {ctx.ivr():.0f}"
        ),
        instrument_class=ctx.instrument_class,
        multi_expiry=False,
        management={
            **short_premium_management(credit),
            "short_strike": short_q.strike,
            "long_strike": long_strike,
            "width": width,
            "max_profit": credit * MULTIPLIER,
        },
    )
    return _finalize(ctx, suggestion)


def propose_put_credit_spread(ctx: TradeContext) -> Optional[Suggestion]:
    if not ivr_floor_ok(ctx):
        return None
    return _build_credit_spread(ctx, Right.PUT, Family.PUT_CREDIT_SPREAD)


def propose_call_credit_spread(ctx: TradeContext) -> Optional[Suggestion]:
    if not ivr_floor_ok(ctx):
        return None
    return _build_credit_spread(ctx, Right.CALL, Family.CALL_CREDIT_SPREAD)


def _bearish(ctx: TradeContext) -> bool:
    bias = ctx.extras.get("bias")
    if bias in {"bearish", "bullish", "neutral"}:
        return bias == "bearish"
    mr = ctx.market_regime
    return bool(mr is not None and mr.downtrend)


def propose(ctx: TradeContext) -> Optional[Suggestion]:
    """Uniform entry point: call spread when bearish, else put spread."""

    if _bearish(ctx):
        return propose_call_credit_spread(ctx)
    return propose_put_credit_spread(ctx)
