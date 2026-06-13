"""Stage 11: alert triggers, severity, store round-trip, action wiring, intraday."""

from __future__ import annotations

from datetime import date

from alerts.alert_store import load_alerts, load_open_alerts, resolve_alert
from alerts.intraday import run_intraday_monitor
from alerts.monitor import run_eod_monitor, stage_suggested_action
from alerts.triggers import (
    PositionSnapshot,
    Severity,
    SuggestedAction,
    TriggerKind,
    evaluate,
)
from core.ib_client import IBClient, MockIB
from core.models import Action, Contract, Family, InstrumentClass, Leg, Right, Suggestion
from store.db import init_db


def kinds(triggers) -> set:
    return {t.kind for t in triggers}


# --------------------------------------------------------------------------- #
# Individual triggers + severity
# --------------------------------------------------------------------------- #
def test_profit_target_info():
    snap = PositionSnapshot("AAPL", "T1", entry_credit=1.0, current_mark=0.4)
    t = evaluate(snap)
    assert TriggerKind.PROFIT_TARGET in kinds(t)
    pt = next(x for x in t if x.kind is TriggerKind.PROFIT_TARGET)
    assert pt.severity is Severity.INFO
    assert pt.suggested_action is SuggestedAction.CLOSE


def test_stop_breached_and_approaching():
    breached = evaluate(PositionSnapshot("X", "T1", entry_credit=1.0, current_mark=2.1))
    assert TriggerKind.STOP_BREACHED in kinds(breached)
    assert next(t for t in breached if t.kind is TriggerKind.STOP_BREACHED).severity is Severity.CRITICAL

    approaching = evaluate(PositionSnapshot("X", "T1", entry_credit=1.0, current_mark=1.7))
    assert TriggerKind.APPROACHING_STOP in kinds(approaching)
    assert next(t for t in approaching if t.kind is TriggerKind.APPROACHING_STOP).severity is Severity.WARN


def test_short_strike_near_and_breached():
    near = evaluate(PositionSnapshot("X", "T1", short_right=Right.PUT, short_strike=95,
                                     underlying_price=96, atr20=2.0))
    assert TriggerKind.SHORT_STRIKE_NEAR in kinds(near)
    breached = evaluate(PositionSnapshot("X", "T1", short_right=Right.PUT, short_strike=95,
                                         underlying_price=94, atr20=2.0))
    assert TriggerKind.SHORT_STRIKE_BREACHED in kinds(breached)


def test_must_touch_by():
    assert TriggerKind.MUST_TOUCH_BY in kinds(evaluate(PositionSnapshot("X", "T1", dte=20)))
    assert TriggerKind.MUST_TOUCH_BY in kinds(evaluate(PositionSnapshot("X", "T1", dte=6, is_calendar=True)))
    assert TriggerKind.MUST_TOUCH_BY not in kinds(evaluate(PositionSnapshot("X", "T1", dte=30)))


def test_assignment_risk_call_and_put():
    call = evaluate(PositionSnapshot("X", "T1", dividend=0.50, short_call_itm=True,
                                     short_call_extrinsic=0.10))
    assert TriggerKind.ASSIGNMENT_IMMINENT in kinds(call)
    put = evaluate(PositionSnapshot("X", "T1", short_put_deep_itm=True, short_put_extrinsic=0.02))
    assert TriggerKind.ASSIGNMENT_IMMINENT in kinds(put)
    assert next(t for t in put if t.kind is TriggerKind.ASSIGNMENT_IMMINENT).severity is Severity.CRITICAL


def test_pin_risk():
    snap = PositionSnapshot("X", "T1", short_strike=100.5, underlying_price=100.0, atr20=2.0, dte=1)
    t = evaluate(snap)
    assert TriggerKind.PIN_RISK in kinds(t)
    assert next(x for x in t if x.kind is TriggerKind.PIN_RISK).severity is Severity.CRITICAL


def test_earnings_exposure():
    t = evaluate(PositionSnapshot("X", "T1", earnings_before_expiry=True))
    assert TriggerKind.EARNINGS_EXPOSURE in kinds(t)
    assert next(x for x in t if x.kind is TriggerKind.EARNINGS_EXPOSURE).severity is Severity.WARN


def test_clean_position_no_triggers():
    assert evaluate(PositionSnapshot("X", "T1", entry_credit=1.0, current_mark=0.9, dte=45)) == []


# --------------------------------------------------------------------------- #
# Monitor (regime flip + ordering + store)
# --------------------------------------------------------------------------- #
def test_regime_hard_skip_alert():
    alerts = run_eod_monitor([], market_hard_skip=True)
    assert len(alerts) == 1
    assert alerts[0].kind is TriggerKind.REGIME_HARD_SKIP
    assert alerts[0].severity is Severity.CRITICAL


def test_monitor_sorts_critical_first():
    snaps = [
        PositionSnapshot("INFO1", "T1", entry_credit=1.0, current_mark=0.4),  # INFO
        PositionSnapshot("CRIT1", "T1", entry_credit=1.0, current_mark=2.5),  # CRITICAL
    ]
    alerts = run_eod_monitor(snaps)
    assert alerts[0].severity is Severity.CRITICAL


def test_alert_store_round_trip():
    db = init_db(":memory:")
    run_eod_monitor([PositionSnapshot("AAPL", "T1", entry_credit=1.0, current_mark=0.4)], db=db)
    rows = load_alerts(db)
    assert len(rows) == 1
    assert rows[0]["kind"] == "profit_target"
    resolve_alert(db, rows[0]["id"], "closed for 60%")
    assert load_open_alerts(db) == []
    assert load_alerts(db)[0]["resolution"] == "closed for 60%"


# --------------------------------------------------------------------------- #
# Action wiring + intraday
# --------------------------------------------------------------------------- #
def _defensive_suggestion() -> Suggestion:
    return Suggestion(
        symbol="AAPL", account_id="T1", family=Family.PUT_CREDIT_SPREAD,
        legs=[
            Leg(contract=Contract.option("AAPL", date(2026, 7, 30), 92, Right.PUT), action=Action.BUY),
        ],
        instrument_class=InstrumentClass.US_EQUITY_OPT, max_loss=120.0,
    )


def test_suggested_action_wires_to_stage_to_tws():
    db = init_db(":memory:")
    client = IBClient(ib=MockIB())
    result = stage_suggested_action(client, _defensive_suggestion(), db=db)
    assert result.accepted is True
    assert result.staged_order.transmit is False
    assert len(db.query("SELECT * FROM whatif_results")) == 1


def test_intraday_inert_by_default():
    snap = PositionSnapshot("X", "T1", entry_credit=1.0, current_mark=0.4)
    assert run_intraday_monitor([snap], enabled=False) == []
    assert run_intraday_monitor([snap], enabled=True)  # delegates -> non-empty
