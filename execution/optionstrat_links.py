"""OptionStrat deep-link builder for out-of-hours modelling of a card.

Encodes each leg as ``[-][ratio].TICKERyymmddR<strike>`` (``-`` = short, no sign =
long; ratio omitted when 1) and joins them with commas under the OptionStrat
``build`` path. Leg encoding is best-effort against the live site and is the
documented seam if the URL scheme changes.
"""

from __future__ import annotations

from core.models import Action, Right, Suggestion

BASE_URL = "https://optionstrat.com/build"


def _fmt_strike(strike: float) -> str:
    return str(int(strike)) if float(strike).is_integer() else str(strike)


def _leg_token(symbol: str, expiry, strike: float, right: Right, action: Action, ratio: int) -> str:
    sign = "-" if action is Action.SELL else ""
    count = str(ratio) if ratio and ratio > 1 else ""
    yymmdd = expiry.strftime("%y%m%d")
    return f"{sign}{count}.{symbol}{yymmdd}{right.value}{_fmt_strike(strike)}"


def optionstrat_url(suggestion: Suggestion, *, strategy: str = "custom") -> str:
    """Build the OptionStrat deep link for a Suggestion's legs."""

    tokens = []
    for leg in suggestion.legs:
        c = leg.contract
        if c.expiry is None or c.strike is None or c.right is None:
            continue
        tokens.append(_leg_token(suggestion.symbol, c.expiry, c.strike, c.right, leg.action, leg.quantity))
    legs = ",".join(tokens)
    return f"{BASE_URL}/{strategy}/{suggestion.symbol}/{legs}"
