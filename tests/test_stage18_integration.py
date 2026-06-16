"""Stage 18: per-engine ranker + governor gating, engine/governor UI, gov alerts.

Covers: per-engine candidate routing; governor gating of staged size; defensive
state suppresses risk-on; governor alerts fire on the right transitions; the
governor panel renders against a fixture governor state.
"""

from __future__ import annotations

from datetime import date, timedelta

from core.bs_pricing import bs_greeks
from core.chain import OptionChain, OptionQuote
from core.context import TradeContext
from core.models import Family, InstrumentClass, Right
from config.schema import GovernorThresholdsCfg
from portfolio.account_profiles import AccountProfile, Pool
from regime.market_regime import classify_market_regime
from regime.stock_regime import stock_regime
from regime.surface import Surface
from selection.engine_ranker import rank_engines
from ui.app import create_app
from ui.state import AppState

ASOF = date(2026, 6, 15)
SPOT = 100.0
CALM = classify_market_regime(14, 15, 17, 110, 100, True)
HARD_SKIP = classify_market_regime(32, 30, 26, 90, 100, False)


def _chain(symbol="SPY") -> OptionChain:
    quotes = []
    for dte in (45, 75, 90, 270):
        exp = ASOF + timedelta(days=dte)
        t = dte / 365.0
        for k in range(60, 141, 2):
            for right in (Right.CALL, Right.PUT):
                g = bs_greeks(SPOT, float(k), t, 0.04, 0.25, right)
                price = max(g["price"], 0.05)
                quotes.append(OptionQuote(expiry=exp, strike=float(k), right=right,
                                          bid=round(price * 0.98, 2), ask=round(price * 1.02 + 0.02, 2),
                                          delta=g["delta"], iv=0.25))
    return OptionChain(symbol=symbol, spot=SPOT, quotes=quotes, asof=ASOF)


def _regime(ivr=60.0):
    surf = Surface(ticker="SPY", iv_9d=0.24, iv_30d=0.25, iv_90d=0.26,
                   slope_9_30=0.01, slope_30_90=0.01, inverted_front=False)
    return stock_regime("SPY", surf, ivr=ivr, vrp_value=0.05)


def _ctx(market=CALM) -> TradeContext:
    return TradeContext(
        symbol="SPY", account_id="T1", instrument_class=InstrumentClass.US_ETF_OPT,
        chain=_chain(), is_etf=True, spot=SPOT, stock_regime=_regime(), market_regime=market,
        per_position_budget=800.0, nlv=100_000.0, asof=ASOF,
        extras={"pool": "trading", "tier": "A", "core_capital": 50_000.0,
                "closes": [50.0 + 0.2 * i for i in range(300)],
                "overlay_name_budget": 5_000.0,
                "core_severe_loss": 30_000.0, "dd_budget": 20_000.0},
    )


TRADING = AccountProfile("T1", "Trading 1", Pool.TRADING, nlv=100_000.0)


# --------------------------------------------------------------------------- #
# Per-engine routing
# --------------------------------------------------------------------------- #
def test_per_engine_candidate_routing():
    res = rank_engines([TRADING], [_ctx()])
    per = res.by_engine["T1"]
    assert "income" in per and "core" in per and "overlay" in per
    # income credit spread, core LEAPS, overlay debit spread/leap
    assert any(s.family in (Family.PUT_CREDIT_SPREAD, Family.IRON_CONDOR) for s in per["income"])
    assert any(s.family in (Family.CORE_LEAPS, Family.CORE_PMCC) for s in per["core"])
    assert any(s.family in (Family.OVERLAY_DEBIT_SPREAD, Family.OVERLAY_LEAP) for s in per["overlay"])
    # the core engine also surfaced its standing hedge
    assert any(s.family is Family.CORE_HEDGE for s in per["core"])
    # all candidates carry their engine tag
    for engine_name, items in per.items():
        assert all(s.engine == engine_name for s in items)


