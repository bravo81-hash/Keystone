"""Dividends: next ex-div date + amount via IBKR generic tick 456 (IBDividends).

The IBDividends tick is a comma string ``past12m,next12m,exDivYYYYMMDD,amount``.
Snapshot-fetched (request + cancel), TTL-cached. Feeds assignment-risk checks
(short call ITM with extrinsic < dividend) and the CC/wheel ex-div skip window.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional, Union

from core.ib_client import ReqKind
from core.models import Contract, Event, EventKind

GENERIC_TICK_DIVIDENDS = "456"


def _as_contract(symbol_or_contract: Union[str, Contract]) -> Contract:
    if isinstance(symbol_or_contract, Contract):
        return symbol_or_contract
    return Contract.stock(symbol_or_contract)


def parse_ib_dividends(raw: Optional[str]) -> Optional[tuple[date, float]]:
    """Parse an IBDividends string -> (next_ex_div_date, amount), or None."""

    if not raw or not isinstance(raw, str):
        return None
    parts = raw.split(",")
    if len(parts) < 4:
        return None
    raw_date, raw_amt = parts[2].strip(), parts[3].strip()
    if not raw_date or raw_date in {"0", "00000000"}:
        return None
    try:
        edate = datetime.strptime(raw_date, "%Y%m%d").date()
        amount = float(raw_amt)
    except ValueError:
        return None
    return edate, amount


def get_next_exdiv(
    symbol_or_contract: Union[str, Contract],
    ib_client: Any,
    *,
    cache: Any = None,
    asof: Optional[date] = None,
    settle_seconds: float = 0.0,
) -> Optional[Event]:
    """Next ex-dividend Event (date + amount in meta), or None. Charges TICK budget."""

    asof = asof or date.today()
    contract = _as_contract(symbol_or_contract)
    symbol = contract.symbol.upper()

    key = ("exdiv", symbol)
    if cache is not None:
        cached = cache.get(key)
        if cached is not None:
            return None if cached is False else cached

    ticker = ib_client.ib.reqMktData(contract, GENERIC_TICK_DIVIDENDS, False, False)
    ib_client.ib.sleep(settle_seconds)
    raw = getattr(ticker, "dividends", None)
    ib_client.ib.cancelMktData(contract)
    ib_client.budget.charge(ReqKind.TICK)

    parsed = parse_ib_dividends(raw)
    event: Optional[Event] = None
    if parsed is not None:
        edate, amount = parsed
        if edate >= asof:
            event = Event(
                symbol=symbol,
                date=edate,
                kind=EventKind.DIV,
                confirmed=True,
                meta={"amount": amount},
            )
    if cache is not None:
        cache.put(key, event if event is not None else False)
    return event
