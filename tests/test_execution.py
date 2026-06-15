"""Stage 10: N-leg combo, whatIf (transmit=False), walk-in, OptionStrat, stage."""

from __future__ import annotations

from datetime import date

import pytest

from core.ib_client import IBClient, MockIB
from core.models import Action, Contract, Family, InstrumentClass, Leg, Right, Suggestion
from execution.mid_walk_in import build_walk_in, walk_in_prices
from execution.n_leg_combo import build_combo
from execution.optionstrat_links import optionstrat_url
from execution.stage import stage_to_tws
from execution.whatif import run_whatif
from store.db import init_db

EXP = date(2026, 7, 30)


def _credit_spread() -> Suggestion:
    return Suggestion(
        symbol="AAPL", account_id="T1", family=Family.PUT_CREDIT_SPREAD,
        legs=[
            Leg(contract=Contract.option("AAPL", EXP, 92, Right.PUT), action=Action.SELL),
            Leg(contract=Contract.option("AAPL", EXP, 87, Right.PUT), action=Action.BUY),
        ],
        instrument_class=InstrumentClass.US_EQUITY_OPT, max_loss=440.0,
        management={"credit": 0.60},
    )


def _leaps() -> Suggestion:
    return Suggestion(
        symbol="MSFT", account_id="T1", family=Family.TREND_LEAPS,
        legs=[Leg(contract=Contract.option("MSFT", EXP, 80, Right.CALL), action=Action.BUY)],
        instrument_class=InstrumentClass.US_EQUITY_OPT, max_loss=2400.0,
    )


def _iron_condor() -> Suggestion:
    return Suggestion(
        symbol="AAPL", account_id="T1", family=Family.IRON_CONDOR,
        legs=[
            Leg(contract=Contract.option("AAPL", EXP, 92, Right.PUT), action=Action.SELL),
            Leg(contract=Contract.option("AAPL", EXP, 87, Right.PUT), action=Action.BUY),
            Leg(contract=Contract.option("AAPL", EXP, 108, Right.CALL), action=Action.SELL),
            Leg(contract=Contract.option("AAPL", EXP, 113, Right.CALL), action=Action.BUY),
        ],
        instrument_class=InstrumentClass.US_EQUITY_OPT, max_loss=380.0,
        management={"credit": 1.20},
    )


# --------------------------------------------------------------------------- #
# Combo assembly
# --------------------------------------------------------------------------- #
def test_credit_spread_combo():
    order = build_combo(_credit_spread())
    assert len(order.combo_legs) == 2
    assert order.action == "SELL"  # net credit
    assert order.limit_price == pytest.approx(0.60)
    assert order.transmit is False


def test_leaps_combo_is_debit():
    order = build_combo(_leaps())
    assert len(order.combo_legs) == 1
    assert order.action == "BUY"  # net debit
    assert order.limit_price == pytest.approx(24.0)  # 2400 / 100
    assert order.transmit is False


def test_iron_condor_combo_four_legs():
    order = build_combo(_iron_condor())
    assert len(order.combo_legs) == 4
    assert order.action == "SELL"
    assert order.transmit is False


def test_transmit_false_on_every_path():
    for sugg in (_credit_spread(), _leaps(), _iron_condor()):
        order = build_combo(sugg)
        assert order.transmit is False
        assert order.order_stub()["transmit"] is False


def test_order_ref_identifies_keystone_lots():
    # Every staged order carries KS:<account>:<family>:<sig> so its fills are
    # identifiable in TWS and reconcilable back to a Keystone entry.
    from execution.n_leg_combo import keystone_order_ref

    sugg = _credit_spread()
    ref = keystone_order_ref(sugg)
    assert ref.startswith("KS:T1:put_credit_spread:")
    assert ref.endswith(sugg.signature())
    assert len(ref) <= 128

    order = build_combo(sugg)
    assert order.order_ref == ref
    assert order.order_stub()["orderRef"] == ref


# --------------------------------------------------------------------------- #
# whatIf
# --------------------------------------------------------------------------- #
def test_whatif_accept_records_result():
    db = init_db(":memory:")
    client = IBClient(ib=MockIB())  # default accepts
    res = run_whatif(client, build_combo(_credit_spread()), _credit_spread(), db=db)
    assert res.accepted is True
    rows = db.query("SELECT accepted FROM whatif_results")
    assert len(rows) == 1 and rows[0]["accepted"] == 1
    assert db.query("SELECT * FROM blocked_structures") == []


def test_whatif_reject_writes_blocked_structure():
    db = init_db(":memory:")
    client = IBClient(ib=MockIB(whatif={"AAPL": {"accepted": False, "reason": "insufficient margin"}}))
    sugg = _credit_spread()
    res = run_whatif(client, build_combo(sugg), sugg, db=db)
    assert res.accepted is False
    blocked = db.query("SELECT signature, reason FROM blocked_structures")
    assert len(blocked) == 1
    assert blocked[0]["signature"] == sugg.signature()
    assert "whatIf rejected" in blocked[0]["reason"]


# --------------------------------------------------------------------------- #
# Walk-in repricing bounds
# --------------------------------------------------------------------------- #
def test_walk_in_bounds_debit():
    prices = walk_in_prices(1.00, 1.50, max_reprices=3)
    assert len(prices) == 4
    assert prices[0] == pytest.approx(1.00) and prices[-1] == pytest.approx(1.50)
    assert prices == sorted(prices)  # monotonic toward marketable
    assert all(1.00 <= p <= 1.50 for p in prices)  # never overshoots


def test_walk_in_bounds_credit():
    prices = walk_in_prices(0.60, 0.50, max_reprices=2)
    assert prices[0] == pytest.approx(0.60) and prices[-1] == pytest.approx(0.50)
    assert all(0.50 <= p <= 0.60 for p in prices)


def test_walk_in_no_reprices_and_never_moc():
    assert walk_in_prices(1.0, 1.5, max_reprices=0) == [1.0]
    plan = build_walk_in(1.0, 1.5)
    assert plan.never_moc is True
    assert plan.tif == "DAY"


# --------------------------------------------------------------------------- #
# OptionStrat URL
# --------------------------------------------------------------------------- #
def test_optionstrat_url():
    url = optionstrat_url(_credit_spread())
    assert url == "https://optionstrat.com/build/custom/AAPL/-.AAPL260730P92,.AAPL260730P87"


# --------------------------------------------------------------------------- #
# stage_to_tws
# --------------------------------------------------------------------------- #
def test_stage_to_tws_end_to_end():
    db = init_db(":memory:")
    client = IBClient(ib=MockIB())
    result = stage_to_tws(client, _credit_spread(), db=db)
    assert result.accepted is True
    assert result.staged_order.transmit is False
    assert result.optionstrat_url.startswith("https://optionstrat.com/build/")
    assert len(db.query("SELECT * FROM whatif_results")) == 1
