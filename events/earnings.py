"""Earnings calendar.

Stage 1 minimal: a CSV-backed ``get_next_earnings`` reading
``data/earnings_manual.csv`` (ticker,date,confirmed). The screen uses it to
hard-skip any name whose next earnings date is unknown or unconfirmed.

Stage 2 expands this into a full source-priority adapter: IBKR reqFundamentalData
-> Finnhub (FINNHUB_KEY env) -> manual CSV override (wins when present). The
CSV reader here is the seed of that override layer.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Optional

from core.models import Event, EventKind

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MANUAL_CSV = DATA_DIR / "earnings_manual.csv"

_TRUE = {"true", "1", "yes", "y", "confirmed"}


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in _TRUE


def _read_manual_csv(csv_path: Path) -> dict[str, list[Event]]:
    """Parse the manual earnings CSV into {ticker: [Event, ...]} sorted by date."""

    events: dict[str, list[Event]] = {}
    if not csv_path.exists():
        return events
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            ticker = (row.get("ticker") or "").strip().upper()
            raw_date = (row.get("date") or "").strip()
            if not ticker or not raw_date:
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


def get_next_earnings(
    symbol: str,
    *,
    asof: Optional[date] = None,
    csv_path: Optional[Path] = None,
) -> Optional[Event]:
    """Next earnings Event on/after ``asof`` for ``symbol``, or None if unknown.

    A returned Event may have ``confirmed=False``; callers treat unknown OR
    unconfirmed as a hard skip for any straddling expiry.
    """

    asof = asof or date.today()
    path = csv_path or MANUAL_CSV
    by_ticker = _read_manual_csv(path)
    for event in by_ticker.get(symbol.upper(), []):
        if event.date >= asof:
            return event
    return None
