"""Governor alerts — book-level transitions the user must act on.

Emitted each cycle from the governor's state (vs the previous cycle):
  * drawdown tier crossed       — WARN entering WARN/DELEVER, CRITICAL at DEFENSIVE
  * de-lever triggered          — applied leverage cut vs last cycle
  * vol-target cut              — exposure scalar fell (vol spike)
  * hedge coverage below floor  — severe-tail hedge no longer covers the core
  * severe-tail budget breached — modeled -20% loss exceeds the DD budget

These are advisory at leverage: acting on CRITICAL is mandatory, not optional.
"""

from __future__ import annotations

from typing import Optional

from alerts.monitor import Alert
from alerts.triggers import Severity, SuggestedAction, TriggerKind
from governor.drawdown_governor import DrawdownState, DrawdownTier

_TIER_SEVERITY = {
    DrawdownTier.FULL: Severity.INFO,
    DrawdownTier.WARN: Severity.WARN,
    DrawdownTier.DELEVER: Severity.WARN,
    DrawdownTier.DEFENSIVE: Severity.CRITICAL,
}
_TIER_ORDER = {DrawdownTier.FULL: 0, DrawdownTier.WARN: 1,
               DrawdownTier.DELEVER: 2, DrawdownTier.DEFENSIVE: 3}


def _portfolio_alert(kind: TriggerKind, severity: Severity, message: str,
                     action: SuggestedAction, **payload) -> Alert:
    return Alert(symbol="PORTFOLIO", account_id="*", kind=kind, severity=severity,
                 message=message, suggested_action=action,
                 payload={"scope": "book", **payload})


def governor_alerts(
    state: DrawdownState,
    *,
    prev_state: Optional[DrawdownState] = None,
    applied_leverage: Optional[float] = None,
    prev_applied_leverage: Optional[float] = None,
    exposure_scalar: Optional[float] = None,
    prev_exposure_scalar: Optional[float] = None,
    hedge_coverage: Optional[float] = None,
    hedge_coverage_floor: float = 0.5,
    severe_within_budget: Optional[bool] = None,
) -> list[Alert]:
    """Build the governor alert list for this cycle. Order: CRITICAL first."""

    alerts: list[Alert] = []

    # Drawdown tier crossed (only when it worsens vs the previous cycle).
    prev_tier = prev_state.tier if prev_state is not None else DrawdownTier.FULL
    if _TIER_ORDER[state.tier] > _TIER_ORDER[prev_tier]:
        sev = _TIER_SEVERITY[state.tier]
        alerts.append(_portfolio_alert(
            TriggerKind.DRAWDOWN_TIER, sev,
            f"Drawdown tier crossed -> {state.tier.value} (dd {state.drawdown:.1%})",
            SuggestedAction.HEDGE if sev is Severity.CRITICAL else SuggestedAction.DEFEND,
            tier=state.tier.value, drawdown=round(state.drawdown, 4)))

    # De-lever triggered.
    if (applied_leverage is not None and prev_applied_leverage is not None
            and applied_leverage < prev_applied_leverage - 1e-9):
        alerts.append(_portfolio_alert(
            TriggerKind.DELEVER_TRIGGERED, Severity.WARN,
            f"De-lever: applied leverage {prev_applied_leverage:.2f} -> {applied_leverage:.2f}",
            SuggestedAction.CLOSE,
            applied_leverage=round(applied_leverage, 4)))

    # Vol-target cut (exposure scalar fell).
    if (exposure_scalar is not None and prev_exposure_scalar is not None
            and exposure_scalar < prev_exposure_scalar - 1e-9):
        alerts.append(_portfolio_alert(
            TriggerKind.VOL_TARGET_CUT, Severity.WARN,
            f"Vol-target cut exposure {prev_exposure_scalar:.2f} -> {exposure_scalar:.2f}",
            SuggestedAction.CLOSE,
            exposure_scalar=round(exposure_scalar, 4)))

    # Hedge coverage below floor.
    if hedge_coverage is not None and hedge_coverage < hedge_coverage_floor:
        alerts.append(_portfolio_alert(
            TriggerKind.HEDGE_COVERAGE_LOW, Severity.WARN,
            f"Hedge coverage {hedge_coverage:.0%} below floor {hedge_coverage_floor:.0%}",
            SuggestedAction.HEDGE,
            hedge_coverage=round(hedge_coverage, 4)))

    # Severe-tail budget breached.
    if severe_within_budget is False:
        alerts.append(_portfolio_alert(
            TriggerKind.SEVERE_TAIL_BREACH, Severity.CRITICAL,
            "Severe-tail (-20%) modeled loss exceeds the 20% DD budget — cut leverage",
            SuggestedAction.HEDGE))

    from alerts.triggers import SEVERITY_ORDER
    alerts.sort(key=lambda a: SEVERITY_ORDER[a.severity])
    return alerts
