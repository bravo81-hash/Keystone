"""Vol-targeting — the global exposure scalar.

scale = portfolio_vol_target_annual / sigma_now, capped at the leverage cap and
floored at a minimum. Vol doubles -> exposure halves; calm markets earn more
size, vol spikes cut it. The scalar multiplies the whole book; the leverage
allocator and drawdown governor gate it further.
"""

from __future__ import annotations

from config.schema import LeverageCapCfg


def exposure_scalar(
    sigma_now: float,
    target_vol: float,
    *,
    leverage: LeverageCapCfg | None = None,
    max_scalar: float | None = None,
    min_scalar: float | None = None,
) -> float:
    """Global exposure scalar = target_vol / sigma_now, clamped to [min, max].

    When ``sigma_now`` is unknown/zero, returns the max scalar (no penalty); the
    bounds come from ``LeverageCapCfg`` unless overridden.
    """

    lev = leverage or LeverageCapCfg()
    hi = lev.max_exposure_scalar if max_scalar is None else max_scalar
    lo = lev.min_exposure_scalar if min_scalar is None else min_scalar
    if sigma_now <= 0:
        return hi
    raw = target_vol / sigma_now
    return max(lo, min(hi, raw))
