"""Shared strategy helpers (private).

Small utilities reused across strategy modules: the short-premium IVR floor
gate, net position greeks from legs, and the standard management-metadata block
(profit target / stop / must-touch-by / alerts).
"""

from __future__ import annotations

from typing import Optional

from core.chain import OptionChain
from core.context import TradeContext
from core.models import Action, Leg

IVR_FLOOR = 30.0  # design-doc short-premium IVR floor


def ivr_floor_ok(ctx: TradeContext, floor: float = IVR_FLOOR) -> bool:
    """True if the per-stock IVR is at/above the floor. No regime => not ok."""

    ivr = ctx.ivr()
    return ivr is not None and ivr >= floor


def short_premium_management(
    credit: float,
    *,
    profit_target_pct: float = 0.5,
    stop_loss_mult: float = 2.0,
    must_touch_by_dte: int = 21,
) -> dict:
    """Standard management metadata for defined-risk short premium."""

    return {
        "credit": round(credit, 4),
        "profit_target_pct": profit_target_pct,  # close at 50% of max profit
        "stop_loss_mult": stop_loss_mult,  # stop at 2x credit received
        "must_touch_by_dte": must_touch_by_dte,  # checkpoint decision by 21 DTE
        "alerts": ["short_strike_test"],
    }


def net_position_delta(legs: list[Leg], chain: OptionChain) -> float:
    """Net delta of a structure (+1 for BUY legs, -1 for SELL legs)."""

    total = 0.0
    for leg in legs:
        q = chain.get(leg.contract.expiry, leg.contract.strike, leg.contract.right)
        if q is None:
            continue
        sign = 1.0 if leg.action is Action.BUY else -1.0
        total += sign * leg.quantity * q.delta
    return total


def net_credit(legs: list[Leg], chain: OptionChain) -> float:
    """Net credit (positive = received) of a structure from leg mids."""

    total = 0.0
    for leg in legs:
        q = chain.get(leg.contract.expiry, leg.contract.strike, leg.contract.right)
        if q is None:
            continue
        sign = 1.0 if leg.action is Action.SELL else -1.0  # sell receives, buy pays
        total += sign * leg.quantity * q.mid
    return total
