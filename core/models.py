"""Domain models shared across Keystone.

Light value objects (pydantic v2) so they serialize cleanly to the sqlite audit
store and to the UI. The trading/instrument enums live here because they are the
lowest-level vocabulary the rest of the system speaks; ``classify()`` and the
account mandate logic in ``portfolio.account_profiles`` import ``InstrumentClass``
from this module.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# Enums — the shared vocabulary
# --------------------------------------------------------------------------- #
class Right(str, Enum):
    """Option right. Values match IBKR's single-letter convention."""

    CALL = "C"
    PUT = "P"


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class SecType(str, Enum):
    """IBKR security types (subset Keystone uses)."""

    STK = "STK"
    OPT = "OPT"
    FOP = "FOP"  # future option
    FUT = "FUT"
    IND = "IND"
    CASH = "CASH"
    BAG = "BAG"  # combo / multi-leg


class InstrumentClass(str, Enum):
    """Settlement/permission class used by account mandates and budgets.

    The SMSF cash account's only structural restriction is on multi-expiry
    combos over European cash-settled index options (EU_CASH_INDEX); American
    style instruments are unrestricted there. See ``account_profiles``.
    """

    EU_CASH_INDEX = "EU_CASH_INDEX"  # SPX, RUT, NDX, XSP (European, cash-settled)
    US_EQUITY_OPT = "US_EQUITY_OPT"  # American single-name equity options
    US_ETF_OPT = "US_ETF_OPT"  # American ETF options (SPY/QQQ/IWM/sectors)
    FUT_OPT = "FUT_OPT"  # options on futures (e.g. ES)


class Family(str, Enum):
    """Strategy families. Each strategy module emits one of these."""

    PUT_CREDIT_SPREAD = "put_credit_spread"
    CALL_CREDIT_SPREAD = "call_credit_spread"
    IRON_CONDOR = "iron_condor"
    TREND_LEAPS = "trend_leaps"
    TREND_DIAGONAL = "trend_diagonal"
    TREND_DEBIT_SPREAD = "trend_debit_spread"
    WHEEL_CSP = "wheel_csp"
    WHEEL_CC = "wheel_cc"
    COLLAR = "collar"
    PMCC = "pmcc"


class EventKind(str, Enum):
    EARNINGS = "EARNINGS"
    DIV = "DIV"


# --------------------------------------------------------------------------- #
# Contracts / legs
# --------------------------------------------------------------------------- #
class Contract(BaseModel):
    """A tradable contract. Mirrors the IBKR fields Keystone needs."""

    model_config = ConfigDict(frozen=False)

    symbol: str
    sec_type: SecType = SecType.OPT
    exchange: str = "SMART"
    currency: str = "USD"
    # Option fields (None for stocks/futures).
    expiry: Optional[date] = None
    strike: Optional[float] = None
    right: Optional[Right] = None
    multiplier: int = 100
    # IBKR identity / routing (filled once resolved against TWS).
    con_id: Optional[int] = None
    trading_class: Optional[str] = None
    local_symbol: Optional[str] = None

    @classmethod
    def stock(cls, symbol: str, exchange: str = "SMART", currency: str = "USD") -> "Contract":
        return cls(symbol=symbol, sec_type=SecType.STK, exchange=exchange, currency=currency)

    @classmethod
    def option(
        cls,
        symbol: str,
        expiry: date,
        strike: float,
        right: Right,
        *,
        exchange: str = "SMART",
        currency: str = "USD",
        multiplier: int = 100,
        sec_type: SecType = SecType.OPT,
    ) -> "Contract":
        return cls(
            symbol=symbol,
            sec_type=sec_type,
            exchange=exchange,
            currency=currency,
            expiry=expiry,
            strike=strike,
            right=right,
            multiplier=multiplier,
        )


class Leg(BaseModel):
    """One leg of a (possibly multi-leg) structure. ``quantity`` is the ratio."""

    contract: Contract
    action: Action
    quantity: int = 1


# --------------------------------------------------------------------------- #
# Suggestion / Position
# --------------------------------------------------------------------------- #
def legs_span_multiple_expiries(legs: list[Leg]) -> bool:
    """True when the legs touch more than one option expiry (calendar/diagonal)."""

    expiries = {leg.contract.expiry for leg in legs if leg.contract.expiry is not None}
    return len(expiries) > 1


class Suggestion(BaseModel):
    """A proposed trade emitted by a strategy's ``propose(ctx)``.

    ``instrument_class`` and ``multi_expiry`` are what the account mandate filter
    (Stage 9) and SMSF blocked rules key on. ``max_loss`` is the defined,
    realizable worst case used by the per-position budget.
    """

    symbol: str
    account_id: str
    family: Family
    legs: list[Leg]
    dte: Optional[int] = None
    entry_greeks: dict[str, float] = Field(default_factory=dict)
    max_loss: Optional[float] = None
    rationale: str = ""
    instrument_class: InstrumentClass
    multi_expiry: bool = False
    tier: Optional[str] = None
    score: Optional[float] = None
    # Free-form management metadata (PT/stop/must-touch-by/etc.) set by strategies.
    management: dict = Field(default_factory=dict)
    meta: dict = Field(default_factory=dict)

    def signature(self) -> str:
        """Stable key for the blocked_structures learn-table (Stage 9/10)."""

        parts = [self.account_id, self.symbol, self.family.value]
        for leg in self.legs:
            c = leg.contract
            parts.append(
                f"{leg.action.value}{leg.quantity}:{c.right.value if c.right else '-'}"
                f"{c.strike if c.strike is not None else '-'}@{c.expiry or '-'}"
            )
        return "|".join(parts)


class Position(BaseModel):
    """An open (or closed) position in the audit store."""

    account_id: str
    symbol: str
    family: Family
    instrument_class: InstrumentClass
    legs: list[Leg]
    multi_expiry: bool = False
    entry_greeks: dict[str, float] = Field(default_factory=dict)
    entry_price: Optional[float] = None
    max_loss: Optional[float] = None
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    status: str = "OPEN"
    rationale: str = ""
    position_id: Optional[int] = None


class Event(BaseModel):
    """Calendar event (earnings/dividend). Fully exercised by the events package."""

    symbol: str
    date: date
    kind: EventKind
    confirmed: bool = False
    meta: dict = Field(default_factory=dict)


class DailyBar(BaseModel):
    """One daily OHLCV bar. Shared primitive for earnings realized-moves (Stage 2)
    and realized-vol / IV history (Stage 3) so they share one cached fetch."""

    date: date
    open: float
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
