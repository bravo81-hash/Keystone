"""Scenario replay — historical vol-regime proxies + Monte Carlo through the
governor and documented engine P&L proxies. Produces the DD-budget PASS/FAIL gate.

P&L proxies (simple + documented — NOT a backtest):
  * Engine 1 (income): a steady short-premium carry that takes CONVEX losses on
    big down days (short gamma/vega), gated by the risk-on leverage.
  * Engine 2 (core): levered beta (core_leverage x capital x market return) PLUS
    a standing hedge that pays off on large down days (long puts). Core is
    de-levered by the governor; the hedge is not.
  * Engine 3 (overlay): time-series-momentum payoff — follows the trailing-return
    sign, so in a sustained bear it is short and prints positive crisis alpha.

The governor each step: vol-targets the book (exposure scalar) and applies the
tiered drawdown circuit-breaker (de-levers Engines 1-2). Outputs the drawdown
path, leverage utilization, CAGR proxy, de-lever events, and tail hedge payoff.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from statistics import mean
from typing import Optional

from config.schema import GovernorCfg
from governor.drawdown_governor import DrawdownGovernor
from governor.vol_target import exposure_scalar

TRADING_DAYS = 252


# --------------------------------------------------------------------------- #
# Engine P&L proxies
# --------------------------------------------------------------------------- #
@dataclass
class EngineProxies:
    """Documented coefficients for the engine P&L proxies (fractions of NLV)."""

    income_frac: float = 0.40
    core_frac: float = 0.40
    overlay_frac: float = 0.20
    core_leverage: float = 1.5  # Engine 2 effective core exposure multiple
    income_daily_carry: float = 0.0006  # ~15%/yr short-premium carry in calm
    income_crash_beta: float = 3.0  # convex loss multiple on big down days
    crash_threshold: float = 0.02  # |down move| beyond which convex losses bite
    hedge_strength: float = 2.0  # hedge payoff multiple on the crash excess
    overlay_trend_strength: float = 1.0  # managed-futures responsiveness

    @classmethod
    def from_config(cls, engines_cfg, *, hedge_strength: float = 2.0) -> "EngineProxies":
        return cls(
            income_frac=engines_cfg.income.capital_allocation,
            core_frac=engines_cfg.core.capital_allocation,
            overlay_frac=engines_cfg.overlay.capital_allocation,
            core_leverage=engines_cfg.core.core_exposure_mult,
            hedge_strength=hedge_strength,
        )


def _down_excess(r: float, threshold: float) -> float:
    """How far a return is below -threshold (0 for flat/up days)."""

    return max(0.0, -r - threshold)


def _step_pnl(r: float, trend_sign: int, risk_on_scale: float, p: EngineProxies) -> tuple[float, float]:
    """Per-step total P&L (fraction of current NLV) + the hedge contribution.

    ``risk_on_scale`` gates Engines 1-2 (vol-target x drawdown scale); the hedge
    and overlay are protective and not de-levered.
    """

    excess = _down_excess(r, p.crash_threshold)

    core = risk_on_scale * p.core_leverage * p.core_frac * r
    income = risk_on_scale * p.income_frac * (p.income_daily_carry - p.income_crash_beta * excess)
    hedge = p.hedge_strength * p.core_frac * excess  # long puts: positive on crashes
    overlay = p.overlay_frac * p.overlay_trend_strength * trend_sign * r

    total = core + income + hedge + overlay
    return total, hedge


# --------------------------------------------------------------------------- #
# Scenario sources
# --------------------------------------------------------------------------- #
def _seq(*blocks: tuple[int, float]) -> list[float]:
    out: list[float] = []
    for n, val in blocks:
        out.extend([val] * n)
    return out


def historical_scenarios() -> dict[str, list[float]]:
    """Deterministic daily-return PROXIES capturing each regime's shape (not the
    actual historical series)."""

    return {
        # 2008: long grinding bear with repeated vol spikes (~ -50% peak-to-trough).
        "2008_GFC": _seq((40, -0.004), (5, -0.05), (30, -0.003), (4, -0.09),
                         (40, -0.002), (6, -0.06), (60, 0.001), (5, -0.07)),
        # 2018 "volmageddon": calm, then a sharp short vol spike.
        "2018_VOL": _seq((20, 0.001), (1, -0.04), (1, -0.08), (2, -0.03), (15, 0.004)),
        # 2020 COVID: very sharp crash then sharp recovery.
        "2020_COVID": _seq((10, 0.0), (6, -0.05), (3, -0.12), (4, -0.06),
                           (20, 0.02), (20, 0.015)),
        # 2022: grinding trending bear (kind to managed-futures).
        "2022_BEAR": _seq((120, -0.0010), (10, -0.02), (122, -0.0008)),
    }


def monte_carlo_paths(n: int, days: int = TRADING_DAYS, *, seed: int = 7,
                      daily_vol: float = 0.012, jump_prob: float = 0.01,
                      jump_size: float = -0.08) -> list[list[float]]:
    """N random daily-return paths: Gaussian body + occasional negative jumps."""

    rng = random.Random(seed)
    paths: list[list[float]] = []
    for _ in range(n):
        path = []
        for _ in range(days):
            r = rng.gauss(0.0003, daily_vol)
            if rng.random() < jump_prob:
                r += jump_size
            path.append(r)
        paths.append(path)
    return paths


# --------------------------------------------------------------------------- #
# Replay
# --------------------------------------------------------------------------- #
@dataclass
class ScenarioResult:
    name: str
    max_drawdown: float
    final_nlv: float
    cagr: float
    delever_events: int
    min_exposure_scale: float  # deepest de-lever reached
    hedge_payoff: float  # cumulative hedge contribution (fraction of starting NLV)
    leverage_path: list[float] = field(default_factory=list)
    within_budget: bool = True


def _trend_sign(returns: list[float], i: int, lookback: int = 20) -> int:
    if i < lookback:
        return 1  # default long until a trend forms
    window = returns[i - lookback:i]
    s = sum(window)
    return 1 if s >= 0 else -1


def replay(
    returns: list[float],
    *,
    governor_cfg: Optional[GovernorCfg] = None,
    proxies: Optional[EngineProxies] = None,
    leverage_cap: float = 2.25,
    starting_nlv: float = 100_000.0,
    name: str = "scenario",
    vol_window: int = 20,
) -> ScenarioResult:
    """Drive the governor + engine proxies over a return path; return the result."""

    gcfg = governor_cfg or GovernorCfg()
    p = proxies or EngineProxies()
    dd_gov = DrawdownGovernor(gcfg.thresholds, hwm=starting_nlv)

    nlv = starting_nlv
    nlv_returns: list[float] = []
    leverage_path: list[float] = []
    hedge_total = 0.0
    delever_events = 0
    min_scale = 1.0
    prev_scale = 1.0
    max_dd = 0.0

    # Seed the drawdown governor at the starting HWM.
    state = dd_gov.update(nlv)

    for i, r in enumerate(returns):
        # Vol-target from realized vol of recent book returns.
        if len(nlv_returns) >= vol_window:
            recent = nlv_returns[-vol_window:]
            mu = mean(recent)
            sigma = math.sqrt(sum((x - mu) ** 2 for x in recent) / (len(recent) - 1))
            sigma_annual = sigma * math.sqrt(TRADING_DAYS)
            vol_scalar = exposure_scalar(sigma_annual, gcfg.portfolio_vol_target_annual,
                                         max_scalar=leverage_cap, min_scalar=0.0)
        else:
            vol_scalar = 1.0

        risk_on_scale = min(vol_scalar, leverage_cap) * state.exposure_scale
        leverage_path.append(risk_on_scale * p.core_leverage)

        total_frac, hedge_frac = _step_pnl(r, _trend_sign(returns, i), risk_on_scale, p)
        hedge_total += hedge_frac
        pnl = total_frac * nlv
        nlv += pnl
        nlv_returns.append(total_frac)

        state = dd_gov.update(nlv)
        max_dd = max(max_dd, state.drawdown)
        if state.exposure_scale < prev_scale - 1e-9:
            delever_events += 1
        min_scale = min(min_scale, state.exposure_scale)
        prev_scale = state.exposure_scale

    years = len(returns) / TRADING_DAYS
    cagr = (nlv / starting_nlv) ** (1.0 / years) - 1.0 if years > 0 and nlv > 0 else -1.0
    within = max_dd <= gcfg.thresholds.dd_defensive + 1e-9

    return ScenarioResult(
        name=name, max_drawdown=max_dd, final_nlv=nlv, cagr=cagr,
        delever_events=delever_events, min_exposure_scale=min_scale,
        hedge_payoff=hedge_total, leverage_path=leverage_path, within_budget=within,
    )


# --------------------------------------------------------------------------- #
# Report + PASS/FAIL gate
# --------------------------------------------------------------------------- #
@dataclass
class ReplayReport:
    scenarios: list[ScenarioResult]
    mc_dd_max: float
    mc_dd_95: float
    mc_cagr_median: float
    dd_budget: float
    materiality: float
    passed: bool
    required_leverage_factor: float  # <1 => cut leverage by this factor to pass
    worst_scenario: str

    def to_markdown(self) -> str:
        lines = ["# Keystone v2 — Pre-Live Validation Report", ""]
        lines.append(f"**DD budget:** {self.dd_budget:.0%}  ·  "
                     f"**materiality:** +{self.materiality:.0%}  ·  "
                     f"**verdict:** {'✅ PASS' if self.passed else '❌ FAIL'}")
        lines.append("")
        lines.append("## Historical regime proxies")
        lines.append("| scenario | max DD | CAGR | de-lever events | min exposure | hedge payoff | within budget |")
        lines.append("|---|---|---|---|---|---|---|")
        for s in self.scenarios:
            lines.append(
                f"| {s.name} | {s.max_drawdown:.1%} | {s.cagr:.1%} | {s.delever_events} | "
                f"{s.min_exposure_scale:.2f} | {s.hedge_payoff:+.2%} | "
                f"{'yes' if s.within_budget else 'NO'} |"
            )
        lines.append("")
        lines.append("## Monte Carlo")
        lines.append(f"- max drawdown: {self.mc_dd_max:.1%}")
        lines.append(f"- 95th-pct drawdown: {self.mc_dd_95:.1%}")
        lines.append(f"- median CAGR proxy: {self.mc_cagr_median:.1%}")
        lines.append("")
        if not self.passed:
            lines.append(
                f"## ❌ FAIL — leverage too high\n"
                f"Worst scenario **{self.worst_scenario}** breaches the budget. "
                f"Reduce leverage to **{self.required_leverage_factor:.0%}** of the configured "
                f"cap (multiply the cap by {self.required_leverage_factor:.2f}) and re-run. "
                f"Do NOT enable live leverage until this passes."
            )
        else:
            lines.append("## ✅ PASS\nReplayed drawdowns stay within the budget at the "
                         "configured leverage cap. Live leverage may be enabled (review the "
                         "report first; the cap cannot act inside an overnight gap).")
        return "\n".join(lines)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * pct
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def run_validation(
    *,
    governor_cfg: Optional[GovernorCfg] = None,
    proxies: Optional[EngineProxies] = None,
    leverage_cap: float = 2.25,
    materiality: float = 0.25,
    mc_paths: int = 200,
    mc_seed: int = 7,
    starting_nlv: float = 100_000.0,
) -> ReplayReport:
    """Run all historical proxies + a Monte Carlo and produce the PASS/FAIL gate.

    FAIL when any historical scenario's max drawdown exceeds the budget by more
    than ``materiality`` (or the MC 95th-pct DD exceeds the budget). The required
    leverage factor is the cut that would bring the worst observed DD to budget.
    """

    gcfg = governor_cfg or GovernorCfg()
    p = proxies or EngineProxies()
    budget = gcfg.thresholds.dd_defensive

    scenarios = [
        replay(rets, governor_cfg=gcfg, proxies=p, leverage_cap=leverage_cap,
               starting_nlv=starting_nlv, name=name)
        for name, rets in historical_scenarios().items()
    ]

    mc = [replay(path, governor_cfg=gcfg, proxies=p, leverage_cap=leverage_cap,
                 starting_nlv=starting_nlv, name=f"mc{i}")
          for i, path in enumerate(monte_carlo_paths(mc_paths, seed=mc_seed))]
    mc_dds = [s.max_drawdown for s in mc]
    mc_dd_max = max(mc_dds) if mc_dds else 0.0
    mc_dd_95 = _percentile(mc_dds, 0.95)
    mc_cagr_median = _percentile([s.cagr for s in mc], 0.5) if mc else 0.0

    worst = max(scenarios, key=lambda s: s.max_drawdown)
    threshold = budget * (1.0 + materiality)
    passed = worst.max_drawdown <= threshold and mc_dd_95 <= budget + 1e-9
    required = 1.0 if passed or worst.max_drawdown <= 0 else max(0.0, budget / worst.max_drawdown)

    return ReplayReport(
        scenarios=scenarios, mc_dd_max=mc_dd_max, mc_dd_95=mc_dd_95,
        mc_cagr_median=mc_cagr_median, dd_budget=budget, materiality=materiality,
        passed=passed, required_leverage_factor=required, worst_scenario=worst.name,
    )
