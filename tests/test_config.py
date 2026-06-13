"""Config load/validate tests (shipped placeholders + fallback to defaults)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from config.loader import load_config
from config.schema import AccountsConfig, RiskConfig, UniverseConfig
from portfolio.account_profiles import Pool, from_config
from core.models import InstrumentClass


def test_shipped_config_loads_and_validates():
    cfg = load_config()  # the real config/*.yaml placeholders
    # Default topology: 3 trading + 1 investing.
    assert len(cfg.accounts.accounts) == 4
    pools = [a.pool for a in cfg.accounts.accounts]
    assert pools.count("trading") == 3
    assert pools.count("investing") == 1

    smsf = next(a for a in cfg.accounts.accounts if a.pool == "investing")
    assert len(smsf.blocked_rules) == 1
    rule = smsf.blocked_rules[0]
    assert rule.instrument_class == "EU_CASH_INDEX"
    assert rule.multi_expiry is True

    # Universe / investing / risk placeholders carry sane values.
    assert cfg.universe.gates.min_last_price == 30.0
    assert cfg.universe.screened_max_age_days == 7
    assert cfg.investing.pmcc_enabled is False
    assert len(cfg.investing.target_holdings) > 0
    assert cfg.risk.trading.max_loss_per_position_pct == 1.0
    assert cfg.risk.smsf.assignment_notional_single_pct == 12.0
    assert cfg.risk.stress.market_spot_shock == pytest.approx(-0.05)


def test_from_config_builds_profiles():
    cfg = load_config()
    profiles = from_config(cfg.accounts)
    assert len(profiles) == 4
    smsf = next(p for p in profiles if p.pool is Pool.INVESTING)
    assert smsf.is_blocked(InstrumentClass.EU_CASH_INDEX, multi_expiry=True) is True
    assert smsf.is_blocked(InstrumentClass.EU_CASH_INDEX, multi_expiry=False) is False
    trading = [p for p in profiles if p.pool is Pool.TRADING]
    assert len(trading) == 3
    assert all(not t.blocked_rules for t in trading)


def test_accounts_config_requires_accounts():
    with pytest.raises(ValidationError):
        AccountsConfig()  # missing required `accounts`


def test_loaders_fall_back_to_defaults(tmp_path):
    # Only accounts.yaml present; the other three fall back to schema defaults.
    (tmp_path / "accounts.yaml").write_text(
        "accounts:\n"
        "  - account_id: A1\n"
        "    label: Solo\n"
        "    pool: trading\n",
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    assert len(cfg.accounts.accounts) == 1
    assert isinstance(cfg.universe, UniverseConfig)
    assert isinstance(cfg.risk, RiskConfig)
    assert cfg.universe.gates.min_option_adv == 5000
    assert cfg.investing.target_holdings == []


def test_invalid_pool_rejected():
    with pytest.raises(ValidationError):
        AccountsConfig(accounts=[{"account_id": "X", "label": "X", "pool": "nonsense"}])
