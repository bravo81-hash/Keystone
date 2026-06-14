"""Live combo staging into TWS — builds a real ib_insync BAG order from a
Suggestion, runs whatIf for margin, and places it UNTRANSMITTED (transmit=False)
so it appears in TWS for you to review and transmit manually.

Live-only (needs a connected ib_insync IB). The mock path uses execution.stage.
"""

from __future__ import annotations

from typing import Any

from core.models import Right, Suggestion

MULTIPLIER = 100


def stage_suggestion_live(ib: Any, suggestion: Suggestion, *, transmit: bool = False) -> dict:
    """Qualify legs -> BAG combo -> whatIf -> placeOrder(transmit=False).

    Returns a result dict (accepted, margins, action/limit, order_id). NEVER
    transmits unless explicitly asked (default False).
    """

    from ib_insync import ComboLeg, Contract as IBContract, Option, Order, Stock

    combo_legs = []
    for leg in suggestion.legs:
        c = leg.contract
        if c.right is not None and c.expiry is not None and c.strike is not None:
            right = "C" if c.right is Right.CALL else "P"
            ibc = Option(c.symbol, c.expiry.strftime("%Y%m%d"), c.strike, right,
                         exchange="SMART", currency="USD")
        else:
            ibc = Stock(c.symbol, "SMART", "USD")
        ib.qualifyContracts(ibc)
        if not getattr(ibc, "conId", None):
            raise RuntimeError(f"could not qualify {c.symbol} {c.strike}{c.right}")
        combo_legs.append(
            ComboLeg(conId=ibc.conId, ratio=leg.quantity, action=leg.action.value, exchange="SMART")
        )

    bag = IBContract(symbol=suggestion.symbol, secType="BAG", currency="USD",
                     exchange="SMART", comboLegs=combo_legs)

    mgmt = suggestion.management or {}
    if mgmt.get("credit") is not None:
        action, limit = "SELL", round(float(mgmt["credit"]), 2)
    else:
        action, limit = "BUY", round(float(suggestion.max_loss or 0) / MULTIPLIER, 2)

    order = Order(action=action, orderType="LMT", totalQuantity=1, lmtPrice=limit,
                  tif="DAY", transmit=transmit)

    state = ib.whatIfOrder(bag, order)

    def _f(name: str) -> float:
        try:
            return float(getattr(state, name, 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    trade = ib.placeOrder(bag, order)  # staged; transmit=False -> not sent
    return {
        "accepted": True,
        "init_margin": _f("initMarginChange"),
        "maint_margin": _f("maintMarginChange"),
        "equity_with_loan": _f("equityWithLoanChange"),
        "action": action,
        "limit": limit,
        "transmit": transmit,
        "order_id": getattr(getattr(trade, "order", None), "orderId", None),
    }
