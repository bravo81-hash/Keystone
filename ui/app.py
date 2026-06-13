"""Flask shell + the five Keystone panels, a built-in Guide, and mock mode.

Dark, readable theme. Panels render from an injected :class:`ui.state.AppState`;
in **mock mode** (default) a populated demo state is generated so the whole UI
can be explored without TWS. Switch to **live** from the status bar.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any, Optional
from zoneinfo import ZoneInfo

from flask import Flask, current_app, jsonify, redirect, request

from core import settings as ksettings
from ui import guide as kguide
from ui.state import AppState

NY = ZoneInfo("America/New_York")

_PANELS = [
    ("/", "dashboard", "Weekly Checkpoint"),
    ("/book", "book", "Open Book"),
    ("/alerts", "alerts", "Alerts Queue"),
    ("/smsf", "smsf", "SMSF View"),
    ("/stress", "stress", "Stress Panel"),
    ("/guide", "guide", "Guide"),
]

_CSS = """
:root{--bg:#0d1117;--panel:#161b22;--panel2:#1c2330;--border:#30363d;--text:#e6edf3;
--muted:#9aa7b4;--accent:#58a6ff;--ok:#3fb950;--warn:#d29922;--crit:#f85149}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.55 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
.container{max-width:1140px;margin:0 auto;padding:22px 20px 60px}
h1{font-size:1.5rem;margin:0;color:#fff;letter-spacing:.4px}
h2{font-size:1.15rem;color:var(--accent);border-bottom:1px solid var(--border);
padding-bottom:6px;margin:22px 0 6px}
h3{color:var(--muted);font-size:.82rem;letter-spacing:.06em;text-transform:uppercase;margin:20px 0 6px}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
p{margin:8px 0}
.statusbar{background:var(--panel);border:1px solid var(--border);border-radius:8px;
padding:9px 13px;margin:12px 0;font-size:.9rem;color:var(--muted);
display:flex;gap:8px 16px;flex-wrap:wrap;align-items:center}
.statusbar b{color:var(--text)}
.nav{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0 4px}
.nav a{padding:6px 11px;border-radius:7px;background:var(--panel);border:1px solid var(--border)}
.nav a:hover{background:var(--panel2);text-decoration:none}
hr{border:none;border-top:1px solid var(--border);margin:14px 0}
table{width:100%;border-collapse:collapse;margin:10px 0;background:var(--panel);
border:1px solid var(--border);border-radius:8px;overflow:hidden;font-size:.92rem}
th,td{padding:8px 11px;text-align:left;border-bottom:1px solid var(--border)}
th{background:var(--panel2);color:var(--muted);font-weight:600;font-size:.76rem;
letter-spacing:.04em;text-transform:uppercase}
tr:last-child td{border-bottom:none}
tbody tr:hover td,table tr:hover td{background:rgba(255,255,255,.025)}
.card{background:var(--panel);border:1px solid var(--border);border-left:3px solid var(--accent);
border-radius:8px;padding:11px 14px;margin:9px 0}
.card .fam{font-weight:600;color:#fff}
.muted{color:var(--muted)}.ok{color:var(--ok)}.err{color:var(--crit)}
.badge{display:inline-block;padding:2px 9px;border-radius:11px;font-size:.74rem;font-weight:700}
.badge.INFO{background:rgba(88,166,255,.16);color:var(--accent)}
.badge.WARN{background:rgba(210,153,34,.18);color:var(--warn)}
.badge.CRITICAL{background:rgba(248,81,73,.18);color:var(--crit)}
.pill{display:inline-block;background:var(--panel2);border:1px solid var(--border);
border-radius:11px;padding:1px 9px;color:var(--text);font-size:.82rem}
button,.btn{background:var(--accent);color:#08111f;border:none;border-radius:6px;
padding:5px 11px;font-weight:600;cursor:pointer;font-size:.85rem}
button:hover,.btn:hover{filter:brightness(1.12);text-decoration:none}
input{background:var(--panel2);border:1px solid var(--border);color:var(--text);
border-radius:6px;padding:7px 9px;font-size:.95rem}
code{background:var(--panel2);padding:1px 5px;border-radius:4px;font-size:.88em}
th[title],span[title]{border-bottom:1px dotted var(--muted);cursor:help}
ul{margin:8px 0;padding-left:20px}li{margin:4px 0}
"""


def _t(value: Any) -> str:
    return escape(str(value))


def _mode() -> str:
    try:
        return current_app.config.get("KEYSTONE_MODE", "mock")
    except RuntimeError:
        return "mock"


def _status_bar() -> str:
    try:
        account = current_app.config.get("KEYSTONE_ACCOUNT") or "none selected"
    except RuntimeError:
        account = "none selected"
    mode = _mode()
    other = "live" if mode == "mock" else "mock"
    host, port = ksettings.get_tws_host(), ksettings.get_tws_port()
    key = "set" if ksettings.finnhub_key_present() else "not set"
    return (
        "<div class='statusbar'>"
        f"<span>mode <b>{_t(mode)}</b> (<a href='/mode?set={other}'>switch to {other}</a>)</span>"
        f"<span>TWS <b>{_t(host)}:{_t(port)}</b></span>"
        f"<span>account <b>{_t(account)}</b></span>"
        f"<span>Finnhub key <b>{_t(key)}</b></span>"
        "<span><a href='/connect'>Connect</a> · <a href='/settings'>Settings</a> · "
        "<a href='/guide'>Guide</a></span>"
        "</div>"
    )


def _page(title: str, body: str) -> str:
    nav = "".join(f"<a href='{r}'>{_t(t)}</a>" for r, _s, t in _PANELS)
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Keystone — {_t(title)}</title><style>{_CSS}</style></head><body>"
        f"<div class='container'><h1>Keystone</h1>{_status_bar()}"
        f"<div class='nav'>{nav}</div><hr><h2>{_t(title)}</h2>{body}</div>"
        "</body></html>"
    )


# --------------------------------------------------------------------------- #
# Panel renderers
# --------------------------------------------------------------------------- #
def render_dashboard(state: AppState) -> str:
    out = []
    if state.market_regime is not None:
        m = state.market_regime
        cls = "err" if m.is_hard_skip else ("warn" if m.is_defensive else "ok")
        out.append(
            f"<p>Market regime: <span class='pill {cls}'>{_t(m.state.value)}</span> "
            f"<span class='muted'>score {_t(round(m.score, 2))}</span></p>"
        )
    else:
        out.append("<p class='muted'>Market regime: n/a</p>")

    out.append("<h3>Screened universe</h3>")
    if state.screened:
        rows = "".join(
            f"<tr><td>{_t(t)}</td>"
            f"<td>{'<span class=ok>pass</span>' if e.get('passed') else '<span class=err>skip</span>'}</td>"
            f"<td>{_t(e.get('tier'))}</td><td>{_t(e.get('sector'))}</td></tr>"
            for t, e in state.screened.items()
        )
        out.append(
            "<table><tr>"
            "<th>ticker</th>"
            f"<th title=\"{_t(kguide.tip('passed'))}\">passed</th>"
            f"<th title=\"{_t(kguide.tip('tier'))}\">tier</th>"
            "<th>sector</th></tr>" + rows + "</table>"
        )
    else:
        out.append("<p class='muted'>no screened universe</p>")

    out.append("<h3>Candidate cards</h3>")
    if state.cards:
        for account_id, cards in state.cards.items():
            label = state.account_labels.get(account_id, account_id)
            out.append(f"<p class='muted'>{_t(label)} ({_t(account_id)})</p>")
            if not cards:
                out.append("<p class='muted'>no cards</p>")
                continue
            for c in cards:
                tip = kguide.strategy_tip(c.family.value)
                out.append(
                    "<div class='card'>"
                    f"<span class='fam' title=\"{_t(tip)}\">{_t(c.family.value)}</span> "
                    f"<span class='pill' title=\"{_t(kguide.tip('score'))}\">score {_t(c.score)}</span><br>"
                    f"<span class='muted'>{_t(c.rationale)}</span></div>"
                )
    else:
        out.append("<p class='muted'>no candidates</p>")
    return _page("Weekly Checkpoint", "".join(out))


def render_book(state: AppState) -> str:
    if not state.book:
        return _page("Open Book", "<p class='muted'>no open positions</p>")
    rows = "".join(
        f"<tr><td>{_t(p.get('account_id'))}</td><td>{_t(p.get('symbol'))}</td>"
        f"<td>{_t(p.get('family'))}</td><td>{_t(p.get('dte'))}</td>"
        f"<td>{_t(p.get('delta'))}</td>"
        f"<td class='{'ok' if (p.get('pnl') or 0) >= 0 else 'err'}'>{_t(p.get('pnl'))}</td></tr>"
        for p in state.book
    )
    table = (
        "<table><tr><th>account</th><th>symbol</th><th>family</th>"
        f"<th title='Days to expiration'>DTE</th><th>delta</th><th>P&amp;L</th></tr>{rows}</table>"
    )
    return _page("Open Book", table)


def render_alerts(state: AppState) -> str:
    if not state.alerts:
        return _page("Alerts Queue", "<p class='muted'>no alerts</p>")
    rows = []
    for a in state.alerts:
        sev = a.severity.value if hasattr(a.severity, "value") else str(a.severity)
        url = state.optionstrat_urls.get(a.symbol, "")
        link = f"<a href='{escape(url)}'>OptionStrat</a>" if url else ""
        button = f"<button name='stage' value='{_t(a.symbol)}'>Stage to TWS</button>"
        rows.append(
            f"<tr><td><span class='badge {_t(sev)}'>{_t(sev)}</span></td>"
            f"<td>{_t(a.symbol)}</td><td>{_t(a.kind.value)}</td><td>{_t(a.message)}</td>"
            f"<td>{_t(a.suggested_action.value)}</td><td>{link}</td><td>{button}</td></tr>"
        )
    table = (
        "<table><tr><th>severity</th><th>symbol</th><th>kind</th><th>message</th>"
        f"<th>action</th><th>link</th><th></th></tr>{''.join(rows)}</table>"
    )
    return _page("Alerts Queue", table)


def render_smsf(state: AppState) -> str:
    out = ["<h3>Core holdings vs target weights</h3>"]
    if state.smsf_holdings:
        rows = "".join(
            f"<tr><td>{_t(h.get('ticker'))}</td><td>{_t(h.get('target_weight'))}</td>"
            f"<td>{_t(h.get('current_weight'))}</td><td>{_t(h.get('wheel_state'))}</td></tr>"
            for h in state.smsf_holdings
        )
        out.append(f"<table><tr><th>ticker</th><th>target</th><th>current</th><th>wheel</th></tr>{rows}</table>")
    else:
        out.append("<p class='muted'>no holdings configured</p>")
    out.append("<h3>Active collars</h3>")
    if state.collars:
        out.append("<ul>" + "".join(f"<li>{_t(c.get('ticker'))}: {_t(c.get('detail'))}</li>" for c in state.collars) + "</ul>")
    else:
        out.append("<p class='muted'>no active collars</p>")
    return _page("SMSF View", "".join(out))


def render_stress(state: AppState) -> str:
    if state.stress is None:
        return _page("Stress Panel", "<p class='muted'>no stress run</p>")
    s = state.stress
    body = (
        "<table><tr><th>row</th><th>P&amp;L</th></tr>"
        f"<tr><td>beta-mapped market (−5% / IV+10)</td>"
        f"<td class='{'ok' if s.market_pnl >= 0 else 'err'}'>{_t(round(s.market_pnl, 2))}</td></tr>"
        f"<tr><td>worst single name: {_t(s.worst_name)}</td>"
        f"<td class='{'ok' if s.worst_name_pnl >= 0 else 'err'}'>{_t(round(s.worst_name_pnl, 2))}</td></tr>"
        "</table>"
    )
    if s.ceiling is not None:
        body += (
            f"<p class='muted'>ceiling ${_t(s.ceiling)} — market within "
            f"<b class='{'ok' if s.market_within_ceiling else 'err'}'>{_t(s.market_within_ceiling)}</b>, "
            f"worst within <b class='{'ok' if s.worst_within_ceiling else 'err'}'>{_t(s.worst_within_ceiling)}</b></p>"
        )
    return _page("Stress Panel", body)


def render_guide(_state: AppState) -> str:
    return _page("Guide — selection criteria", kguide.render_guide())


_RENDERERS = {
    "dashboard": render_dashboard,
    "book": render_book,
    "alerts": render_alerts,
    "smsf": render_smsf,
    "stress": render_stress,
    "guide": render_guide,
}


# --------------------------------------------------------------------------- #
# App factory
# --------------------------------------------------------------------------- #
def _effective_state(app: Flask) -> AppState:
    if app.config.get("KEYSTONE_STATE_EXPLICIT"):
        return app.config["KEYSTONE_STATE"]
    if app.config.get("KEYSTONE_MODE", "mock") == "mock":
        cached = app.config.get("KEYSTONE_MOCK_STATE")
        if cached is None:
            from ui.mock import build_mock_state

            cached = build_mock_state()
            app.config["KEYSTONE_MOCK_STATE"] = cached
        return cached
    return app.config.get("KEYSTONE_STATE") or AppState()


def create_app(
    config: Optional[dict[str, Any]] = None,
    state: Optional[AppState] = None,
    mode: Optional[str] = None,
) -> Flask:
    """Application factory. mode: 'mock' (default, populated demo) or 'live'."""

    app = Flask(__name__)
    if config:
        app.config.update(config)
    app.config["KEYSTONE_MODE"] = mode or app.config.get("KEYSTONE_MODE", "mock")
    if state is not None:
        app.config["KEYSTONE_STATE"] = state
        app.config["KEYSTONE_STATE_EXPLICIT"] = True

    @app.get("/health")
    def health() -> Any:
        return jsonify(status="ok", app="keystone", stage=12, mode=app.config["KEYSTONE_MODE"],
                       time=datetime.now(NY).isoformat(), timezone="America/New_York")

    def _make_view(slug: str):
        def view() -> str:
            return _RENDERERS[slug](_effective_state(app))

        view.__name__ = f"panel_{slug}"
        return view

    for route, slug, _title in _PANELS:
        app.add_url_rule(route, endpoint=f"panel_{slug}", view_func=_make_view(slug))

    @app.get("/mode")
    def mode_view():
        want = request.args.get("set")
        if want in ("mock", "live"):
            app.config["KEYSTONE_MODE"] = want
        return redirect("/")

    # --- settings (save the Finnhub key + TWS host/port once) ------------- #
    @app.get("/settings")
    def settings_get() -> str:
        saved = request.args.get("saved")
        masked = ksettings.masked_finnhub_key() or "not set"
        body = (
            ("<p class='ok'>Saved.</p>" if saved else "")
            + "<form method='post' action='/settings'>"
            f"<p>Finnhub API key (current: <i>{_t(masked)}</i>):<br>"
            "<input type='password' name='finnhub_key' size='46' "
            "placeholder='leave blank to keep current'></p>"
            f"<p>TWS host:<br><input name='tws_host' value='{_t(ksettings.get_tws_host())}'></p>"
            f"<p>TWS port:<br><input name='tws_port' value='{_t(ksettings.get_tws_port())}'></p>"
            "<button type='submit'>Save</button></form>"
            f"<p class='muted'>Saved to {_t(ksettings.secrets_path())} — entered once, reused every run.</p>"
        )
        return _page("Settings", body)

    @app.post("/settings")
    def settings_post():
        key = (request.form.get("finnhub_key") or "").strip()
        if key:
            ksettings.set_finnhub_key(key)
        host = (request.form.get("tws_host") or "").strip()
        port = (request.form.get("tws_port") or "").strip()
        ksettings.set_tws(host or None, int(port) if port.isdigit() else None)
        return redirect("/settings?saved=1")

    # --- connect to TWS + pick an account --------------------------------- #
    def _account_table(accounts: list, note: str) -> str:
        rows = "".join(
            f"<tr><td>{_t(a['account'])}</td><td>{_t(a.get('nlv'))}</td>"
            f"<td><a class='btn' href=\"/select?account={escape(str(a['account']))}"
            f"&nlv={escape(str(a.get('nlv') or ''))}\">select</a></td></tr>"
            for a in accounts
        )
        return f"<p class='ok'>{note}</p><table><tr><th>account</th><th>NLV</th><th></th></tr>{rows}</table>"

    @app.get("/connect")
    def connect_view() -> str:
        if app.config.get("KEYSTONE_MODE") == "mock":
            from ui.mock import MOCK_ACCOUNTS

            return _page("Connect (mock)", _account_table(
                MOCK_ACCOUNTS, "Mock mode — sample accounts (no TWS). Switch to live to use TWS."))

        from core.ib_client import with_ib
        from portfolio.account_profiles import list_managed_accounts

        host, port = ksettings.get_tws_host(), ksettings.get_tws_port()
        try:
            accounts = with_ib(list_managed_accounts)
        except Exception as exc:  # noqa: BLE001
            body = (
                f"<p class='err'>Could not connect to TWS at {_t(host)}:{_t(port)}.</p>"
                f"<pre class='muted'>{_t(exc)}</pre>"
                "<p>Start TWS/Gateway with the API enabled (and the port allowed), install live "
                "deps (<code>pip install -r requirements-live.txt</code>), set host/port in "
                "<a href='/settings'>Settings</a>, then retry. A new dynamic clientId is used each "
                "time, so this won't clash with your other TWS apps. Or "
                "<a href='/mode?set=mock'>use mock mode</a>.</p>"
            )
            return _page("Connect to TWS", body)
        if not accounts:
            return _page("Connect to TWS", "<p class='muted'>Connected, but TWS returned no managed accounts.</p>")
        return _page("Connect to TWS", _account_table(accounts, f"Connected ({len(accounts)} account(s))."))

    @app.get("/select")
    def select_view():
        account = request.args.get("account")
        nlv = request.args.get("nlv")
        if account:
            app.config["KEYSTONE_ACCOUNT"] = account
            if nlv:
                try:
                    app.config["KEYSTONE_ACCOUNT_NLV"] = float(nlv)
                except ValueError:
                    pass
        return redirect("/")

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False)