def test_governor_gating_of_staged_size():
    # income gated to 0 -> no income staged; core/overlay full.
    res = rank_engines([TRADING], [_ctx()],
                       engine_scale={"income": 0.0, "core": 1.0, "overlay": 1.0})
    staged = res.staged["T1"]
    assert staged
    assert all(s.engine != "income" for s in staged)
    assert any(s.engine == "core" for s in staged)


def test_defensive_state_suppresses_risk_on():
    # risk_on=False -> only hedge actions surface.
    res = rank_engines([TRADING], [_ctx()], risk_on=False)
    staged = res.staged["T1"]
    assert staged  # the standing hedge still surfaces
    assert all(s.family is Family.CORE_HEDGE for s in staged)


def test_hard_skip_vetoes_risk_on_but_allows_hedge():
    res = rank_engines([TRADING], [_ctx(market=HARD_SKIP)])
    per = res.by_engine.get("T1", {})
    # no risk-on income/overlay candidates survive HARD_SKIP
    assert all(not v for k, v in per.items() if k in ("income", "overlay"))
    # the standing hedge (CORE_HEDGE) is still allowed
    core = per.get("core", [])
    assert core and all(s.family is Family.CORE_HEDGE for s in core)


# --------------------------------------------------------------------------- #
# Governor alerts
# --------------------------------------------------------------------------- #
def test_governor_alerts_fire_on_transitions():
    from alerts.governor_alerts import governor_alerts
    from alerts.triggers import Severity, TriggerKind
    from governor.drawdown_governor import DrawdownGovernor

    cfg = GovernorThresholdsCfg(dd_warn=0.10, dd_delever=0.15, dd_defensive=0.20)
    g = DrawdownGovernor(cfg)
    g.update(100_000)
    prev = g.update(98_000)  # FULL
    now = g.update(78_000)  # DEFENSIVE (22%)

    alerts = governor_alerts(
        now, prev_state=prev,
        applied_leverage=0.4, prev_applied_leverage=1.5,
        exposure_scalar=0.5, prev_exposure_scalar=1.0,
        hedge_coverage=0.3, hedge_coverage_floor=0.5,
        severe_within_budget=False,
    )
    kinds = {a.kind for a in alerts}
    assert TriggerKind.DRAWDOWN_TIER in kinds
    assert TriggerKind.DELEVER_TRIGGERED in kinds
    assert TriggerKind.VOL_TARGET_CUT in kinds
    assert TriggerKind.HEDGE_COVERAGE_LOW in kinds
    assert TriggerKind.SEVERE_TAIL_BREACH in kinds
    # CRITICAL first
    assert alerts[0].severity is Severity.CRITICAL


def test_governor_alerts_quiet_when_stable():
    from alerts.governor_alerts import governor_alerts
    from governor.drawdown_governor import DrawdownGovernor

    g = DrawdownGovernor()
    g.update(100_000)
    st = g.update(99_000)  # FULL, no change
    alerts = governor_alerts(st, prev_state=st, applied_leverage=1.0,
                             prev_applied_leverage=1.0, exposure_scalar=1.0,
                             prev_exposure_scalar=1.0, hedge_coverage=0.8,
                             severe_within_budget=True)
    assert alerts == []


# --------------------------------------------------------------------------- #
# Governor panel rendering
# --------------------------------------------------------------------------- #
def test_governor_panel_renders():
    state = AppState(
        governor={"vol_target": 0.13, "sigma_now": 0.11, "exposure_scalar": 1.18,
                  "drawdown": "4.0%", "tier": "FULL", "leverage_util": "1.4x",
                  "hedge_coverage": "82%", "severe_tail_pass": True},
        engine_allocations={"income": {"target": 0.40, "actual": 0.38},
                            "core": {"target": 0.40, "actual": 0.41},
                            "overlay": {"target": 0.20, "actual": 0.20}},
    )
    app = create_app(state=state)
    html = app.test_client().get("/governor").data.decode()
    assert "Governor state" in html
    assert "exposure scalar" in html
    assert "PASS" in html
    assert "Engine allocations" in html
    assert "income" in html and "overlay" in html


def test_governor_panel_empty_when_off():
    html = create_app(mode="mock").test_client().get("/governor").data.decode()
    assert "no governor cycle" in html
