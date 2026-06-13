"""IBClient pacing: batch-and-cancel, request budget, Fridays-only chains."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from core.ib_client import IBClient, MockIB, ReqKind, RequestBudget, TTLCache
from core.models import Contract, SecType

NY = ZoneInfo("America/New_York")
# Jan 1 2026 is a Thursday; Jan 2 2026 is a Friday.
FRIDAY = datetime(2026, 1, 2, 10, 0, tzinfo=NY)
THURSDAY = datetime(2026, 1, 1, 10, 0, tzinfo=NY)


def _contracts(n: int) -> list[Contract]:
    return [Contract(symbol=f"T{i}", sec_type=SecType.STK) for i in range(n)]


def test_batch_and_cancel_never_exceeds_batch_size():
    ib = MockIB()
    client = IBClient(ib=ib, batch_size=40)
    client.fetch_quotes(_contracts(41))

    # 41 contracts -> 41 opens, 41 cancels, but never more than 40 open at once.
    assert len(ib.req_mkt_data_calls) == 41
    assert len(ib.cancel_mkt_data_calls) == 41
    assert ib.max_concurrent_lines == 40
    assert ib._open_lines == 0  # everything cancelled


def test_budget_counts_market_data_requests():
    ib = MockIB()
    budget = RequestBudget()
    client = IBClient(ib=ib, budget=budget, batch_size=40)
    client.fetch_quotes(_contracts(41))

    assert budget.count(ReqKind.MKT_DATA) == 41
    assert budget.total == 41
    assert budget.by_kind() == {"mkt_data": 41}


def test_single_full_batch_opens_exactly_batch_size():
    ib = MockIB()
    client = IBClient(ib=ib, batch_size=40)
    client.fetch_quotes(_contracts(40))
    assert ib.max_concurrent_lines == 40
    assert len(ib.cancel_mkt_data_calls) == 40


def test_fridays_only_chain_fetch_and_cache():
    ib = MockIB(chains={"AAPL": {"symbol": "AAPL", "expirations": ["20260116"]}})
    budget = RequestBudget()
    client = IBClient(ib=ib, budget=budget, clock=lambda: FRIDAY)

    chain = client.get_option_chain("AAPL")
    assert chain["symbol"] == "AAPL"
    assert budget.count(ReqKind.CHAIN) == 1
    assert ib.req_chain_calls == ["AAPL"]

    # Second call same week: served from cache, no new request.
    again = client.get_option_chain("AAPL")
    assert again == chain
    assert budget.count(ReqKind.CHAIN) == 1
    assert ib.req_chain_calls == ["AAPL"]


def test_non_friday_does_not_fetch_chain():
    ib = MockIB(chains={"AAPL": {"symbol": "AAPL"}})
    budget = RequestBudget()
    client = IBClient(ib=ib, budget=budget, clock=lambda: THURSDAY)

    # Cold cache on a non-Friday: returns None and issues no request.
    assert client.get_option_chain("AAPL") is None
    assert budget.count(ReqKind.CHAIN) == 0
    assert ib.req_chain_calls == []


def test_non_friday_serves_existing_cache():
    ib = MockIB(chains={"AAPL": {"symbol": "AAPL"}})
    budget = RequestBudget()
    # Mutable clock: warm the cache on Friday, then move to a non-Friday.
    now = {"t": FRIDAY}
    client = IBClient(ib=ib, budget=budget, clock=lambda: now["t"])

    client.get_option_chain("AAPL")
    assert budget.count(ReqKind.CHAIN) == 1
    now["t"] = THURSDAY
    cached = client.get_option_chain("AAPL")
    assert cached["symbol"] == "AAPL"
    assert budget.count(ReqKind.CHAIN) == 1  # no extra request on the non-Friday


def test_force_refresh_overrides_friday_policy():
    ib = MockIB(chains={"AAPL": {"symbol": "AAPL"}})
    budget = RequestBudget()
    client = IBClient(ib=ib, budget=budget, clock=lambda: THURSDAY)

    chain = client.get_option_chain("AAPL", force=True)
    assert chain["symbol"] == "AAPL"
    assert budget.count(ReqKind.CHAIN) == 1


def test_is_chain_refresh_day():
    assert IBClient(ib=MockIB(), clock=lambda: FRIDAY).is_chain_refresh_day() is True
    assert IBClient(ib=MockIB(), clock=lambda: THURSDAY).is_chain_refresh_day() is False


def test_ttl_cache_expiry():
    now = {"t": 0.0}
    cache = TTLCache(ttl_seconds=10.0, clock=lambda: now["t"])
    cache.put("k", 123)
    assert cache.get("k") == 123
    now["t"] = 9.9
    assert cache.get("k") == 123
    now["t"] = 10.0
    assert cache.get("k") is None  # expired


def test_budget_reset():
    budget = RequestBudget()
    budget.charge(ReqKind.CHAIN, 3)
    budget.charge(ReqKind.MKT_DATA)
    assert budget.total == 4
    budget.reset()
    assert budget.total == 0
    assert budget.by_kind() == {}
