"""Persist alerts + resolutions to the store (the edge audit foundation)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


def save_alert(db: Any, alert: Any) -> int:
    """Insert an Alert (from alerts.monitor) and return its rowid."""

    return db.insert(
        "alerts",
        position_id=alert.position_id,
        severity=alert.severity.value,
        kind=alert.kind.value,
        message=alert.message,
        suggested_action=alert.suggested_action.value,
        payload_json=json.dumps(alert.payload),
    )


def resolve_alert(db: Any, alert_id: int, resolution: str, *, when: Optional[datetime] = None) -> None:
    conn = db.connect()
    ts = (when or datetime.now(NY)).isoformat()
    conn.execute(
        "UPDATE alerts SET resolved_at = ?, resolution = ? WHERE id = ?",
        (ts, resolution, alert_id),
    )
    conn.commit()


def load_open_alerts(db: Any) -> list:
    return db.query("SELECT * FROM alerts WHERE resolved_at IS NULL ORDER BY id")


def load_alerts(db: Any) -> list:
    return db.query("SELECT * FROM alerts ORDER BY id")
