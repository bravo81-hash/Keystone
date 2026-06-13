"""Long-premium trend convexity (trading sleeve, small).

Three structures, defined risk = debit:
  * LEAPS — deep ITM ~75 delta, 6-12mo, stock-replacement.
  * Diagonal — long LEAPS + short ~30 delta monthly call, directional carry.
  * Debit spread — long ~60 / short ~30 delta, 60-120 DTE.

Sizing doctrine: per-position debit <= 0.5% NLV; aggregate trend-sleeve <= 5%
NLV (proposals that would breach the ceiling are rejected; current usage comes
from ctx.sleeve_usage["trend"]). Management: trail an underlying stop on trend
invalidation (close below 200DMA); NO profit target on the long leg; the diagonal
short call rolls monthly or at 80% profit; optional partial scale-out.

``build_diagonal`` is reused by the SMSF PMCC wrapper (Stage 7).
"""

from __future__ import annotations

from typing import Optional

from core.context import TradeContext
from core.models import Action, Contract, Family, Leg, Right, Suggestion
from strategies.trend_filter import TrendState

PER_POSITION_PCT = 0.005  # 0.5% NLV per position
SLEEVE_CEILING_PCT = 0.05  # 5% NLV aggregate trend sleeve
MULTIPLIER = 100

LEAPS_DELTA = 0.75
LEAPS_TARGET_DTE, LEAPS_MIN_DTE, LEAPS_MAX_DTE = 270, 180, 365
SHORT_CALL_DELTA = 0.30
SHORT_TARGET_DTE, SHORT_MIN_DTE, SHORT_MAX_DTE = 30, 21, 45
DEBIT_LONG_DELTA, DEBIT_SHORT_DELTA = 0.60, 0.30
DEBIT_TARGET_DTE, DEBIT_MIN_DTE, DEBIT_MAX_DTE = 90, 60, 120


def trend_management(*, diagonal: bool = False, scale_out: bool = False) -> dict:
    m = {
        "trail_stop": "close below 200DMA (trend invalidation)",
        "profit_target_long_leg": None,  # let trends run — no PT on the long leg
        "partial_scale_out": scale_out,
        "alerts": ["trend_invalidation"],
    }
    if diagonal:
        m["short_call_roll"] = "monthly or at 80% profit"
    return m


def _direction_right(ctx: TradeContext) -> Optional[Right]:
    trend = ctx.extras.get("trend")
    if trend is TrendState.UP:
        return Right.CALL
    if trend is TrendState.DOWN:
        return Right.PUT
    return None


def _sleeve_breach(ctx: TradeContext, debit_dollars: float) -> Optional[str]:
    """Return a breach reason if this debit violates the per-position or sleeve cap."""

    nlv = ctx.nlv
    if not nlv or nlv <= 0:
        return "no NLV available for trend sizing"
    per_position_cap = PER_POSITION_PCT * nlv
    if debit_dollars > per_position_cap:
        return f"debit ${debit_dollars:.0f} exceeds per-position cap ${per_position_cap:.0f} (0.5% NLV)"
    used = ctx.sleeve_usage.get("trend", 0.0)
    ceiling = SLEEVE_CEILING_PCT * nlv
    if used + debit_dollars > ceiling:
        return f"would breach trend-sleeve ceiling ${ceiling:.0f} (used ${used:.0f} + ${debit_dollars:.0f})"
    return None


def _expiry(ctx: TradeContext, target: int, lo: int, hi: int):
    return ctx.chain.nearest_expiry(target, min_dte=lo, max_dte=hi, asof=ctx.asof or ctx.chain.asof)


def propose_leaps(ctx: TradeContext) -> Optional[Suggestion]:
    right = _direction_right(ctx)
    if right is None:
        return None
    expiry = _expiry(ctx, LEAPS_TARGET_DTE, LEAPS_MIN_DTE, LEAPS_MAX_DTE)
    if expiry is None:
        return None
    leg_q = ctx.chain.by_delta(expiry, right, LEAPS_DELTA)
    if leg_q is None or leg_q.mid <= 0:
        return None
    debit = leg_q.mid * MULTIPLIER
    if _sleeve_breach(ctx, debit):
        return None

    legs = [Leg(contract=Contract.option(ctx.symbol, expiry, leg_q.strike, right), action=Action.BUY)]
    return Suggestion(
        symbol=ctx.symbol,
        account_id=ctx.account_id,
        family=Family.TREND_LEAPS,
        legs=legs,
        dte=ctx.chain.dte(expiry, ctx.asof or ctx.chain.asof),
        entry_greeks={"net_delta": leg_q.delta},  # long single leg: signed delta
        max_loss=debit,
        rationale=f"LEAPS {right.value} {leg_q.strike} @ {expiry} (~{leg_q.abs_delta:.2f}d), debit {leg_q.mid:.2f}",
        instrument_class=ctx.instrument_class,
        multi_expiry=False,
        management=trend_management(),
    )


