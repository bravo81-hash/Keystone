"""Engine 3 — trend/managed-futures + convexity overlay orchestration.

Wraps ``strategies.trend_overlay`` behind the uniform Engine interface, tagging
each suggestion ``engine="overlay"``. Exposes net exposure by basket sleeve
(equity/bonds/gold/energy/commodity/usd) and the modeled crisis payoff — the
positive severe-tail P&L the allocator counts as hedge headroom for Engines 1-2.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from config.schema import EnginesConfig, OverlayEngineCfg
from core.context import TradeContext
from core.models import Suggestion
from engines.base import Engine, tag_engine
from strategies import trend_overlay


class Engine3Overlay(Engine):
    name = "overlay"

    def __init__(self, cfg: OverlayEngineCfg | None = None) -> None:
        self.cfg = cfg or OverlayEngineCfg()

    def propose(self, ctx: TradeContext) -> list[Suggestion]:
        name_budget = float(ctx.extras.get("overlay_name_budget", 0.0) or 0.0)
        expression = ctx.extras.get("overlay_expression", "debit_spread")
        s = trend_overlay.propose(
            ctx, signal_mode=self.cfg.signal, name_budget=name_budget, expression=expression
        )
        return tag_engine([s], self.name)

    def net_exposure_by_sleeve(self, suggestions: Iterable[Suggestion]) -> dict[str, float]:
        """Net delta (share-equivalent) grouped by basket sleeve."""

        out: dict[str, float] = defaultdict(float)
        for s in suggestions:
            if getattr(s, "engine", None) != self.name:
                continue
            sleeve = s.management.get("sleeve", "other")
            out[sleeve] += float(s.entry_greeks.get("net_delta", 0.0))
        return dict(out)

    def modeled_crisis_payoff(self, suggestions: Iterable[Suggestion]) -> float:
        """Summed modeled severe-tail (-20%) payoff across overlay positions.

        Positive => the overlay pays off in the crash (crisis alpha / hedge
        headroom); the allocator nets this against Engine 1-2 severe-tail loss.
        """

        total = 0.0
        for s in suggestions:
            if getattr(s, "engine", None) != self.name:
                continue
            total += float(s.management.get("modeled_crisis_payoff", 0.0))
        return total

    def target_allocation(self, engines_cfg: EnginesConfig) -> float:
        return engines_cfg.overlay.capital_allocation
