"""Engine 1 — income. Thin orchestrator over the existing v1 strategies.

Wraps the v1 defined-risk short-premium (credit spreads, iron condor) and SMSF
wheel modules (CSP, CC, collar, PMCC) behind the uniform Engine interface. It
calls the SAME ``propose`` functions the v1 ranker calls and tags each result
``engine="income"`` — so this introduces NO behaviour change to v1 strategies;
it only re-frames them as Engine 1.

The trading TREND families (LEAPS/diagonal/debit) are intentionally NOT here —
they fold into Engine 3 (overlay) in Stage 15.

Pool selection: ``ctx.extras["pool"]`` ("trading" | "investing") picks the
generator set; absent, both run and the downstream mandate filter drops the
wrong-pool families (exactly as the v1 ranker already filters).
"""

from __future__ import annotations

from config.schema import EnginesConfig
from core.context import TradeContext
from core.models import Suggestion
from engines.base import Engine, tag_engine
from strategies import collar, credit_spread, iron_condor, pmcc, wheel_cc, wheel_csp

#: Income generators by pool. Mirrors the v1 ranker minus the trend families.
INCOME_TRADING_GENERATORS = [credit_spread.propose, iron_condor.propose]
INCOME_SMSF_GENERATORS = [wheel_csp.propose, wheel_cc.propose, collar.propose, pmcc.propose]


def income_generators_for(pool: str | None):
    """Income generator callables for a pool; both sets when pool is unknown."""

    if pool == "trading":
        return list(INCOME_TRADING_GENERATORS)
    if pool == "investing":
        return list(INCOME_SMSF_GENERATORS)
    return INCOME_TRADING_GENERATORS + INCOME_SMSF_GENERATORS


class IncomeEngine(Engine):
    name = "income"

    def propose(self, ctx: TradeContext) -> list[Suggestion]:
        pool = ctx.extras.get("pool")
        generators = income_generators_for(pool)
        return tag_engine((generate(ctx) for generate in generators), self.name)

    def target_allocation(self, engines_cfg: EnginesConfig) -> float:
        return engines_cfg.income.capital_allocation
