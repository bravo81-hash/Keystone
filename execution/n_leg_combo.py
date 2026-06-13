"""Build N-leg combo (BAG) orders from a Suggestion. transmit=False ALWAYS.

A :class:`StagedOrder` is Keystone's broker-agnostic representation of a combo:
the per-leg actions/ratios, a net signed limit price, and the order params with
``transmit`` hard-wired to False. ``to_ib_order()`` is the (lazy) seam that
builds the real ib_insync Order; it likewise never transmits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from core.models import Action, Contract, Right, SecType, Suggestion

MULTIPLIER = 100


@dataclass
class ComboLeg:
    symbol: str
    expiry: Optional[date]
    strike: Optional[float]
    right: Optional[Right]
    action: Action
    ratio: int = 1


@dataclass
class StagedOrder:
    symbol: str
    combo_legs: list[ComboLeg]
    action: str  # BUY (net debit) | SELL (net credit)
    quantity: int
    order_type: str = "LMT"
    limit_price: Optional[float] = None
    tif: str = "DAY"  # never MOC
    transmit: bool = False  # ALWAYS — staged only
    meta: dict = field(default_factory=dict)

    @property
    def contract(self) -> Contract:
        return Contract(symbol=self.symbol, sec_type=SecType.BAG)

    def order_stub(self) -> dict:
        """Broker-agnostic order payload (used by whatIf / the mock path)."""

        return {
            "action": self.action,
            "orderType": self.order_type,
            "totalQuantity": self.quantity,
            "lmtPrice": self.limit_price,
            "tif": self.tif,
            "transmit": False,
        }

    def to_ib_order(self):  # pragma: no cover - live seam
        """Build an ib_insync Order (lazy import). transmit stays False."""

        from ib_insync import Order

        return Order(
            action=self.action,
            orderType=self.order_type,
            totalQuantity=self.quantity,
            lmtPrice=self.limit_price,
            tif=self.tif,
            transmit=False,
        )


def build_combo(
    suggestion: Suggestion,
    *,
    quantity: int = 1,
    limit_price: Optional[float] = None,
) -> StagedOrder:
    """Assemble a staged combo order from a Suggestion's legs."""

    combo_legs = [
        ComboLeg(
            symbol=leg.contract.symbol,
            expiry=leg.contract.expiry,
            strike=leg.contract.strike,
            right=leg.contract.right,
            action=leg.action,
            ratio=leg.quantity,
        )
        for leg in suggestion.legs
    ]

    credit = suggestion.management.get("credit")
    if limit_price is None:
        if credit is not None:
            action, limit_price = "SELL", round(float(credit), 4)  # net credit received
        elif suggestion.max_loss:
            action, limit_price = "BUY", round(float(suggestion.max_loss) / MULTIPLIER, 4)  # net debit
        else:
            action, limit_price = "BUY", None
    else:
        action = "SELL" if credit is not None else "BUY"

    return StagedOrder(
        symbol=suggestion.symbol,
        combo_legs=combo_legs,
        action=action,
        quantity=quantity,
        limit_price=limit_price,
        transmit=False,
        meta={"family": suggestion.family.value, "multi_expiry": suggestion.multi_expiry},
    )
