"""Covered call on SMSF core shares — the wheel exit leg.

30-45 DTE, ~15-25 delta (low, rarely called away). Roll at 21 DTE or 80% profit.
Skip a cycle if the strike would straddle confirmed earnings, or sit in an ex-div
assignment-risk window (extrinsic < dividend) — both caught by american_guards.
Requires >= 100 core shares; writes one call per 100 shares.
"""

from __future__ import annotations

from typing import Optional

from core.context import TradeContext
from core.models import Action, Contract, Family, Leg, Right, Suggestion
from strategies._guards import american_guards

TARGET_DTE = 38
MIN_DTE = 30
MAX_DTE = 45
DEFAULT_DELTA = 0.20  # 15-25 delta band, low assignment odds
MULTIPLIER = 100


def propose(ctx: TradeContext) -> Optional[Suggestion]:
    if ctx.core_shares < 100:
        return None
    chain = ctx.chain
    asof = ctx.asof or chain.asof
    expiry = chain.nearest_expiry(TARGET_DTE, min_dte=MIN_DTE, max_dte=MAX_DTE, asof=asof)
    if expiry is None:
        return None

    short = chain.by_delta(expiry, Right.CALL, DEFAULT_DELTA)
    if short is None or short.mid <= 0:
        return None

    contracts = ctx.core_shares // 100
    credit = short.mid
    legs = [
        Leg(
            contract=Contract.option(ctx.symbol, expiry, short.strike, Right.CALL),
            action=Action.SELL,
            quantity=contracts,
        )
    ]
    suggestion = Suggestion(
        symbol=ctx.symbol,
        account_id=ctx.account_id,
        family=Family.WHEEL_CC,
        legs=legs,
        dte=chain.dte(expiry, asof),
        entry_greeks={"short_delta": short.delta},
        max_loss=None,  # overlay on owned shares
        rationale=(
            f"covered call {short.strike}C x{contracts} @ {expiry} (~{short.abs_delta:.2f}d), "
            f"credit {credit:.2f}"
        ),
        instrument_class=ctx.instrument_class,
        multi_expiry=False,
        management={
            "credit": round(credit, 4),
            "strike": short.strike,
            "contracts": contracts,
            "roll": "at 21 DTE or 80% profit",
            "profit_target_pct": 0.8,
        },
    )
    guard = american_guards(ctx, suggestion)
    if not guard.valid:
        return None  # skip the cycle (earnings straddle or ex-div assignment risk)
    if guard.warnings:
        suggestion.management.setdefault("warnings", []).extend(guard.warnings)
    return suggestion
