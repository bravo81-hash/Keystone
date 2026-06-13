"""Stage 2: earnings (IBKR/Finnhub/CSV) + dividends + earnings-premium."""

from __future__ import annotations

from datetime import date

import pytest

from core.ib_client import IBClient, MockIB, ReqKind, TTLCache, _FakeTicker
from core.models import DailyBar, EventKind
from events.base import get_events
from events.dividends import get_next_exdiv, parse_ib_dividends
from events.earnings import (
    FinnhubEarnings,
    get_next_earnings,
    ibkr_next_earnings,
    parse_ibkr_calendar,
)
from events.earnings_premium import (
    implied_move_from_ivs,
    implied_move_from_straddle,
    median_realized_move,
    realized_earnings_moves,
)

ASOF = date(2026, 6, 14)
_IBKR_XML = '<FundamentalData><EarningsAnnouncement date="2026-07-30" confirmed="true"/></FundamentalData>'


def _write_csv(tmp_path, rows: str):
    p = tmp_path / "earnings.csv"
    p.write_text("ticker,date,confirmed\n" + rows, encoding="utf-8")
    return p


# --------------------------------------------------------------------------- #
# IBKR earnings adapter
# --------------------------------------------------------------------------- #
def test_parse_ibkr_calendar():
    assert parse_ibkr_calendar(_IBKR_XML) == (date(2026, 7, 30), True)
    assert parse_ibkr_calendar('<x><e date="2026-09-01" confirmed="false"/></x>') == (
        date(2026, 9, 1),
        False,
    )
    assert parse_ibkr_calendar(None) is None
    assert parse_ibkr_calendar("not xml") is None


def test_ibkr_adapter_conformance():
    client = IBClient(ib=MockIB(fundamentals={"AAPL": _IBKR_XML}))
    ev = ibkr_next_earnings("AAPL", client, asof=ASOF)
    assert ev is not None
    assert ev.date == date(2026, 7, 30)
    assert ev.confirmed is True
    assert ev.meta["source"] == "ibkr"
    assert client.budget.count(ReqKind.FUNDAMENTAL) == 1


def test_ibkr_adapter_caches_within_week():
    mock = MockIB(fundamentals={"AAPL": _IBKR_XML})
    client = IBClient(ib=mock)
    cache = TTLCache(7 * 24 * 3600)
    ibkr_next_earnings("AAPL", client, asof=ASOF, cache=cache)
    ibkr_next_earnings("AAPL", client, asof=ASOF, cache=cache)
    assert len(mock.req_fundamental_calls) == 1  # second call served from cache
    assert client.budget.count(ReqKind.FUNDAMENTAL) == 1


def test_ibkr_adapter_caches_miss():
    mock = MockIB(fundamentals={})  # no data
    client = IBClient(ib=mock)
    cache = TTLCache(7 * 24 * 3600)
    assert ibkr_next_earnings("ZZZ", client, asof=ASOF, cache=cache) is None
    assert ibkr_next_earnings("ZZZ", client, asof=ASOF, cache=cache) is None
    assert len(mock.req_fundamental_calls) == 1  # miss is cached too


# --------------------------------------------------------------------------- #
# Finnhub adapter
# --------------------------------------------------------------------------- #
def test_finnhub_adapter_conformance():
    def fake_get(url, params):
        assert params["symbol"] == "AAPL"
        assert params["token"] == "key"
        return {"earningsCalendar": [{"date": "2026-08-01"}, {"date": "2026-05-01"}]}

    fh = FinnhubEarnings(api_key="key", http_get=fake_get)
    ev = fh.next_earnings("AAPL", asof=ASOF)
    assert ev.date == date(2026, 8, 1)  # earliest future date
    assert ev.confirmed is True
    assert ev.meta["source"] == "finnhub"


def test_finnhub_without_key_returns_none():
    fh = FinnhubEarnings(api_key="", http_get=lambda u, p: {})
    assert fh.next_earnings("AAPL", asof=ASOF) is None


# --------------------------------------------------------------------------- #
# Resolver priority: CSV override -> IBKR -> Finnhub
# --------------------------------------------------------------------------- #
def test_manual_csv_overrides_ibkr(tmp_path):
    csv = _write_csv(tmp_path, "AAPL,2026-07-30,true\n")
    client = IBClient(ib=MockIB(fundamentals={"AAPL": '<x><e date="2026-08-15" confirmed="true"/></x>'}))
    ev = get_next_earnings("AAPL", ib_client=client, asof=ASOF, csv_path=csv)
    assert ev.date == date(2026, 7, 30)  # CSV wins
    assert ev.meta["source"] == "manual_csv"
    assert client.budget.count(ReqKind.FUNDAMENTAL) == 0  # IBKR not even queried


