"""Engine 2 core — capital-efficient long beta via deep-ITM LEAPS / PMCC.

Builds leveraged equity-risk-premium exposure on quality broad/sector ETFs and
quality names: a deep-ITM LEAPS (~70-80 delta, 6-12mo) as stock replacement, or
a PMCC (LEAPS + short ~25d call as a covered diagonal). Contracts are sized so
effective core exposure ≈ ``core_exposure_mult`` x allocated capital.

Account rules (the caller signals the pool via ``ctx.extras['pool']``):
  * margin ("trading")    — LEAPS/PMCC, BPR-efficient (margin permitted).
  * SMSF   ("investing")  — IDENTICAL structure, but the long premium MUST be
                            fully paid from available cash (no borrowing); the
                            short call is routed as a covered diagonal (the long
                            LEAPS covers it — permitted American-style). If the
                            premium exceeds available cash the proposal is
                            dropped (Keystone never borrows in the SMSF).

``max_loss`` is the (defined) net debit — the long deep-ITM leg dominates, so
the structure cannot lose more than what's paid.
"""

from __future__ import annotations

from typing import Optional

from core.context import TradeContext
from core.models import Action, Contract, Family, Leg, Right, Suggestion

LEAPS_DELTA = 0.75  # ~70-80 delta deep-ITM
LEAPS_TARGET_DTE, LEAPS_MIN_DTE, LEAPS_MAX_DTE = 270, 180, 365
SHORT_CALL_DELTA = 0.25
SHORT_TARGET_DTE, SHORT_MIN_DTE, SHORT_MAX_DTE = 35, 21, 45
MULTIPLIER = 100


def _expiry(ctx: TradeContext, target: int, lo: int, hi: int):
    return ctx.chain.nearest_expiry(target, min_dte=lo, max_dte=hi, asof=ctx.asof or ctx.chain.asof)


def _core_capital(ctx: TradeContext) -> float:
    """Capital allocated to this name's core sleeve (USD)."""

    cap = ctx.extras.get("core_capital")
    if cap is not None:
        return float(cap)
    return float(ctx.nlv or 0.0)


def _available_cash(ctx: TradeContext) -> float:
    """Cash available to fully pay SMSF premium (no borrowing)."""

    cash = ctx.extras.get("available_cash")
    if cash is not None:
        return float(cash)
    return _core_capital(ctx)


def propose(
    ctx: TradeContext,
    *,
    core_exposure_mult: float = 1.5,
    leaps_delta: float = LEAPS_DELTA,
    use_pmcc: bool = False,
    short_delta: float = SHORT_CALL_DELTA,
) -> Optional[Suggestion]:
    """Build the leveraged core leg(s) for one name, exposure-sized.

    ``use_pmcc`` adds a short-call covered diagonal (PMCC); otherwise a plain
    deep-ITM LEAPS. Returns None when the chain can't support it or (SMSF) the
    premium can't be fully paid from cash.
    """

    chain = ctx.chain
    spot = ctx.spot_price()
    allocated = _core_capital(ctx)
    if spot <= 0 or allocated <= 0:
        return None

    long_exp = _expiry(ctx, LEAPS_TARGET_DTE, LEAPS_MIN_DTE, LEAPS_MAX_DTE)
    if long_exp is None:
        return None
    long_q = chain.by_delta(long_exp, Right.CALL, leaps_delta)
    if long_q is None or long_q.mid <= 0 or long_q.delta <= 0:
        return None

    # Effective per-contract exposure = signed delta x spot x multiplier.
    per_contract_exposure = long_q.delta * spot * MULTIPLIER
    if per_contract_exposure <= 0:
        return None
    target_exposure = core_exposure_mult * allocated
    contracts = max(1, round(target_exposure / per_contract_exposure))

    is_smsf = ctx.extras.get("pool") == "investing"

    legs = [Leg(contract=Contract.option(ctx.symbol, long_exp, long_q.strike, Right.CALL),
                action=Action.BUY, quantity=contracts)]
    short_q = None
    multi_expiry = False
    family = Family.CORE_LEAPS
    net_debit_per = long_q.mid

    if use_pmcc:
        short_exp = _expiry(ctx, SHORT_TARGET_DTE, SHORT_MIN_DTE, SHORT_MAX_DTE)
        if short_exp is not None and short_exp != long_exp:
            short_q = chain.by_delta(short_exp, Right.CALL, short_delta)
            if short_q is not None and short_q.mid > 0 and short_q.mid < long_q.mid:
                legs.append(Leg(contract=Contract.option(ctx.symbol, short_exp, short_q.strike, Right.CALL),
                                action=Action.SELL, quantity=contracts))
                net_debit_per = long_q.mid - short_q.mid
                multi_expiry = True
                family = Family.CORE_PMCC

    debit = net_debit_per * MULTIPLIER * contracts
    if debit <= 0:
        return None

    # SMSF: must be fully paid from cash — never borrow.
    fully_paid = True
    if is_smsf and debit > _available_cash(ctx) + 1e-6:
        return None  # would require borrowing — not permitted in the SMSF
    effective_exposure = per_contract_exposure * contracts
    realized_mult = effective_exposure / allocated

    greeks = {"long_delta": long_q.delta, "net_delta_shares": long_q.delta * contracts}
    if short_q is not None:
        greeks["short_delta"] = short_q.delta
        greeks["net_delta_shares"] = (long_q.delta - short_q.delta) * contracts

    management = {
        "engine": "core",
        "core_exposure_mult_target": round(core_exposure_mult, 3),
        "core_exposure_mult_realized": round(realized_mult, 3),
        "effective_exposure": round(effective_exposure, 2),
        "allocated_capital": round(allocated, 2),
        "contracts": contracts,
        "net_debit": round(debit, 2),
        "roll": "roll the LEAPS at ~60-90 DTE; do not let the core decay to expiry",
    }
    if family is Family.CORE_PMCC:
        management["short_call_roll"] = "monthly or at 80% profit"
        management["covered_diagonal"] = True  # long LEAPS covers the short call
    if is_smsf:
        management["fully_paid"] = fully_paid
        management["no_borrow"] = True
        management["available_cash"] = round(_available_cash(ctx), 2)

    side = "PMCC" if family is Family.CORE_PMCC else "LEAPS"
    rationale = (
        f"{side} core: long {contracts}x {long_q.strike}C @ {long_exp} "
        f"(~{long_q.abs_delta:.2f}d)"
        + (f" / short {short_q.strike}C @ {short_q.expiry}" if short_q is not None else "")
        + f", effective exposure ${effective_exposure:,.0f} "
        f"({realized_mult:.2f}x of ${allocated:,.0f}), net debit ${debit:,.0f}"
        + (" [SMSF fully paid, no borrow]" if is_smsf else "")
    )

    return Suggestion(
        symbol=ctx.symbol,
        account_id=ctx.account_id,
        family=family,
        legs=legs,
        dte=chain.dte(long_exp, ctx.asof or chain.asof),
        entry_greeks=greeks,
        max_loss=debit,  # defined: long deep-ITM dominates
        rationale=rationale,
        instrument_class=ctx.instrument_class,
        multi_expiry=multi_expiry,
        management=management,
        meta={"effective_exposure": effective_exposure, "fully_paid": fully_paid if is_smsf else None},
    )
