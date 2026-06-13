"""american_guards(ctx, suggestion) — validity checks every strategy runs.

Three guards (the design-doc doctrine):
  * Earnings straddle — no SHORT leg in an expiry that STRADDLES a confirmed
    earnings date (names; ETFs are exempt from the earnings binary). HARD block.
  * Ex-div assignment — a SHORT CALL with an ex-div before expiry whose
    *extrinsic* value is below the dividend is early-exercise bait. HARD block.
  * Pin risk — a SHORT strike within 0.5 * 20d ATR of spot at <= 2 DTE. This is
    a card WARNING, not a block.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.context import TradeContext
from core.models import Action, Leg, Right, Suggestion
from regime.proximity import straddles_earnings

PIN_RISK_DTE = 2
PIN_RISK_ATR_FRACTION = 0.5


@dataclass
class GuardResult:
    valid: bool
    blocks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _short_legs(suggestion: Suggestion) -> list[Leg]:
    return [leg for leg in suggestion.legs if leg.action is Action.SELL]


def guard_earnings_straddle(ctx: TradeContext, suggestion: Suggestion) -> Optional[str]:
    """Block if any short leg's expiry straddles a confirmed earnings date (names)."""

    if ctx.is_etf or ctx.next_earnings is None:
        return None
    asof = ctx.asof or ctx.chain.asof
    for leg in _short_legs(suggestion):
        expiry = leg.contract.expiry
        if expiry is None:
            continue
        if straddles_earnings([expiry], ctx.next_earnings, asof):
            return f"short leg {expiry} straddles confirmed earnings {ctx.next_earnings}"
    return None


def guard_exdiv_assignment(ctx: TradeContext, suggestion: Suggestion) -> Optional[str]:
    """Block a short call whose extrinsic < dividend with an ex-div before expiry."""

    if ctx.next_exdiv is None:
        return None
    exdiv_date = ctx.next_exdiv.date
    dividend = float(ctx.next_exdiv.meta.get("amount", 0.0))
    if dividend <= 0:
        return None
    spot = ctx.spot_price()
    for leg in _short_legs(suggestion):
        c = leg.contract
        if c.right is not Right.CALL or c.expiry is None:
            continue
        if not (exdiv_date < c.expiry):  # ex-div must fall before expiry
            continue
        quote = ctx.chain.get(c.expiry, c.strike, Right.CALL)
        if quote is None:
            continue
        intrinsic = max(spot - c.strike, 0.0)
        extrinsic = quote.mid - intrinsic
        if extrinsic < dividend:
            return (
                f"short call {c.strike} extrinsic {extrinsic:.2f} < dividend "
                f"{dividend:.2f} with ex-div {exdiv_date} before {c.expiry}"
            )
    return None


def guard_pin_risk(ctx: TradeContext, suggestion: Suggestion) -> Optional[str]:
    """Warn (not block) on pin risk: short strike within 0.5*ATR at <= 2 DTE."""

    if ctx.atr20 is None or ctx.atr20 <= 0:
        return None
    asof = ctx.asof or ctx.chain.asof
    spot = ctx.spot_price()
    band = PIN_RISK_ATR_FRACTION * ctx.atr20
    for leg in _short_legs(suggestion):
        c = leg.contract
        if c.expiry is None or c.strike is None:
            continue
        dte = ctx.chain.dte(c.expiry, asof)
        if dte <= PIN_RISK_DTE and abs(spot - c.strike) <= band:
            return f"pin risk: short strike {c.strike} within {band:.2f} of spot at {dte} DTE"
    return None


def american_guards(ctx: TradeContext, suggestion: Suggestion) -> GuardResult:
    """Run all guards. Earnings + ex-div are hard blocks; pin risk is a warning."""

    blocks: list[str] = []
    warnings: list[str] = []

    for guard in (guard_earnings_straddle, guard_exdiv_assignment):
        reason = guard(ctx, suggestion)
        if reason:
            blocks.append(reason)

    pin = guard_pin_risk(ctx, suggestion)
    if pin:
        warnings.append(pin)

    return GuardResult(valid=not blocks, blocks=blocks, warnings=warnings)
