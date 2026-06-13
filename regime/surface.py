"""Per-stock vol surface: ATM IV at constant 9d/30d/90d tenors.

From the cached Friday chain we have ATM IV at the *listed* expiries (irregular
tenors). We interpolate to fixed 9d/30d/90d tenors in **total-variance** space —
w(T) = iv(T)^2 * T is interpolated linearly in T, then iv = sqrt(w/T) — which is
the arbitrage-sane way to interpolate vol across tenor. Outside the listed range
we hold IV flat (variance grows linearly at the endpoint vol).

Emits term-structure slopes and an inverted-front flag the per-stock regime and
strategy selection consume.

Pacing: this reuses the existing Fridays-only cached chain — no new requests.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# Constant tenors (calendar days) we interpolate to.
TENOR_9D = 9
TENOR_30D = 30
TENOR_90D = 90
_DAYS_PER_YEAR = 365.0


class Surface(BaseModel):
    ticker: str
    iv_9d: float
    iv_30d: float
    iv_90d: float
    slope_9_30: float  # iv_30d - iv_9d  (positive = upward/contango)
    slope_30_90: float  # iv_90d - iv_30d
    inverted_front: bool  # front (9d) IV above 30d => backwardated front
    points: list[tuple[int, float]] = Field(default_factory=list)  # (days, atm_iv) inputs


def interp_atm_iv(points: list[tuple[float, float]], target_days: float) -> float:
    """Interpolate ATM IV to ``target_days`` via linear total-variance interpolation.

    ``points`` = [(days, atm_iv), ...]. Flat-IV extrapolation beyond the ends.
    """

    if not points:
        raise ValueError("no surface points to interpolate")
    pts = sorted((float(d), float(iv)) for d, iv in points)
    if len(pts) == 1:
        return pts[0][1]

    t_star = target_days / _DAYS_PER_YEAR
    if target_days <= pts[0][0]:
        return pts[0][1]  # flat extrapolation at the front
    if target_days >= pts[-1][0]:
        return pts[-1][1]  # flat extrapolation at the back

    for (d_a, iv_a), (d_b, iv_b) in zip(pts, pts[1:]):
        if d_a <= target_days <= d_b:
            t_a, t_b = d_a / _DAYS_PER_YEAR, d_b / _DAYS_PER_YEAR
            w_a, w_b = iv_a * iv_a * t_a, iv_b * iv_b * t_b
            frac = (t_star - t_a) / (t_b - t_a)
            w_star = w_a + (w_b - w_a) * frac
            return (w_star / t_star) ** 0.5
    return pts[-1][1]  # unreachable, defensive


def build_surface(
    ticker: str,
    points: list[tuple[float, float]],
    *,
    flat_tol: float = 0.0,
) -> Surface:
    """Build a :class:`Surface` from listed (days, atm_iv) points."""

    iv_9 = interp_atm_iv(points, TENOR_9D)
    iv_30 = interp_atm_iv(points, TENOR_30D)
    iv_90 = interp_atm_iv(points, TENOR_90D)
    slope_9_30 = iv_30 - iv_9
    slope_30_90 = iv_90 - iv_30
    return Surface(
        ticker=ticker,
        iv_9d=iv_9,
        iv_30d=iv_30,
        iv_90d=iv_90,
        slope_9_30=slope_9_30,
        slope_30_90=slope_30_90,
        inverted_front=slope_9_30 < -flat_tol,
        points=[(int(d), float(iv)) for d, iv in points],
    )
