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
from execution.optionstrat_links import optionstrat_url
from ui import guide as kguide
from ui.state import AppState

NY = ZoneInfo("America/New_York")

_PANELS = [
    ("/", "dashboard", "Weekly Checkpoint"),
    ("/book", "book", "Open Book"),
    ("/alerts", "alerts", "Alerts Queue"),
    ("/smsf", "smsf", "SMSF View"),
    ("/stress", "stress", "Stress Panel"),
    ("/governor", "governor", "Governor"),
    ("/scout", "scout", "Scout"),
    ("/guide", "guide", "Guide"),
]

_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Outfit:wght@500;600;700&display=swap');

:root {
  --bg: #090b10;
  --panel: #0f141f;
  --panel2: #162030;
  --border: #1e283c;
  --border-light: #2c3c58;
  --text: #f0f4f9;
  --muted: #8e9faa;
  --accent: #3a86ff;
  --accent-hover: #5a9bff;
  --accent-glow: rgba(58, 134, 255, 0.12);
  --ok: #00e676;
  --ok-bg: rgba(0, 230, 118, 0.08);
  --warn: #ffb300;
  --warn-bg: rgba(255, 179, 0, 0.08);
  --crit: #ff3d00;
  --crit-bg: rgba(255, 61, 0, 0.08);
  --font-sans: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --font-mono: 'JetBrains Mono', "SF Mono", Cascadia Code, Consolas, monospace;
  --font-display: 'Outfit', sans-serif;
}

* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-sans);
  font-size: 14px;
  line-height: 1.6;
}

.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px 20px 60px;
}

h1 {
  font-family: var(--font-display);
  font-size: 1.8rem;
  font-weight: 700;
  color: #fff;
  letter-spacing: 0.5px;
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 8px;
}

h1::before {
  content: "";
  display: inline-block;
  width: 8px;
  height: 24px;
  background: var(--accent);
  border-radius: 2px;
}

h2 {
  font-family: var(--font-display);
  font-size: 1.3rem;
  font-weight: 600;
  color: #fff;
  border-bottom: 2px solid var(--border);
  padding-bottom: 8px;
  margin: 28px 0 16px;
}

h3 {
  font-family: var(--font-display);
  color: var(--muted);
  font-size: 0.85rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin: 24px 0 10px;
}

a {
  color: var(--accent);
  text-decoration: none;
  transition: color 0.15s ease;
}

a:hover {
  color: var(--accent-hover);
  text-decoration: none;
}

p {
  margin: 8px 0;
}

.statusbar {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
  margin: 16px 0;
  font-size: 0.88rem;
  color: var(--muted);
  display: flex;
  gap: 12px 24px;
  flex-wrap: wrap;
  align-items: center;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.statusbar b {
  color: var(--text);
}

.statusbar a {
  color: var(--accent);
  font-weight: 500;
}

.statusbar a:hover {
  text-decoration: underline;
}

.status-links {
  margin-left: auto;
  display: flex;
  gap: 12px;
}

@media (max-width: 768px) {
  .status-links {
    margin-left: 0;
    width: 100%;
    border-top: 1px solid var(--border);
    padding-top: 8px;
  }
}

.nav {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin: 16px 0;
}

.nav a {
  padding: 8px 16px;
  border-radius: 6px;
  background: var(--panel);
  border: 1px solid var(--border);
  color: var(--muted);
  font-weight: 500;
  font-size: 0.92rem;
  transition: all 0.15s ease;
}

.nav a:hover {
  background: var(--panel2);
  color: var(--text);
  border-color: var(--border-light);
}

.nav a.active {
  background: var(--accent-glow);
  color: var(--accent);
  border-color: var(--accent);
  box-shadow: 0 0 10px var(--accent-glow);
}

hr {
  border: none;
  border-top: 1px solid var(--border);
  margin: 20px 0;
}

table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  margin: 16px 0;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  font-size: 0.9rem;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

th, td {
  padding: 12px 16px;
  text-align: left;
  border-bottom: 1px solid var(--border);
}

th {
  background: var(--panel2);
  color: var(--muted);
  font-weight: 600;
  font-size: 0.78rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  font-family: var(--font-display);
}

tr:last-child td {
  border-bottom: none;
}

tbody tr {
  transition: background 0.15s ease;
}

tbody tr:hover td {
  background: rgba(255, 255, 255, 0.015);
}

td:nth-child(2), td:nth-child(4), td:nth-child(5), td:nth-child(6) {
  font-family: var(--font-mono);
}

.cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 16px;
  margin: 16px 0;
}

