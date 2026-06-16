"""Pre-live validation — the mandatory gate before enabling live leverage.

Keystone has no backtester; this harness replays historical vol-regime proxies
(2008 / 2018-vol / 2020 / 2022) and a Monte Carlo through the governor + simple,
documented engine P&L proxies, then reports the drawdown distribution against
the 20% DD budget with a hard PASS/FAIL. Live leverage must not be enabled until
this passes at the configured leverage cap.
"""

from __future__ import annotations

from validation.scenario_replay import (
    EngineProxies,
    ReplayReport,
    ScenarioResult,
    historical_scenarios,
    monte_carlo_paths,
    replay,
    run_validation,
)

__all__ = [
    "EngineProxies", "ReplayReport", "ScenarioResult", "historical_scenarios",
    "monte_carlo_paths", "replay", "run_validation",
]
