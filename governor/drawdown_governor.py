"""Drawdown circuit-breaker — high-water-mark tracking + tiered de-lever.

Tiers from the configured thresholds (drawdown measured from the HWM):
  * FULL      (dd < warn)            — full allowed exposure (scale 1.0)
  * WARN      (warn <= dd < delever) — linear de-lever 1.0 -> 0.5
  * DELEVER   (delever <= dd < def)  — hedge-heavy, cut Engines 1-2; 0.5 -> 0.0
  * DEFENSIVE (dd >= defensive)      — close/hedge; NO risk-on until NLV recovers
                                       ``reentry_recovery_margin`` back above the
                                       defensive line (anti-whipsaw lock)

Stateful: feed NLV each cycle via :meth:`DrawdownGovernor.update`. Instantiate
one per pool AND one for the aggregate book.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from config.schema import GovernorThresholdsCfg


class DrawdownTier(str, Enum):
    FULL = "FULL"
    WARN = "WARN"
    DELEVER = "DELEVER"
    DEFENSIVE = "DEFENSIVE"


@dataclass
class DrawdownState:
    hwm: float
    nlv: float
    drawdown: float  # fraction below HWM (>= 0)
    tier: DrawdownTier
    exposure_scale: float  # [0, 1] multiplier the governor permits
    risk_on: bool  # False => only de-risking / hedge actions allowed
    locked: bool  # anti-whipsaw lock engaged (was DEFENSIVE, not yet recovered)


def _linear(x: float, x0: float, x1: float, y0: float, y1: float) -> float:
    if x1 <= x0:
        return y1
    t = max(0.0, min(1.0, (x - x0) / (x1 - x0)))
    return y0 + t * (y1 - y0)


class DrawdownGovernor:
    """Per-scope drawdown governor with anti-whipsaw re-entry."""

    def __init__(self, cfg: GovernorThresholdsCfg | None = None, *, hwm: float = 0.0) -> None:
        self.cfg = cfg or GovernorThresholdsCfg()
        self.hwm = hwm
        self.locked = False

    def _classify(self, dd: float) -> tuple[DrawdownTier, float]:
        c = self.cfg
        if dd < c.dd_warn:
            return DrawdownTier.FULL, 1.0
        if dd < c.dd_delever:
            return DrawdownTier.WARN, _linear(dd, c.dd_warn, c.dd_delever, 1.0, 0.5)
        if dd < c.dd_defensive:
            return DrawdownTier.DELEVER, _linear(dd, c.dd_delever, c.dd_defensive, 0.5, 0.0)
        return DrawdownTier.DEFENSIVE, 0.0

    def update(self, nlv: float) -> DrawdownState:
        """Record a new NLV mark and return the resulting drawdown state."""

        self.hwm = max(self.hwm, nlv)
        dd = 0.0 if self.hwm <= 0 else (self.hwm - nlv) / self.hwm

        # Anti-whipsaw lock: engage at/over the defensive line; release only once
        # NLV has recovered the margin back above it.
        if dd >= self.cfg.dd_defensive:
            self.locked = True
        elif self.locked and dd <= self.cfg.dd_defensive - self.cfg.reentry_recovery_margin:
            self.locked = False

        tier, scale = self._classify(dd)
        if self.locked:
            # Held defensive until the recovery margin is regained.
            tier, scale = DrawdownTier.DEFENSIVE, 0.0
        risk_on = scale > 0.0
        return DrawdownState(self.hwm, nlv, dd, tier, scale, risk_on, self.locked)
