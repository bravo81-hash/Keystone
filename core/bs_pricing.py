"""Black-Scholes(-Merton) price + greeks with a continuous dividend yield.

Used for risk graphs and guard checks (e.g. extrinsic-vs-dividend assignment
risk) — NOT a binomial/American model. Pure standard-library ``math`` (no numpy/
scipy): the normal CDF is built from ``math.erf``.

Conventions (documented because tests and callers depend on them):
  * ``T`` is in years; ``r`` and ``q`` are continuous annual rates; ``sigma`` is
    annualized vol as a decimal (0.20 == 20%).
  * ``vega`` is per 1.00 change in vol (i.e. +100 vol points). Divide by 100 for
    "per 1 vol point".
  * ``theta`` is per year. Divide by 365 for per-calendar-day.
  * ``rho`` is per 1.00 change in the rate. Divide by 100 for "per 1%".
"""

from __future__ import annotations

import math
from typing import Union

from core.models import Right

_SQRT_2 = math.sqrt(2.0)
_SQRT_2PI = math.sqrt(2.0 * math.pi)

RightLike = Union[Right, str]


def norm_cdf(x: float) -> float:
    """Standard normal CDF via the error function."""

    return 0.5 * (1.0 + math.erf(x / _SQRT_2))


def norm_pdf(x: float) -> float:
    """Standard normal PDF."""

    return math.exp(-0.5 * x * x) / _SQRT_2PI


def _is_call(right: RightLike) -> bool:
    if isinstance(right, Right):
        return right is Right.CALL
    return str(right).strip().upper().startswith("C")


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float, q: float) -> tuple[float, float]:
    vol = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / vol
    d2 = d1 - vol
    return d1, d2


def bs_price(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    right: RightLike,
    q: float = 0.0,
) -> float:
    """Black-Scholes-Merton option price."""

    call = _is_call(right)
    if T <= 0.0 or sigma <= 0.0:
        # Degenerate: discounted intrinsic on the dividend-adjusted forward.
        fwd = S * math.exp((r - q) * T) if T > 0.0 else S
        disc = math.exp(-r * T) if T > 0.0 else 1.0
        intrinsic = max(fwd - K, 0.0) if call else max(K - fwd, 0.0)
        return disc * intrinsic

    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    df_q = math.exp(-q * T)
    df_r = math.exp(-r * T)
    if call:
        return S * df_q * norm_cdf(d1) - K * df_r * norm_cdf(d2)
    return K * df_r * norm_cdf(-d2) - S * df_q * norm_cdf(-d1)


def bs_greeks(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    right: RightLike,
    q: float = 0.0,
) -> dict[str, float]:
    """Price + delta, gamma, vega, theta, rho. See module docstring for units."""

    call = _is_call(right)
    price = bs_price(S, K, T, r, sigma, right, q)

    if T <= 0.0 or sigma <= 0.0:
        if call:
            delta = 1.0 if S > K else (0.5 if S == K else 0.0)
        else:
            delta = -1.0 if S < K else (-0.5 if S == K else 0.0)
        return {
            "price": price,
            "delta": delta,
            "gamma": 0.0,
            "vega": 0.0,
            "theta": 0.0,
            "rho": 0.0,
        }

    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    sqrt_t = math.sqrt(T)
    df_q = math.exp(-q * T)
    df_r = math.exp(-r * T)
    pdf_d1 = norm_pdf(d1)

    gamma = df_q * pdf_d1 / (S * sigma * sqrt_t)
    vega = S * df_q * pdf_d1 * sqrt_t
    common_theta = -(S * df_q * pdf_d1 * sigma) / (2.0 * sqrt_t)

    if call:
        delta = df_q * norm_cdf(d1)
        theta = common_theta + q * S * df_q * norm_cdf(d1) - r * K * df_r * norm_cdf(d2)
        rho = K * T * df_r * norm_cdf(d2)
    else:
        delta = -df_q * norm_cdf(-d1)
        theta = common_theta - q * S * df_q * norm_cdf(-d1) + r * K * df_r * norm_cdf(-d2)
        rho = -K * T * df_r * norm_cdf(-d2)

    return {
        "price": price,
        "delta": delta,
        "gamma": gamma,
        "vega": vega,
        "theta": theta,
        "rho": rho,
    }


def black_scholes(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    right: RightLike,
    q: float = 0.0,
) -> dict[str, float]:
    """Alias for :func:`bs_greeks` (price + greeks in one dict)."""

    return bs_greeks(S, K, T, r, sigma, right, q)
