"""Stage 13: v2 engine scaffolding + leverage/governor config.

Covers: config load/validate incl. the new engines.yaml + governor fields and
their bounds; the Engine 1 income wrapper emits the SAME suggestions as the v1
generators (tagged engine="income"); Engine interface conformance.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from config.loader import load_config, load_engines
from config.schema import (
    CoreEngineCfg,
    EnginesConfig,
    GovernorThresholdsCfg,
    IncomeEngineCfg,
    LeverageCapCfg,
    OverlayEngineCfg,
    RiskConfig,
)
from core.chain import OptionChain, OptionQuote
from core.context import TradeContext
from core.models import Family, InstrumentClass, Right
from engines import IncomeEngine
from engines.base import Engine, tag_engine
from engines.engine1_income import income_generators_for
from regime.stock_regime import stock_regime
from regime.surface import Surface
from strategies import credit_spread, iron_condor, wheel_csp

ASOF = date(2026, 6, 15)
EXPIRY = date(2026, 7, 30)

_PUTS = [(100, -0.50, 3.00), (95, -0.30, 1.80), (92, -0.20, 1.20), (90, -0.15, 0.90),
         (87, -0.10, 0.60), (85, -0.07, 0.40), (80, -0.04, 0.20)]
_CALLS = [(100, 0.50, 3.00), (105, 0.30, 1.80), (108, 0.20, 1.20), (110, 0.15, 0.90),
          (113, 0.10, 0.60), (115, 0.07, 0.40), (120, 0.04, 0.20)]


def _chain() -> OptionChain:
    quotes = [OptionQuote(expiry=EXPIRY, strike=k, right=Right.PUT, bid=m, ask=m, delta=d, iv=0.30)
              for k, d, m in _PUTS]
    quotes += [OptionQuote(expiry=EXPIRY, strike=k, right=Right.CALL, bid=m, ask=m, delta=d, iv=0.30)
               for k, d, m in _CALLS]
    return OptionChain(symbol="AAPL", spot=100.0, quotes=quotes, asof=ASOF)


def _ctx(pool: str, *, acquire=None) -> TradeContext:
    surf = Surface(ticker="AAPL", iv_9d=0.24, iv_30d=0.25, iv_90d=0.26,
                   slope_9_30=0.01, slope_30_90=0.01, inverted_front=False)
    return TradeContext(
        symbol="AAPL", account_id="A1", instrument_class=InstrumentClass.US_EQUITY_OPT,
        chain=_chain(), spot=100.0, stock_regime=stock_regime("AAPL", surf, ivr=55.0, vrp_value=0.05),
        per_position_budget=600.0, acquire_below_price=acquire, asof=ASOF,
        extras={"pool": pool},
    )


# --------------------------------------------------------------------------- #
# Config: new fields + bounds
# --------------------------------------------------------------------------- #
def test_config_loads_engines_and_governor():
    cfg = load_config()
    assert abs(cfg.engines.income.capital_allocation
               + cfg.engines.core.capital_allocation
               + cfg.engines.overlay.capital_allocation - 1.0) < 0.05
    assert cfg.engines.income.short_premium_target_pct == 15.0
    assert cfg.engines.income.short_premium_max_pct == 18.0
    assert 1.3 <= cfg.engines.core.core_exposure_mult <= 1.7
    assert cfg.engines.overlay.trend_overlay_risk_pct > 0
    g = cfg.risk.governor
    assert g.portfolio_vol_target_annual == pytest.approx(0.13)
    assert (g.thresholds.dd_warn, g.thresholds.dd_delever, g.thresholds.dd_defensive) == (0.10, 0.15, 0.20)
    assert g.leverage.gross_notional_ceiling == pytest.approx(2.25)
    # severe tail present on the stress block
    assert cfg.risk.stress.severe_spot_shock == pytest.approx(-0.20)
    assert cfg.risk.stress.severe_iv_shock == pytest.approx(30.0)


def test_engines_yaml_matches_defaults():
    # The shipped engines.yaml should validate and round-trip to the same band.
    eng = load_engines()
    assert isinstance(eng, EnginesConfig)
    assert eng.income.short_premium_max_pct >= eng.income.short_premium_target_pct


def test_core_exposure_mult_bounds():
    with pytest.raises(ValidationError):
        CoreEngineCfg(core_exposure_mult=1.1)  # below 1.3
    with pytest.raises(ValidationError):
        CoreEngineCfg(core_exposure_mult=2.0)  # above 1.7
    assert CoreEngineCfg(core_exposure_mult=1.7).core_exposure_mult == 1.7


def test_income_heat_band_bounds():
    with pytest.raises(ValidationError):
        IncomeEngineCfg(short_premium_target_pct=20.0, short_premium_max_pct=18.0)  # target > max


def test_governor_threshold_ordering():
    with pytest.raises(ValidationError):
        GovernorThresholdsCfg(dd_warn=0.15, dd_delever=0.10)  # warn > delever
    with pytest.raises(ValidationError):
        GovernorThresholdsCfg(dd_defensive=1.5)  # >= 1
    ok = GovernorThresholdsCfg(dd_warn=0.08, dd_delever=0.14, dd_defensive=0.22)
    assert ok.dd_defensive == 0.22


def test_leverage_cap_bounds():
    with pytest.raises(ValidationError):
        LeverageCapCfg(gross_notional_ceiling=0.0)
    with pytest.raises(ValidationError):
        LeverageCapCfg(min_exposure_scalar=2.0, max_exposure_scalar=1.0)


def test_engine_allocations_must_sum_to_one():
    with pytest.raises(ValidationError):
        EnginesConfig(income=IncomeEngineCfg(capital_allocation=0.8),
                      core=CoreEngineCfg(capital_allocation=0.8),
                      overlay=OverlayEngineCfg(capital_allocation=0.8))


def test_overlay_must_be_load_bearing():
    with pytest.raises(ValidationError):
        OverlayEngineCfg(trend_overlay_risk_pct=0.0)


def test_risk_config_defaults_have_governor():
    # A sparse RiskConfig still materializes the governor + severe-tail defaults.
    rc = RiskConfig()
    assert rc.governor.portfolio_vol_target_annual == pytest.approx(0.13)
    assert rc.stress.severe_spot_shock == pytest.approx(-0.20)


# --------------------------------------------------------------------------- #
# Engine 1 wrapper == v1, tagged
# --------------------------------------------------------------------------- #
def test_income_engine_trading_matches_v1():
    ctx = _ctx("trading")
    engine = IncomeEngine()
    out = engine.propose(ctx)
    assert out, "expected income candidates in a calm, high-IVR regime"
    assert all(s.engine == "income" for s in out)
    families = {s.family for s in out}
    # same families the v1 generators would emit (credit spread + iron condor)
    assert Family.PUT_CREDIT_SPREAD in families
    # the wrapped functions emit identical legs to calling v1 directly
    v1 = credit_spread.propose(ctx)
    wrapped = next(s for s in out if s.family is v1.family)
    assert [(l.contract.strike, l.action) for l in wrapped.legs] == \
           [(l.contract.strike, l.action) for l in v1.legs]


def test_income_engine_smsf_matches_v1():
    ctx = _ctx("investing", acquire=95.0)
    out = IncomeEngine().propose(ctx)
    assert all(s.engine == "income" for s in out)
    csp = wheel_csp.propose(ctx)
    if csp is not None:
        assert any(s.family is Family.WHEEL_CSP for s in out)


def test_income_generators_exclude_trend():
    # Trend families fold into Engine 3 (Stage 15) — not Engine 1.
    trading = income_generators_for("trading")
    assert credit_spread.propose in trading and iron_condor.propose in trading
    from strategies import trend_long
    assert trend_long.propose not in trading


# --------------------------------------------------------------------------- #
# Engine interface conformance
# --------------------------------------------------------------------------- #
def test_engine_interface_conformance():
    engine = IncomeEngine()
    assert isinstance(engine, Engine)
    assert engine.name == "income"
    assert engine.target_allocation(load_engines()) == pytest.approx(load_engines().income.capital_allocation)
    out = engine.propose(_ctx("trading"))
    # current_risk sums only this engine's defined max-loss
    risk = engine.current_risk(out)
    assert risk == pytest.approx(sum(abs(s.max_loss or 0) for s in out))
    assert engine.risk_contribution(out) == risk
    # items from another engine are ignored
    for s in out:
        s.engine = "core"
    assert engine.current_risk(out) == 0.0


def test_tag_engine_drops_none():
    out = tag_engine([None], "income")
    assert out == []
