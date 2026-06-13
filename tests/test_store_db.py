"""SQLite store: init/migrations + a round-trip insert for every table."""

from __future__ import annotations

import sqlite3

import pytest

from store.db import TABLES, Database, init_db


def test_init_sets_schema_version_and_is_idempotent():
    db = init_db(":memory:")
    assert db.schema_version == 1
    db.init()  # second call applies nothing
    assert db.schema_version == 1


def test_all_tables_exist():
    db = init_db(":memory:")
    names = {
        r["name"]
        for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")
    }
    for table in TABLES:
        assert table in names


def test_round_trip_positions():
    db = init_db(":memory:")
    rid = db.insert(
        "positions",
        account_id="A1",
        symbol="AAPL",
        family="put_credit_spread",
        instrument_class="US_EQUITY_OPT",
        multi_expiry=0,
        entry_price=1.25,
        max_loss=375.0,
        status="OPEN",
    )
    row = db.get("positions", rid)
    assert row["symbol"] == "AAPL"
    assert row["family"] == "put_credit_spread"
    assert row["max_loss"] == 375.0
    assert row["status"] == "OPEN"
    assert row["created_at"] is not None  # default applied


def test_round_trip_entries():
    db = init_db(":memory:")
    rid = db.insert(
        "entries",
        account_id="A1",
        symbol="MSFT",
        family="iron_condor",
        suggestion_json="{}",
    )
    assert db.get("entries", rid)["symbol"] == "MSFT"


def test_round_trip_alerts():
    db = init_db(":memory:")
    rid = db.insert(
        "alerts",
        severity="CRITICAL",
        kind="short_strike_breached",
        message="short strike breached",
        suggested_action="defend",
    )
    row = db.get("alerts", rid)
    assert row["severity"] == "CRITICAL"
    assert row["suggested_action"] == "defend"


def test_round_trip_screen_snapshots():
    db = init_db(":memory:")
    rid = db.insert(
        "screen_snapshots",
        generated_at="2026-06-12T16:00:00-04:00",
        payload_json='{"AAPL": {"passed": true}}',
    )
    assert db.get("screen_snapshots", rid)["generated_at"].startswith("2026-06-12")


def test_round_trip_whatif_results():
    db = init_db(":memory:")
    rid = db.insert(
        "whatif_results",
        account_id="A1",
        symbol="SPY",
        family="iron_condor",
        signature="sig-1",
        init_margin=1200.0,
        accepted=1,
    )
    row = db.get("whatif_results", rid)
    assert row["accepted"] == 1
    assert row["init_margin"] == 1200.0


def test_round_trip_blocked_structures():
    db = init_db(":memory:")
    rid = db.insert(
        "blocked_structures",
        signature="acct|AAPL|iron_condor|...",
        account_id="A1",
        symbol="AAPL",
        family="iron_condor",
        reason="whatIf rejected: insufficient margin",
    )
    assert db.get("blocked_structures", rid)["reason"].startswith("whatIf rejected")


def test_blocked_structures_signature_is_unique():
    db = init_db(":memory:")
    db.insert("blocked_structures", signature="dup")
    with pytest.raises(sqlite3.IntegrityError):
        db.insert("blocked_structures", signature="dup")


def test_insert_unknown_table_rejected():
    db = init_db(":memory:")
    with pytest.raises(ValueError):
        db.insert("not_a_table", foo="bar")


def test_context_manager_inits_and_closes():
    with Database(":memory:") as db:
        assert db.schema_version == 1
        db.insert("alerts", severity="INFO", kind="profit_target")
