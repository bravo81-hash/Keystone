"""TWS connection (dynamic clientId), settings persistence, market-data fallback.

Backend only — no Flask/UI. ``fresh_settings`` comes from tests/conftest.py.
"""

from __future__ import annotations

from collections import namedtuple

import pytest

from core.ib_client import MockIB, connect_ib, with_ib
from core.market_data import (
    FinnhubProvider,
    MarketData,
    YFinanceProvider,
    build_market_data,
)
from portfolio.account_profiles import list_managed_accounts


# --------------------------------------------------------------------------- #
# Settings persistence
# --------------------------------------------------------------------------- #
def test_settings_persist_finnhub_key(fresh_settings):
    s = fresh_settings
    assert s.finnhub_key_present() is False
    s.set_finnhub_key("ABC12345")
    assert s.get_finnhub_key() == "ABC12345"
    assert s.finnhub_key_present() is True
    assert s.secrets_path().exists()
    assert "…" in s.masked_finnhub_key()


def test_settings_tws_defaults_and_set(fresh_settings):
    s = fresh_settings
    assert s.get_tws_host() == "127.0.0.1"
    assert s.get_tws_port() == 7496  # live default
    s.set_tws("10.0.0.5", 4002)
    assert s.get_tws_host() == "10.0.0.5"
    assert s.get_tws_port() == 4002


def test_settings_env_overrides_file(fresh_settings, monkeypatch):
    s = fresh_settings
    s.set_finnhub_key("file-key")
    monkeypatch.setenv("FINNHUB_KEY", "env-key")
    assert s.get_finnhub_key() == "env-key"  # env wins


# --------------------------------------------------------------------------- #
# Dynamic clientId + ephemeral connection
# --------------------------------------------------------------------------- #
def test_connect_ib_retries_on_clientid_collision():
    tried: list[int] = []
    state = {"n": 0}

    class FakeIB:
        def __init__(self):
            self._conn = False

        def connect(self, host, port, clientId, timeout):  # noqa: N803
            tried.append(clientId)
            state["n"] += 1
            if state["n"] <= 2:
                raise RuntimeError("client id is already in use")
            self._conn = True

        def isConnected(self):
            return self._conn

        def disconnect(self):
            self._conn = False

    ib, cid = connect_ib("h", 7496, ib_factory=FakeIB, client_ids=[101, 102, 103, 104])
    assert ib.isConnected()
    assert tried == [101, 102, 103]  # retried with NEW ids until one worked
    assert cid == 103


def test_connect_ib_raises_after_max_attempts():
    class AlwaysCollide:
        def connect(self, *a, **k):
            raise RuntimeError("client id is already in use")  # collision -> keeps retrying

        def isConnected(self):
            return False

        def disconnect(self):
            pass

    with pytest.raises(ConnectionError):
        connect_ib("h", 7496, ib_factory=AlwaysCollide, client_ids=[1, 2], max_attempts=2)


def test_connect_ib_fails_fast_on_non_collision():
    calls = {"n": 0}

    class Refused:
        def connect(self, *a, **k):
            calls["n"] += 1
            raise ConnectionRefusedError("connection refused")  # TWS down / API off

        def isConnected(self):
            return False

        def disconnect(self):
            pass

    with pytest.raises(ConnectionError):
        connect_ib("h", 7496, ib_factory=Refused, client_ids=[1, 2, 3, 4], max_attempts=4)
    assert calls["n"] == 1  # did NOT retry a non-collision failure


def test_with_ib_runs_job_and_returns():
    class FakeIB:
        def __init__(self):
            self.connected = False

        def connect(self, host, port, clientId, timeout):  # noqa: N803
            self.connected = True

        def isConnected(self):
            return self.connected

        def disconnect(self):
            self.connected = False

        def managedAccounts(self):  # noqa: N802
            return ["U1", "U2"]

    result = with_ib(lambda ib: ib.managedAccounts(), "h", 7496, ib_factory=FakeIB, client_ids=[1, 2])
    assert result == ["U1", "U2"]


# --------------------------------------------------------------------------- #
# Managed accounts
# --------------------------------------------------------------------------- #
def test_list_managed_accounts():
    Row = namedtuple("Row", "account tag value")
    ib = MockIB(
        managed_accounts=["U1", "U2"],
        account_summary=[Row("U1", "NetLiquidation", "100000"), Row("U2", "NetLiquidation", "50000")],
    )
    accts = list_managed_accounts(ib)
    assert accts == [{"account": "U1", "nlv": 100000.0}, {"account": "U2", "nlv": 50000.0}]


# --------------------------------------------------------------------------- #
# Market-data fallback ordering
# --------------------------------------------------------------------------- #
class _StubProvider:
    def __init__(self, name, price, bars=None):
        self.name = name
        self._price = price
        self._bars = bars

    def last_price(self, symbol):
        return self._price

    def daily_bars(self, symbol, days=300):
        return self._bars


def test_fallback_skips_tws_when_none():
    md = MarketData([_StubProvider("tws", None), _StubProvider("yfinance", 123.0),
                     _StubProvider("finnhub", 999.0)])
    dp = md.last_price("AAPL")
    assert dp.value == 123.0 and dp.source == "yfinance"  # first non-None wins


def test_fallback_all_none():
    assert MarketData([_StubProvider("tws", None), _StubProvider("yfinance", None)]).last_price("X") is None


def test_fallback_skips_raising_provider():
    class Boom:
        name = "tws"

        def last_price(self, symbol):
            raise RuntimeError("tws down")

    md = MarketData([Boom(), _StubProvider("yfinance", 50.0)])
    assert md.last_price("X").source == "yfinance"


def test_build_market_data_offline_excludes_tws():
    md = build_market_data(mode="offline", finnhub_key="")
    names = [p.name for p in md.providers]
    assert "tws" not in names and "yfinance" in names


def test_build_market_data_live_includes_tws_and_finnhub():
    md = build_market_data(mode="live", finnhub_key="k")
    names = [p.name for p in md.providers]
    assert names[0] == "tws"
    assert "finnhub" in names
    assert isinstance(md.providers[-1], FinnhubProvider)
    assert any(isinstance(p, YFinanceProvider) for p in md.providers)


def test_finnhub_provider_uses_injected_http():
    fh = FinnhubProvider("key", http_get=lambda url, params: {"c": 187.5})
    assert fh.last_price("AAPL") == 187.5
    assert FinnhubProvider(None).last_price("AAPL") is None  # no key -> None
