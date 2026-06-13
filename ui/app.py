"""Minimal Flask shell for Keystone.

Stage 0 ships a health route and empty panel stubs; the real panels are wired in
Stage 12 (weekly checkpoint dashboard, open book, alerts queue, SMSF view,
stress panel). Use the ``create_app`` factory so tests can spin up a client
without a live server.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from flask import Flask, jsonify

NY = ZoneInfo("America/New_York")

#: (route, slug, title, Stage-12 description) for the five planned panels.
_PANELS: list[tuple[str, str, str, str]] = [
    ("/", "dashboard", "Weekly Checkpoint",
     "Market + per-stock regime read, screened universe, candidate cards per account/sleeve."),
    ("/book", "book", "Open Book",
     "Positions across accounts — greeks, P&L, DTE."),
    ("/alerts", "alerts", "Alerts Queue",
     "Severity-sorted alerts with suggested action, OptionStrat link, stage-to-TWS button."),
    ("/smsf", "smsf", "SMSF View",
     "Core holdings vs target weights, wheel state, active collars."),
    ("/stress", "stress", "Stress Panel",
     "Beta-mapped market row + worst-single-name row."),
]


def _page(title: str, body: str) -> str:
    nav = " · ".join(f'<a href="{route}">{t}</a>' for route, _slug, t, _d in _PANELS)
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>Keystone — {title}</title></head><body>"
        "<h1>Keystone</h1>"
        f"<nav>{nav}</nav><hr>"
        f"<h2>{title}</h2>{body}"
        "</body></html>"
    )


def create_app(config: Optional[dict[str, Any]] = None) -> Flask:
    """Application factory. ``config`` is merged into ``app.config`` if given."""

    app = Flask(__name__)
    if config:
        app.config.update(config)

    @app.get("/health")
    def health() -> Any:
        return jsonify(
            status="ok",
            app="keystone",
            stage=0,
            time=datetime.now(NY).isoformat(),
            timezone="America/New_York",
        )

    def _make_panel(slug: str, title: str, desc: str):
        def view() -> str:
            return _page(
                title,
                f"<p>{desc}</p><p><em>Panel stub — implemented in Stage 12.</em></p>",
            )

        view.__name__ = f"panel_{slug}"
        return view

    for route, slug, title, desc in _PANELS:
        app.add_url_rule(route, endpoint=f"panel_{slug}", view_func=_make_panel(slug, title, desc))

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=True)
