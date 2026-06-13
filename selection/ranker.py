"""Ranker — mandate filter -> per-sleeve candidates -> regime scoring -> fit -> cards.

Pipeline per (account, symbol) TradeContext:
  1. Account mandate FIRST — a Suggestion whose family isn't permitted for the
     account's pool, or whose instrument_class/multi_expiry is blocked by the
     account's rules, is never produced (SMSF never sees a trading family or an
     EU-cash-index multi-expiry; trading never sees a wheel family).
  2. Generate per-sleeve candidates from the strategy modules.
  3. Score with the regime blend (0.4/0.6) x tier multiplier (Tier B 0.6x).
     Market HARD_SKIP vetoes ALL candidates for that context.
  4. Consult blocked_structures — skip exact whatIf/budget-rejected repeats.
  5. portfolio.fit — drop budget breaches.
  6. Emit the top cards per account, score-sorted, with full rationale.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional

from config.schema import RiskConfig
from core.context import TradeContext
from core.models import Family, Suggestion
from portfolio.budgets import BookItem
from portfolio.fit import fit
from portfolio.account_profiles import AccountProfile, Pool
from regime.blend import MARKET_WEIGHT, STOCK_WEIGHT, blend, stock_regime_score
from strategies import collar, credit_spread, iron_condor, pmcc, trend_long, wheel_cc, wheel_csp
from universe.seed import by_ticker

TIER_B_MULTIPLIER = 0.6

TRADING_FAMILIES = frozenset(
    {
        Family.PUT_CREDIT_SPREAD,
        Family.CALL_CREDIT_SPREAD,
        Family.IRON_CONDOR,
        Family.TREND_LEAPS,
        Family.TREND_DIAGONAL,
        Family.TREND_DEBIT_SPREAD,
    }
)
SMSF_FAMILIES = frozenset({Family.WHEEL_CSP, Family.WHEEL_CC, Family.COLLAR, Family.PMCC})

TRADING_GENERATORS = [credit_spread.propose, iron_condor.propose, trend_long.propose]
SMSF_GENERATORS = [wheel_csp.propose, wheel_cc.propose, collar.propose, pmcc.propose]


def allowed_families(pool: Pool) -> frozenset[Family]:
    return TRADING_FAMILIES if pool is Pool.TRADING else SMSF_FAMILIES


def generators_for(pool: Pool):
    return TRADING_GENERATORS if pool is Pool.TRADING else SMSF_GENERATORS


def mandate_ok(profile: AccountProfile, suggestion: Suggestion) -> bool:
    """Account mandate: family permitted for the pool AND not structurally blocked."""

    if suggestion.family not in allowed_families(profile.pool):
        return False
    if profile.is_blocked(suggestion.instrument_class, suggestion.multi_expiry):
        return False
    return True


def _base_score(ctx: TradeContext) -> float:
    market, stock = ctx.market_regime, ctx.stock_regime
    if market is not None and stock is not None:
        return blend(market, stock).score
    if market is not None:
        return MARKET_WEIGHT * market.score + STOCK_WEIGHT * 0.5
    if stock is not None:
        return MARKET_WEIGHT * 0.5 + STOCK_WEIGHT * stock_regime_score(stock)
    return 0.5


def score_candidate(ctx: TradeContext) -> float:
    """Regime-blend score x tier multiplier (Tier B 0.6x)."""

    tier = ctx.extras.get("tier", "A")
    multiplier = TIER_B_MULTIPLIER if tier == "B" else 1.0
    return _base_score(ctx) * multiplier


def load_blocked_signatures(db: Any) -> set[str]:
    if db is None:
        return set()
    return {row["signature"] for row in db.query("SELECT signature FROM blocked_structures")}


def _sector_for(ctx: TradeContext) -> str:
    sector = ctx.extras.get("sector")
    if sector:
        return sector
    seed = by_ticker(ctx.symbol)
    return seed.sector if seed is not None else "UNKNOWN"


def rank(
    profiles: list[AccountProfile],
    contexts: list[TradeContext],
    *,
    cfg: Optional[RiskConfig] = None,
    books: Optional[dict[str, list[BookItem]]] = None,
    db: Any = None,
    top_n: int = 3,
) -> dict[str, list[Suggestion]]:
    """Rank candidates across accounts; return top cards per account."""

    cfg = cfg or RiskConfig()
    books = books or {}
    blocked = load_blocked_signatures(db)
    profile_by_id = {p.account_id: p for p in profiles}
    cards: dict[str, list[Suggestion]] = defaultdict(list)

    for ctx in contexts:
        profile = profile_by_id.get(ctx.account_id)
        if profile is None:
            continue
        # Market HARD_SKIP vetoes all new entries for this context (both sleeves).
        if ctx.market_regime is not None and ctx.market_regime.is_hard_skip:
            continue

        tier = ctx.extras.get("tier", "A")
        score = score_candidate(ctx)
        if score <= 0:
            continue
        sector = _sector_for(ctx)
        book = books.get(ctx.account_id, [])
        nlv = profile.nlv or ctx.nlv or 0.0
        pool = "trading" if profile.is_trading() else "investing"

        for generate in generators_for(profile.pool):
            suggestion = generate(ctx)
            if suggestion is None:
                continue
            if not mandate_ok(profile, suggestion):
                continue
            if suggestion.signature() in blocked:
                continue
            suggestion.score = round(score, 6)
            suggestion.tier = tier
            result = fit(
                suggestion,
                book,
                cfg,
                nlv,
                pool=pool,
                sector=sector,
                is_etf=ctx.is_etf,
                notional=float(suggestion.management.get("cash_reserved", 0.0) or 0.0),
                db=db,
            )
            if not result.ok:
                continue
            cards[ctx.account_id].append(suggestion)

    return {
        account_id: sorted(items, key=lambda s: s.score or 0.0, reverse=True)[:top_n]
        for account_id, items in cards.items()
    }
