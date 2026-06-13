"""Fit filter — a Suggestion breaching any budget bucket is filtered pre-card.

Routes the candidate to the right pool's budget check and, on a breach, logs the
reason to the store (blocked_structures, the same learn-table the ranker consults
in Stage 9). A passing candidate returns ``ok=True`` with no breaches.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from config.schema import RiskConfig
from core.models import Suggestion
from portfolio.budgets import BookItem, check_smsf_budget, check_trading_budget


@dataclass
class FitResult:
    ok: bool
    pool: str
    breaches: list[str] = field(default_factory=list)


def log_fit_breach(db: Any, suggestion: Suggestion, breaches: list[str]) -> None:
    """Record a budget breach to blocked_structures (idempotent on signature)."""

    conn = db.connect()
    conn.execute(
        "INSERT OR IGNORE INTO blocked_structures "
        "(signature, account_id, symbol, family, reason) VALUES (?, ?, ?, ?, ?)",
        (
            suggestion.signature(),
            suggestion.account_id,
            suggestion.symbol,
            suggestion.family.value,
            "budget: " + "; ".join(breaches),
        ),
    )
    conn.commit()


def fit(
    suggestion: Suggestion,
    book: list[BookItem],
    cfg: RiskConfig,
    nlv: float,
    *,
    pool: str,
    sector: str = "UNKNOWN",
    is_etf: bool = False,
    notional: float = 0.0,
    correlation_fn: Optional[Callable[[str, str], float]] = None,
    db: Any = None,
) -> FitResult:
    """Check a Suggestion against its pool's budgets; log + return breaches."""

    item = BookItem.from_suggestion(suggestion, sector=sector, is_etf=is_etf, notional=notional)
    if pool == "trading":
        check = check_trading_budget(item, book, cfg.trading, nlv, correlation_fn=correlation_fn)
    else:
        check = check_smsf_budget(item, book, cfg.smsf, nlv)

    if not check.ok and db is not None:
        log_fit_breach(db, suggestion, check.breaches)
    return FitResult(ok=check.ok, pool=pool, breaches=check.breaches)
