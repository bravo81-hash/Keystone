"""Engine 3 — trend/managed-futures + convexity overlay (load-bearing).

Systematic time-series momentum across a diversified ETF basket (equities,
bonds, gold, energy, broad commodity, USD). Signal is 12-1m return sign and/or
50/200 MA state. Expressed ONLY via long-premium DEFINED-RISK options so it
needs no stock shorting and works in margin AND the SMSF:

  * long trend  -> call debit spread (or long-call LEAP)
  * short trend -> put debit spread

Defined risk = the net debit. The v1 ``trend_long`` convexity geometry folds in
here (same delta/DTE bands), now sized LOAD-BEARING (larger than a pure
return-maximizer) — and every position reports its modeled severe-tail
(-20% spot) payoff so the allocator can credit Engine 3's positive crisis alpha
as hedge headroom.
"""

from __future__ import annotations

from typing import Optional

from core.context import TradeContext
from core.models import Action, Contract, Family, Leg, Right, Suggestion
from strategies.trend_long import (
    DEBIT_LONG_DELTA,
    DEBIT_MAX_DTE,
    DEBIT_MIN_DTE,
    DEBIT_SHORT_DELTA,
    DEBIT_TARGET_DTE,
    LEAPS_DELTA,
    LEAPS_MAX_DTE,
    LEAPS_MIN_DTE,
    LEAPS_TARGET_DTE,
)

MULTIPLIER = 100
SEVERE_SPOT_SHOCK = -0.20

#: Basket sleeve classification (for net-exposure-by-sleeve reporting).
SLEEVE = {
    "SPY": "equity", "QQQ": "equity", "IWM": "equity",
    "TLT": "bonds", "GLD": "gold", "XLE": "energy", "USO": "energy",
    "DBC": "commodity", "UUP": "usd",
}


# --------------------------------------------------------------------------- #
# Signals
# --------------------------------------------------------------------------- #
def ts_momentum_signal(closes: list[float], *, lookback: int = 252, skip: int = 21) -> int:
    """12-1m time-series momentum: sign of the return from ``lookback`` days ago
    to ``skip`` days ago (excludes the most recent month). +1/-1/0."""

    if len(closes) < lookback + 1:
        return 0
    past = closes[-(lookback + 1)]
    recent = closes[-(skip + 1)] if skip > 0 else closes[-1]
    if past <= 0:
        return 0
    ret = recent / past - 1.0
    if ret > 0:
        return 1
    if ret < 0:
        return -1
    return 0


def ma_state_signal(closes: list[float], *, fast: int = 50, slow: int = 200) -> int:
    """50/200 MA state: +1 when fast MA > slow MA and price above, -1 when below."""

    if len(closes) < slow:
        return 0
    fast_ma = sum(closes[-fast:]) / fast
    slow_ma = sum(closes[-slow:]) / slow
    price = closes[-1]
    if fast_ma > slow_ma and price >= slow_ma:
        return 1
    if fast_ma < slow_ma and price <= slow_ma:
        return -1
    return 0


def overlay_signal(closes: list[float], mode: str = "both") -> int:
    """Combine the configured signals. 'both' requires agreement (else flat)."""

    ts = ts_momentum_signal(closes)
    ma = ma_state_signal(closes)
    if mode == "ts_momentum":
        return ts
    if mode == "ma_state":
        return ma
    # both: agree or flat
    if ts == ma:
        return ts
    return 0


# --------------------------------------------------------------------------- #
# Crisis payoff (expiry-intrinsic, conservative — ignores IV/time value)
# --------------------------------------------------------------------------- #
def _leg_intrinsic(leg: Leg, shocked_spot: float) -> float:
    c = leg.contract
    if c.right is Right.CALL:
        val = max(0.0, shocked_spot - (c.strike or 0.0))
    else:
        val = max(0.0, (c.strike or 0.0) - shocked_spot)
    sign = 1.0 if leg.action is Action.BUY else -1.0
    return sign * val * MULTIPLIER * leg.quantity


def modeled_crisis_payoff(legs: list[Leg], spot: float, debit_dollars: float,
                          severe_spot_shock: float = SEVERE_SPOT_SHOCK) -> float:
    """P&L of a defined-risk structure in the -20% gap (expiry intrinsic - debit).

    Positive for put structures (crisis alpha); ~ -debit for long-equity calls.
    """

    shocked = spot * (1.0 + severe_spot_shock)
    intrinsic = sum(_leg_intrinsic(leg, shocked) for leg in legs)
    return intrinsic - debit_dollars


# --------------------------------------------------------------------------- #
# Construction
# --------------------------------------------------------------------------- #
def _expiry(ctx: TradeContext, target: int, lo: int, hi: int):
    return ctx.chain.nearest_expiry(target, min_dte=lo, max_dte=hi, asof=ctx.asof or ctx.chain.asof)


