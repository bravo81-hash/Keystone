"""Keystone v2 governor — the spine above portfolio that makes leverage survivable.

  portfolio_vol      — whole-book vol estimate (realized blended with implied) +
                       measured cross-engine correlation matrix.
  vol_target         — global exposure scalar = target_vol / sigma_now (capped).
  drawdown_governor  — HWM tracking + tiered de-lever circuit-breaker with
                       anti-whipsaw re-entry, per-pool and aggregate.
  leverage_allocator — stress-constrained per-engine sizing: raise Engine 1/2
                       leverage until severe-tail loss (net of hedge + overlay
                       crisis alpha) hits the DD budget. Hedging buys leverage.
"""

from __future__ import annotations

from governor.drawdown_governor import DrawdownGovernor, DrawdownState, DrawdownTier
from governor.leverage_allocator import AllocationResult, allocate
from governor.portfolio_vol import (
    PortfolioVol,
    blend_vol,
    correlation_matrix,
    implied_vol_from_vix,
    portfolio_vol_estimate,
)
from governor.vol_target import exposure_scalar

__all__ = [
    "PortfolioVol", "blend_vol", "correlation_matrix", "implied_vol_from_vix",
    "portfolio_vol_estimate", "exposure_scalar", "DrawdownGovernor",
    "DrawdownState", "DrawdownTier", "AllocationResult", "allocate",
]
