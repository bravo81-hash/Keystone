"""Stage 1: seed pool + screen gates + affordability + staleness + earnings."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from config.schema import UniverseConfig
from core.models import Event, EventKind
from universe.screen import (
    ScreenResult,
    TickerSnapshot,
    count_leading_consecutive_weeklies,
    is_csp_affordable_smsf,
    load_screened,
    relative_spread,
    run_screen,
    screen_ticker,
    write_screened,
)
from universe.seed import SEED, SeedEntry, by_ticker, etfs, names

NY = ZoneInfo("America/New_York")
CFG = UniverseConfig()  # defaults: NLV 92k, single 12%, etf 25%, standard gates

# Injectable earnings lookups (so tests don't depend on the manual CSV file).
_CONFIRMED = lambda _t: Event(symbol="X", date=date(2026, 9, 1), kind=EventKind.EARNINGS, confirmed=True)
_UNCONFIRMED = lambda _t: Event(symbol="X", date=date(2026, 9, 1), kind=EventKind.EARNINGS, confirmed=False)
_UNKNOWN = lambda _t: None

_FRIDAYS = [date(2026, 6, 19) + timedelta(days=7 * i) for i in range(4)]
_NAME = SeedEntry("AAPL", "A", "Information Technology", is_etf=False)
_ETF = SeedEntry("XLE", "A", "Energy", is_etf=True)


def make_snapshot(ticker: str = "AAPL", **overrides) -> TickerSnapshot:
    base = dict(
        ticker=ticker,
        last_price=200.0,
        atm_bid_front=1.00,
        atm_ask_front=1.04,   # 3.9% spread
        atm_bid_back=2.00,
        atm_ask_back=2.12,    # 5.8% spread
        weekly_expiries=list(_FRIDAYS),
        option_adv=10000.0,
        open_interest_atm=5000,
    )
    base.update(overrides)
    return TickerSnapshot(**base)


# --------------------------------------------------------------------------- #
# Seed pool
# --------------------------------------------------------------------------- #
def test_seed_pool_shape():
    assert len(SEED) >= 90
    assert len(names()) >= 70
    assert len(etfs()) == 21
    assert all(e.tier in {"A", "B"} for e in SEED)
    assert all(e.tier == "A" for e in etfs())  # broad/sector ETFs are Tier A
    for t in ("AAPL", "NVDA", "XLE"):  # sanity tickers present
        assert by_ticker(t) is not None
    assert by_ticker("aapl").ticker == "AAPL"  # case-insensitive


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def test_relative_spread():
    assert relative_spread(1.0, 1.04) == pytest.approx(0.04 / 1.02)
    assert relative_spread(0.0, 0.0) is None       # no market
    assert relative_spread(1.0, 0.9) is None        # crossed


def test_count_leading_consecutive_weeklies():
    assert count_leading_consecutive_weeklies(_FRIDAYS) == 4
    assert count_leading_consecutive_weeklies(_FRIDAYS[:3]) == 3
    # A monthly gap after two weeklies breaks the leading run.
    broken = [_FRIDAYS[0], _FRIDAYS[1], _FRIDAYS[1] + timedelta(days=30)]
    assert count_leading_consecutive_weeklies(broken) == 2
    assert count_leading_consecutive_weeklies([]) == 0


# --------------------------------------------------------------------------- #
# Gates
# --------------------------------------------------------------------------- #
def test_full_pass():
    res = screen_ticker(_NAME, make_snapshot(), CFG, get_earnings=_CONFIRMED)
    assert res.passed is True
    assert res.reasons == []
    assert res.tier == "A"
    assert "csp_eligible_smsf" in res.flags
    assert res.flags["is_etf"] is False


def test_price_gate():
    res = screen_ticker(_NAME, make_snapshot(last_price=25.0), CFG, get_earnings=_CONFIRMED)
    assert res.passed is False
    assert any("last price" in r for r in res.reasons)


def test_front_spread_gate():
    res = screen_ticker(
        _NAME, make_snapshot(atm_bid_front=1.00, atm_ask_front=1.20), CFG, get_earnings=_CONFIRMED
    )
    assert res.passed is False
    assert any("front ATM spread" in r for r in res.reasons)


def test_back_spread_gate():
    res = screen_ticker(
        _NAME, make_snapshot(atm_bid_back=2.00, atm_ask_back=2.40), CFG, get_earnings=_CONFIRMED
    )
    assert res.passed is False
    assert any("back ATM spread" in r for r in res.reasons)


def test_weeklies_gate():
    res = screen_ticker(
        _NAME, make_snapshot(weekly_expiries=_FRIDAYS[:3]), CFG, get_earnings=_CONFIRMED
    )
    assert res.passed is False
    assert any("consecutive weeklies" in r for r in res.reasons)


def test_adv_and_oi_gates():
    res_adv = screen_ticker(_NAME, make_snapshot(option_adv=1000.0), CFG, get_earnings=_CONFIRMED)
    assert any("ADV" in r for r in res_adv.reasons)
    res_oi = screen_ticker(_NAME, make_snapshot(open_interest_atm=100), CFG, get_earnings=_CONFIRMED)
    assert any("OI" in r for r in res_oi.reasons)


def test_earnings_hard_skip_for_names():
    unknown = screen_ticker(_NAME, make_snapshot(), CFG, get_earnings=_UNKNOWN)
    assert unknown.passed is False
    assert any("earnings" in r for r in unknown.reasons)

    unconfirmed = screen_ticker(_NAME, make_snapshot(), CFG, get_earnings=_UNCONFIRMED)
    assert any("earnings" in r for r in unconfirmed.reasons)

    confirmed = screen_ticker(_NAME, make_snapshot(), CFG, get_earnings=_CONFIRMED)
    assert not any("earnings" in r for r in confirmed.reasons)


def test_etf_exempt_from_earnings():
    # ETF with unknown earnings still passes the earnings gate.
    res = screen_ticker(_ETF, make_snapshot(ticker="XLE", last_price=85.0), CFG, get_earnings=_UNKNOWN)
    assert not any("earnings" in r for r in res.reasons)
    assert res.passed is True


# --------------------------------------------------------------------------- #
# Affordability (both branches)
# --------------------------------------------------------------------------- #
def test_affordability_single_name_branch():
    # NLV 92k, 12% -> threshold $11,040 of premium -> price <= 110.4.
    assert is_csp_affordable_smsf(100.0, is_etf=False, cfg=CFG) is True
    assert is_csp_affordable_smsf(150.0, is_etf=False, cfg=CFG) is False


def test_affordability_etf_branch():
    # NLV 92k, 25% -> threshold $23,000 -> price <= 230.
    assert is_csp_affordable_smsf(150.0, is_etf=True, cfg=CFG) is True
    assert is_csp_affordable_smsf(250.0, is_etf=True, cfg=CFG) is False


def test_affordability_flag_in_result():
    res = screen_ticker(_NAME, make_snapshot(last_price=100.0), CFG, get_earnings=_CONFIRMED)
    assert res.flags["csp_eligible_smsf"] is True
    res2 = screen_ticker(_NAME, make_snapshot(last_price=150.0), CFG, get_earnings=_CONFIRMED)
    assert res2.flags["csp_eligible_smsf"] is False


# --------------------------------------------------------------------------- #
# run_screen + persistence + staleness
# --------------------------------------------------------------------------- #
def test_run_screen_assembles_report():
    snaps = {"AAPL": make_snapshot("AAPL"), "XLE": make_snapshot("XLE", last_price=85.0)}
    report = run_screen(snaps, CFG, get_earnings=_CONFIRMED)
    assert set(report["entries"]) == {"AAPL", "XLE"}
    assert report["generated_at"]
    assert report["entries"]["AAPL"]["passed"] is True


def test_staleness_fresh_vs_stale(tmp_path):
    now = datetime(2026, 6, 14, 12, 0, tzinfo=NY)
    entries = {"AAPL": {"passed": True, "reasons": [], "tier": "A", "sector": "IT", "flags": {}}}

    fresh = {"generated_at": (now - timedelta(days=1)).isoformat(), "entries": entries}
    p = tmp_path / "screened.json"
    write_screened(fresh, p)
    assert load_screened(p, max_age_days=7, asof=now) == entries

    stale = {"generated_at": (now - timedelta(days=10)).isoformat(), "entries": entries}
    write_screened(stale, p)
    assert load_screened(p, max_age_days=7, asof=now) == {}


def test_load_missing_returns_empty(tmp_path):
    assert load_screened(tmp_path / "nope.json") == {}


def test_screen_result_round_trips_json():
    res = screen_ticker(_NAME, make_snapshot(), CFG, get_earnings=_CONFIRMED, generated_at="2026-06-12T16:00:00-04:00")
    dumped = res.model_dump(mode="json")
    assert ScreenResult(**dumped).ticker == "AAPL"