def test_unconfirmed_csv_flag(tmp_path):
    csv = _write_csv(tmp_path, "AAPL,2026-07-30,false\n")
    ev = get_next_earnings("AAPL", asof=ASOF, csv_path=csv)
    assert ev is not None and ev.confirmed is False  # caller hard-skips


def test_unknown_returns_none(tmp_path):
    csv = _write_csv(tmp_path, "")  # empty
    assert get_next_earnings("ZZZ", asof=ASOF, csv_path=csv) is None


def test_finnhub_fallback_when_csv_and_ibkr_empty(tmp_path):
    csv = _write_csv(tmp_path, "")
    fh = FinnhubEarnings(api_key="key", http_get=lambda u, p: {"earningsCalendar": [{"date": "2026-09-09"}]})
    ev = get_next_earnings("NFLX", finnhub=fh, asof=ASOF, csv_path=csv)
    assert ev.date == date(2026, 9, 9)
    assert ev.meta["source"] == "finnhub"


# --------------------------------------------------------------------------- #
# Dividends adapter (generic tick 456)
# --------------------------------------------------------------------------- #
def test_parse_ib_dividends():
    assert parse_ib_dividends("0.96,0.96,20260808,0.24") == (date(2026, 8, 8), 0.24)
    assert parse_ib_dividends("0.96,0.96,0,0") is None
    assert parse_ib_dividends("bad") is None
    assert parse_ib_dividends(None) is None


def test_dividends_adapter_conformance():
    mock = MockIB(quotes={"KO": _FakeTicker(dividends="1.92,1.92,20260815,0.48")})
    client = IBClient(ib=mock)
    ev = get_next_exdiv("KO", client, asof=ASOF)
    assert ev is not None
    assert ev.kind is EventKind.DIV
    assert ev.date == date(2026, 8, 15)
    assert ev.meta["amount"] == pytest.approx(0.48)
    assert client.budget.count(ReqKind.TICK) == 1
    assert len(mock.cancel_mkt_data_calls) == 1  # snapshot cancelled (pacing)


def test_dividends_past_date_returns_none():
    mock = MockIB(quotes={"KO": _FakeTicker(dividends="1.92,1.92,20260101,0.48")})
    client = IBClient(ib=mock)
    assert get_next_exdiv("KO", client, asof=ASOF) is None


# --------------------------------------------------------------------------- #
# Earnings premium
# --------------------------------------------------------------------------- #
def test_implied_move_from_ivs():
    # iv_front chosen so the excess variance over a 7-day tenor implies a 5% move.
    assert implied_move_from_ivs(0.4694, 0.30, 7 / 365) == pytest.approx(0.05, abs=1e-3)
    # Front IV below baseline -> no event premium.
    assert implied_move_from_ivs(0.20, 0.30, 7 / 365) == 0.0
    assert implied_move_from_ivs(0.40, 0.30, 0.0) == 0.0


def test_implied_move_from_straddle():
    assert implied_move_from_straddle(5.0, 100.0) == pytest.approx(0.05)
    assert implied_move_from_straddle(5.0, 0.0) == 0.0


def test_realized_moves_and_median():
    bars = [
        DailyBar(date=date(2026, 1, 10), open=99.0, close=100.0),
        DailyBar(date=date(2026, 1, 11), open=110.0, close=112.0),  # +10% gap
        DailyBar(date=date(2026, 4, 9), open=205.0, close=200.0),
        DailyBar(date=date(2026, 4, 12), open=190.0, close=188.0),  # -5% gap
    ]
    dates = [date(2026, 1, 10), date(2026, 4, 10)]
    moves = realized_earnings_moves(bars, dates)
    assert moves == pytest.approx([0.10, 0.05])
    assert median_realized_move(bars, dates) == pytest.approx(0.075)


def test_median_realized_move_empty():
    assert median_realized_move([], [date(2026, 1, 1)]) is None


# --------------------------------------------------------------------------- #
# Combined interface
# --------------------------------------------------------------------------- #
def test_get_events_combines_earnings_and_dividends():
    # AAPL earnings come from the shipped manual CSV (2026-07-30, confirmed).
    mock = MockIB(quotes={"AAPL": _FakeTicker(dividends="0.96,0.96,20260808,0.24")})
    client = IBClient(ib=mock)
    evs = get_events("AAPL", window_days=120, ib_client=client, asof=ASOF)
    kinds = {e.kind for e in evs}
    assert EventKind.DIV in kinds
    assert evs == sorted(evs, key=lambda e: e.date)  # date-sorted
