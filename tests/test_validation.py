"""Stage 19: validation harness — historical/MC scenario replay + 20% DD gate.

Covers: replay runs on bundled fixture regimes; DD distribution + report fields;
PASS/FAIL logic (a deliberately over-levered config FAILs and prints the cut).
"""

from __future__ import annotations

from validation import (
    EngineProxies,
    historical_scenarios,
    monte_carlo_paths,
    replay,
    run_validation,
)


def test_historical_scenarios_bundled():
    sc = historical_scenarios()
    assert {"2008_GFC", "2018_VOL", "2020_COVID", "2022_BEAR"} <= set(sc)
    assert all(len(v) > 0 for v in sc.values())


def test_replay_produces_fields():
    rets = historical_scenarios()["2020_COVID"]
    res = replay(rets, name="2020_COVID")
    assert res.name == "2020_COVID"
    assert 0.0 <= res.max_drawdown <= 1.0
    assert len(res.leverage_path) == len(rets)
    assert res.hedge_payoff >= 0.0  # hedge only ever pays (long puts)
    assert res.min_exposure_scale <= 1.0


def test_monte_carlo_paths_deterministic():
    a = monte_carlo_paths(5, days=50, seed=1)
    b = monte_carlo_paths(5, days=50, seed=1)
    assert a == b  # seeded -> reproducible
    assert len(a) == 5 and all(len(p) == 50 for p in a)


def test_governor_delevers_in_a_crash():
    # A sharp crash should trip the drawdown governor at least once.
    res = replay(historical_scenarios()["2008_GFC"],
                 proxies=EngineProxies(core_leverage=1.6, hedge_strength=1.0))
    assert res.delever_events >= 1
    assert res.min_exposure_scale < 1.0


def test_overlevered_config_fails_and_prints_cut():
    over = EngineProxies(core_leverage=3.0, hedge_strength=0.2, income_crash_beta=5.0)
    report = run_validation(proxies=over, leverage_cap=3.0, mc_paths=60)
    assert report.passed is False
    assert report.required_leverage_factor < 1.0
    md = report.to_markdown()
    assert "FAIL" in md
    assert "Reduce leverage" in md
    assert f"{report.required_leverage_factor:.0%}" in md


def test_moderate_config_passes():
    # Modest leverage + a strong standing hedge keeps drawdowns within budget.
    safe = EngineProxies(core_leverage=1.3, hedge_strength=4.0, income_crash_beta=1.0)
    report = run_validation(proxies=safe, leverage_cap=1.5, mc_paths=60)
    assert report.passed is True
    assert report.required_leverage_factor == 1.0
    assert "PASS" in report.to_markdown()


def test_report_has_all_fields():
    report = run_validation(mc_paths=40)
    assert len(report.scenarios) == 4
    md = report.to_markdown()
    for field in ("Historical regime proxies", "Monte Carlo", "max DD",
                  "95th-pct drawdown", "DD budget"):
        assert field in md
    assert 0.0 <= report.mc_dd_95 <= 1.0
