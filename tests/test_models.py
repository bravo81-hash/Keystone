"""Core model behaviour: contract factories, multi-expiry, suggestion signature."""

from __future__ import annotations

from datetime import date

from core.models import (
    Action,
    Contract,
    Family,
    InstrumentClass,
    Leg,
    Right,
    SecType,
    Suggestion,
    legs_span_multiple_expiries,
)


def test_contract_factories():
    stk = Contract.stock("AAPL")
    assert stk.sec_type is SecType.STK and stk.right is None

    opt = Contract.option("AAPL", date(2026, 7, 17), 200.0, Right.PUT)
    assert opt.sec_type is SecType.OPT
    assert opt.right is Right.PUT
    assert opt.strike == 200.0
    assert opt.multiplier == 100


def _spread_legs(short_expiry: date, long_expiry: date) -> list[Leg]:
    return [
        Leg(contract=Contract.option("AAPL", short_expiry, 190.0, Right.PUT), action=Action.SELL),
        Leg(contract=Contract.option("AAPL", long_expiry, 185.0, Right.PUT), action=Action.BUY),
    ]


def test_multi_expiry_detection():
    same = _spread_legs(date(2026, 7, 17), date(2026, 7, 17))
    assert legs_span_multiple_expiries(same) is False
    diff = _spread_legs(date(2026, 7, 17), date(2026, 8, 21))
    assert legs_span_multiple_expiries(diff) is True


def test_suggestion_signature_is_stable_and_distinct():
    legs = _spread_legs(date(2026, 7, 17), date(2026, 7, 17))
    s = Suggestion(
        symbol="AAPL",
        account_id="A1",
        family=Family.PUT_CREDIT_SPREAD,
        legs=legs,
        instrument_class=InstrumentClass.US_EQUITY_OPT,
        dte=33,
        max_loss=375.0,
    )
    sig = s.signature()
    assert sig == s.signature()  # stable
    assert "AAPL" in sig and "put_credit_spread" in sig

    other = s.model_copy(update={"account_id": "A2"})
    assert other.signature() != sig


def test_enum_string_values_serialize():
    assert Right.CALL.value == "C"
    assert InstrumentClass.EU_CASH_INDEX.value == "EU_CASH_INDEX"
    assert Family.WHEEL_CSP.value == "wheel_csp"
    s = Suggestion(
        symbol="SPY",
        account_id="A1",
        family=Family.IRON_CONDOR,
        legs=[],
        instrument_class=InstrumentClass.US_ETF_OPT,
    )
    dumped = s.model_dump(mode="json")
    assert dumped["family"] == "iron_condor"
    assert dumped["instrument_class"] == "US_ETF_OPT"
