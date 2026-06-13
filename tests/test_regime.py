"""Stage 3: surface interpolation, IVR/IVP, RV, VRP, skew, stock regime."""

from __future__ import annotations

import pytest

from regime.skew import build_skew, risk_reversal
from regime.stock_regime import (
    EarningsProximity,
    IVRBucket,
    StockRegimeState,
    TermState,
    VRPSign,
    classify_term,
    stock_regime,
)
from regime.surface import Surface, build_surface, interp_atm_iv
from regime.vol_history import iv_percentile, iv_rank, realized_vol, vrp

# Listed ATM IV points (days, iv): front-rich (inverted) term structure.
_POINTS = [(7, 0.30), (37, 0.25), (100, 0.22)]


# --------------------------------------------------------------------------- #
# Surface — total-variance interpolation vs hand-computed fixture
# --------------------------------------------------------------------------- #
def test_interp_atm_iv_hand_computed():
    assert interp_atm_iv(_POINTS, 9) == pytest.approx(0.28716, abs=1e-3)
    assert interp_atm_iv(_POINTS, 30) == pytest.approx(0.25298, abs=1e-3)
    assert interp_atm_iv(_POINTS, 90) == pytest.approx(0.22207, abs=1e-3)


def test_interp_flat_extrapolation():
    assert interp_atm_iv([(30, 0.25)], 9) == 0.25  # single point
    assert interp_atm_iv(_POINTS, 1) == 0.30  # below front -> flat
    assert interp_atm_iv(_POINTS, 365) == 0.22  # beyond back -> flat


def test_build_surface_slopes_and_inversion():
    s = build_surface("AAPL", _POINTS)
    assert s.iv_30d == pytest.approx(0.25298, abs=1e-3)
    assert s.slope_9_30 < 0  # front IV above 30d
    assert s.inverted_front is True
    assert s.slope_30_90 == pytest.approx(s.iv_90d - s.iv_30d)


def test_classify_term():
    assert classify_term(0.02) is TermState.CONTANGO
    assert classify_term(-0.02) is TermState.INVERTED
    assert classify_term(0.0) is TermState.FLAT


# --------------------------------------------------------------------------- #
# IV history metrics
# --------------------------------------------------------------------------- #
def test_iv_rank():
    series = [10, 20, 30, 40, 50]
    assert iv_rank(series) == pytest.approx(100.0)  # current = last = max
    assert iv_rank(series, current=30) == pytest.approx(50.0)
    assert iv_rank([25, 25, 25]) == 0.0  # flat -> 0


def test_iv_percentile():
    series = [10, 20, 30, 40, 50]
    assert iv_percentile(series, current=30) == pytest.approx(40.0)  # 2 of 5 below
    assert iv_percentile(series) == pytest.approx(80.0)  # last=50, 4 below


def test_realized_vol():
    assert realized_vol([100, 110], window=20) is None  # insufficient
    # window=2: two equal-magnitude opposite log returns.
    assert realized_vol([100, 110, 100], window=2) == pytest.approx(2.1399, abs=1e-3)
    # constant growth -> zero dispersion -> zero realized vol.
    assert realized_vol([100, 110, 121], window=2) == pytest.approx(0.0, abs=1e-9)


def test_vrp_sign_convention():
    assert vrp(0.25, 0.18) == pytest.approx(0.07)  # implied richer -> positive
    assert vrp(0.18, 0.25) == pytest.approx(-0.07)
    assert vrp(0.20, 0.20) == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# Skew (25-delta risk reversal)
# --------------------------------------------------------------------------- #
def test_risk_reversal_and_flags():
    assert risk_reversal(0.30, 0.20) == pytest.approx(10.0)  # vol points
    call = build_skew("X", 0.30, 0.20)
    assert call.extreme_call_skew is True and call.extreme_put_skew is False
    put = build_skew("X", 0.20, 0.35)  # RR -15
    assert put.extreme_put_skew is True and put.extreme_call_skew is False
    normal = build_skew("X", 0.25, 0.27)  # RR -2
    assert not normal.extreme_call_skew and not normal.extreme_put_skew


# --------------------------------------------------------------------------- #
# Stock regime composition
# --------------------------------------------------------------------------- #
def _surface(slope_9_30: float = 0.01, iv30: float = 0.25) -> Surface:
    return Surface(
        ticker="X",
        iv_9d=iv30 - slope_9_30,
        iv_30d=iv30,
        iv_90d=iv30 + 0.01,
        slope_9_30=slope_9_30,
        slope_30_90=0.01,
        inverted_front=slope_9_30 < 0,
    )


def test_regime_premium_rich():
    r = stock_regime("X", _surface(), ivr=80.0, vrp_value=0.05)
    assert r.ivr_bucket is IVRBucket.HIGH
    assert r.vrp_sign is VRPSign.POSITIVE
    assert r.state is StockRegimeState.PREMIUM_RICH
    assert r.sell_premium_ok is True


def test_regime_premium_thin_below_ivr_floor():
    r = stock_regime("X", _surface(), ivr=20.0, vrp_value=0.05)
    assert r.ivr_bucket is IVRBucket.LOW
    assert r.state is StockRegimeState.PREMIUM_THIN
    assert r.sell_premium_ok is False


def test_regime_earnings_blackout_overrides():
    r = stock_regime("X", _surface(), ivr=85.0, vrp_value=0.05, days_to_earnings=1)
    assert r.earnings_proximity is EarningsProximity.IMMINENT
    assert r.state is StockRegimeState.EARNINGS_BLACKOUT
    assert r.sell_premium_ok is False  # even with rich premium


def test_regime_premium_fair():
    r = stock_regime("X", _surface(), ivr=40.0, vrp_value=0.0)
    assert r.ivr_bucket is IVRBucket.MEDIUM
    assert r.state is StockRegimeState.PREMIUM_FAIR


def test_regime_neutral_when_elevated_but_negative_vrp():
    r = stock_regime("X", _surface(), ivr=60.0, vrp_value=-0.05)
    assert r.ivr_bucket is IVRBucket.ELEVATED
    assert r.vrp_sign is VRPSign.NEGATIVE
    assert r.state is StockRegimeState.NEUTRAL
    assert r.sell_premium_ok is True  # elevated IVR, not in earnings window


def test_regime_inverted_term_and_skew_passthrough():
    r = stock_regime(
        "X", _surface(slope_9_30=-0.03), ivr=55.0, vrp_value=0.02, skew=build_skew("X", 0.20, 0.35)
    )
    assert r.term_state is TermState.INVERTED
    assert r.extreme_put_skew is True
