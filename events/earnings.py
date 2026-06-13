"""Earnings calendar with source priority.

Resolution order (the manual CSV is an *override* and wins when present):
  1. data/earnings_manual.csv  (ticker,date,confirmed)
  2. IBKR reqFundamentalData "CalendarReport"  (pacing: one req/ticker/week, cached)
  3. Finnhub /calendar/earnings  (FINNHUB_KEY from env)

Unknown OR unconfirmed => the returned Event has ``confirmed=False`` (or the
lookup returns None); callers hard-skip any expiry that could straddle it.

``get_next_earnings(symbol)`` with no ib_client/finnhub is CSV-only — the
signature the Stage 1 screen depends on.
"""

from __future__ import annotations

import csv
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Optional
from xml.etree import ElementTree

from core.ib_client import ReqKind
from core.models import Contract, Event, EventKind

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MANUAL_CSV = DATA_DIR / "earnings_manual.csv"

_TRUE = {"true", "1", "yes", "y", "confirmed"}


def _parse_bool(value: str) -> bool:
    return str(value).strip().lower() in _TRUE


# --------------------------------------------------------------------------- #
# Source 1: manual CSV (override)
# --------------------------------------------------------------------------- #
def _read_manual_csv(csv_path: Path) -> dict[str, list[Event]]:
    events: dict[str, list[Event]] = {}
    if not csv_path.exists():
        return events
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            ticker = (row.get("ticker") or "").strip().upper()
            raw_date = (row.get("date") or "").strip()
            if not ticker or ticker.startswith("#") or not raw_date:
                continue
            try:
                edate = date.fromisoformat(raw_date)
            except ValueError:
                continue
            events.setdefault(ticker, []).append(
                Event(
                    symbol=ticker,
                    date=edate,
                    kind=EventKind.EARNINGS,
                    confirmed=_parse_bool(row.get("confirmed", "")),
                    meta={"source": "manual_csv"},
                )
            )
    for evs in events.values():
        evs.sort(key=lambda e: e.date)
    return events


def csv_next_earnings(symbol: str, asof: date, csv_path: Path = MANUAL_CSV) -> Optional[Event]:
    for event in _read_manual_csv(csv_path).get(symbol.upper(), []):
        if event.date >= asof:
            return event
    return None


# --------------------------------------------------------------------------- #
# Source 2: IBKR fundamentals
# --------------------------------------------------------------------------- #
def parse_ibkr_calendar(xml: Optional[str]) -> Optional[tuple[date, bool]]:
    """Best-effort parse of an IBKR CalendarReport for the next earnings date.

    Tolerant: finds the first element carrying a ``date`` attribute (ISO).
    Live XML tag names vary by data vendor — verify against your TWS feed; this
    is the integration seam.
    """

    if not xml or not isinstance(xml, str):
        return None
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return None
    for elem in root.iter():
        raw = elem.get("date")
        if not raw:
            continue
        try:
            edate = date.fromisoformat(raw)
        except ValueError:
            continue
        return edate, _parse_bool(elem.get("confirmed", "false"))
    return None


def ibkr_next_earnings(
    symbol: str,
    ib_client: Any,
    *,
    asof: date,
    cache: Any = None,
) -> Optional[Event]:
    """Next earnings via ib_client.reqFundamentalData. Charges the FUNDAMENTAL budget."""

    key = ("earnings", symbol.upper())
    if cache is not None:
        cached = cache.get(key)
        if cached is not None:
            return None if cached is False else cached

    xml = ib_client.ib.reqFundamentalData(Contract.stock(symbol), "CalendarReport")
    ib_client.budget.charge(ReqKind.FUNDAMENTAL)
    parsed = parse_ibkr_calendar(xml)
    event: Optional[Event] = None
    if parsed is not None:
        edate, confirmed = parsed
        if edate >= asof:
            event = Event(
                symbol=symbol.upper(),
                date=edate,
                kind=EventKind.EARNINGS,
                confirmed=confirmed,
                meta={"source": "ibkr"},
            )
    if cache is not None:
        cache.put(key, event if event is not None else False)
    return event


# --------------------------------------------------------------------------- #
# Source 3: Finnhub
# --------------------------------------------------------------------------- #
HttpGet = Callable[[str, dict], dict]


def _default_http_get(url: str, params: dict) -> dict:
    import json
    import urllib.parse
    import urllib.request

    full = f"{url}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(full, timeout=10) as resp:  # noqa: S310 (trusted host)
        return json.loads(resp.read().decode("utf-8"))


class FinnhubEarnings:
    """Finnhub earnings-calendar adapter. ``http_get`` is injectable for tests."""

    BASE = "https://finnhub.io/api/v1/calendar/earnings"

    def __init__(self, api_key: Optional[str] = None, http_get: Optional[HttpGet] = None) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("FINNHUB_KEY")
        self._http_get = http_get or _default_http_get

    def next_earnings(self, symbol: str, *, asof: date, horizon_days: int = 365) -> Optional[Event]:
        if not self.api_key:
            return None
        payload = self._http_get(
            self.BASE,
            {
                "symbol": symbol.upper(),
                "from": asof.isoformat(),
                "to": (asof + timedelta(days=horizon_days)).isoformat(),
                "token": self.api_key,
            },
        )
        dates: list[date] = []
        for row in (payload or {}).get("earningsCalendar", []):
            raw = row.get("date")
            if not raw:
                continue
            try:
                dates.append(date.fromisoformat(raw))
            except ValueError:
                continue
        future = sorted(d for d in dates if d >= asof)
        if not future:
            return None
        # Finnhub lists scheduled dates; treat a concrete calendar date as confirmed.
        return Event(
            symbol=symbol.upper(),
            date=future[0],
            kind=EventKind.EARNINGS,
            confirmed=True,
            meta={"source": "finnhub"},
        )


# --------------------------------------------------------------------------- #
# Resolver
# --------------------------------------------------------------------------- #
def get_next_earnings(
    symbol: str,
    *,
    ib_client: Any = None,
    finnhub: Optional[FinnhubEarnings] = None,
    asof: Optional[date] = None,
    csv_path: Optional[Path] = None,
    cache: Any = None,
) -> Optional[Event]:
    """Resolve next earnings by source priority (CSV override -> IBKR -> Finnhub)."""

    asof = asof or date.today()

    event = csv_next_earnings(symbol, asof, csv_path or MANUAL_CSV)
    if event is not None:
        return event

    if ib_client is not None:
        event = ibkr_next_earnings(symbol, ib_client, asof=asof, cache=cache)
        if event is not None:
            return event

    if finnhub is not None:
        event = finnhub.next_earnings(symbol, asof=asof)
        if event is not None:
            return event

    return None
