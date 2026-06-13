"""classify() across instrument classes + SMSF blocked-rule behaviour."""

from __future__ import annotations

import pytest

from core.models import Contract, InstrumentClass, SecType
from portfolio.account_profiles import (
    BlockedRule,
    Pool,
    classify,
    default_topology,
)


@pytest.mark.parametrize(
    "symbol, sec_type, expected",
    [
        ("SPX", SecType.OPT, InstrumentClass.EU_CASH_INDEX),
        ("RUT", SecType.OPT, InstrumentClass.EU_CASH_INDEX),
        ("NDX", SecType.OPT, InstrumentClass.EU_CASH_INDEX),
        ("XSP", SecType.OPT, InstrumentClass.EU_CASH_INDEX),
        ("SPY", SecType.OPT, InstrumentClass.US_ETF_OPT),
        ("QQQ", SecType.OPT, InstrumentClass.US_ETF_OPT),
        ("XLE", SecType.OPT, InstrumentClass.US_ETF_OPT),
        ("AAPL", SecType.OPT, InstrumentClass.US_EQUITY_OPT),
        ("PLTR", SecType.OPT, InstrumentClass.US_EQUITY_OPT),
        ("ES", SecType.FOP, InstrumentClass.FUT_OPT),
        ("ES", SecType.FUT, InstrumentClass.FUT_OPT),
    ],
)
def test_classify(symbol, sec_type, expected):
    assert classify(Contract(symbol=symbol, sec_type=sec_type)) == expected


def test_classify_is_case_insensitive():
    assert classify(Contract(symbol="spx", sec_type=SecType.OPT)) == InstrumentClass.EU_CASH_INDEX
    assert classify(Contract(symbol="spy", sec_type=SecType.OPT)) == InstrumentClass.US_ETF_OPT


def test_smsf_profile_blocks_eu_cash_index_multi_expiry():
    smsf = next(p for p in default_topology() if p.pool is Pool.INVESTING)
    # Blocked: multi-expiry on EU cash index.
    assert smsf.is_blocked(InstrumentClass.EU_CASH_INDEX, multi_expiry=True) is True
    # Allowed: single-expiry EU cash index (e.g. a same-expiry vertical).
    assert smsf.is_blocked(InstrumentClass.EU_CASH_INDEX, multi_expiry=False) is False
    # Allowed: American-style instruments, multi-expiry or not.
    assert smsf.is_blocked(InstrumentClass.US_EQUITY_OPT, multi_expiry=True) is False
    assert smsf.is_blocked(InstrumentClass.US_ETF_OPT, multi_expiry=True) is False
    assert smsf.is_blocked(InstrumentClass.FUT_OPT, multi_expiry=True) is False


def test_trading_profiles_block_nothing():
    for p in default_topology():
        if p.pool is Pool.TRADING:
            assert p.is_blocked(InstrumentClass.EU_CASH_INDEX, multi_expiry=True) is False
            assert p.is_blocked(InstrumentClass.US_EQUITY_OPT, multi_expiry=False) is False


def test_blocked_rule_matching_semantics():
    # multi_expiry=None matches any candidate.
    any_rule = BlockedRule(InstrumentClass.EU_CASH_INDEX, multi_expiry=None)
    assert any_rule.matches(InstrumentClass.EU_CASH_INDEX, True) is True
    assert any_rule.matches(InstrumentClass.EU_CASH_INDEX, False) is True
    # Different instrument class never matches.
    assert any_rule.matches(InstrumentClass.US_EQUITY_OPT, True) is False


def test_default_topology_shape():
    profiles = default_topology()
    assert len(profiles) == 4
    assert sum(p.pool is Pool.TRADING for p in profiles) == 3
    assert sum(p.pool is Pool.INVESTING for p in profiles) == 1
