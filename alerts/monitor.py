"""EOD position monitor (the fast clock). Monitors OPEN positions only.

Per position: runs the triggers (mark/P&L, short-leg moneyness, DTE, ATR
distance, assignment + pin risk, earnings exposure). Portfolio-level: a
HARD_SKIP regime flip raises a book-wide CRITICAL, and budget utilization /
stress are summarized. Each alert carries a suggested action and is wired to
execution.stage_to_tws + the OptionStrat deep link.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from alerts.alert_store import save_alert
from alerts.triggers import (
    PositionSnapshot,
    SuggestedAction,
    Trigger,
    TriggerKind,
    evaluate,
    regime_hard_skip_trigger,
)


@dataclass
class Alert:
    symbol: str
    account_id: str
    kind: TriggerKind
    severity: Any  # Severity
    message: str
    suggested_action: SuggestedAction
    position_id: Optional[int] = None
    payload: dict = field(default_factory=dict)

    @classmethod
    def from_trigger(cls, snapshot: PositionSnapshot, trigger: Trigger) -> "Alert":
        return cls(
            symbol=snapshot.symbol,
            account_id=snapshot.account_id,
            kind=trigger.kind,
            severity=trigger.severity,
            message=trigger.message,
            suggested_action=trigger.suggested_action,
            payload={"symbol": snapshot.symbol, "account_id": snapshot.account_id,
                     "family": snapshot.family, "dte": snapshot.dte},
        )


def run_eod_monitor(
    snapshots: list[PositionSnapshot],
    *,
    market_hard_skip: bool = False,
    db: Any = None,
) -> list[Alert]:
    """Evaluate all open positions; emit alerts (CRITICAL-first)."""

    alerts: list[Alert] = []
    for snap in snapshots:
        for trigger in evaluate(snap):
            alerts.append(Alert.from_trigger(snap, trigger))

    if market_hard_skip:
        t = regime_hard_skip_trigger()
        alerts.append(
            Alert(symbol="PORTFOLIO", account_id="*", kind=t.kind, severity=t.severity,
                  message=t.message, suggested_action=t.suggested_action, payload={"scope": "book"})
        )

    from alerts.triggers import SEVERITY_ORDER

    alerts.sort(key=lambda a: SEVERITY_ORDER[a.severity])
    if db is not None:
        for alert in alerts:
            save_alert(db, alert)
    return alerts


def stage_suggested_action(ib_client: Any, suggestion: Any, *, db: Any = None) -> Any:
    """Wire an alert's suggested action to execution.stage_to_tws (transmit=False)."""

    from execution.stage import stage_to_tws

    return stage_to_tws(ib_client, suggestion, db=db)


def portfolio_health(
    book: list,
    cfg: Any,
    nlv: float,
    *,
    stress_positions: Optional[list] = None,
) -> dict:
    """Light portfolio-level summary: budget utilization + optional stress refresh."""

    from portfolio.budgets import SHORT_PREMIUM_FAMILIES, TREND_FAMILIES

    short_prem = sum(i.max_loss for i in book if i.family in SHORT_PREMIUM_FAMILIES)
    trend = sum(i.max_loss for i in book if i.family in TREND_FAMILIES)
    sectors: dict[str, int] = {}
    for item in book:
        sectors[item.sector] = sectors.get(item.sector, 0) + 1

    summary = {
        "positions": len(book),
        "short_premium_risk": short_prem,
        "short_premium_util": (short_prem / (cfg.trading.aggregate_short_premium_pct / 100 * nlv))
        if nlv > 0 else 0.0,
        "trend_risk": trend,
        "sector_counts": sectors,
    }
    if stress_positions is not None:
        from portfolio.stress import stress_book

        summary["stress"] = stress_book(stress_positions, cfg.stress)
    return summary
