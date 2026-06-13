"""SQLite audit store: init + migrations + thin insert/query helpers.

Six tables form the audit/edge foundation:
  positions          open/closed positions
  entries            staged entries with full rationale (regime, greeks, sizing)
  alerts             every alert + its resolution
  screen_snapshots   weekly screened-universe snapshots
  whatif_results     whatIf margin/impact checks
  blocked_structures whatIf-rejected structures the ranker learns to skip

Migrations are tracked with ``PRAGMA user_version``; ``Database.init()`` applies
any not-yet-applied versions in order and is safe to call repeatedly.
Timestamps are stored as TEXT ISO-8601 strings (America/New_York in app code);
audit columns default to ``datetime('now')`` (UTC) when omitted.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional, Union

#: Tables Keystone owns. ``insert`` only accepts these (defensive allowlist).
TABLES: tuple[str, ...] = (
    "positions",
    "entries",
    "alerts",
    "screen_snapshots",
    "whatif_results",
    "blocked_structures",
)

SCHEMA_VERSION = 1

# Each migration version maps to a list of statements applied in order.
_MIGRATIONS: dict[int, list[str]] = {
    1: [
        """
        CREATE TABLE IF NOT EXISTS positions (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id         TEXT    NOT NULL,
            symbol             TEXT    NOT NULL,
            family             TEXT    NOT NULL,
            instrument_class   TEXT    NOT NULL,
            multi_expiry       INTEGER NOT NULL DEFAULT 0,
            legs_json          TEXT,
            entry_greeks_json  TEXT,
            entry_price        REAL,
            max_loss           REAL,
            opened_at          TEXT,
            closed_at          TEXT,
            status             TEXT    NOT NULL DEFAULT 'OPEN',
            rationale          TEXT,
            created_at         TEXT    NOT NULL DEFAULT (datetime('now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS entries (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id         INTEGER REFERENCES positions(id),
            account_id          TEXT    NOT NULL,
            symbol              TEXT    NOT NULL,
            family              TEXT    NOT NULL,
            suggestion_json     TEXT,
            regime_json         TEXT,
            screen_snapshot_id  INTEGER REFERENCES screen_snapshots(id),
            staged_at           TEXT,
            created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS alerts (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id       INTEGER REFERENCES positions(id),
            severity          TEXT    NOT NULL,
            kind              TEXT    NOT NULL,
            message           TEXT,
            suggested_action  TEXT,
            payload_json      TEXT,
            created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
            resolved_at       TEXT,
            resolution        TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS screen_snapshots (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            generated_at  TEXT    NOT NULL,
            payload_json  TEXT,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS whatif_results (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id       TEXT,
            symbol           TEXT,
            family           TEXT,
            signature        TEXT,
            init_margin      REAL,
            maint_margin     REAL,
            equity_with_loan REAL,
            accepted         INTEGER NOT NULL DEFAULT 0,
            raw_json         TEXT,
            created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS blocked_structures (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            signature   TEXT    NOT NULL UNIQUE,
            account_id  TEXT,
            symbol      TEXT,
            family      TEXT,
            reason      TEXT,
            raw_json    TEXT,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        )
        """,
    ],
}


class Database:
    """Thin sqlite wrapper. Pass ``:memory:`` (default) for tests."""

    def __init__(self, path: Union[str, Path] = ":memory:") -> None:
        self.path = str(path)
        self.conn: Optional[sqlite3.Connection] = None

    # --- lifecycle -------------------------------------------------------- #
    def connect(self) -> sqlite3.Connection:
        if self.conn is None:
            self.conn = sqlite3.connect(self.path)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")
        return self.conn

    def init(self) -> "Database":
        """Apply any pending migrations. Safe to call repeatedly."""

        conn = self.connect()
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        for version in sorted(_MIGRATIONS):
            if version > current:
                for statement in _MIGRATIONS[version]:
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {version}")
        conn.commit()
        return self

    @property
    def schema_version(self) -> int:
        return self.connect().execute("PRAGMA user_version").fetchone()[0]

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def __enter__(self) -> "Database":
        return self.init()

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    # --- helpers ---------------------------------------------------------- #
    def insert(self, table: str, **columns: Any) -> int:
        """Insert a row; returns the new rowid. ``table`` must be a known table."""

        if table not in TABLES:
            raise ValueError(f"unknown table: {table!r}")
        conn = self.connect()
        keys = ", ".join(columns)
        placeholders = ", ".join("?" for _ in columns)
        cur = conn.execute(
            f"INSERT INTO {table} ({keys}) VALUES ({placeholders})",
            tuple(columns.values()),
        )
        conn.commit()
        return int(cur.lastrowid)

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        return self.connect().execute(sql, tuple(params)).fetchall()

    def get(self, table: str, row_id: int) -> Optional[sqlite3.Row]:
        if table not in TABLES:
            raise ValueError(f"unknown table: {table!r}")
        rows = self.query(f"SELECT * FROM {table} WHERE id = ?", (row_id,))
        return rows[0] if rows else None


def init_db(path: Union[str, Path] = ":memory:") -> Database:
    """Convenience: create + migrate a Database in one call."""

    return Database(path).init()
