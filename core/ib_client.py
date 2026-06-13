"""Pacing-aware IBKR client (ib_insync), with a MockIB for tests.

Pacing doctrine (re-implemented fresh, not imported):
  * Market-data requests are issued in batches of at most ``batch_size`` (40)
    and cancelled before the next batch opens, so we never hold more than one
    batch of streaming lines at once.
  * Per-request-type TTL caches avoid re-requesting within a refresh window.
  * Option chains are refreshed Fridays only; other days serve from cache.
  * Every request is counted in a ``RequestBudget`` so tests can assert a full
    weekly refresh stays within TWS limits (the pacing audit, Stage 3).

ib_insync is imported lazily inside :meth:`IBClient.connect` so the rest of
Keystone — and the entire test suite — runs without it installed. Tests inject
a :class:`MockIB`; CI never opens a live connection.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Iterable, Iterator, Optional
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
FRIDAY = 4  # datetime.weekday(): Monday=0 .. Sunday=6


# --------------------------------------------------------------------------- #
# Request accounting
# --------------------------------------------------------------------------- #
class ReqKind(str, Enum):
    """Request types tracked by the budget (one TTL cache per chain/history)."""

    CHAIN = "chain"
    MKT_DATA = "mkt_data"
    HISTORICAL = "historical"
    FUNDAMENTAL = "fundamental"
    CONTRACT_DETAILS = "contract_details"
    TICK = "tick"  # generic ticks (e.g. ex-div 456)


class RequestBudget:
    """Counts requests by kind so pacing can be asserted in tests."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def charge(self, kind: ReqKind, n: int = 1) -> None:
        self._counts[kind.value] = self._counts.get(kind.value, 0) + n

    @property
    def total(self) -> int:
        return sum(self._counts.values())

    def count(self, kind: ReqKind) -> int:
        return self._counts.get(kind.value, 0)

    def by_kind(self) -> dict[str, int]:
        return dict(self._counts)

    def reset(self) -> None:
        self._counts.clear()


# --------------------------------------------------------------------------- #
# TTL cache
# --------------------------------------------------------------------------- #
@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


