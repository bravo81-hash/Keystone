"""Stage 3 pacing audit: a full weekly refresh stays within the TWS budget.

Asserts the documented per-name request math (1 chain + 1 IV-history +
1 daily-history) and that re-running within the week (caches warm) costs zero
additional requests.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from core.ib_client import IBClient, MockIB, ReqKind, RequestBudget, TTLCache
from regime.vol_history import (
    WEEKLY_METADATA_PER_NAME,
    fetch_daily_history,
    fetch_iv_history,
)
from universe.seed import seed_tickers

NY = ZoneInfo("America/New_York")
FRIDAY = datetime(2026, 1, 2, 10, 0, tzinfo=NY)

#: Documented weekly metadata ceiling (headroom over the 80-name baseline of 240).
WEEKLY_METADATA_CEILING = 300


def _refresh(client: IBClient, names, iv_cache, daily_cache) -> None:
    for name in names:
        client.get_option_chain(name)  # CHAIN (Fridays-only, weekly cache)
        fetch_iv_history(client, name, cache=iv_cache)  # HISTORICAL
        fetch_daily_history(client, name, cache=daily_cache)  # HISTORICAL (shared w/ moves)


def test_weekly_refresh_request_math():
    names = seed_tickers()[:80]
    assert len(names) == 80
    budget = RequestBudget()
    client = IBClient(ib=MockIB(), budget=budget, clock=lambda: FRIDAY)
    iv_cache, daily_cache = TTLCache(7 * 24 * 3600), TTLCache(7 * 24 * 3600)

    _refresh(client, names, iv_cache, daily_cache)

    assert budget.count(ReqKind.CHAIN) == 80
    assert budget.count(ReqKind.HISTORICAL) == 160  # iv + daily per name
    assert budget.total == WEEKLY_METADATA_PER_NAME * 80 == 240
    assert budget.total <= WEEKLY_METADATA_CEILING


def test_warm_caches_add_zero_requests():
    names = seed_tickers()[:80]
    budget = RequestBudget()
    client = IBClient(ib=MockIB(), budget=budget, clock=lambda: FRIDAY)
    iv_cache, daily_cache = TTLCache(7 * 24 * 3600), TTLCache(7 * 24 * 3600)

    _refresh(client, names, iv_cache, daily_cache)
    first = budget.total
    _refresh(client, names, iv_cache, daily_cache)  # same week, caches warm
    assert budget.total == first  # no additional requests


def test_shared_daily_cache_dedupes_rv_and_moves():
    # The daily TRADES fetch is cached once and reused by RV20 + earnings moves.
    budget = RequestBudget()
    client = IBClient(ib=MockIB(), budget=budget, clock=lambda: FRIDAY)
    cache = TTLCache(7 * 24 * 3600)
    fetch_daily_history(client, "AAPL", cache=cache)
    fetch_daily_history(client, "AAPL", cache=cache)  # second consumer, same week
    assert budget.count(ReqKind.HISTORICAL) == 1
