"""Pydantic schemas for the four Keystone config files.

Every field carries a sensible default so a sparse YAML still validates; the
only hard requirement is that ``accounts.yaml`` lists at least one account.
Real values are filled by the user — the shipped YAMLs are documented
placeholders. Budget/stress numbers are expressed *per $100k NLV* unless noted.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


# --------------------------------------------------------------------------- #
# accounts.yaml
# --------------------------------------------------------------------------- #
class BlockedRuleCfg(BaseModel):
    """A structural restriction for an account.

    ``multi_expiry`` None means "any"; True restricts only multi-expiry combos
    of that instrument class (the SMSF EU cash-index rule), False only single.
    """

    instrument_class: str
    multi_expiry: Optional[bool] = None


class AccountCfg(BaseModel):
    account_id: str
    label: str
    pool: Literal["trading", "investing"]
    nlv: Optional[float] = None  # account net liquidation value (USD)
    blocked_rules: list[BlockedRuleCfg] = Field(default_factory=list)
    budget_overrides: dict = Field(default_factory=dict)


class AccountsConfig(BaseModel):
    base_currency: str = "USD"
    accounts: list[AccountCfg]


# --------------------------------------------------------------------------- #
# universe.yaml
# --------------------------------------------------------------------------- #
class UniverseGatesCfg(BaseModel):
    min_last_price: float = 30.0
    max_atm_spread_front: float = 0.05  # <= 5% of mid, front expiry
    max_atm_spread_back: float = 0.08  # <= 8% of mid, back expiry
    min_consecutive_weeklies: int = 4
    min_option_adv: int = 5000  # contracts/day
    min_open_interest: int = 1000  # near ATM


class UniverseConfig(BaseModel):
    smsf_nlv: float = 92000.0  # USD; used for affordability flags
    smsf_affordability_single_pct: float = 12.0
    smsf_affordability_etf_pct: float = 25.0
    screened_max_age_days: int = 7  # consumers skip a staler screened.json
    gates: UniverseGatesCfg = Field(default_factory=UniverseGatesCfg)
    extra_tickers: list[str] = Field(default_factory=list)
    excluded_tickers: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# investing.yaml  (SMSF target weights — filled by the user before live use)
# --------------------------------------------------------------------------- #
class TargetHoldingCfg(BaseModel):
    ticker: str
    target_weight: float  # fraction of SMSF NLV (0..1)
    acquire_below_price: Optional[float] = None
    is_etf: bool = False


class InvestingConfig(BaseModel):
    smsf_nlv: float = 92000.0
    pmcc_enabled: bool = False  # PMCC family default OFF (design doc SS5)
    target_holdings: list[TargetHoldingCfg] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# risk.yaml
# --------------------------------------------------------------------------- #
class TradingBudgetCfg(BaseModel):
    max_loss_per_position_pct: float = 1.0  # defined-risk, per $100k NLV
    aggregate_short_premium_pct: float = 6.0
    trend_sleeve_cap_pct: float = 5.0
    max_positions: int = 6
    max_names_per_sector: int = 2
    correlation_cap: float = 0.7


class SMSFBudgetCfg(BaseModel):
    csp_cash_reserve_cap_pct: float = 60.0  # of SMSF NLV reservable to CSPs
    core_notional_cap_pct: float = 100.0
    assignment_notional_single_pct: float = 12.0
    assignment_notional_etf_pct: float = 25.0
    collar_hedge_allowance_pct: float = 5.0
    max_names_per_sector: int = 2


class StressCfg(BaseModel):
    market_spot_shock: float = -0.05  # -5%
    market_iv_shock: float = 10.0  # IV +10 (vol points)
    market_horizon_days: int = 2
    worst_name_gap: float = -0.15  # -15% single-name gap
    worst_name_iv_shock: float = 15.0  # IV +15
    earnings_implied_move_mult: float = 1.5  # +/-1.5x implied move in earnings window
    weekly_pnl_ceiling: Optional[float] = None  # calibrate to THIS book; set by user
    # v2 severe tail (Stage 17): the gap scenario that enforces the DD-hard budget.
    severe_spot_shock: float = -0.20  # -20% overnight gap
    severe_iv_shock: float = 30.0  # IV +30 (vol points)
    severe_horizon_days: int = 1  # overnight


class IndexBookIngestCfg(BaseModel):
    enabled: bool = False  # optional, off by default (Stage 8)
    source: Optional[str] = None


# --------------------------------------------------------------------------- #
# risk.yaml — v2 governor / leverage section
# --------------------------------------------------------------------------- #
class GovernorThresholdsCfg(BaseModel):
    """Tiered drawdown-from-high-water-mark thresholds (fractions of HWM NLV).

    ``dd_warn`` begins linear de-levering; ``dd_delever`` goes hedge-heavy and
    cuts Engines 1-2; ``dd_defensive`` closes/hedges and blocks risk-on until
    NLV recovers ``reentry_recovery_margin`` back above the defensive line
    (anti-whipsaw). Must satisfy 0 < warn < delever < defensive < 1.
    """

    dd_warn: float = 0.10
    dd_delever: float = 0.15
    dd_defensive: float = 0.20
    reentry_recovery_margin: float = 0.03  # NLV must recover this far above the line

    @model_validator(mode="after")
    def _ordered(self) -> "GovernorThresholdsCfg":
        if not (0.0 < self.dd_warn < self.dd_delever < self.dd_defensive < 1.0):
            raise ValueError(
                "governor thresholds must satisfy 0 < dd_warn < dd_delever < dd_defensive < 1"
            )
        if self.reentry_recovery_margin < 0.0:
            raise ValueError("reentry_recovery_margin must be >= 0")
        return self


class LeverageCapCfg(BaseModel):
    """Leverage backstops. The risk-based cap (stress-loss / vol budget) is the
    PRIMARY governor; ``gross_notional_ceiling`` is a hard secondary backstop."""

    gross_notional_ceiling: float = 2.25  # gross notional / NLV hard cap
    min_exposure_scalar: float = 0.0  # vol-target floor (0 = can fully de-risk)
    max_exposure_scalar: float = 2.25  # vol-target cap (aligns with gross ceiling)

    @model_validator(mode="after")
    def _bounds(self) -> "LeverageCapCfg":
        if self.gross_notional_ceiling <= 0:
            raise ValueError("gross_notional_ceiling must be > 0")
        if not (0.0 <= self.min_exposure_scalar <= self.max_exposure_scalar):
            raise ValueError("require 0 <= min_exposure_scalar <= max_exposure_scalar")
        return self


class GovernorCfg(BaseModel):
    portfolio_vol_target_annual: float = 0.13  # 13% annualized whole-book vol target
    thresholds: GovernorThresholdsCfg = Field(default_factory=GovernorThresholdsCfg)
    leverage: LeverageCapCfg = Field(default_factory=LeverageCapCfg)

    @model_validator(mode="after")
    def _vol_target_positive(self) -> "GovernorCfg":
        if self.portfolio_vol_target_annual <= 0:
            raise ValueError("portfolio_vol_target_annual must be > 0")
        return self


class RiskConfig(BaseModel):
    trading: TradingBudgetCfg = Field(default_factory=TradingBudgetCfg)
    smsf: SMSFBudgetCfg = Field(default_factory=SMSFBudgetCfg)
    stress: StressCfg = Field(default_factory=StressCfg)
    index_book_ingest: IndexBookIngestCfg = Field(default_factory=IndexBookIngestCfg)
    governor: GovernorCfg = Field(default_factory=GovernorCfg)


# --------------------------------------------------------------------------- #
# engines.yaml  (v2 — three-engine allocations + per-engine risk budget)
# --------------------------------------------------------------------------- #
class IncomeEngineCfg(BaseModel):
    """Engine 1 (income) — existing v1 strategies, heat raised under governor
    control. The heat is a BAND: the governor sizes short premium between the v1
    floor and ``short_premium_max_pct``, targeting ``short_premium_target_pct``.
    """

    enabled: bool = True
    capital_allocation: float = 0.40  # fraction of NLV allocated to this engine
    risk_budget_pct: float = 0.35  # share of the severe-tail DD budget
    short_premium_target_pct: float = 15.0  # governor target heat (% NLV max-loss)
    short_premium_max_pct: float = 18.0  # hard ceiling on Engine-1 heat

    @model_validator(mode="after")
    def _heat_band(self) -> "IncomeEngineCfg":
        if not (0.0 < self.short_premium_target_pct <= self.short_premium_max_pct):
            raise ValueError("require 0 < short_premium_target_pct <= short_premium_max_pct")
        return self


class CoreEngineCfg(BaseModel):
    """Engine 2 (leveraged protected core) — LEAPS/PMCC + standing hedge."""

    enabled: bool = True
    capital_allocation: float = 0.40
    risk_budget_pct: float = 0.45
    core_exposure_mult: float = 1.5  # effective core exposure x allocated capital
    leaps_delta: float = 0.75  # deep-ITM target delta (70-80)
    hedge_base_otm_pct: float = 0.05  # base layer: OTM index put-spread distance
    hedge_base_spread_width_pct: float = 0.05  # width of the base put spread
    hedge_tail_otm_pct: float = 0.15  # tail layer: deep-OTM long put distance
    severe_tail_loss_cap_pct: float = 0.20  # cap core severe-tail loss near DD budget

    @model_validator(mode="after")
    def _bounds(self) -> "CoreEngineCfg":
        if not (1.3 <= self.core_exposure_mult <= 1.7):
            raise ValueError("core_exposure_mult must be in [1.3, 1.7]")
        if not (0.5 <= self.leaps_delta < 1.0):
            raise ValueError("leaps_delta must be in [0.5, 1.0)")
        return self


class OverlayEngineCfg(BaseModel):
    """Engine 3 (trend/managed-futures + convexity) — load-bearing, defined-risk."""

    enabled: bool = True
    capital_allocation: float = 0.20
    risk_budget_pct: float = 0.20
    trend_overlay_risk_pct: float = 8.0  # load-bearing (> a pure return-maximizer)
    signal: Literal["ts_momentum", "ma_state", "both"] = "both"
    basket: list[str] = Field(
        default_factory=lambda: ["SPY", "QQQ", "IWM", "TLT", "GLD", "XLE", "DBC", "UUP"]
    )

    @model_validator(mode="after")
    def _load_bearing(self) -> "OverlayEngineCfg":
        if self.trend_overlay_risk_pct <= 0:
            raise ValueError("trend_overlay_risk_pct must be > 0 (load-bearing)")
        return self


class EnginesConfig(BaseModel):
    """Three-engine allocation. Capital allocations should sum to ~1.0; risk
    budgets are shares of the severe-tail DD budget and should also sum to ~1.0."""

    income: IncomeEngineCfg = Field(default_factory=IncomeEngineCfg)
    core: CoreEngineCfg = Field(default_factory=CoreEngineCfg)
    overlay: OverlayEngineCfg = Field(default_factory=OverlayEngineCfg)

    @model_validator(mode="after")
    def _allocations(self) -> "EnginesConfig":
        cap = self.income.capital_allocation + self.core.capital_allocation + self.overlay.capital_allocation
        if abs(cap - 1.0) > 0.05:
            raise ValueError(f"engine capital_allocation must sum to ~1.0 (got {cap:.3f})")
        risk = self.income.risk_budget_pct + self.core.risk_budget_pct + self.overlay.risk_budget_pct
        if abs(risk - 1.0) > 0.05:
            raise ValueError(f"engine risk_budget_pct must sum to ~1.0 (got {risk:.3f})")
        return self


# --------------------------------------------------------------------------- #
# Aggregate
# --------------------------------------------------------------------------- #
class KeystoneConfig(BaseModel):
    accounts: AccountsConfig
    universe: UniverseConfig
    investing: InvestingConfig
    risk: RiskConfig
    engines: EnginesConfig = Field(default_factory=EnginesConfig)
