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

#: Prefix stamped on every Keystone-staged order's ``orderRef`` so its fills are
#: identifiable in TWS and reconcilable back to a Keystone entry. NOTE: IBKR nets
#: positions by (account, contract) — orderRef rides the order/fills, not the
#: netted position — so this tags *what Keystone staged*, which is then matched
#: against the ``entries`` store (the monitor watches Keystone's own book, never a
#: blind ib.positions() sweep). See the alert engine for that contract.
ORDER_REF_PREFIX = "KS"


def keystone_order_ref(suggestion: Suggestion) -> str:
    """Stable, human-readable orderRef: ``KS:<account>:<family>:<sig>``.

    Bounded to IBKR's practical orderRef length; the signature is the unique key
    used to reconcile a fill back to the staged entry.
    """

    account = (getattr(suggestion, "account_id", None) or "?")
    family = getattr(suggestion.family, "value", str(suggestion.family))
    sig = suggestion.signature()
    return f"{ORDER_REF_PREFIX}:{account}:{family}:{sig}"[:128]


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
    order_ref: Optional[str] = None  # KS:<account>:<family>:<sig> — identifies Keystone's lots
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
            "orderRef": self.order_ref,
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
            orderRef=self.order_ref or "",
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
        order_ref=keystone_order_ref(suggestion),
        meta={"family": suggestion.family.value, "multi_expiry": suggestion.multi_expiry},
    )