def build_diagonal(
    ctx: TradeContext,
    right: Right,
    *,
    long_delta: float = LEAPS_DELTA,
    short_delta: float = SHORT_CALL_DELTA,
    family: Family = Family.TREND_DIAGONAL,
) -> Optional[Suggestion]:
    """Long LEAPS + short near-dated option (reused by SMSF PMCC, Stage 7)."""

    long_exp = _expiry(ctx, LEAPS_TARGET_DTE, LEAPS_MIN_DTE, LEAPS_MAX_DTE)
    short_exp = _expiry(ctx, SHORT_TARGET_DTE, SHORT_MIN_DTE, SHORT_MAX_DTE)
    if long_exp is None or short_exp is None or long_exp == short_exp:
        return None
    long_q = ctx.chain.by_delta(long_exp, right, long_delta)
    short_q = ctx.chain.by_delta(short_exp, right, short_delta)
    if long_q is None or short_q is None or long_q.mid <= short_q.mid:
        return None

    net_debit = (long_q.mid - short_q.mid) * MULTIPLIER
    if _sleeve_breach(ctx, net_debit):
        return None

    legs = [
        Leg(contract=Contract.option(ctx.symbol, long_exp, long_q.strike, right), action=Action.BUY),
        Leg(contract=Contract.option(ctx.symbol, short_exp, short_q.strike, right), action=Action.SELL),
    ]
    return Suggestion(
        symbol=ctx.symbol,
        account_id=ctx.account_id,
        family=family,
        legs=legs,
        dte=ctx.chain.dte(long_exp, ctx.asof or ctx.chain.asof),
        entry_greeks={"long_delta": long_q.delta, "short_delta": short_q.delta},
        max_loss=net_debit,
        rationale=(
            f"diagonal long {long_q.strike}@{long_exp} / short {short_q.strike}@{short_exp} "
            f"({right.value}), net debit {(long_q.mid - short_q.mid):.2f}"
        ),
        instrument_class=ctx.instrument_class,
        multi_expiry=True,
        management=trend_management(diagonal=True),
    )


def propose_diagonal(ctx: TradeContext) -> Optional[Suggestion]:
    right = _direction_right(ctx)
    if right is None:
        return None
    return build_diagonal(ctx, right)


def propose_debit_spread(ctx: TradeContext) -> Optional[Suggestion]:
    right = _direction_right(ctx)
    if right is None:
        return None
    expiry = _expiry(ctx, DEBIT_TARGET_DTE, DEBIT_MIN_DTE, DEBIT_MAX_DTE)
    if expiry is None:
        return None
    long_q = ctx.chain.by_delta(expiry, right, DEBIT_LONG_DELTA)
    short_q = ctx.chain.by_delta(expiry, right, DEBIT_SHORT_DELTA)
    if long_q is None or short_q is None or long_q.strike == short_q.strike or long_q.mid <= short_q.mid:
        return None

    net_debit = (long_q.mid - short_q.mid) * MULTIPLIER
    if _sleeve_breach(ctx, net_debit):
        return None

    legs = [
        Leg(contract=Contract.option(ctx.symbol, expiry, long_q.strike, right), action=Action.BUY),
        Leg(contract=Contract.option(ctx.symbol, expiry, short_q.strike, right), action=Action.SELL),
    ]
    return Suggestion(
        symbol=ctx.symbol,
        account_id=ctx.account_id,
        family=Family.TREND_DEBIT_SPREAD,
        legs=legs,
        dte=ctx.chain.dte(expiry, ctx.asof or ctx.chain.asof),
        entry_greeks={"long_delta": long_q.delta, "short_delta": short_q.delta},
        max_loss=net_debit,
        rationale=(
            f"debit spread long {long_q.strike} / short {short_q.strike} @ {expiry} "
            f"({right.value}), net debit {(long_q.mid - short_q.mid):.2f}"
        ),
        instrument_class=ctx.instrument_class,
        multi_expiry=False,
        management=trend_management(),
    )


def propose(ctx: TradeContext) -> Optional[Suggestion]:
    """Uniform entry point. ctx.extras['trend_structure'] in {leaps,diagonal,debit}."""

    structure = ctx.extras.get("trend_structure", "leaps")
    if structure == "diagonal":
        return propose_diagonal(ctx)
    if structure == "debit":
        return propose_debit_spread(ctx)
    return propose_leaps(ctx)
