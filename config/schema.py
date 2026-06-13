"""Pydantic schemas for the four Keystone config files.

Every field carries a sensible default so a sparse YAML still validates; the
only hard requirement is that ``accounts.yaml`` lists at least one account.
Real values are filled by the user — the shipped YAMLs are documented
placeholders. Budget/stress numbers are expressed *per $100k NLV* unless noted.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


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


class IndexBookIngestCfg(BaseModel):
    enabled: bool = False  # optional, off by default (Stage 8)
    source: Optional[str] = None


class RiskConfig(BaseModel):
    trading: TradingBudgetCfg = Field(default_factory=TradingBudgetCfg)
    smsf: SMSFBudgetCfg = Field(default_factory=SMSFBudgetCfg)
    stress: StressCfg = Field(default_factory=StressCfg)
    index_book_ingest: IndexBookIngestCfg = Field(default_factory=IndexBookIngestCfg)


# --------------------------------------------------------------------------- #
# Aggregate
# --------------------------------------------------------------------------- #
class KeystoneConfig(BaseModel):
    accounts: AccountsConfig
    universe: UniverseConfig
    investing: InvestingConfig
    risk: RiskConfig
