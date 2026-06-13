"""Mid-price with bounded walk-in reprices. Never into MOC.

Start at the mid and step toward the marketable price in a bounded number of
reprices. The plan never overshoots the marketable price and never converts to
market-on-close (``tif`` stays DAY / the order stays a limit).
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_MAX_REPRICES = 3


@dataclass
class WalkInPlan:
    prices: list[float]
    never_moc: bool = True
    tif: str = "DAY"
    meta: dict = field(default_factory=dict)


def walk_in_prices(mid: float, marketable: float, *, max_reprices: int = DEFAULT_MAX_REPRICES) -> list[float]:
    """Limit prices from ``mid`` toward ``marketable`` in equal steps (inclusive).

    Returns ``[mid]`` if no reprices allowed; otherwise ``max_reprices + 1``
    prices ending exactly at ``marketable`` (never beyond it).
    """

    if max_reprices <= 0:
        return [round(mid, 4)]
    return [
        round(mid + (marketable - mid) * (i / max_reprices), 4)
        for i in range(max_reprices + 1)
    ]


def build_walk_in(mid: float, marketable: float, *, max_reprices: int = DEFAULT_MAX_REPRICES) -> WalkInPlan:
    return WalkInPlan(
        prices=walk_in_prices(mid, marketable, max_reprices=max_reprices),
        never_moc=True,
        tif="DAY",
        meta={"mid": mid, "marketable": marketable, "max_reprices": max_reprices},
    )
