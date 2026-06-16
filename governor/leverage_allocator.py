"""Stress-constrained leverage allocator — "hedging buys leverage headroom".

Raises Engine 1/2 leverage until the modeled severe-tail loss, NET of Engine 2's
hedge payoff and Engine 3's crisis payoff, reaches the DD budget. Because the
hedge + overlay have negative marginal risk in the tail, more of them frees more
budget for the risk-on engines.

The risk-based leverage is then GATED by the vol-target scalar and the gross
notional ceiling, and scaled down by the drawdown governor's exposure scale.
Engine 3 (overlay) and the standing hedge are NOT de-levered with 1/2 — they are
the protection that earns the leverage.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AllocationResult:
    engine_scale: dict[str, float]  # leverage multiplier per engine
    severe_tail_loss: float  # net modeled severe-tail loss at the chosen scale ($)
    dd_budget: float  # the 20% DD budget in $
    within_budget: bool
    risk_implied_leverage: float  # the budget-clearing leverage on Engines 1/2
    applied_leverage: float  # the gated/de-levered leverage actually applied to 1/2


def allocate(
    *,
    dd_budget: float,
    income_severe_loss: float,
    core_severe_loss: float,
    hedge_payoff: float,
    overlay_crisis_payoff: float,
    vol_target_scalar: float,
    drawdown_scale: float,
    leverage_cap: float,
) -> AllocationResult:
    """Compute per-engine leverage targets under the severe-tail DD budget.

    All loss/payoff inputs are modeled severe-tail (-20%) dollar figures: losses
    POSITIVE, the hedge/overlay payoffs POSITIVE when protective.
    """

    base_loss = max(0.0, income_severe_loss) + max(0.0, core_severe_loss)
    # Protective offset (signed): hedge payoff + overlay crisis payoff.
    offset = hedge_payoff + overlay_crisis_payoff

    if base_loss <= 0:
        risk_L = leverage_cap
    else:
        risk_L = max(0.0, (dd_budget + offset) / base_loss)

    # Gate by vol-target + the gross-notional ceiling, then de-lever per drawdown.
    gated = min(risk_L, max(0.0, vol_target_scalar), leverage_cap)
    applied = gated * max(0.0, min(1.0, drawdown_scale))

    severe_tail_loss = applied * base_loss - offset
    within_budget = severe_tail_loss <= dd_budget + 1e-6

    return AllocationResult(
        engine_scale={"income": applied, "core": applied, "overlay": 1.0},
        severe_tail_loss=severe_tail_loss,
        dd_budget=dd_budget,
        within_budget=within_budget,
        risk_implied_leverage=risk_L,
        applied_leverage=applied,
    )