def _build(ctx: TradeContext, direction: int, expression: str, name_budget: float
           ) -> Optional[Suggestion]:
    right = Right.CALL if direction > 0 else Right.PUT
    chain = ctx.chain
    spot = ctx.spot_price()

    if expression == "leap":
        expiry = _expiry(ctx, LEAPS_TARGET_DTE, LEAPS_MIN_DTE, LEAPS_MAX_DTE)
        if expiry is None:
            return None
        long_q = chain.by_delta(expiry, right, LEAPS_DELTA)
        if long_q is None or long_q.mid <= 0:
            return None
        per_contract_debit = long_q.mid * MULTIPLIER
        contracts = max(1, round(name_budget / per_contract_debit)) if name_budget > 0 else 1
        legs = [Leg(contract=Contract.option(ctx.symbol, expiry, long_q.strike, right),
                    action=Action.BUY, quantity=contracts)]
        family = Family.OVERLAY_LEAP
        greeks = {"net_delta": long_q.delta * contracts}
        label = f"LEAP {right.value} {long_q.strike:g}@{expiry}"
    else:  # debit spread (long ~60d / short ~30d), defined risk
        expiry = _expiry(ctx, DEBIT_TARGET_DTE, DEBIT_MIN_DTE, DEBIT_MAX_DTE)
        if expiry is None:
            return None
        long_q = chain.by_delta(expiry, right, DEBIT_LONG_DELTA)
        short_q = chain.by_delta(expiry, right, DEBIT_SHORT_DELTA)
        if (long_q is None or short_q is None or long_q.strike == short_q.strike
                or long_q.mid <= short_q.mid):
            return None
        per_contract_debit = (long_q.mid - short_q.mid) * MULTIPLIER
        contracts = max(1, round(name_budget / per_contract_debit)) if name_budget > 0 else 1
        legs = [
            Leg(contract=Contract.option(ctx.symbol, expiry, long_q.strike, right),
                action=Action.BUY, quantity=contracts),
            Leg(contract=Contract.option(ctx.symbol, expiry, short_q.strike, right),
                action=Action.SELL, quantity=contracts),
        ]
        family = Family.OVERLAY_DEBIT_SPREAD
        greeks = {"long_delta": long_q.delta, "short_delta": short_q.delta,
                  "net_delta": (long_q.delta - short_q.delta) * contracts}
        label = f"{right.value} debit spread {long_q.strike:g}/{short_q.strike:g}@{expiry}"

    debit = per_contract_debit * contracts
    if debit <= 0:
        return None
    crisis = modeled_crisis_payoff(legs, spot, debit)
    sleeve = SLEEVE.get(ctx.symbol, "other")
    bias = "long" if direction > 0 else "short"

    return Suggestion(
        symbol=ctx.symbol, account_id=ctx.account_id, family=family, legs=legs,
        dte=chain.dte(expiry, ctx.asof or chain.asof),
        entry_greeks=greeks, max_loss=debit,  # defined risk = debit
        rationale=(
            f"overlay {bias} trend ({sleeve}): {contracts}x {label}, "
            f"debit ${debit:,.0f}, modeled -20% payoff ${crisis:,.0f}"
        ),
        instrument_class=ctx.instrument_class, multi_expiry=False,
        management={
            "engine": "overlay", "sleeve": sleeve, "trend": bias,
            "contracts": contracts, "net_debit": round(debit, 2),
            "modeled_crisis_payoff": round(crisis, 2),
            "trail_stop": "trend invalidation (signal flip)",
            "profit_target_long_leg": None,
        },
        meta={"sleeve": sleeve, "modeled_crisis_payoff": crisis},
    )


def propose(
    ctx: TradeContext,
    *,
    signal_mode: str = "both",
    name_budget: Optional[float] = None,
    expression: Optional[str] = None,
) -> Optional[Suggestion]:
    """Build the overlay position for one basket member from its trend signal.

    Price history comes from ``ctx.extras['closes']``. ``name_budget`` (USD) is
    the load-bearing risk allocated to this name (contracts sized to it);
    ``expression`` in {"debit_spread", "leap"}. Both fall back to
    ``ctx.extras`` ("overlay_name_budget" / "overlay_expression") when omitted.
    Returns None when the signal is flat or the chain can't support it.
    """

    if name_budget is None:
        name_budget = float(ctx.extras.get("overlay_name_budget", 0.0) or 0.0)
    if expression is None:
        expression = ctx.extras.get("overlay_expression", "debit_spread")

    closes = ctx.extras.get("closes") or []
    direction = overlay_signal(list(closes), signal_mode)
    if direction == 0:
        return None
    return _build(ctx, direction, expression, name_budget)
