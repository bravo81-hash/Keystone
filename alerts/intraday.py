"""Intraday monitor hook (3x/day). DISABLED by default.

Pacing budget (so enabling it later stays within TWS limits): the monitor reads
only OPEN positions (small N) — marks + greeks — at most 3x/day. For a book of
<= 6 trading + a handful of SMSF positions, that is a few dozen market-data
snapshots per run (batched 40-and-cancel), far inside TWS limits. No chain or
history requests are issued intraday (those stay on the weekly clock).
"""

from __future__ import annotations

from typing import Any

INTRADAY_ENABLED_DEFAULT = False
RUNS_PER_DAY = 3


def run_intraday_monitor(
    snapshots: list,
    *,
    enabled: bool = INTRADAY_ENABLED_DEFAULT,
    market_hard_skip: bool = False,
    db: Any = None,
) -> list:
    """Inert unless ``enabled``; then delegates to the EOD monitor logic."""

    if not enabled:
        return []
    from alerts.monitor import run_eod_monitor

    return run_eod_monitor(snapshots, market_hard_skip=market_hard_skip, db=db)
