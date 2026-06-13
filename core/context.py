"""TradeContext — the read-only inputs every ``strategy.propose(ctx)`` consumes.

Assembled by the ranker (Stage 9). Strategies never reach out to TWS directly;
they read the chain, regime reads, events, ATR, and the per-position budget off
``ctx``. Regime types are referenced only under TYPE_CHECKING so ``core`` never
imports ``regime`` at runtime (regime already depends on core).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any, Optional

from core.chain import OptionChain
from core.models import Event, InstrumentClass

if TYPE_CHECKING:  # pragma: no cover - typing only
    from regime.market_regime import MarketRegime
    from regime.stock_regime import StockRegime


@dataclass
class TradeContext:
    symbol: str
    account_id: str
    instrument_class: InstrumentClass
    chain: OptionChain
    is_etf: bool = False
    spot: Optional[float] = None  # defaults to chain.spot
    # Regime reads (Stages 3-4).
    stock_regime: "Optional[StockRegime]" = None
    market_regime: "Optional[MarketRegime]" = None
    # Events (Stage 2).
    next_earnings: Optional[date] = None  # confirmed next earnings date
    next_exdiv: Optional[Event] = None  # ex-div event (date + meta['amount'])
    # Risk inputs.
    atr20: Optional[float] = None  # 20-day ATR of the underlying
    per_position_budget: float = 1000.0  # defined max-loss budget ($)
    nlv: Optional[float] = None
    # Sleeve / sizing context (Stages 6-7).
    sleeve_usage: dict[str, float] = field(default_factory=dict)  # e.g. {"trend": 0.0}
    target_weight: Optional[float] = None  # SMSF target weight for this name
    acquire_below_price: Optional[float] = None  # SMSF wheel acquisition cap
    core_shares: int = 0  # SMSF core share count (for covered calls)
    pmcc_enabled: bool = False
    # Bookkeeping.
    asof: Optional[date] = None
    extras: dict[str, Any] = field(default_factory=dict)
    ib: Optional[Any] = None

    def spot_price(self) -> float:
        return self.spot if self.spot is not None else self.chain.spot

    def ivr(self) -> Optional[float]:
        return self.stock_regime.ivr if self.stock_regime is not None else None
