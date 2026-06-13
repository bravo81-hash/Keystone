"""whatIf margin/impact check — runs before anything is staged. transmit=False.

On rejection, writes a blocked_structures row (the ranker's learn-table) so the
exact structure is skipped next time. Every check is recorded to whatif_results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.models import Suggestion
from execution.n_leg_combo import StagedOrder


@dataclass
class WhatIfResult:
    accepted: bool
    init_margin: float = 0.0
    maint_margin: float = 0.0
    equity_with_loan: float = 0.0
    reason: str = ""
    raw: dict = field(default_factory=dict)


def _record(db: Any, suggestion: Suggestion, result: WhatIfResult) -> None:
    conn = db.connect()
    conn.execute(
        "INSERT INTO whatif_results "
        "(account_id, symbol, family, signature, init_margin, maint_margin, "
        "equity_with_loan, accepted) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            suggestion.account_id,
            suggestion.symbol,
            suggestion.family.value,
            suggestion.signature(),
            result.init_margin,
            result.maint_margin,
            result.equity_with_loan,
            1 if result.accepted else 0,
        ),
    )
    if not result.accepted:
        conn.execute(
            "INSERT OR IGNORE INTO blocked_structures "
            "(signature, account_id, symbol, family, reason) VALUES (?, ?, ?, ?, ?)",
            (
                suggestion.signature(),
                suggestion.account_id,
                suggestion.symbol,
                suggestion.family.value,
                "whatIf rejected: " + (result.reason or "margin/impact"),
            ),
        )
    conn.commit()


def run_whatif(
    ib_client: Any,
    staged_order: StagedOrder,
    suggestion: Suggestion,
    *,
    db: Any = None,
) -> WhatIfResult:
    """Run the whatIf check for a staged order (never transmits)."""

    assert staged_order.transmit is False, "whatIf must never transmit"
    raw = ib_client.ib.whatIfOrder(staged_order.contract, staged_order.order_stub())
    result = WhatIfResult(
        accepted=bool(raw.get("accepted", True)),
        init_margin=float(raw.get("init_margin", 0.0)),
        maint_margin=float(raw.get("maint_margin", 0.0)),
        equity_with_loan=float(raw.get("equity_with_loan", 0.0)),
        reason=str(raw.get("reason", "")),
        raw=dict(raw),
    )
    if db is not None:
        _record(db, suggestion, result)
    return result
