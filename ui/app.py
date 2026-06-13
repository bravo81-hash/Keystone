"""Flask shell + the five Keystone panels (Stage 12).

Panels render from an injected :class:`ui.state.AppState` (tests pass a fixture;
a live build assembles one from the weekly/EOD pipeline). The app factory keeps
the panels server-free for testing via the Flask test client.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any, Optional
from zoneinfo import ZoneInfo

from flask import Flask, jsonify

from ui.state import AppState

NY = ZoneInfo("America/New_York")

_PANELS = [
    ("/", "dashboard", "Weekly Checkpoint"),
    ("/book", "book", "Open Book"),
    ("/alerts", "alerts", "Alerts Queue"),
    ("/smsf", "smsf", "SMSF View"),
    ("/stress", "stress", "Stress Panel"),
]


def _page(title: str, body: str) -> str:
    nav = " · ".join(f'<a href="{r}">{t}</a>' for r, _s, t in _PANELS)
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>Keystone — {escape(title)}</title></head><body>"
        f"<h1>Keystone</h1><nav>{nav}</nav><hr><h2>{escape(title)}</h2>{body}"
        "</body></html>"
    )


def _fmt(x: Any) -> str:
    return escape(str(x))


# --------------------------------------------------------------------------- #
# Panel renderers
# --------------------------------------------------------------------------- #
def render_dashboard(state: AppState) -> str:
    out = []
    if state.market_regime is not None:
        m = state.market_regime
        out.append(f"<p><b>Market regime:</b> {_fmt(m.state.value)} (score {_fmt(round(m.score, 2))})</p>")
    else:
        out.append("<p><b>Market regime:</b> n/a</p>")

    out.append("<h3>Screened universe</h3>")
    if state.screened:
        rows = "".join(
            f"<tr><td>{_fmt(t)}</td><td>{_fmt(e.get('passed'))}</td>"
            f"<td>{_fmt(e.get('tier'))}</td><td>{_fmt(e.get('sector'))}</td></tr>"
            for t, e in state.screened.items()
        )
        out.append(f"<table border=1><tr><th>ticker</th><th>passed</th><th>tier</th><th>sector</th></tr>{rows}</table>")
    else:
        out.append("<p>no screened universe</p>")

    out.append("<h3>Candidate cards</h3>")
    if state.cards:
        for account_id, cards in state.cards.items():
            label = state.account_labels.get(account_id, account_id)
            out.append(f"<h4>{_fmt(label)} ({_fmt(account_id)})</h4>")
            if not cards:
                out.append("<p>no cards</p>")
                continue
            items = "".join(
                f"<li>{_fmt(c.family.value)} — score {_fmt(c.score)} — {_fmt(c.rationale)}</li>"
                for c in cards
            )
            out.append(f"<ul>{items}</ul>")
    else:
        out.append("<p>no candidates</p>")
    return _page("Weekly Checkpoint", "".join(out))


def render_book(state: AppState) -> str:
    if not state.book:
        return _page("Open Book", "<p>no open positions</p>")
    rows = "".join(
        f"<tr><td>{_fmt(p.get('account_id'))}</td><td>{_fmt(p.get('symbol'))}</td>"
        f"<td>{_fmt(p.get('family'))}</td><td>{_fmt(p.get('dte'))}</td>"
        f"<td>{_fmt(p.get('delta'))}</td><td>{_fmt(p.get('pnl'))}</td></tr>"
        for p in state.book
    )
    table = (
        "<table border=1><tr><th>account</th><th>symbol</th><th>family</th>"
        f"<th>DTE</th><th>delta</th><th>P&amp;L</th></tr>{rows}</table>"
    )
    return _page("Open Book", table)


def render_alerts(state: AppState) -> str:
    if not state.alerts:
        return _page("Alerts Queue", "<p>no alerts</p>")
    rows = []
    for a in state.alerts:
        sev = a.severity.value if hasattr(a.severity, "value") else str(a.severity)
        url = state.optionstrat_urls.get(a.symbol, "")
        link = f'<a href="{escape(url)}">OptionStrat</a>' if url else ""
        button = f'<button name="stage" value="{_fmt(a.symbol)}">Stage to TWS</button>'
        rows.append(
            f"<tr><td>{_fmt(sev)}</td><td>{_fmt(a.symbol)}</td><td>{_fmt(a.kind.value)}</td>"
            f"<td>{_fmt(a.message)}</td><td>{_fmt(a.suggested_action.value)}</td>"
            f"<td>{link}</td><td>{button}</td></tr>"
        )
    table = (
        "<table border=1><tr><th>severity</th><th>symbol</th><th>kind</th><th>message</th>"
        f"<th>action</th><th>link</th><th></th></tr>{''.join(rows)}</table>"
    )
    return _page("Alerts Queue", table)


def render_smsf(state: AppState) -> str:
    out = ["<h3>Core holdings vs target weights</h3>"]
    if state.smsf_holdings:
        rows = "".join(
            f"<tr><td>{_fmt(h.get('ticker'))}</td><td>{_fmt(h.get('target_weight'))}</td>"
            f"<td>{_fmt(h.get('current_weight'))}</td><td>{_fmt(h.get('wheel_state'))}</td></tr>"
            for h in state.smsf_holdings
        )
        out.append(f"<table border=1><tr><th>ticker</th><th>target</th><th>current</th><th>wheel</th></tr>{rows}</table>")
    else:
        out.append("<p>no holdings configured</p>")
    out.append("<h3>Active collars</h3>")
    if state.collars:
        out.append("<ul>" + "".join(f"<li>{_fmt(c.get('ticker'))}: {_fmt(c.get('detail'))}</li>" for c in state.collars) + "</ul>")
    else:
        out.append("<p>no active collars</p>")
    return _page("SMSF View", "".join(out))


def render_stress(state: AppState) -> str:
    if state.stress is None:
        return _page("Stress Panel", "<p>no stress run</p>")
    s = state.stress
    body = (
        "<table border=1><tr><th>row</th><th>P&amp;L</th></tr>"
        f"<tr><td>beta-mapped market (-5% / IV+10)</td><td>{_fmt(round(s.market_pnl, 2))}</td></tr>"
        f"<tr><td>worst name: {_fmt(s.worst_name)}</td><td>{_fmt(round(s.worst_name_pnl, 2))}</td></tr>"
        "</table>"
    )
    if s.ceiling is not None:
        body += f"<p>ceiling ${_fmt(s.ceiling)} — market within: {_fmt(s.market_within_ceiling)}, worst within: {_fmt(s.worst_within_ceiling)}</p>"
    return _page("Stress Panel", body)


_RENDERERS = {
    "dashboard": render_dashboard,
    "book": render_book,
    "alerts": render_alerts,
    "smsf": render_smsf,
    "stress": render_stress,
}


def create_app(config: Optional[dict[str, Any]] = None, state: Optional[AppState] = None) -> Flask:
    """Application factory. ``state`` is the AppState the panels render."""

    app = Flask(__name__)
    if config:
        app.config.update(config)
    app.config["KEYSTONE_STATE"] = state if state is not None else AppState()

    @app.get("/health")
    def health() -> Any:
        return jsonify(
            status="ok", app="keystone", stage=12,
            time=datetime.now(NY).isoformat(), timezone="America/New_York",
        )

    def _make_view(slug: str):
        def view() -> str:
            return _RENDERERS[slug](app.config["KEYSTONE_STATE"])

        view.__name__ = f"panel_{slug}"
        return view

    for route, slug, _title in _PANELS:
        app.add_url_rule(route, endpoint=f"panel_{slug}", view_func=_make_view(slug))

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=True)
