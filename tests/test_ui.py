"""Stage 12: Flask shell + the five panels render against fixture AppState."""

from __future__ import annotations

import pytest

from alerts.monitor import Alert
from alerts.triggers import Severity, SuggestedAction, TriggerKind
from core.models import Family, InstrumentClass, Suggestion
from portfolio.stress import StressResult
from regime.market_regime import classify_market_regime
from ui.app import create_app
from ui.state import AppState


def _state() -> AppState:
    card = Suggestion(symbol="AAPL", account_id="T1", family=Family.PUT_CREDIT_SPREAD,
                      legs=[], instrument_class=InstrumentClass.US_EQUITY_OPT,
                      score=0.82, rationale="put credit spread 92/87")
    alert = Alert(symbol="AAPL", account_id="T1", kind=TriggerKind.PROFIT_TARGET,
                  severity=Severity.INFO, message="profit target hit",
                  suggested_action=SuggestedAction.CLOSE)
    return AppState(
        market_regime=classify_market_regime(14, 15, 17, 110, 100, True),
        screened={"AAPL": {"passed": True, "tier": "A", "sector": "Information Technology"}},
        cards={"T1": [card]},
        account_labels={"T1": "Trading 1"},
        book=[{"account_id": "T1", "symbol": "AAPL", "family": "put_credit_spread",
               "dte": 40, "delta": 0.05, "pnl": 120.0}],
        alerts=[alert],
        optionstrat_urls={"AAPL": "https://optionstrat.com/build/custom/AAPL/-.AAPL260730P92"},
        smsf_holdings=[{"ticker": "XLE", "target_weight": 0.15, "current_weight": 0.05,
                        "wheel_state": "CSP open"}],
        collars=[{"ticker": "XLU", "detail": "long 70P financed by CC"}],
        stress=StressResult(market_pnl=-500.0, worst_name="BBB", worst_name_pnl=-2000.0,
                            ceiling=1000.0, market_within_ceiling=True, worst_within_ceiling=False),
    )


@pytest.fixture()
def client():
    return create_app({"TESTING": True}, state=_state()).test_client()


def test_health(client):
    data = client.get("/health").get_json()
    assert data["status"] == "ok"
    assert data["timezone"] == "America/New_York"


def test_dashboard_panel(client):
    html = client.get("/").data.decode()
    assert "Weekly Checkpoint" in html
    assert "CALM_TREND" in html  # market regime read
    assert "AAPL" in html  # screened universe + card
    assert "put_credit_spread" in html  # candidate card family
    assert "Trading 1" in html  # account label


def test_book_panel(client):
    html = client.get("/book").data.decode()
    assert "Open Book" in html
    assert "AAPL" in html and "put_credit_spread" in html


def test_alerts_panel(client):
    html = client.get("/alerts").data.decode()
    assert "Alerts Queue" in html
    assert "INFO" in html
    assert "Stage to TWS" in html  # stage-to-TWS button
    assert "optionstrat.com" in html  # deep link


def test_smsf_panel(client):
    html = client.get("/smsf").data.decode()
    assert "SMSF" in html
    assert "XLE" in html  # holding vs target
    assert "XLU" in html  # active collar


def test_stress_panel(client):
    html = client.get("/stress").data.decode()
    assert "Stress" in html
    assert "BBB" in html  # worst single name
    assert "-500" in html  # market row P&L


def test_empty_state_renders():
    client = create_app(state=AppState()).test_client()
    for route in ("/", "/book", "/alerts", "/smsf", "/stress"):
        assert client.get(route).status_code == 200
