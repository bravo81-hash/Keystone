"""Target-weight rebalance hook for the SMSF investing core.

Compares current core holdings to target weights and surfaces actions at the
slow (monthly/quarterly) checkpoint. Underweight names route to wheel_csp
(accumulate via cash-secured puts rather than market buys). Overweight names are
flagged to trim. Investing pool sits OUTSIDE any trading DTE scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from config.schema import TargetHoldingCfg


class RebalanceActionType(str, Enum):
    ACQUIRE_CSP = "ACQUIRE_CSP"  # underweight -> accumulate via cash-secured put
    TRIM = "TRIM"  # overweight -> trim
    HOLD = "HOLD"  # within tolerance


@dataclass
class RebalanceAction:
    ticker: str
    current_weight: float
    target_weight: float
    gap: float  # target - current
    action: RebalanceActionType
    is_etf: bool = False
    acquire_below_price: float | None = None


def detect_rebalance(
    current_values: dict[str, float],
    targets: list[TargetHoldingCfg],
    nlv: float,
    *,
    tolerance: float = 0.02,
) -> list[RebalanceAction]:
    """Compare current holding values to target weights; classify each."""

    actions: list[RebalanceAction] = []
    for tgt in targets:
        current_weight = (current_values.get(tgt.ticker, 0.0) / nlv) if nlv > 0 else 0.0
        gap = tgt.target_weight - current_weight
        if gap > tolerance:
            action = RebalanceActionType.ACQUIRE_CSP
        elif gap < -tolerance:
            action = RebalanceActionType.TRIM
        else:
            action = RebalanceActionType.HOLD
        actions.append(
            RebalanceAction(
                ticker=tgt.ticker,
                current_weight=current_weight,
                target_weight=tgt.target_weight,
                gap=gap,
                action=action,
                is_etf=tgt.is_etf,
                acquire_below_price=tgt.acquire_below_price,
            )
        )
    return actions


def route_to_csp(actions: list[RebalanceAction]) -> list[str]:
    """Tickers whose underweight should be acquired via the wheel (CSP)."""

    return [a.ticker for a in actions if a.action is RebalanceActionType.ACQUIRE_CSP]