.section-label {
  font-size: 0.95rem;
  font-weight: 600;
  margin: 16px 0 8px;
  color: #fff;
  font-family: var(--font-display);
}

.card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-left: 4px solid var(--accent);
  border-radius: 8px;
  padding: 16px;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  box-shadow: 0 4px 10px rgba(0,0,0,0.15);
}

.card:hover {
  transform: translateY(-2px);
  border-color: var(--border-light);
  box-shadow: 0 8px 20px rgba(0,0,0,0.3);
}

.card .fam {
  font-family: var(--font-mono);
  font-weight: 600;
  font-size: 0.85rem;
  color: #fff;
  letter-spacing: 0.5px;
  display: inline-block;
  margin-bottom: 6px;
  border-bottom: 1px dotted var(--muted);
  cursor: help;
}

.card .ticker {
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 1.15rem;
  color: var(--accent, #6c8cff);
  letter-spacing: 0.5px;
  margin-right: 10px;
  vertical-align: middle;
}

.card .pill {
  float: right;
  margin-top: -2px;
}

.card-rationale {
  font-size: 0.82rem;
  margin-top: 10px;
  display: block;
  line-height: 1.5;
  color: var(--muted);
}

.card-legs {
  font-family: var(--font-mono);
  font-size: 0.82rem;
  color: var(--text);
  margin: 10px 0 6px;
  line-height: 1.7;
}

.card-meta {
  font-family: var(--font-mono);
  font-size: 0.82rem;
  margin: 3px 0;
}

.card-actions {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 12px;
}

.card-actions button {
  padding: 6px 12px;
  font-size: 0.8rem;
}

.muted {
  color: var(--muted);
}

.ok {
  color: var(--ok) !important;
}

.err {
  color: var(--crit) !important;
}

.warn {
  color: var(--warn) !important;
}

.badge {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 20px;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-family: var(--font-mono);
}

.badge.INFO {
  background: rgba(58, 134, 255, 0.12);
  color: var(--accent);
}

.badge.WARN {
  background: var(--warn-bg);
  color: var(--warn);
}

.badge.CRITICAL {
  background: var(--crit-bg);
  color: var(--crit);
}

.pill {
  display: inline-block;
  background: var(--panel2);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 2px 10px;
  color: var(--text);
  font-size: 0.82rem;
  font-family: var(--font-mono);
  font-weight: 500;
}

.pill.ok {
  background: var(--ok-bg);
  border-color: rgba(0, 230, 118, 0.3);
}

.pill.warn {
  background: var(--warn-bg);
  border-color: rgba(255, 179, 0, 0.3);
}

.pill.err {
  background: var(--crit-bg);
  border-color: rgba(255, 61, 0, 0.3);
}

button, .btn {
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: 6px;
  padding: 8px 16px;
  font-weight: 600;
  font-size: 0.86rem;
  cursor: pointer;
  font-family: var(--font-sans);
  transition: all 0.15s ease;
  box-shadow: 0 4px 10px var(--accent-glow);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

button:hover, .btn:hover {
  background: var(--accent-hover);
  box-shadow: 0 6px 14px rgba(58, 134, 255, 0.25);
  transform: translateY(-1px);
}

button:active, .btn:active {
  transform: translateY(0);
}

input {
  background: var(--panel2);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 6px;
  padding: 9px 12px;
  font-size: 0.95rem;
  font-family: var(--font-mono);
  transition: border-color 0.15s ease;
}

input:focus {
  outline: none;
  border-color: var(--accent);
}

code {
  background: var(--panel2);
  color: var(--accent-hover);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.88em;
  font-family: var(--font-mono);
}

th[title], span[title] {
  border-bottom: 1px dotted var(--muted);
  cursor: help;
}

ul {
  margin: 12px 0;
  padding-left: 20px;
}

li {
  margin: 6px 0;
}

form {
  background: var(--panel);
  border: 1px solid var(--border);
  padding: 24px;
  border-radius: 8px;
  max-width: 600px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
}

form p {
  margin-bottom: 20px;
}

form label {
  display: block;
  font-size: 0.85rem;
  color: var(--muted);
  margin-bottom: 6px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

form input {
  width: 100%;
}
"""


def _t(value: Any) -> str:
    return escape(str(value))


def _num(value: Any) -> Optional[float]:
    """Coerce to float, returning None for None / non-numeric / NaN / inf.

    Guards the cards against ``$nan`` when a quote is missing (TWS down /
    pre-market) — yfinance returns no usable bid/ask so prices come back NaN.
    """

    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):  # NaN != NaN
        return None
    return f


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
    
    mode_class = "ok" if mode == "live" else "warn"
    key_class = "ok" if key == "set" else "err"
    
    return (
        "<div class='statusbar'>"
        f"<span>mode <b class='pill {mode_class}'>{_t(mode)}</b> (<a href='/mode?set={other}'>switch to {other}</a>)</span>"
        f"<span>TWS <b>{_t(host)}:{_t(port)}</b></span>"
        f"<span>account <b class='pill'>{_t(account)}</b></span>"
        f"<span>Finnhub key <b class='pill {key_class}'>{_t(key)}</b></span>"
        "<span class='status-links'><a href='/connect'>Connect</a> · <a href='/settings'>Settings</a> · "
        "<a href='/guide'>Guide</a></span>"
        "</div>"
    )


def _page(title: str, body: str) -> str:
    try:
        current_path = request.path
    except RuntimeError:
        current_path = "/"
    nav = "".join(f"<a href='{r}' class='{'active' if current_path == r else ''}'>{_t(t)}</a>" for r, _s, t in _PANELS)
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Keystone — {_t(title)}</title><style>{_CSS}</style></head><body>"
        f"<div class='container'><h1>KEY<span style='color:var(--accent);'>STONE</span></h1>{_status_bar()}"
        f"<div class='nav'>{nav}</div><hr><h2>{_t(title)}</h2>{body}</div>"
        "</body></html>"
    )


def _card_html(s: Any) -> str:
    """Rich candidate card: legs, net credit/debit, max P/L, greeks, OptionStrat,
    and a Stage-to-TWS button (whatIf, transmit=False)."""

    mgmt = s.management or {}
    greeks = s.entry_greeks or {}
    tip = kguide.strategy_tip(s.family.value)

    legs = "<br>".join(
        f"{leg.action.value} {leg.quantity} {_t(leg.contract.symbol)} {leg.contract.strike:g}"
        f"{leg.contract.right.value if leg.contract.right else ''} {leg.contract.expiry}"
        for leg in s.legs
    ) or "<span class='muted'>—</span>"

    credit = _num(mgmt.get("credit"))
    if credit is not None:
        net = f"<span class='ok'>credit ${credit * 100:.0f}</span> <span class='muted'>({credit:.2f})</span>"
        max_profit = _num(mgmt.get("max_profit"))
        mp = f"${max_profit:.0f}" if max_profit is not None else f"${credit * 100:.0f}"
        max_loss = _num(s.max_loss)
        pl = f"max profit {mp} · max loss {('$%.0f' % max_loss) if max_loss is not None else '—'}"
    elif mgmt.get("credit") is not None or s.max_loss is None:
        # A net was expected but the quote was NaN/missing (TWS down / pre-market).
        net = "<span class='warn'>no live quote</span> <span class='muted'>(TWS down / pre-market)</span>"
        pl = "<span class='muted'>pricing unavailable — re-run when the market is live</span>"
    else:
        max_loss = _num(s.max_loss)
        net = f"<span class='warn'>debit {('$%.0f' % max_loss) if max_loss is not None else '—'}</span>"
        pl = "max profit: <span class='muted'>open (no PT on long leg)</span> · " \
             f"max loss {('$%.0f' % max_loss) if max_loss is not None else '—'}"

    greek_str = ", ".join(
        f"{k} {gv:+.2f}" for k, v in greeks.items() if (gv := _num(v)) is not None
    ) or "—"
    try:
        url = optionstrat_url(s)
    except Exception:  # noqa: BLE001
        url = ""
    os_link = f"<a href='{escape(url)}' target='_blank'>OptionStrat ↗</a>" if url else ""

    stage = (
        "<form method='post' action='/stage' style='display:inline'>"
        f"<input type='hidden' name='account' value='{_t(s.account_id)}'>"
        f"<input type='hidden' name='sig' value='{_t(s.signature())}'>"
        "<button type='submit'>Stage to TWS</button></form>"
    )

    return (
        "<div class='card'>"
        f"<span class='ticker'>{_t(s.symbol)}</span>"
        f"<span class='fam' title=\"{_t(tip)}\">{_t(s.family.value)}</span>"
        f"<span class='pill' title=\"{_t(kguide.tip('score'))}\">score {_t(s.score)}</span>"
        f"<div class='card-legs'>{legs}</div>"
        f"<div class='card-meta'>{net} · DTE {_t(s.dte)}</div>"
        f"<div class='card-meta muted'>{pl}</div>"
        f"<div class='card-meta muted'>greeks: {_t(greek_str)}</div>"
        f"<span class='card-rationale'>{_t(s.rationale)}</span>"
        f"<div class='card-actions'>{os_link} {stage}</div>"
        "</div>"
    )


# --------------------------------------------------------------------------- #
# Panel renderers
# --------------------------------------------------------------------------- #
def render_dashboard(state: AppState) -> str:
    out = []
    if _mode() == "live":
        try:
            errs = current_app.config.get("KEYSTONE_SCAN_ERRORS") or []
        except RuntimeError:
            errs = []
        out.append(
            "<p><a class='btn' href='/scan'>↻ Run weekly checkpoint</a> "
            "<span class='muted'>live scan via yfinance chains — takes ~20-40s</span></p>"
        )
        if errs:
            out.append(f"<p class='muted'>scan notes: {_t('; '.join(errs[:8]))}</p>")
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
            out.append(f"<p class='section-label'>{_t(label)} <span class='muted'>({_t(account_id)})</span></p>")
            if not cards:
                out.append("<p class='muted'>no cards</p>")
                continue
            out.append("<div class='cards-grid'>")
            for c in cards:
                out.append(_card_html(c))
            out.append("</div>")
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


def render_governor(state: AppState) -> str:
    """v2 governor panel: engine allocations + governor state (vol target,
    exposure scalar, drawdown tier, leverage utilization, hedge coverage,
    severe-tail pass/fail)."""

    out: list[str] = []
    g = state.governor
    if not g and not state.engine_allocations:
        return _page("Governor", "<p class='muted'>no governor cycle run "
                     "(v2 leverage off until validation passes — see Guide)</p>")

    if g:
        tier = str(g.get("tier", "—"))
        pass_ = g.get("severe_tail_pass")
        out.append("<h3>Governor state</h3>")
        out.append(
            "<table><tr><th>metric</th><th>value</th></tr>"
            f"<tr><td>vol target (annual)</td><td>{_t(g.get('vol_target', '—'))}</td></tr>"
            f"<tr><td>portfolio vol (now)</td><td>{_t(g.get('sigma_now', '—'))}</td></tr>"
            f"<tr><td>exposure scalar</td><td>{_t(g.get('exposure_scalar', '—'))}</td></tr>"
            f"<tr><td>drawdown</td><td>{_t(g.get('drawdown', '—'))}</td></tr>"
            f"<tr><td>drawdown tier</td>"
            f"<td class='{'err' if tier == 'DEFENSIVE' else ('warn' if tier in ('WARN', 'DELEVER') else 'ok')}'>"
            f"{_t(tier)}</td></tr>"
            f"<tr><td>leverage utilization</td><td>{_t(g.get('leverage_util', '—'))}</td></tr>"
            f"<tr><td>hedge coverage ratio</td><td>{_t(g.get('hedge_coverage', '—'))}</td></tr>"
            f"<tr><td>severe-tail (−20%) vs DD budget</td>"
            f"<td class='{'ok' if pass_ else 'err'}'>"
            f"{'PASS' if pass_ else 'FAIL'}</td></tr>"
            "</table>"
        )

    if state.engine_allocations:
        rows = "".join(
            f"<tr><td>{_t(name)}</td><td>{_t(a.get('target', '—'))}</td>"
            f"<td>{_t(a.get('actual', '—'))}</td></tr>"
            for name, a in state.engine_allocations.items()
        )
        out.append("<h3>Engine allocations (target vs actual)</h3>")
        out.append(f"<table><tr><th>engine</th><th>target</th><th>actual</th></tr>{rows}</table>")

    return _page("Governor", "".join(out))


def render_guide(_state: AppState) -> str:
    return _page("Guide — selection criteria", kguide.render_guide())


# --------------------------------------------------------------------------- #
# Scout panel helpers
# --------------------------------------------------------------------------- #

def _scout_card_html(s: Any) -> str:
    """Card variant without Stage button (Scout cards use separate account IDs)."""
    mgmt = s.management or {}
    greeks = s.entry_greeks or {}
    tip = kguide.strategy_tip(s.family.value)

    legs = "<br>".join(
        f"{leg.action.value} {leg.quantity} {_t(leg.contract.symbol)} {leg.contract.strike:g}"
        f"{leg.contract.right.value if leg.contract.right else ''} {leg.contract.expiry}"
        for leg in s.legs
    ) or "<span class='muted'>—</span>"

    credit = _num(mgmt.get("credit"))
    if credit is not None:
        max_profit = _num(mgmt.get("max_profit"))
        mp = f"${max_profit:.0f}" if max_profit is not None else f"${credit * 100:.0f}"
        max_loss = _num(s.max_loss)
        net = f"<span class='ok'>credit ${credit * 100:.0f}</span> <span class='muted'>({credit:.2f})</span>"
        pl = f"max profit {mp} · max loss {('$%.0f' % max_loss) if max_loss is not None else '—'}"
    elif mgmt.get("credit") is not None or s.max_loss is None:
        net = "<span class='warn'>no live quote</span> <span class='muted'>(TWS down / pre-market)</span>"
        pl = "<span class='muted'>pricing unavailable</span>"
    else:
        max_loss = _num(s.max_loss)
        net = f"<span class='warn'>debit {('$%.0f' % max_loss) if max_loss is not None else '—'}</span>"
        pl = f"max profit: open · max loss {('$%.0f' % max_loss) if max_loss is not None else '—'}"

    greek_str = ", ".join(
        f"{k} {gv:+.2f}" for k, v in greeks.items() if (gv := _num(v)) is not None
    ) or "—"
    try:
        url = optionstrat_url(s)
    except Exception:  # noqa: BLE001
        url = ""
    os_link = f"<a href='{escape(url)}' target='_blank'>OptionStrat ↗</a>" if url else ""

    return (
        "<div class='card'>"
        f"<span class='ticker'>{_t(s.symbol)}</span>"
        f"<span class='fam' title=\"{_t(tip)}\">{_t(s.family.value)}</span>"
        f"<span class='pill' title=\"{_t(kguide.tip('score'))}\">score {_t(s.score)}</span>"
        f"<div class='card-legs'>{legs}</div>"
        f"<div class='card-meta'>{net} · DTE {_t(s.dte)}</div>"
        f"<div class='card-meta muted'>{pl}</div>"
        f"<div class='card-meta muted'>greeks: {_t(greek_str)}</div>"
        f"<span class='card-rationale'>{_t(s.rationale)}</span>"
        f"<div class='card-actions'>{os_link}</div>"
        "</div>"
    )


def _render_scout_result(result: Any) -> str:
    """Build the HTML fragment returned by POST /scout/analyse."""
    from html import escape as _esc

    parts: list[str] = []

    # ── tech score ─────────────────────────────────────────────────
    tech = result.tech
    if tech:
        sig_cls = "ok" if tech.signal.value == "STRONG_BUY" else (
            "warn" if tech.signal.value == "WATCH" else "err")
        factor_cells = "".join(
            f"<td class=\"{'ok' if f else 'err'}\">{'✓' if f else '✗'}</td>"
            for f in tech.factors
        )
        trio_badge = (
            "<span class='pill ok'>trio ✓</span>" if tech.trio
            else "<span class='pill err'>trio ✗</span>"
        )
        parts.append(
            "<h3>Technical Score</h3>"
            "<table>"
            "<tr><th>F1 EMA</th><th>F2 Weekly</th><th>F3 HMA</th><th>F4 ADX</th>"
            "<th>F5 RSI</th><th>F6 RS</th><th>F7 OBV</th><th>F8 ATR%</th>"
            "<th>Score</th><th>Signal</th></tr>"
            f"<tr>{factor_cells}"
            f"<td><b>{tech.score}/8</b> {trio_badge}</td>"
            f"<td><span class='badge {sig_cls.upper()}'>{_t(tech.signal.value)}</span></td></tr>"
            "</table>"
            "<table>"
            "<tr><th title='Limit entry = spot − 1.5×ATR'>Entry (ATR)</th>"
            "<th title='Stop = entry − 2.5×ATR'>Stop</th>"
            "<th title='Target = entry + 4.0×ATR'>Target</th>"
            "<th>ATR%</th><th>RSI(14)</th><th>ADX(14)</th></tr>"
            f"<tr><td>${tech.entry:.2f}</td><td>${tech.stop:.2f}</td>"
            f"<td>${tech.target:.2f}</td>"
            f"<td>{tech.atr_pct:.1f}%</td>"
            f"<td>{tech.rsi:.1f}</td><td>{tech.adx:.1f}</td></tr>"
            "</table>"
        )
        if tech.recommended_structure:
            parts.append(
                f"<p class='muted'>Suggested structure: <b>{_t(tech.recommended_structure)}</b> "
                "(based on VRP heuristic — final structure determined by IVR regime)</p>"
            )

    # ── vol context + regime ────────────────────────────────────────
    if result.atm_iv is not None or result.rv20 is not None or result.stock_regime is not None:
        sr = result.stock_regime
        state_val = sr.state.value if sr else "—"
        state_cls = ("ok" if sr and "RICH" in state_val else
                     ("warn" if sr and "FAIR" in state_val else
                      ("err" if sr and ("THIN" in state_val or "BLACKOUT" in state_val) else "")))
        vrp_str = (f"{result.vrp:+.1f}v" if result.vrp is not None else "—")
        atm_str = (f"{result.atm_iv:.1f}%" if result.atm_iv is not None else "—")
        rv_str = (f"{result.rv20:.1f}%" if result.rv20 is not None else "—")
        ivr_str = (f"{result.ivr:.0f}" if result.ivr is not None else "—")
        sell_ok = sr.sell_premium_ok if sr else None
        sell_badge = (
            "<span class='pill ok'>sell ok</span>" if sell_ok
            else "<span class='pill err'>no sell</span>"
        ) if sell_ok is not None else ""
        parts.append(
            "<h3>Volatility Context</h3>"
            "<table>"
            "<tr><th title='30-day ATM implied vol (from chain)'>ATM IV (30d)</th>"
            "<th title='20-day realized vol'>RV20</th>"
            "<th title='ATM IV − RV20 (positive = implied rich)'>VRP</th>"
            "<th title='Realized-vol rank proxy for IVR'>IVR proxy</th>"
            "<th>Regime</th></tr>"
            f"<tr><td>{_t(atm_str)}</td><td>{_t(rv_str)}</td>"
            f"<td class=\"{'ok' if result.vrp and result.vrp > 3 else ('err' if result.vrp and result.vrp < 0 else '')}\">"
            f"{_t(vrp_str)}</td>"
            f"<td>{_t(ivr_str)}</td>"
            f"<td class='{state_cls}'>{_t(state_val)} {sell_badge}</td></tr>"
            "</table>"
        )

    # ── strategy cards ──────────────────────────────────────────────
    if result.cards:
        parts.append("<h3>Strategy Cards <span class='muted' style='font-size:0.8rem'>"
                     "(hypothetical — scout accounts, $100k NLV)</span></h3>")
        acct_labels = {"SCOUT-TRADING": "Trading", "SCOUT-SMSF": "SMSF"}
        for account_id, cards in result.cards.items():
            if not cards:
                continue
            label = acct_labels.get(account_id, account_id)
            parts.append(f"<p class='section-label'>{_t(label)}</p>")
            parts.append("<div class='cards-grid'>")
            for c in cards:
                parts.append(_scout_card_html(c))
            parts.append("</div>")
    elif result.tech is not None:
        parts.append("<p class='muted'>No option chain data — cards require a live market session.</p>")

    return "".join(parts)


def render_scout(_state: AppState) -> str:
    body = (
        "<p class='muted'>Enter any ticker to run an on-demand analysis: "
        "8-factor technical score, volatility context, and Keystone strategy cards. "
        "Fetches live data from yfinance — not affected by mock/live mode.</p>"
        "<div style='display:flex;gap:12px;align-items:flex-end;margin:16px 0'>"
        "<div><label style='display:block;font-size:0.82rem;color:var(--muted);"
        "text-transform:uppercase;letter-spacing:0.05em;margin-bottom:6px'>Ticker</label>"
        "<input id='scout-ticker' type='text' placeholder='AAPL, NVDA, SPY ...' "
        "style='width:200px;font-size:1rem' autocomplete='off' autocapitalize='characters'></div>"
        "<button id='scout-btn' onclick='runScout()'>Analyse →</button>"
        "</div>"
        "<div id='scout-result'></div>"
        "<script>"
        "async function runScout() {"
        "  const ticker = document.getElementById('scout-ticker').value.trim().toUpperCase();"
        "  if (!ticker) return;"
        "  const btn = document.getElementById('scout-btn');"
        "  const out = document.getElementById('scout-result');"
        "  btn.disabled = true; btn.textContent = 'Analysing…';"
        "  out.innerHTML = \"<p class='muted'>Fetching data for \" + ticker + \"…</p>\";"
        "  try {"
        "    const res = await fetch('/scout/analyse', {"
        "      method: 'POST',"
        "      headers: {'Content-Type': 'application/json'},"
        "      body: JSON.stringify({ticker})"
        "    });"
        "    const data = await res.json();"
        "    if (data.ok) {"
        "      out.innerHTML = \"<h2>\" + data.ticker + \" — Scout Result</h2>\" + data.html;"
        "    } else {"
        "      out.innerHTML = \"<p class='err'>\" + (data.error || 'Analysis failed') + '</p>';"
        "    }"
        "  } catch(e) {"
        "    out.innerHTML = \"<p class='err'>Request failed: \" + e.message + '</p>';"
        "  } finally {"
        "    btn.disabled = false; btn.textContent = 'Analyse →';"
        "  }"
        "}"
        "document.getElementById('scout-ticker').addEventListener('keydown', function(e) {"
        "  if (e.key === 'Enter') runScout();"
        "});"
        "</script>"
    )
    return _page("Scout", body)


_RENDERERS = {
    "dashboard": render_dashboard,
    "book": render_book,
    "alerts": render_alerts,
    "smsf": render_smsf,
    "stress": render_stress,
    "governor": render_governor,
    "scout": render_scout,
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
    # live: the last weekly-checkpoint scan, else empty until /scan runs.
    return app.config.get("KEYSTONE_LIVE_STATE") or app.config.get("KEYSTONE_STATE") or AppState()


def _find_suggestion(app: Flask, account_id: str, signature: str):
    state = _effective_state(app)
    for sugg in state.cards.get(account_id, []):
        if sugg.signature() == signature:
            return sugg
    return None


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

    # --- live weekly-checkpoint scan -------------------------------------- #
    @app.get("/scan")
    def scan_view():
        if app.config.get("KEYSTONE_MODE") != "live":
            return redirect("/")  # mock is already populated
        from config.loader import load_config
        from core.market_data import build_market_data
        from core.yf_chain import fetch_chain_yf
        from events.earnings import get_next_earnings
        from portfolio.account_profiles import from_config
        from selection.live_scan import build_scan_targets, run_checkpoint

        cfg_all = load_config()
        profiles = from_config(cfg_all.accounts)
        smsf_watch = [h.ticker for h in cfg_all.investing.target_holdings]
        acquire = {h.ticker: h.acquire_below_price for h in cfg_all.investing.target_holdings
                   if h.acquire_below_price}
        targets = build_scan_targets(profiles, smsf_watchlist=smsf_watch)
        md = build_market_data(mode="live")

        nlv_over = {}
        acct, nlv = app.config.get("KEYSTONE_ACCOUNT"), app.config.get("KEYSTONE_ACCOUNT_NLV")
        if acct and nlv:
            nlv_over[acct] = nlv
        try:
            result = run_checkpoint(
                profiles, targets, market_data=md, chain_provider=fetch_chain_yf,
                get_earnings=get_next_earnings, acquire_below=acquire, nlv_overrides=nlv_over, top_n=5,
            )
        except Exception as exc:  # noqa: BLE001
            return _page("Weekly Checkpoint",
                         f"<p class='err'>Scan failed: {_t(exc)}</p><p><a href='/'>back</a></p>")
        app.config["KEYSTONE_LIVE_STATE"] = AppState(
            market_regime=result.market_regime, screened=result.screened,
            cards=result.cards, account_labels=result.account_labels,
        )
        app.config["KEYSTONE_SCAN_ERRORS"] = result.errors
        return redirect("/")

    # --- stage a candidate to TWS (whatIf, transmit=False) ---------------- #
    @app.post("/stage")
    def stage_view():
        account = request.form.get("account", "")
        sig = request.form.get("sig", "")
        suggestion = _find_suggestion(app, account, sig)
        if suggestion is None:
            return _page("Stage to TWS",
                         "<p class='err'>Candidate not found — re-run the scan.</p><p><a href='/'>back</a></p>")

        mode = app.config.get("KEYSTONE_MODE")
        try:
            if mode == "live":
                from core.ib_client import with_ib
                from execution.stage_live import stage_suggestion_live

                d = with_ib(lambda ib: stage_suggestion_live(ib, suggestion))
                accepted, init_m, maint_m = d["accepted"], d["init_margin"], d["maint_margin"]
                action, limit, transmit = d["action"], d["limit"], d["transmit"]
            else:
                from core.ib_client import IBClient, MockIB
                from execution.stage import stage_to_tws

                res = stage_to_tws(IBClient(ib=MockIB()), suggestion)
                wi, so = res.whatif, res.staged_order
                accepted, init_m, maint_m = wi.accepted, wi.init_margin, wi.maint_margin
                action, limit, transmit = so.action, so.limit_price, so.transmit
        except Exception as exc:  # noqa: BLE001
            return _page("Stage to TWS",
                         f"<p class='err'>Staging failed: {_t(exc)}</p><p><a href='/'>back</a></p>")

        try:
            url = optionstrat_url(suggestion)
        except Exception:  # noqa: BLE001
            url = ""
        os_link = f"<a href='{escape(url)}' target='_blank'>OptionStrat ↗</a> · " if url else ""
        body = (
            f"<p class='ok'>Staged <b>{_t(suggestion.family.value)}</b> on "
            f"<b>{_t(suggestion.symbol)}</b> — <b>transmit=False</b> "
            f"({'placed untransmitted in TWS — review & send there' if mode == 'live' else 'mock'}).</p>"
            "<table><tr><th>field</th><th>value</th></tr>"
            f"<tr><td>whatIf accepted</td><td>{_t(accepted)}</td></tr>"
            f"<tr><td>init margin</td><td>{_t(round(init_m, 2))}</td></tr>"
            f"<tr><td>maint margin</td><td>{_t(round(maint_m, 2))}</td></tr>"
            f"<tr><td>order</td><td>{_t(action)} @ {_t(limit)} (transmit={_t(transmit)})</td></tr>"
            "</table>"
            f"<p>{os_link}<a href='/'>back to candidates</a></p>"
        )
        return _page("Stage to TWS", body)

    # --- scout: on-demand single-ticker analysis -------------------------- #
    @app.post("/scout/analyse")
    def scout_analyse() -> Any:
        from selection.scout import run_scout

        body = request.get_json(silent=True) or {}
        ticker = str(body.get("ticker", "")).strip().upper()
        if not ticker:
            return jsonify(ok=False, error="ticker required")

        market_regime = None
        try:
            market_regime = _effective_state(app).market_regime
        except Exception:  # noqa: BLE001
            pass

        result = run_scout(ticker, market_regime=market_regime)
        if result.error:
            return jsonify(ok=False, error=result.error)

        return jsonify(ok=True, ticker=ticker, html=_render_scout_result(result))

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False)
