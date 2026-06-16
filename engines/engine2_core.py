"""Engine 2 — leveraged protected core. Orchestrates core + standing hedge.

Wraps ``strategies.leveraged_core`` (the LEAPS/PMCC long-beta core) and
``strategies.core_hedge`` (the standing layered tail hedge) as one engine, all
tagged ``engine="core"``. Exposes net core delta and the hedge coverage ratio
(modeled severe-tail hedge payoff / modeled severe-tail core loss) so the
governor/allocator can credit the hedge's negative marginal risk.

``propose(ctx)`` builds the core leg(s) for one name. The hedge is sized against
the AGGREGATE core severe-tail loss on an index, so it has its own entry point
(``propose_hedge``) the orchestrator calls once per book.
"""

from __future__ import annotations

from typing import Iterable

from config.schema import CoreEngineCfg, EnginesConfig
from core.context import TradeContext
from core.models import Family, Suggestion
from engines.base import Engine, tag_engine
from strategies import core_hedge, leveraged_core
from strategies.core_hedge import HedgePlan

SEVERE_SPOT_SHOCK = -0.20
_CORE_FAMILIES = (Family.CORE_LEAPS, Family.CORE_PMCC)


class Engine2Core(Engine):
    name = "core"

    def __init__(self, cfg: CoreEngineCfg | None = None) -> None:
        self.cfg = cfg or CoreEngineCfg()

    # --- core leg(s) ------------------------------------------------------- #
    def propose(self, ctx: TradeContext) -> list[Suggestion]:
        use_pmcc = bool(ctx.extras.get("use_pmcc", False))
        s = leveraged_core.propose(
            ctx,
            core_exposure_mult=self.cfg.core_exposure_mult,
            leaps_delta=self.cfg.leaps_delta,
            use_pmcc=use_pmcc,
        )
        return tag_engine([s], self.name)

    # --- standing hedge ---------------------------------------------------- #
    def propose_hedge(
        self, ctx: TradeContext, *, core_severe_loss: float, dd_budget_dollars: float
    ) -> HedgePlan:
        plan = core_hedge.propose_hedge(
            ctx,
            core_severe_loss=core_severe_loss,
            dd_budget_dollars=dd_budget_dollars,
            base_otm_pct=self.cfg.hedge_base_otm_pct,
            base_spread_width_pct=self.cfg.hedge_base_spread_width_pct,
            tail_otm_pct=self.cfg.hedge_tail_otm_pct,
        )
        plan.suggestions = tag_engine(plan.suggestions, self.name)
        return plan

    # --- exposure / coverage reporting ------------------------------------ #
    def net_core_delta(self, suggestions: Iterable[Suggestion]) -> float:
        """Net core delta in share-equivalents (hedge legs excluded)."""

        total = 0.0
        for s in suggestions:
            if getattr(s, "engine", None) != self.name or s.family not in _CORE_FAMILIES:
                continue
            total += float(s.entry_greeks.get("net_delta_shares", 0.0))
        return total

    def modeled_core_severe_loss(
        self, suggestions: Iterable[Suggestion], severe_spot_shock: float = SEVERE_SPOT_SHOCK
    ) -> float:
        """Modeled severe-tail core loss ($, positive) = effective exposure x |shock|."""

        exposure = 0.0
        for s in suggestions:
            if getattr(s, "engine", None) != self.name or s.family not in _CORE_FAMILIES:
                continue
            exposure += float(s.management.get("effective_exposure", 0.0))
        return exposure * abs(severe_spot_shock)

    @staticmethod
    def hedge_coverage_ratio(core_severe_loss: float, hedge_payoff: float) -> float:
        """Fraction of the core's modeled severe-tail loss the hedge offsets."""

        if core_severe_loss <= 0:
            return 0.0
        return hedge_payoff / core_severe_loss

    def target_allocation(self, engines_cfg: EnginesConfig) -> float:
        return engines_cfg.core.capital_allocation
