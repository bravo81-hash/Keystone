"""Events interface — one front door over earnings + dividends.

``Event(symbol, date, kind {EARNINGS, DIV}, confirmed, meta)`` lives in
core.models. This module exposes the lookups the rest of Keystone calls:
``get_next_earnings``, ``get_next_exdiv``, and ``get_events`` (both kinds within
a forward window). Sources/pacing live in events.earnings and events.dividends;
this is a thin, stable facade.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Optional, Union
from zoneinfo import ZoneInfo

from core.models import Contract, Event
from events.dividends import get_next_exdiv as _get_next_exdiv
from events.earnings import FinnhubEarnings
from events.earnings import get_next_earnings as _get_next_earnings

NY = ZoneInfo("America/New_York")


def get_next_earnings(
    symbol: str,
    *,
    ib_client: Any = None,
    finnhub: Optional[FinnhubEarnings] = None,
    asof: Optional[date] = None,
    **kwargs: Any,
) -> Optional[Event]:
    return _get_next_earnings(
        symbol, ib_client=ib_client, finnhub=finnhub, asof=asof, **kwargs
    )


def get_next_exdiv(
    symbol_or_contract: Union[str, Contract],
    ib_client: Any,
    *,
    asof: Optional[date] = None,
    **kwargs: Any,
) -> Optional[Event]:
    return _get_next_exdiv(symbol_or_contract, ib_client, asof=asof, **kwargs)


def get_events(
    symbol: str,
    *,
    window_days: int = 90,
    ib_client: Any = None,
    finnhub: Optional[FinnhubEarnings] = None,
    asof: Optional[date] = None,
) -> list[Event]:
    """All known events (earnings + ex-div) for ``symbol`` within the window."""

    asof = asof or datetime.now(NY).date()
    end = asof + timedelta(days=window_days)
    events: list[Event] = []

    earnings = _get_next_earnings(symbol, ib_client=ib_client, finnhub=finnhub, asof=asof)
    if earnings is not None and asof <= earnings.date <= end:
        events.append(earnings)

    if ib_client is not None:
        exdiv = _get_next_exdiv(symbol, ib_client, asof=asof)
        if exdiv is not None and asof <= exdiv.date <= end:
            events.append(exdiv)

    events.sort(key=lambda e: e.date)
    return events
