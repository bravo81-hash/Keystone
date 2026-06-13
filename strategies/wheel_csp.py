"""Cash-secured put — the SMSF wheel accumulation engine.

CSP on quality you'd own: 30-45 DTE, ~20-30 delta (closer to ATM — assignment is
desired), strike at/below ``acquire_below_price`` when set, never straddling a
confirmed earnings date. Cash reserved = strike * 100. Management: PT 50% ->
close & redeploy OR allow assignment; roll only to avoid assignment when the
stock isn't wanted yet. Investing pool — outside any trading DTE scope.
"""

from __future__ import annotations

from typing import Optional

from core.context import TradeContext
from core.models import Action, Contract, Family, Leg, Right, Suggestion
from strategies._guards import american_guards

TARGET_DTE = 38
MIN_DTE = 30
MAX_DTE = 45
DEFAULT_DELTA = 0.25  # 20-30 delta band, assignment-friendly
MULTIPLIER = 100


def propose(ctx: TradeContext) -> Optional[Suggestion]:
    chain = ctx.chain
    asof = ctx.asof or chain.asof
    expiry = chain.nearest_expiry(TARGET_DTE, min_dte=MIN_DTE, max_dte=MAX_DTE, asof=asof)
    if expiry is None:
        return None

    puts = chain.quotes_for(expiry, Right.PUT)
    if ctx.acquire_below_price is not None:
        puts = [q for q in puts if q.strike <= ctx.acquire_below_price]
    if not puts:
        return None
    short = min(puts, key=lambda q: abs(q.abs_delta - DEFAULT_DELTA))
    if short.mid <= 0:
        return None

    credit = short.mid
    cash_reserved = short.strike * MULTIPLIER
    max_loss = (short.strike - credit) * MULTIPLIER  # assigned, stock -> 0
    legs = [Leg(contract=Contract.option(ctx.symbol, expiry, short.strike, Right.PUT), action=Action.SELL)]
    suggestion = Suggestion(
        symbol=ctx.symbol,
        account_id=ctx.account_id,
        family=Family.WHEEL_CSP,
        legs=legs,
        dte=chain.dte(expiry, asof),
        entry_greeks={"short_delta": short.delta},
        max_loss=max_loss,
        rationale=(
            f"CSP {short.strike}P @ {expiry} (~{short.abs_delta:.2f}d), credit {credit:.2f}, "
            f"cash reserved ${cash_reserved:.0f}"
            + (f", at/below acquire price {ctx.acquire_below_price}" if ctx.acquire_below_price else "")
        ),
        instrument_class=ctx.instrument_class,
        multi_expiry=False,
        management={
            "credit": round(credit, 4),
            "strike": short.strike,
            "cash_reserved": cash_reserved,
            "profit_target_pct": 0.5,
            "on_target": "close & redeploy or allow assignment",
            "roll": "only to avoid assignment when the stock isn't wanted yet",
        },
        meta={"cash_reserved": cash_reserved},
    )
    guard = american_guards(ctx, suggestion)
    if not guard.valid:
        return None
    if guard.warnings:
        suggestion.management.setdefault("warnings", []).extend(guard.warnings)
    return suggestion
