"""UI features: settings page, connect/account select, mock mode, guide, theme.

``fresh_settings`` (tests/conftest.py) isolates secrets to a temp dir.
"""

from __future__ import annotations

from ui.app import create_app


def test_settings_page_saves(fresh_settings):
    client = create_app().test_client()
    assert client.get("/settings").status_code == 200
    resp = client.post("/settings", data={"finnhub_key": "SAVED123", "tws_host": "127.0.0.1", "tws_port": "7496"})
    assert resp.status_code in (302, 303)
    assert fresh_settings.get_finnhub_key() == "SAVED123"
    assert fresh_settings.get_tws_port() == 7496


def test_connect_handles_no_tws(fresh_settings, monkeypatch):
    # Closed port -> deterministic whether or not ib_insync / TWS is present.
    monkeypatch.setenv("KEYSTONE_TWS_PORT", "65500")
    client = create_app(mode="live").test_client()
    resp = client.get("/connect")
    assert resp.status_code == 200
    assert b"Could not connect to TWS" in resp.data


def test_mock_connect_lists_sample_accounts(fresh_settings):
    client = create_app(mode="mock").test_client()
    html = client.get("/connect").data.decode()
    assert "MOCK-TRADING" in html and "MOCK-SMSF" in html  # no TWS needed


def test_select_account_sets_config(fresh_settings):
    app = create_app(mode="live")
    client = app.test_client()
    resp = client.get("/select?account=U7654321&nlv=90000")
    assert resp.status_code in (302, 303)
    assert app.config["KEYSTONE_ACCOUNT"] == "U7654321"
    assert app.config["KEYSTONE_ACCOUNT_NLV"] == 90000.0
    assert b"U7654321" in client.get("/").data  # shown in the status bar


def test_status_bar_shows_tws_target(fresh_settings):
    html = create_app(mode="live").test_client().get("/").data.decode()
    assert "7496" in html and "Finnhub key" in html


def test_mock_mode_dashboard_is_populated(fresh_settings):
    html = create_app(mode="mock").test_client().get("/").data.decode()
    assert "CALM_TREND" in html  # regime read
    assert "Trading 1 (mock)" in html  # mock account label
    assert ("put_credit_spread" in html or "iron_condor" in html)  # real ranker cards
    assert "--bg:#0d1117" in html  # dark theme present


def test_guide_page_has_criteria(fresh_settings):
    html = create_app().test_client().get("/guide").data.decode()
    assert "Universe screen" in html
    assert "IVR" in html
    assert "wheel_csp" in html and "HARD_SKIP" in html


def test_mode_toggle(fresh_settings):
    app = create_app(mode="mock")
    resp = app.test_client().get("/mode?set=live")
    assert resp.status_code in (302, 303)
    assert app.config["KEYSTONE_MODE"] == "live"


def test_health_reports_mode(fresh_settings):
    assert create_app(mode="mock").test_client().get("/health").get_json()["mode"] == "mock"
