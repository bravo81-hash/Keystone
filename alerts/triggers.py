"""Alert triggers + severity for OPEN positions.

A :class:`PositionSnapshot` carries the marks/greeks the EOD monitor computes;
each ``check_*`` fires a :class:`Trigger` (kind + severity + suggested action) or
returns None. Severity doctrine:

  INFO     profit target hit (50% max profit) -> opportunistic close
  WARN     approaching stop; must-touch-by DTE; short strike within X*ATR; roll due;
           earnings exposure
  CRITICAL stop breached; short strike breached; assignment imminent; pin risk;
           market regime flipped HARD_SKIP
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from core.models import Right


class Severity(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    CRITICAL = "CRITICAL"


SEVERITY_ORDER = {Severity.CRITICAL: 0, Severity.WARN: 1, Severity.INFO: 2}


class SuggestedAction(str, Enum):
    CLOSE = "close"
    ROLL = "roll"
    DEFEND = "defend"
    HEDGE = "hedge"
    NONE = "none"


class TriggerKind(str, Enum):
    PROFIT_TARGET = "profit_target"
    APPROACHING_STOP = "approaching_stop"
    STOP_BREACHED = "stop_breached"
    SHORT_STRIKE_NEAR = "short_strike_near"
    SHORT_STRIKE_BREACHED = "short_strike_breached"
    MUST_TOUCH_BY = "must_touch_by"
    ASSIGNMENT_IMMINENT = "assignment_imminent"
    PIN_RISK = "pin_risk"
    REGIME_HARD_SKIP = "regime_hard_skip"
    EARNINGS_EXPOSURE = "earnings_exposure"


@dataclass
class Trigger:
    kind: TriggerKind
    severity: Severity
    message: str
    suggested_action: SuggestedAction


@dataclass
class PositionSnapshot:
    symbol: str
    account_id: str
    family: str = ""
    is_short_premium: bool = True
    # marks (per-spread, in price terms)
    entry_credit: float = 0.0  # credit received at entry
    current_mark: float = 0.0  # cost to close now (debit)
    # short leg geometry
    short_right: Optional[Right] = None
    short_strike: Optional[float] = None
    underlying_price: float = 0.0
    atr20: float = 0.0
    dte: int = 999
    is_calendar: bool = False  # short calendar leg -> must-touch 7 (else 21)
    # assignment risk
    dividend: float = 0.0  # next ex-div before expiry (0 if none)
    short_call_itm: bool = False
    short_call_extrinsic: Optional[float] = None
    short_put_deep_itm: bool = False
    short_put_extrinsic: Optional[float] = None
    earnings_before_expiry: bool = False
    # thresholds
    stop_mult: float = 2.0
    profit_target_pct: float = 0.5
    near_atr_mult: float = 1.0


# --------------------------------------------------------------------------- #
# Individual checks
# --------------------------------------------------------------------------- #
def check_profit_target(s: PositionSnapshot) -> Optional[Trigger]:
    if not s.is_short_premium or s.entry_credit <= 0:
        return None
    captured = (s.entry_credit - s.current_mark) / s.entry_credit
    if captured >= s.profit_target_pct:
        return Trigger(
            TriggerKind.PROFIT_TARGET, Severity.INFO,
            f"profit target hit ({captured:.0%} of max)", SuggestedAction.CLOSE,
        )
    return None


def check_stop(s: PositionSnapshot) -> Optional[Trigger]:
    if not s.is_short_premium or s.entry_credit <= 0:
        return None
    stop_level = s.stop_mult * s.entry_credit
    if s.current_mark >= stop_level:
        return Trigger(
            TriggerKind.STOP_BREACHED, Severity.CRITICAL,
            f"stop breached (mark {s.current_mark:.2f} >= {stop_level:.2f})", SuggestedAction.CLOSE,
        )
    if s.current_mark >= 0.8 * stop_level:
        return Trigger(
            TriggerKind.APPROACHING_STOP, Severity.WARN,
            f"approaching stop (mark {s.current_mark:.2f})", SuggestedAction.DEFEND,
        )
    return None


def check_short_strike(s: PositionSnapshot) -> Optional[Trigger]:
    if s.short_strike is None or s.short_right is None or s.atr20 <= 0 or s.underlying_price <= 0:
        return None
    if s.short_right is Right.PUT:
        cushion = s.underlying_price - s.short_strike
    else:
        cushion = s.short_strike - s.underlying_price
    if cushion <= 0:
        return Trigger(
            TriggerKind.SHORT_STRIKE_BREACHED, Severity.CRITICAL,
            f"short strike {s.short_strike} breached", SuggestedAction.DEFEND,
        )
    if cushion <= s.near_atr_mult * s.atr20:
        return Trigger(
            TriggerKind.SHORT_STRIKE_NEAR, Severity.WARN,
            f"short strike within {cushion / s.atr20:.1f} ATR", SuggestedAction.DEFEND,
        )
    return None


def check_must_touch_by(s: PositionSnapshot) -> Optional[Trigger]:
    must_by = 7 if s.is_calendar else 21
    if 0 < s.dte <= must_by:
        return Trigger(
            TriggerKind.MUST_TOUCH_BY, Severity.WARN,
            f"must-touch-by {must_by} DTE reached (DTE {s.dte})", SuggestedAction.ROLL,
        )
    return None


def check_assignment_risk(s: PositionSnapshot) -> Optional[Trigger]:
    # short call ITM with ex-div before expiry and extrinsic < dividend
    if (
        s.dividend > 0
        and s.short_call_itm
        and s.short_call_extrinsic is not None
        and s.short_call_extrinsic < s.dividend
    ):
        return Trigger(
            TriggerKind.ASSIGNMENT_IMMINENT, Severity.CRITICAL,
            f"ex-div assignment risk: extrinsic {s.short_call_extrinsic:.2f} < div {s.dividend:.2f}",
            SuggestedAction.ROLL,
        )
    # short put deep ITM, extrinsic < $0.05
    if (
        s.short_put_deep_itm
        and s.short_put_extrinsic is not None
        and s.short_put_extrinsic < 0.05
    ):
        return Trigger(
            TriggerKind.ASSIGNMENT_IMMINENT, Severity.CRITICAL,
            f"deep-ITM short put assignment risk (extrinsic {s.short_put_extrinsic:.2f})",
            SuggestedAction.ROLL,
        )
    return None


def check_pin_risk(s: PositionSnapshot) -> Optional[Trigger]:
    if s.short_strike is None or s.atr20 <= 0 or s.underlying_price <= 0:
        return None
    if s.dte <= 2 and abs(s.underlying_price - s.short_strike) <= 0.5 * s.atr20:
        return Trigger(
            TriggerKind.PIN_RISK, Severity.CRITICAL,
            f"pin risk at {s.dte} DTE (within 0.5 ATR of {s.short_strike})", SuggestedAction.CLOSE,
        )
    return None


def check_earnings_exposure(s: PositionSnapshot) -> Optional[Trigger]:
    if s.earnings_before_expiry:
        return Trigger(
            TriggerKind.EARNINGS_EXPOSURE, Severity.WARN,
            "confirmed earnings before expiry — exposed", SuggestedAction.ROLL,
        )
    return None


_CHECKS = (
    check_profit_target,
    check_stop,
    check_short_strike,
    check_must_touch_by,
    check_assignment_risk,
    check_pin_risk,
    check_earnings_exposure,
)


def evaluate(snapshot: PositionSnapshot) -> list[Trigger]:
    """All per-position triggers that fire for this snapshot."""

    return [t for check in _CHECKS if (t := check(snapshot)) is not None]


def regime_hard_skip_trigger() -> Trigger:
    """Portfolio-level CRITICAL when the market regime flips to HARD_SKIP."""

    return Trigger(
        TriggerKind.REGIME_HARD_SKIP, Severity.CRITICAL,
        "market regime flipped to HARD_SKIP — no new entries; defend the book",
        SuggestedAction.DEFEND,
    )
