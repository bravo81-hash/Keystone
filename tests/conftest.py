"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture()
def fresh_settings(tmp_path, monkeypatch):
    """Isolate core.settings to a temp ~/.keystone and clear overriding env vars."""

    monkeypatch.setenv("KEYSTONE_HOME", str(tmp_path))
    monkeypatch.delenv("FINNHUB_KEY", raising=False)
    monkeypatch.delenv("KEYSTONE_TWS_HOST", raising=False)
    monkeypatch.delenv("KEYSTONE_TWS_PORT", raising=False)
    from core import settings as s  # reads KEYSTONE_HOME + env dynamically each call

    return s
