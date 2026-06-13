"""Flask shell: health route + panel stubs render."""

from __future__ import annotations

import pytest

from ui.app import create_app


@pytest.fixture()
def client():
    app = create_app({"TESTING": True})
    return app.test_client()


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert data["app"] == "keystone"
    assert data["timezone"] == "America/New_York"


@pytest.mark.parametrize("route", ["/", "/book", "/alerts", "/smsf", "/stress"])
def test_panels_render(client, route):
    resp = client.get(route)
    assert resp.status_code == 200
    assert b"Keystone" in resp.data
    assert b"stub" in resp.data.lower()
