"""Budgets per pool (scaled to NLV). Two pools, separate buckets.

Trading (margin): defined-risk max-loss per position <= 1% NLV; aggregate
short-premium risk cap; trend sleeve aggregate 5%; max positions; max 2 names
per sector; correlation cap.

SMSF: CSP cash-reserve cap; core-holdings notional cap; assignment notional per
name 12% (single) / 25% (diversified ETF); collar hedge allowance; max 2 names
per sector.

Each check returns a :class:`BudgetCheck` listing any breaches; an empty list
means the candidate fits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from config.schema import SMSFBudgetCfg, TradingBudgetCfg
from core.models import Family, InstrumentClass, Suggestion

SHORT_PREMIUM_FAMILIES = frozenset(
    {Family.PUT_CREDIT_SPREAD, Family.CALL_CREDIT_SPREAD, Family.IRON_CONDOR}
)
TREND_FAMILIES = frozenset(
    {Family.TREND_LEAPS, Family.TREND_DIAGONAL, Family.TREND_DEBIT_SPREAD}
)


def _sleeve_for(family: Family) -> str:
    if family in SHORT_PREMIUM_FAMILIES:
        return "short_premium"
    if family in TREND_FAMILIES:
        return "trend"
    if family is Family.WHEEL_CSP:
        return "wheel_csp"
    if family is Family.WHEEL_CC:
        return "core"
    if family is Family.COLLAR:
        return "collar"
    if family is Family.PMCC:
        return "core"
    return "other"


@dataclass
class BookItem:
    symbol: str
    sector: str
    family: Family
    instrument_class: InstrumentClass = InstrumentClass.US_EQUITY_OPT
    max_loss: float = 0.0
    is_etf: bool = False
    cash_reserved: float = 0.0  # CSP
    notional: float = 0.0  # assignment / core notional
    sleeve: str = "other"

    @classmethod
    def from_suggestion(
        cls,
        suggestion: Suggestion,
        *,
        sector: str,
        is_etf: bool,
        notional: float = 0.0,
    ) -> "BookItem":
        cash = float(suggestion.management.get("cash_reserved", 0.0))
        return cls(
            symbol=suggestion.symbol,
            sector=sector,
            family=suggestion.family,
            instrument_class=suggestion.instrument_class,
            max_loss=float(suggestion.max_loss or 0.0),
            is_etf=is_etf,
            cash_reserved=cash,
            notional=notional or cash,
            sleeve=_sleeve_for(suggestion.family),
        )


@dataclass
class BudgetCheck:
    ok: bool = True
    breaches: list[str] = field(default_factory=list)

    def add(self, reason: Optional[str]) -> None:
        if reason:
            self.breaches.append(reason)
            self.ok = False


def _pct(pct: float, nlv: float) -> float:
    return (pct / 100.0) * nlv


def _names_in_sector(items: list[BookItem], sector: str) -> set[str]:
    return {i.symbol for i in items if i.sector == sector}


def check_trading_budget(
    candidate: BookItem,
    book: list[BookItem],
    cfg: TradingBudgetCfg,
    nlv: float,
    *,
    correlation_fn: Optional[Callable[[str, str], float]] = None,
) -> BudgetCheck:
    """Check a trading-pool candidate against all trading buckets."""

    check = BudgetCheck()
    combined = book + [candidate]

    # per-position defined-risk
    cap = _pct(cfg.max_loss_per_position_pct, nlv)
    if candidate.max_loss > cap:
        check.add(f"max-loss ${candidate.max_loss:.0f} > per-position cap ${cap:.0f}")

    # aggregate short-premium risk
    if candidate.sleeve == "short_premium":
        agg = sum(i.max_loss for i in combined if i.sleeve == "short_premium")
        sp_cap = _pct(cfg.aggregate_short_premium_pct, nlv)
        if agg > sp_cap:
            check.add(f"aggregate short-premium ${agg:.0f} > cap ${sp_cap:.0f}")

    # trend sleeve aggregate
    if candidate.sleeve == "trend":
        agg = sum(i.max_loss for i in combined if i.sleeve == "trend")
        tr_cap = _pct(cfg.trend_sleeve_cap_pct, nlv)
        if agg > tr_cap:
            check.add(f"aggregate trend sleeve ${agg:.0f} > cap ${tr_cap:.0f}")

    # position count
    if len(combined) > cfg.max_positions:
        check.add(f"position count {len(combined)} > max {cfg.max_positions}")

    # sector concentration
    names = _names_in_sector(combined, candidate.sector)
    if len(names) > cfg.max_names_per_sector:
        check.add(
            f"{len(names)} names in sector {candidate.sector} > max {cfg.max_names_per_sector}"
        )

    # correlation cap
    if correlation_fn is not None:
        for item in book:
            if item.symbol == candidate.symbol:
                continue
            corr = correlation_fn(candidate.symbol, item.symbol)
            if corr > cfg.correlation_cap:
                check.add(
                    f"correlation {corr:.2f} with {item.symbol} > cap {cfg.correlation_cap}"
                )
                break
    return check


def check_smsf_budget(
    candidate: BookItem,
    book: list[BookItem],
    cfg: SMSFBudgetCfg,
    nlv: float,
) -> BudgetCheck:
    """Check an SMSF candidate against the SMSF buckets."""

    check = BudgetCheck()
    combined = book + [candidate]

    # CSP cash-reserve cap
    if candidate.family is Family.WHEEL_CSP:
        reserved = sum(i.cash_reserved for i in combined if i.family is Family.WHEEL_CSP)
        cap = _pct(cfg.csp_cash_reserve_cap_pct, nlv)
        if reserved > cap:
            check.add(f"CSP cash reserved ${reserved:.0f} > cap ${cap:.0f}")

    # per-name assignment notional (single 12% / ETF 25%)
    if candidate.notional > 0:
        per_name = sum(i.notional for i in combined if i.symbol == candidate.symbol)
        pct = cfg.assignment_notional_etf_pct if candidate.is_etf else cfg.assignment_notional_single_pct
        cap = _pct(pct, nlv)
        if per_name > cap:
            kind = "ETF" if candidate.is_etf else "single"
            check.add(f"{candidate.symbol} assignment notional ${per_name:.0f} > {kind} cap ${cap:.0f}")

    # collar hedge allowance
    if candidate.family is Family.COLLAR:
        spent = sum(i.max_loss for i in combined if i.family is Family.COLLAR)
        cap = _pct(cfg.collar_hedge_allowance_pct, nlv)
        if spent > cap:
            check.add(f"collar hedge spend ${spent:.0f} > allowance ${cap:.0f}")

    # sector concentration
    names = _names_in_sector(combined, candidate.sector)
    if len(names) > cfg.max_names_per_sector:
        check.add(
            f"{len(names)} names in sector {candidate.sector} > max {cfg.max_names_per_sector}"
        )
    return check
