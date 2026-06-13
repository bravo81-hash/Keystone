"""Black-Scholes price + greeks vs a known textbook fixture.

Fixture: S=K=100, r=5%, T=1y, sigma=20%, q=0. Canonical published values:
  call = 10.4506, put = 5.5735, delta_call = 0.6368.
"""

from __future__ import annotations

import math

import pytest

from core.bs_pricing import bs_greeks, bs_price, norm_cdf, norm_pdf
from core.models import Right

S, K, T, R, SIGMA = 100.0, 100.0, 1.0, 0.05, 0.20


def test_norm_helpers():
    assert norm_cdf(0.0) == pytest.approx(0.5)
    assert norm_cdf(-1.0) + norm_cdf(1.0) == pytest.approx(1.0)
    assert norm_pdf(0.0) == pytest.approx(1.0 / math.sqrt(2 * math.pi))


def test_known_call_and_put_prices():
    call = bs_price(S, K, T, R, SIGMA, Right.CALL)
    put = bs_price(S, K, T, R, SIGMA, Right.PUT)
    assert call == pytest.approx(10.4506, abs=1e-3)
    assert put == pytest.approx(5.5735, abs=1e-3)


def test_put_call_parity():
    call = bs_price(S, K, T, R, SIGMA, Right.CALL)
    put = bs_price(S, K, T, R, SIGMA, Right.PUT)
    # C - P = S*e^{-qT} - K*e^{-rT}  (q = 0)
    assert call - put == pytest.approx(S - K * math.exp(-R * T), abs=1e-9)


def test_call_greeks_match_fixture():
    g = bs_greeks(S, K, T, R, SIGMA, Right.CALL)
    assert g["price"] == pytest.approx(10.4506, abs=1e-3)
    assert g["delta"] == pytest.approx(0.6368, abs=1e-4)
    assert g["gamma"] == pytest.approx(0.0187620, abs=1e-6)
    assert g["vega"] == pytest.approx(37.5240, abs=1e-3)  # per 1.00 vol
    assert g["theta"] == pytest.approx(-6.41403, abs=1e-3)  # per year
    assert g["rho"] == pytest.approx(53.2325, abs=1e-3)  # per 1.00 rate


def test_put_greeks():
    g = bs_greeks(S, K, T, R, SIGMA, Right.PUT)
    assert g["delta"] == pytest.approx(-0.3632, abs=1e-4)
    # Gamma and vega are identical for call and put at the same strike.
    gc = bs_greeks(S, K, T, R, SIGMA, Right.CALL)
    assert g["gamma"] == pytest.approx(gc["gamma"], abs=1e-12)
    assert g["vega"] == pytest.approx(gc["vega"], abs=1e-12)


def test_dividend_yield_lowers_call_and_scales_delta():
    base = bs_greeks(S, K, T, R, SIGMA, Right.CALL, q=0.0)
    with_div = bs_greeks(S, K, T, R, SIGMA, Right.CALL, q=0.03)
    assert with_div["price"] < base["price"]
    assert with_div["delta"] < base["delta"]  # discounted by e^{-qT}


def test_right_accepts_string_and_enum():
    assert bs_price(S, K, T, R, SIGMA, "C") == pytest.approx(
        bs_price(S, K, T, R, SIGMA, Right.CALL)
    )
    assert bs_price(S, K, T, R, SIGMA, "put") == pytest.approx(
        bs_price(S, K, T, R, SIGMA, Right.PUT)
    )


def test_expiry_edge_returns_intrinsic():
    assert bs_price(110.0, 100.0, 0.0, R, SIGMA, Right.CALL) == pytest.approx(10.0)
    assert bs_price(90.0, 100.0, 0.0, R, SIGMA, Right.CALL) == pytest.approx(0.0)
    assert bs_price(90.0, 100.0, 0.0, R, SIGMA, Right.PUT) == pytest.approx(10.0)
    g = bs_greeks(110.0, 100.0, 0.0, R, SIGMA, Right.CALL)
    assert g["delta"] == pytest.approx(1.0)
    assert g["gamma"] == 0.0
