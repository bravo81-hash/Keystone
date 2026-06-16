"""AppState — the view model the Flask panels render.

Decouples the panels from the live pipeline: tests inject a fixture AppState,
and a live build assembles one from the weekly/EOD pipeline outputs. All fields
default to empty so panels degrade gracefully when a section has no data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class AppState:
    # Weekly checkpoint dashboard
    market_regime: Optional[Any] = None  # regime.market_regime.MarketRegime
    screened: dict[str, dict] = field(default_factory=dict)  # ticker -> screened entry
    cards: dict[str, list] = field(default_factory=dict)  # account_id -> [Suggestion]
    account_labels: dict[str, str] = field(default_factory=dict)
    # Open book
    book: list[dict] = field(default_factory=list)  # position rows
    # Alerts queue
    alerts: list = field(default_factory=list)  # [alerts.monitor.Alert]
    optionstrat_urls: dict[str, str] = field(default_factory=dict)  # symbol -> url
    # SMSF view
    smsf_holdings: list[dict] = field(default_factory=list)  # {ticker,target,current,wheel_state}
    collars: list[dict] = field(default_factory=list)
    # Stress panel
    stress: Optional[Any] = None  # portfolio.stress.StressResult
    # v2 governor panel
    engine_allocations: dict[str, dict] = field(default_factory=dict)  # engine -> {target, actual}
    governor: Optional[dict] = None  # {vol_target, sigma_now, exposure_scalar, drawdown,
    #   tier, leverage_util, hedge_coverage, severe_tail_pass, severe_tail_loss, dd_budget}
