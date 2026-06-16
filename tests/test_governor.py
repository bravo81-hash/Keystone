"""Stage 16: governor — portfolio vol, vol-targeting, drawdown breaker, allocator.

Covers: vol blend + correlation matrix; vol-target scaling (vol doubles ->
exposure halves); drawdown tiers + anti-whipsaw re-entry; allocator respects the
DD budget and lets the hedge free Engine 1/2 leverage.
"""

from __future__ import annotations

import pytest

from config.schema import GovernorThresholdsCfg, LeverageCapCfg
from governor import (
    DrawdownGovernor,
    DrawdownTier,
    allocate,
    blend_vol,
    correlation_matrix,
    exposure_scalar,
    portfolio_vol_estimate,
)


# --------------------------------------------------------------------------- #
# Portfolio vol + correlation
# --------------------------------------------------------------------------- #
def test_blend_vol_weights_and_fallbacks():
    assert blend_vol(0.10, 0.20, 0.5) == pytest.approx(0.15)
    assert blend_vol(None, 0.20) == pytest.approx(0.20)
    assert blend_vol(0.10, None) == pytest.approx(0.10)
    assert blend_vol(None, None) == 0.0


def test_portfolio_vol_estimate_blends_realized_and_implied():
    # Flat-ish returns -> low realized; VIX 20 -> implied 0.20.
    rets = [0.001 * (1 if i % 2 == 0 else -1) for i in range(40)]
    pv = portfolio_vol_estimate(rets, vix_level=20.0, window=20)
    assert pv.implied == pytest.approx(0.20, abs=1e-9)
    assert pv.realized is not None
    assert min(pv.realized, pv.implied) <= pv.blended <= max(pv.realized, pv.implied)


def test_correlation_matrix_measures_diversification():
    up = [0.01, 0.02, -0.01, 0.03, -0.02]
    same = list(up)
    opp = [-x for x in up]
    m = correlation_matrix({"income": up, "core": same, "overlay": opp})
    assert m["income"]["income"] == pytest.approx(1.0)
    assert m["income"]["core"] == pytest.approx(1.0, abs=1e-9)  # identical
    assert m["income"]["overlay"] == pytest.approx(-1.0, abs=1e-9)  # anti-correlated
    assert m["overlay"]["income"] == m["income"]["overlay"]  # symmetric


# --------------------------------------------------------------------------- #
# Vol targeting
# --------------------------------------------------------------------------- #
def test_vol_target_halves_when_vol_doubles():
    lev = LeverageCapCfg(max_exposure_scalar=5.0, min_exposure_scalar=0.0)
    s1 = exposure_scalar(0.13, 0.13, leverage=lev)
    s2 = exposure_scalar(0.26, 0.13, leverage=lev)
    assert s1 == pytest.approx(1.0)
    assert s2 == pytest.approx(0.5)


def test_vol_target_clamped_to_caps():
    lev = LeverageCapCfg(max_exposure_scalar=2.25, min_exposure_scalar=0.25)
    assert exposure_scalar(0.01, 0.13, leverage=lev) == pytest.approx(2.25)  # capped
    assert exposure_scalar(5.0, 0.13, leverage=lev) == pytest.approx(0.25)  # floored
    assert exposure_scalar(0.0, 0.13, leverage=lev) == pytest.approx(2.25)  # unknown -> max


# --------------------------------------------------------------------------- #
# Drawdown governor tiers + anti-whipsaw
# --------------------------------------------------------------------------- #
def test_drawdown_tiers():
    cfg = GovernorThresholdsCfg(dd_warn=0.10, dd_delever=0.15, dd_defensive=0.20)
    g = DrawdownGovernor(cfg)
    assert g.update(100_000).tier is DrawdownTier.FULL  # sets HWM
    assert g.update(95_000).tier is DrawdownTier.FULL  # 5% dd
    assert g.update(88_000).tier is DrawdownTier.WARN  # 12% dd
    assert g.update(83_000).tier is DrawdownTier.DELEVER  # 17% dd
    st = g.update(78_000)  # 22% dd
    assert st.tier is DrawdownTier.DEFENSIVE
    assert st.exposure_scale == 0.0 and st.risk_on is False


def test_drawdown_warn_scale_is_linear():
    cfg = GovernorThresholdsCfg(dd_warn=0.10, dd_delever=0.20, dd_defensive=0.30)
    g = DrawdownGovernor(cfg)
    g.update(100_000)
    st = g.update(85_000)  # 15% dd -> midpoint of warn..delever -> ~0.75
    assert st.tier is DrawdownTier.WARN
    assert st.exposure_scale == pytest.approx(0.75, abs=0.01)


def test_drawdown_anti_whipsaw_reentry():
    cfg = GovernorThresholdsCfg(dd_warn=0.10, dd_delever=0.15, dd_defensive=0.20,
                                reentry_recovery_margin=0.05)
    g = DrawdownGovernor(cfg)
    g.update(100_000)
    assert g.update(78_000).locked is True  # 22% -> defensive lock
    # bounce back to 17% dd (83k): still locked (not recovered the 0.05 margin)
    st = g.update(83_000)
    assert st.locked is True and st.risk_on is False and st.tier is DrawdownTier.DEFENSIVE
    # recover past 15% dd (85k) -> dd 0.15 <= 0.20-0.05 -> unlocks
    st2 = g.update(85_000)
    assert st2.locked is False
    assert st2.risk_on is True


# --------------------------------------------------------------------------- #
# Leverage allocator
# --------------------------------------------------------------------------- #
def _alloc(**kw):
    base = dict(
        dd_budget=20_000.0, income_severe_loss=15_000.0, core_severe_loss=25_000.0,
        hedge_payoff=0.0, overlay_crisis_payoff=0.0,
        vol_target_scalar=5.0, drawdown_scale=1.0, leverage_cap=5.0,
    )
    base.update(kw)
    return allocate(**base)


def test_allocator_respects_dd_budget():
    res = _alloc()
    assert res.severe_tail_loss <= res.dd_budget + 1e-6
    assert res.within_budget
    assert res.engine_scale["income"] == res.engine_scale["core"]
    assert res.engine_scale["overlay"] == 1.0  # overlay not de-levered


def test_hedge_frees_leverage():
    # More hedge payoff (and overlay crisis alpha) -> higher allowed Engine 1/2 size.
    low = _alloc(hedge_payoff=0.0, overlay_crisis_payoff=0.0)
    high = _alloc(hedge_payoff=20_000.0, overlay_crisis_payoff=10_000.0)
    assert high.engine_scale["income"] > low.engine_scale["income"]
    assert high.risk_implied_leverage > low.risk_implied_leverage
    # still within budget after the extra leverage
    assert high.severe_tail_loss <= high.dd_budget + 1e-6


def test_drawdown_scale_delevers_engines():
    full = _alloc(drawdown_scale=1.0)
    cut = _alloc(drawdown_scale=0.5)
    assert cut.applied_leverage == pytest.approx(0.5 * full.applied_leverage)
    assert cut.engine_scale["overlay"] == 1.0  # protection stays on


def test_vol_target_gates_leverage():
    # A tight vol-target scalar caps leverage below the risk-implied level.
    res = _alloc(vol_target_scalar=0.5, hedge_payoff=50_000.0)
    assert res.applied_leverage == pytest.approx(0.5)
