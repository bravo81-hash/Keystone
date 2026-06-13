"""Trade context passed to every ``strategy.propose(ctx)``.

Carries the shared, read-only inputs a strategy needs to build a Suggestion:
the pacing IB client, the resolved account profile, regime reads (market +
per-stock), event lookups (earnings/dividends), the screened-universe entry,
and the per-position budget. Strategies never reach out to TWS directly — they
read from ``ctx``.

The full dataclass is assembled by the ranker (Stage 9) once the regime,
events, and portfolio layers exist. Defined minimally here so type hints in
later stages resolve.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class TradeContext:
    """Minimal placeholder; fields are added as later stages land."""

    symbol: str
    account_id: str
    # Populated by later stages (regime/events/portfolio/universe).
    extras: dict[str, Any] = field(default_factory=dict)
    ib: Optional[Any] = None