class TTLCache:
    """Tiny time-to-live cache. ``clock`` returns seconds (monotonic by default)."""

    def __init__(self, ttl_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl = ttl_seconds
        self._clock = clock
        self._store: dict[Any, _CacheEntry] = {}

    def get(self, key: Any) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        if self._clock() >= entry.expires_at:
            del self._store[key]
            return None
        return entry.value

    def put(self, key: Any, value: Any) -> None:
        self._store[key] = _CacheEntry(value, self._clock() + self.ttl)

    def __contains__(self, key: Any) -> bool:
        return self.get(key) is not None

    def clear(self) -> None:
        self._store.clear()


def _chunk(items: list[Any], size: int) -> Iterator[list[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


# --------------------------------------------------------------------------- #
# Mock IB for tests
# --------------------------------------------------------------------------- #
class _FakeTicker:
    """Minimal ticker stand-in (the fields IBClient reads off a snapshot)."""

    def __init__(
        self,
        bid: float = 0.0,
        ask: float = 0.0,
        last: float = 0.0,
        dividends: Optional[str] = None,
    ) -> None:
        self.bid = bid
        self.ask = ask
        self.last = last
        # IBDividends (generic tick 456) string: "past12m,next12m,exDivYYYYMMDD,amount".
        self.dividends = dividends


class MockIB:
    """In-memory stand-in for ``ib_insync.IB``.

    Records every reqMktData / cancelMktData call and tracks the maximum number
    of simultaneously-open market-data lines, so tests can assert the
    batch-and-cancel pacing never exceeds ``batch_size``.
    """

    def __init__(
        self,
        quotes: Optional[dict[str, _FakeTicker]] = None,
        chains: Optional[dict[str, Any]] = None,
        fundamentals: Optional[dict[str, Any]] = None,
    ) -> None:
        self._quotes = quotes or {}
        self._chains = chains or {}
        self._fundamentals = fundamentals or {}
        self.req_mkt_data_calls: list[Any] = []
        self.cancel_mkt_data_calls: list[Any] = []
        self.req_chain_calls: list[str] = []
        self.req_fundamental_calls: list[tuple[str, str]] = []
        self._open_lines = 0
        self.max_concurrent_lines = 0
        self.connected = False

    # --- connection ------------------------------------------------------- #
    def isConnected(self) -> bool:  # noqa: N802 (match ib_insync API)
        return self.connected

    def sleep(self, _seconds: float = 0.0) -> None:  # event-loop pump no-op
        return None

    # --- market data ------------------------------------------------------ #
    def reqMktData(self, contract: Any, *args: Any, **kwargs: Any) -> _FakeTicker:  # noqa: N802
        self.req_mkt_data_calls.append(contract)
        self._open_lines += 1
        self.max_concurrent_lines = max(self.max_concurrent_lines, self._open_lines)
        key = getattr(contract, "symbol", contract)
        return self._quotes.get(key, _FakeTicker())

    def cancelMktData(self, contract: Any) -> None:  # noqa: N802
        self.cancel_mkt_data_calls.append(contract)
        self._open_lines = max(0, self._open_lines - 1)

    # --- option chain ----------------------------------------------------- #
    def reqSecDefOptParams(self, symbol: str, *args: Any, **kwargs: Any) -> Any:  # noqa: N802
        self.req_chain_calls.append(symbol)
        return self._chains.get(
            symbol, {"symbol": symbol, "expirations": [], "strikes": []}
        )

    # --- fundamentals (earnings calendar) --------------------------------- #
    def reqFundamentalData(  # noqa: N802
        self, contract: Any, report_type: str = "CalendarReport", *args: Any, **kwargs: Any
    ) -> Any:
        symbol = getattr(contract, "symbol", contract)
        self.req_fundamental_calls.append((symbol, report_type))
        return self._fundamentals.get(symbol)


# --------------------------------------------------------------------------- #
# The client
# --------------------------------------------------------------------------- #
class IBClient:
    """Pacing-aware wrapper around an ib_insync ``IB`` (or a ``MockIB``)."""

    DEFAULT_BATCH_SIZE = 40

    def __init__(
        self,
        ib: Optional[Any] = None,
        budget: Optional[RequestBudget] = None,
        clock: Optional[Callable[[], datetime]] = None,
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
        chain_ttl_seconds: float = 7 * 24 * 3600,  # one week
        quote_ttl_seconds: float = 60.0,
        settle_seconds: float = 1.0,
        mono_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ib = ib
        self.budget = budget or RequestBudget()
        # Wall-clock in America/New_York; used for the Fridays-only policy.
        self.clock = clock or (lambda: datetime.now(NY))
        self.batch_size = batch_size
        self.settle_seconds = settle_seconds
        self._chain_cache = TTLCache(chain_ttl_seconds, clock=mono_clock)
        self._quote_cache = TTLCache(quote_ttl_seconds, clock=mono_clock)

    # --- connection ------------------------------------------------------- #
    def connect(self, host: str = "127.0.0.1", port: int = 7497, client_id: int = 1) -> Any:
        """Open a live TWS connection. Imports ib_insync lazily."""

        from ib_insync import IB  # local import: only needed for live use

        ib = IB()
        ib.connect(host, port, clientId=client_id)
        self.ib = ib
        return ib

    def is_connected(self) -> bool:
        return bool(self.ib) and bool(getattr(self.ib, "isConnected", lambda: False)())

    # --- pacing policy ---------------------------------------------------- #
    def is_chain_refresh_day(self) -> bool:
        """Fridays-only chain policy (America/New_York)."""

        return self.clock().weekday() == FRIDAY

    # --- market data (batch + cancel) ------------------------------------- #
    def fetch_quotes(self, contracts: Iterable[Any]) -> dict[Any, _FakeTicker]:
        """Snapshot quotes for many contracts in batches of ``batch_size``.

        Each batch opens up to ``batch_size`` market-data lines, lets ticks
        settle, snapshots them, then cancels every line before the next batch —
        so no more than one batch is ever open at once. Every request is charged
        to the budget.
        """

        contracts = list(contracts)
        results: dict[Any, _FakeTicker] = {}
        for batch in _chunk(contracts, self.batch_size):
            opened: list[tuple[Any, _FakeTicker]] = []
            for contract in batch:
                ticker = self.ib.reqMktData(contract)
                self.budget.charge(ReqKind.MKT_DATA)
                opened.append((contract, ticker))
            self.ib.sleep(self.settle_seconds)  # let ticks arrive
            for contract, ticker in opened:
                key = getattr(contract, "symbol", contract)
                results[key] = ticker
                self.ib.cancelMktData(contract)
        return results

    # --- option chains (Fridays-only + TTL cache) ------------------------- #
    def get_option_chain(self, symbol: str, *, force: bool = False) -> Optional[Any]:
        """Return the cached option chain, refreshing only on Fridays.

        On non-Fridays (and not ``force``) returns whatever is cached (possibly
        None) without issuing a request. On Fridays (or ``force``) fetches fresh
        on a cache miss and charges the budget.
        """

        cached = self._chain_cache.get(symbol)
        if cached is not None and not force:
            return cached
        if not (self.is_chain_refresh_day() or force):
            # Pacing policy: don't fetch chains on non-Fridays.
            return cached  # may be None
        chain = self.ib.reqSecDefOptParams(symbol)
        self.budget.charge(ReqKind.CHAIN)
        self._chain_cache.put(symbol, chain)
        return chain

    # --- cache maintenance ------------------------------------------------ #
    def clear_caches(self) -> None:
        self._chain_cache.clear()
        self._quote_cache.clear()
