"""Per-engine candidate routing + governor gating (v2 pipeline).

Generates candidates per engine (income / core / overlay), still mandate-filtered
per account, then the leverage allocator + drawdown governor decide HOW MUCH of
each engine's candidates to actually stage this cycle:

  * ``engine_scale`` (from the allocator) sets the fraction of each engine's
    ranked candidates that surface.
  * a DEFENSIVE drawdown state (or market HARD_SKIP) suppresses risk-on entirely
    — only de-risking / hedge actions (CORE_HEDGE) surface.

The v1 ``selection.ranker.rank`` is untouched; this is the additive v2 path.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from config.schema import EnginesConfig, RiskConfig
from core.context import TradeContext
from core.models import Family, Suggestion
from engines.base import Engine
from engines.engine1_income import IncomeEngine
from engines.engine2_core import Engine2Core
from engines.engine3_overlay import Engine3Overlay
from portfolio.budgets import BookItem
from portfolio.fit import fit
from selection.ranker import score_candidate
from store.db import Database

INCOME_TRADING_FAMILIES = frozenset(
    {Family.PUT_CREDIT_SPREAD, Family.CALL_CREDIT_SPREAD, Family.IRON_CONDOR}
)
INCOME_SMSF_FAMILIES = frozenset({Family.WHEEL_CSP, Family.WHEEL_CC, Family.COLLAR, Family.PMCC})
CORE_FAMILIES = frozenset({Family.CORE_LEAPS, Family.CORE_PMCC, Family.CORE_HEDGE})
OVERLAY_FAMILIES = frozenset({Family.OVERLAY_DEBIT_SPREAD, Family.OVERLAY_LEAP})
HEDGE_FAMILIES = frozenset({Family.CORE_HEDGE})


def default_engines(engines_cfg: Optional[EnginesConfig] = None) -> list[Engine]:
    eng = engines_cfg or EnginesConfig()
    return [IncomeEngine(), Engine2Core(eng.core), Engine3Overlay(eng.overlay)]


def engine_mandate_ok(profile, s: Suggestion) -> bool:
    """Mandate for the engine path. Income stays pool-split (spreads=margin,
    wheel=SMSF); core + overlay apply to BOTH pools. The SMSF EU-cash-index
    multi-expiry block still applies."""

    if profile.is_blocked(s.instrument_class, s.multi_expiry):
        return False
    if s.family in INCOME_TRADING_FAMILIES:
        return profile.is_trading()
    if s.family in INCOME_SMSF_FAMILIES:
        return not profile.is_trading()
    if s.family in CORE_FAMILIES or s.family in OVERLAY_FAMILIES:
        return True
    return False


def _gate_count(scale: float, top_n: int) -> int:
    if scale <= 0:
        return 0
    return max(1, round(min(1.0, scale) * top_n))


@dataclass
class EngineRankResult:
    # account_id -> engine -> ranked candidates (mandate-filtered, scored)
    by_engine: dict[str, dict[str, list[Suggestion]]] = field(default_factory=dict)
    # account_id -> the gated subset to stage this cycle
    staged: dict[str, list[Suggestion]] = field(default_factory=dict)
    risk_on: bool = True


def rank_engines(
    profiles,
    contexts: list[TradeContext],
    *,
    engines: Optional[list[Engine]] = None,
    cfg: Optional[RiskConfig] = None,
    books: Optional[dict[str, list[BookItem]]] = None,
    db: Optional[Database] = None,
    engine_scale: Optional[dict[str, float]] = None,
    risk_on: bool = True,
    top_n: int = 3,
) -> EngineRankResult:
    """Produce per-engine candidates and the governor-gated staging set.

    ``engine_scale`` (allocator output) caps how many of each engine's candidates
    stage; ``risk_on=False`` (DEFENSIVE / HARD_SKIP) surfaces only hedge actions.
    """

    cfg = cfg or RiskConfig()
    books = books or {}
    engines = engines or default_engines()
    engine_scale = engine_scale or {"income": 1.0, "core": 1.0, "overlay": 1.0}
    profile_by_id = {p.account_id: p for p in profiles}

    by_engine: dict[str, dict[str, list[Suggestion]]] = defaultdict(lambda: defaultdict(list))

    for ctx in contexts:
        profile = profile_by_id.get(ctx.account_id)
        if profile is None:
            continue
        market_hard_skip = ctx.market_regime is not None and ctx.market_regime.is_hard_skip
        score = score_candidate(ctx)

        for engine in engines:
            for s in engine.propose(ctx):
                if not engine_mandate_ok(profile, s):
                    continue
                # Risk-on entries are vetoed in HARD_SKIP; the standing hedge is not.
                if market_hard_skip and s.family not in HEDGE_FAMILIES:
                    continue
                s.score = round(score, 6)
                # v1 per-position budget fit applies to income only; core/overlay
                # are governed by the allocator + severe-tail stress.
                if engine.name == "income":
                    nlv = profile.nlv or ctx.nlv or 0.0
                    pool = "trading" if profile.is_trading() else "investing"
                    res = fit(s, books.get(ctx.account_id, []), cfg, nlv, pool=pool,
                              sector=ctx.extras.get("sector", "UNKNOWN"), is_etf=ctx.is_etf,
                              notional=float(s.management.get("cash_reserved", 0.0) or 0.0), db=db)
                    if not res.ok:
                        continue
                by_engine[ctx.account_id][engine.name].append(s)

    # Sort each engine's candidates by score; apply governor gating to staging.
    result = EngineRankResult(risk_on=risk_on)
    for account_id, per_engine in by_engine.items():
        result.by_engine[account_id] = {}
        staged: list[Suggestion] = []
        for engine_name, items in per_engine.items():
            ranked = sorted(items, key=lambda s: s.score or 0.0, reverse=True)
            result.by_engine[account_id][engine_name] = ranked
            if not risk_on:
                # Defensive: only hedge / de-risking actions surface.
                staged.extend(s for s in ranked if s.family in HEDGE_FAMILIES)
                continue
            n = _gate_count(engine_scale.get(engine_name, 1.0), top_n)
            staged.extend(ranked[:n])
        result.staged[account_id] = staged

    return result
