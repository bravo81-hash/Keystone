"""Option-chain value objects + strike/expiry selection helpers.

Strategies pick legs off an :class:`OptionChain` — find the expiry near a target
DTE, then the strike near a target |delta|. Built live from ib_client's cached
Friday chain (2-pass ATM + 25-delta); constructed directly from fixtures in
tests. Delta is stored signed (calls 0..1, puts -1..0); selection matches on
absolute delta.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field

from core.models import Right


class OptionQuote(BaseModel):
    expiry: date
    strike: float
    right: Right
    bid: float = 0.0
    ask: float = 0.0
    iv: float = 0.0
    delta: float = 0.0  # signed: calls +, puts -

    @property
    def mid(self) -> float:
        if self.bid <= 0 and self.ask <= 0:
            return 0.0
        if self.bid <= 0:
            return self.ask
        if self.ask <= 0:
            return self.bid
        return (self.bid + self.ask) / 2.0

    @property
    def abs_delta(self) -> float:
        return abs(self.delta)


class OptionChain(BaseModel):
    symbol: str
    spot: float
    quotes: list[OptionQuote] = Field(default_factory=list)
    asof: Optional[date] = None
    multiplier: int = 100

    # --- expiries --------------------------------------------------------- #
    def expiries(self) -> list[date]:
        return sorted({q.expiry for q in self.quotes})

    def dte(self, expiry: date, asof: Optional[date] = None) -> int:
        ref = asof or self.asof or date.today()
        return (expiry - ref).days

    def nearest_expiry(
        self,
        target_dte: int,
        *,
        min_dte: int,
        max_dte: int,
        asof: Optional[date] = None,
    ) -> Optional[date]:
        """Expiry whose DTE is within [min_dte, max_dte], closest to target_dte."""

        ref = asof or self.asof or date.today()
        candidates = [e for e in self.expiries() if min_dte <= self.dte(e, ref) <= max_dte]
        if not candidates:
            return None
        return min(candidates, key=lambda e: abs(self.dte(e, ref) - target_dte))

    # --- strikes ---------------------------------------------------------- #
    def quotes_for(self, expiry: date, right: Right) -> list[OptionQuote]:
        qs = [q for q in self.quotes if q.expiry == expiry and q.right == right]
        return sorted(qs, key=lambda q: q.strike)

    def by_delta(self, expiry: date, right: Right, target_abs_delta: float) -> Optional[OptionQuote]:
        """Quote whose |delta| is closest to ``target_abs_delta``."""

        qs = self.quotes_for(expiry, right)
        if not qs:
            return None
        return min(qs, key=lambda q: abs(q.abs_delta - target_abs_delta))

    def get(self, expiry: date, strike: float, right: Right) -> Optional[OptionQuote]:
        for q in self.quotes:
            if q.expiry == expiry and q.right == right and abs(q.strike - strike) < 1e-9:
                return q
        return None
