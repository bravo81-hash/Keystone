"""Engine 2 standing tail hedge — always on, layered, regime-scaled.

Two layers protect the leveraged core:
  * base layer — OTM index put SPREADS (SPY/QQQ), rolled. Cheap, always on,
    caps the everyday drawdown.
  * tail layer — thin deep-OTM long puts (VIX-style convexity). Small premium,
    large payoff in a gap.

Sizing: the hedge's modeled severe-tail payoff (-20% spot) is set so the core's
modeled severe-tail loss net of the hedge is capped NEAR the DD budget. Weight
scales UP as the market regime degrades (DEFENSIVE -> HARD_SKIP) — Engine 3's
crisis alpha lets this explicit hedge run lighter than a naked levered book.

SMSF variant: long puts / defined put spreads only (no naked index shorting) —
the base spread is a debit spread (long higher strike, short lower), permitted.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.context import TradeContext
from core.models import Action, Contract, Family, Leg, Right, Suggestion

MULTIPLIER = 100
HEDGE_TARGET_DTE, HEDGE_MIN_DTE, HEDGE_MAX_DTE = 75, 45, 120
SEVERE_SPOT_SHOCK = -0.20  # the gap the hedge is sized against
BASE_PAYOFF_SHARE = 0.6  # base spreads carry 60% of target payoff, tail 40%


def regime_hedge_scale(market) -> float:
    """Hedge weight multiplier — heavier as the regime degrades."""

    if market is None:
        return 1.0
    if getattr(market, "is_hard_skip", False):
        return 1.6
    if getattr(market, "is_defensive", False):
        return 1.3
    return 1.0


def _put_intrinsic(strike: float, shocked_spot: float, contracts: int) -> float:
    return max(0.0, strike - shocked_spot) * MULTIPLIER * contracts


def _nearest_put(chain, expiry, target_strike: float):
    puts = chain.quotes_for(expiry, Right.PUT)
    if not puts:
        return None
    return min(puts, key=lambda q: abs(q.strike - target_strike))


@dataclass
class HedgePlan:
    suggestions: list[Suggestion]
    modeled_severe_payoff: float  # $ payoff in the -20% scenario (intrinsic, conservative)
    target_payoff: float  # $ payoff the sizing aimed for
    regime_scale: float


def propose_hedge(
    ctx: TradeContext,
    *,
    core_severe_loss: float,
    dd_budget_dollars: float,
    base_otm_pct: float = 0.05,
    base_spread_width_pct: float = 0.05,
    tail_otm_pct: float = 0.15,
    severe_spot_shock: float = SEVERE_SPOT_SHOCK,
) -> HedgePlan:
    """Build the standing layered hedge on the index ``ctx.symbol``.

    ``core_severe_loss`` is the core's modeled loss in the severe-tail scenario
    (positive $). The hedge targets a severe-tail payoff that brings the net core
    loss down toward ``dd_budget_dollars``, scaled up by the regime.
    """

    chain = ctx.chain
    spot = ctx.spot_price()
    scale = regime_hedge_scale(ctx.market_regime)
    # Target payoff: the part of the core loss exceeding the DD budget (>=0),
    # then scaled up by the regime so the hedge gets heavier as conditions worsen.
    excess = max(0.0, core_severe_loss - dd_budget_dollars)
    target_payoff = excess * scale
    plan = HedgePlan(suggestions=[], modeled_severe_payoff=0.0, target_payoff=target_payoff,
                     regime_scale=scale)
    if spot <= 0 or target_payoff <= 0:
        return plan

    expiry = chain.nearest_expiry(HEDGE_TARGET_DTE, min_dte=HEDGE_MIN_DTE, max_dte=HEDGE_MAX_DTE,
                                  asof=ctx.asof or chain.asof)
    if expiry is None:
        return plan

    shocked_spot = spot * (1.0 + severe_spot_shock)
    total_payoff = 0.0

    # --- base layer: OTM put debit spread ------------------------------------ #
    long_put = _nearest_put(chain, expiry, spot * (1.0 - base_otm_pct))
    short_put = _nearest_put(chain, expiry, spot * (1.0 - base_otm_pct - base_spread_width_pct))
    if long_put is not None and short_put is not None and long_put.strike > short_put.strike:
        per_contract = _put_intrinsic(long_put.strike, shocked_spot, 1) - \
            _put_intrinsic(short_put.strike, shocked_spot, 1)
        if per_contract > 0:
            base_target = target_payoff * BASE_PAYOFF_SHARE
            contracts = max(1, round(base_target / per_contract))
            net_debit = max(0.0, (long_put.mid - short_put.mid)) * MULTIPLIER * contracts
            payoff = per_contract * contracts
            total_payoff += payoff
            plan.suggestions.append(Suggestion(
                symbol=ctx.symbol, account_id=ctx.account_id, family=Family.CORE_HEDGE,
                legs=[
                    Leg(contract=Contract.option(ctx.symbol, expiry, long_put.strike, Right.PUT),
                        action=Action.BUY, quantity=contracts),
                    Leg(contract=Contract.option(ctx.symbol, expiry, short_put.strike, Right.PUT),
                        action=Action.SELL, quantity=contracts),
                ],
                dte=chain.dte(expiry, ctx.asof or chain.asof),
                entry_greeks={"long_put_delta": long_put.delta, "short_put_delta": short_put.delta},
                max_loss=net_debit,
                rationale=(
                    f"hedge base: {contracts}x {long_put.strike:g}/{short_put.strike:g}P put spread "
                    f"@ {expiry}, modeled -20% payoff ${payoff:,.0f}, regime x{scale:g}"
                ),
                instrument_class=ctx.instrument_class, multi_expiry=False,
                management={"engine": "core", "hedge_layer": "base", "rolled": True,
                            "modeled_severe_payoff": round(payoff, 2),
                            "defined_spread": True, "smsf_ok": True},
            ))

    # --- tail layer: thin deep-OTM long puts --------------------------------- #
    tail_put = _nearest_put(chain, expiry, spot * (1.0 - tail_otm_pct))
    if tail_put is not None and tail_put.mid > 0:
        per_contract = _put_intrinsic(tail_put.strike, shocked_spot, 1)
        if per_contract > 0:
            tail_target = target_payoff * (1.0 - BASE_PAYOFF_SHARE)
            contracts = max(1, round(tail_target / per_contract))
            cost = tail_put.mid * MULTIPLIER * contracts
            payoff = per_contract * contracts
            total_payoff += payoff
            plan.suggestions.append(Suggestion(
                symbol=ctx.symbol, account_id=ctx.account_id, family=Family.CORE_HEDGE,
                legs=[Leg(contract=Contract.option(ctx.symbol, expiry, tail_put.strike, Right.PUT),
                          action=Action.BUY, quantity=contracts)],
                dte=chain.dte(expiry, ctx.asof or chain.asof),
                entry_greeks={"long_put_delta": tail_put.delta},
                max_loss=cost,
                rationale=(
                    f"hedge tail: {contracts}x {tail_put.strike:g}P deep-OTM long put @ {expiry}, "
                    f"modeled -20% payoff ${payoff:,.0f} (convexity), regime x{scale:g}"
                ),
                instrument_class=ctx.instrument_class, multi_expiry=False,
                management={"engine": "core", "hedge_layer": "tail", "rolled": True,
                            "modeled_severe_payoff": round(payoff, 2),
                            "defined_spread": True, "smsf_ok": True},
            ))

    # Both layers are long-put / defined-spread => SMSF-permitted exactly as built.
    plan.modeled_severe_payoff = total_payoff
    return plan
