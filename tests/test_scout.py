"""Stage 20: Scout panel — 8-factor tech score + single-ticker on-demand analysis.

Covers: primitive indicators, factor logic, signal gating, ATR levels, VRP
structure hint; scout pipeline with injected fixtures (no network calls).
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from core.chain import OptionChain, OptionQuote
from core.models import Right
from selection.scout import ScoutResult, run_scout
from strategies.tech_score import TechSignal, TechScoreResult, compute_tech_score


# --------------------------------------------------------------------------- #
# Shared fixtures
# --------------------------------------------------------------------------- #

def _uptrend_ohlc(n: int = 300, daily_return: float = 0.002) -> dict:
    """Steady uptrend: price multiplies by (1 + daily_return) each bar."""
    closes, highs, lows, volumes = [], [], [], []
    price = 100.0
    for _ in range(n):
        price *= 1.0 + daily_return
        closes.append(price)
        highs.append(price * 1.005)
        lows.append(price * 0.995)
        volumes.append(1_000_000.0)
    weekly = closes[4::5]  # every 5th bar ≈ weekly close
    spy = [c * 0.95 for c in closes]  # SPY slightly underperforms
    return dict(closes=closes, highs=highs, lows=lows, volumes=volumes,
                weekly_closes=weekly, spy_closes=spy)


def _flat_ohlc(n: int = 300) -> dict:
    """Sideways oscillating series — no clear trend."""
    closes, highs, lows, volumes = [], [], [], []
    for i in range(n):
        price = 100.0 + math.sin(i / 20.0) * 2.0
        closes.append(price)
        highs.append(price + 0.5)
        lows.append(price - 0.5)
        volumes.append(500_000.0)
    weekly = closes[4::5]
    spy = closes[:]
    return dict(closes=closes, highs=highs, lows=lows, volumes=volumes,
                weekly_closes=weekly, spy_closes=spy)


def _fixture_chain(spot: float = 100.0, ticker: str = "TEST") -> OptionChain:
    asof = date.today()
    exp = asof + timedelta(days=45)
    puts = [(100, -0.50, 3.0), (95, -0.30, 1.8), (92, -0.20, 1.2),
            (90, -0.15, 0.9), (87, -0.10, 0.6)]
    calls = [(100, 0.50, 3.0), (105, 0.30, 1.8), (108, 0.20, 1.2),
             (110, 0.15, 0.9), (113, 0.10, 0.6)]
    q = [OptionQuote(expiry=exp, strike=k, right=Right.PUT,
                     bid=m, ask=m, delta=d, iv=0.25) for k, d, m in puts]
    q += [OptionQuote(expiry=exp, strike=k, right=Right.CALL,
                      bid=m, ask=m, delta=d, iv=0.25) for k, d, m in calls]
    return OptionChain(symbol=ticker, spot=spot, quotes=q, asof=asof)


# --------------------------------------------------------------------------- #
# TechScore — primitive + factor tests
# --------------------------------------------------------------------------- #

class TestTechScore:

    def test_returns_result_type(self):
        data = _uptrend_ohlc()
        r = compute_tech_score("X", data["closes"], data["highs"], data["lows"],
                               data["volumes"], data["spy_closes"], data["weekly_closes"])
        assert isinstance(r, TechScoreResult)

    def test_too_short_returns_skip(self):
        closes = [100.0 + float(i) for i in range(20)]
        highs = [c + 1.0 for c in closes]
        lows = [c - 1.0 for c in closes]
        vols = [1_000_000.0] * 20
        r = compute_tech_score("X", closes, highs, lows, vols, closes[:], [])
        assert r.signal is TechSignal.SKIP
        assert r.score == 0

    def test_uptrend_passes_f1(self):
        data = _uptrend_ohlc(300)
        r = compute_tech_score("X", data["closes"], data["highs"], data["lows"],
                               data["volumes"], data["spy_closes"], data["weekly_closes"])
        assert r.f1 is True, "EMA8>EMA21>EMA34 must hold for a steady uptrend"

    def test_score_equals_sum_of_factors(self):
        data = _uptrend_ohlc()
        r = compute_tech_score("X", data["closes"], data["highs"], data["lows"],
                               data["volumes"], data["spy_closes"], data["weekly_closes"])
        assert r.score == sum(r.factors)
        assert r.score == sum([r.f1, r.f2, r.f3, r.f4, r.f5, r.f6, r.f7, r.f8])

    def test_atr_levels_correctly_ordered(self):
        data = _uptrend_ohlc()
        r = compute_tech_score("X", data["closes"], data["highs"], data["lows"],
                               data["volumes"], data["spy_closes"], data["weekly_closes"])
        assert r.stop < r.entry < r.spot
        assert r.target > r.spot

    def test_strong_buy_requires_trio_and_score6(self):
        data = _uptrend_ohlc(300)
        r = compute_tech_score("X", data["closes"], data["highs"], data["lows"],
                               data["volumes"], data["spy_closes"], data["weekly_closes"])
        if r.signal is TechSignal.STRONG_BUY:
            assert r.trio is True
            assert r.score >= 6

    def test_no_strong_buy_without_trio(self):
        # Regardless of score, no STRONG_BUY without trio.
        data = _flat_ohlc()
        r = compute_tech_score("X", data["closes"], data["highs"], data["lows"],
                               data["volumes"], data["spy_closes"], data["weekly_closes"])
        if not r.trio:
            assert r.signal is not TechSignal.STRONG_BUY

    def test_watch_requires_f1(self):
        data = _uptrend_ohlc()
        r = compute_tech_score("X", data["closes"], data["highs"], data["lows"],
                               data["volumes"], data["spy_closes"], data["weekly_closes"])
        if r.signal is TechSignal.WATCH:
            assert r.f1 is True

    def test_high_vrp_recommends_credit_spread(self):
        data = _uptrend_ohlc()
        r = compute_tech_score("X", data["closes"], data["highs"], data["lows"],
                               data["volumes"], data["spy_closes"], data["weekly_closes"],
                               vrp=0.10)
        assert "credit_spread" in r.recommended_structure

    def test_low_vrp_recommends_long(self):
        data = _uptrend_ohlc()
        r = compute_tech_score("X", data["closes"], data["highs"], data["lows"],
                               data["volumes"], data["spy_closes"], data["weekly_closes"],
                               vrp=0.00)
        assert "trend_long" in r.recommended_structure

    def test_f6_false_when_spy_too_short(self):
        data = _uptrend_ohlc(300)
        r = compute_tech_score("X", data["closes"], data["highs"], data["lows"],
                               data["volumes"], data["spy_closes"][:15], data["weekly_closes"])
        assert r.f6 is False

    def test_uptrend_scores_higher_than_flat(self):
        up_data = _uptrend_ohlc()
        flat_data = _flat_ohlc()
        r_up = compute_tech_score("U", up_data["closes"], up_data["highs"], up_data["lows"],
                                  up_data["volumes"], up_data["spy_closes"], up_data["weekly_closes"])
        r_flat = compute_tech_score("F", flat_data["closes"], flat_data["highs"], flat_data["lows"],
                                    flat_data["volumes"], flat_data["spy_closes"], flat_data["weekly_closes"])
        assert r_up.score >= r_flat.score

    def test_atr_pct_in_range_for_normal_data(self):
        data = _uptrend_ohlc()
        r = compute_tech_score("X", data["closes"], data["highs"], data["lows"],
                               data["volumes"], data["spy_closes"], data["weekly_closes"])
        # ATR% should be positive and reasonable for the fixture data
        assert r.atr_pct > 0.0

    def test_rsi_populated(self):
        data = _uptrend_ohlc()
        r = compute_tech_score("X", data["closes"], data["highs"], data["lows"],
                               data["volumes"], data["spy_closes"], data["weekly_closes"])
        assert 0.0 <= r.rsi <= 100.0

    def test_adx_populated(self):
        data = _uptrend_ohlc()
        r = compute_tech_score("X", data["closes"], data["highs"], data["lows"],
                               data["volumes"], data["spy_closes"], data["weekly_closes"])
        assert r.adx >= 0.0


# --------------------------------------------------------------------------- #
# Scout — pipeline tests (no network — all overrides)
# --------------------------------------------------------------------------- #

class TestScout:

    def test_empty_ticker_returns_error(self):
        r = run_scout("")
        assert r.error is not None
        assert r.ticker == ""

    def test_whitespace_ticker_returns_error(self):
        r = run_scout("   ")
        assert r.error is not None

    def test_ticker_normalised_to_upper(self):
        data = _uptrend_ohlc()
        r = run_scout("aapl", ohlc_override=data, chain_override=None)
        assert r.ticker == "AAPL"

    def test_ohlc_override_bypasses_network(self):
        data = _uptrend_ohlc()
        chain = _fixture_chain()
        r = run_scout("AAPL", ohlc_override=data, chain_override=chain)
        assert r.error is None
        assert r.spot is not None
        assert r.spot > 0

    def test_tech_score_populated(self):
        data = _uptrend_ohlc()
        r = run_scout("AAPL", ohlc_override=data, chain_override=_fixture_chain())
        assert r.tech is not None
        assert isinstance(r.tech, TechScoreResult)
        assert r.tech.score >= 0

    def test_vol_metrics_populated_with_chain(self):
        data = _uptrend_ohlc()
        r = run_scout("AAPL", ohlc_override=data, chain_override=_fixture_chain())
        assert r.ivr is not None
        assert r.rv20 is not None

    def test_cards_generated_for_trading_mandate(self):
        data = _uptrend_ohlc()
        r = run_scout("AAPL", ohlc_override=data, chain_override=_fixture_chain())
        total = sum(len(v) for v in r.cards.values())
        assert total >= 1, f"Expected at least one card; got cards={r.cards}"

    def test_no_cards_without_chain(self):
        data = _uptrend_ohlc()
        r = run_scout("AAPL", ohlc_override=data, chain_override=None)
        assert r.error is None
        assert r.cards == {}

    def test_tech_score_present_without_chain(self):
        data = _uptrend_ohlc()
        r = run_scout("AAPL", ohlc_override=data, chain_override=None)
        assert r.tech is not None

    def test_hard_skip_vetoes_all_cards(self):
        from regime.market_regime import classify_market_regime
        hard_skip = classify_market_regime(32, 30, 26, 90, 100, False)
        data = _uptrend_ohlc()
        chain = _fixture_chain()
        r = run_scout("AAPL", ohlc_override=data, chain_override=chain,
                      market_regime=hard_skip)
        total = sum(len(v) for v in r.cards.values())
        assert total == 0, "HARD_SKIP must veto all new entries"

    def test_smsf_cards_use_investing_mandate(self):
        data = _uptrend_ohlc()
        chain = _fixture_chain()
        r = run_scout("AAPL", ohlc_override=data, chain_override=chain)
        smsf_cards = r.cards.get("SCOUT-SMSF", [])
        from core.models import Family
        from selection.ranker import SMSF_FAMILIES
        for card in smsf_cards:
            assert card.family in SMSF_FAMILIES, f"SMSF got non-SMSF family: {card.family}"

    def test_stock_regime_set_when_chain_available(self):
        data = _uptrend_ohlc()
        r = run_scout("AAPL", ohlc_override=data, chain_override=_fixture_chain())
        assert r.stock_regime is not None

    def test_spot_matches_last_close(self):
        data = _uptrend_ohlc(100)
        r = run_scout("AAPL", ohlc_override=data, chain_override=None)
        assert r.spot == pytest.approx(data["closes"][-1], rel=1e-6)

    def test_iv_history_provider_sets_real_ivr(self):
        """When iv_history_provider is given, ivr_is_real=True and IVR comes from iv_rank."""
        from regime.vol_history import iv_rank

        n = 252
        iv_hist = [0.20 + 0.10 * abs((i - n // 2) / (n // 2)) for i in range(n)]
        expected = iv_rank(iv_hist)

        data = _uptrend_ohlc()
        chain = _fixture_chain()
        r = run_scout("AAPL", ohlc_override=data, chain_override=chain,
                      iv_history_provider=lambda _ticker: iv_hist)
        assert r.ivr_is_real is True
        assert r.ivr == pytest.approx(expected, abs=0.01)

    def test_no_iv_provider_gives_proxy_ivr(self):
        """Without iv_history_provider, ivr_is_real stays False."""
        data = _uptrend_ohlc()
        r = run_scout("AAPL", ohlc_override=data, chain_override=_fixture_chain())
        assert r.ivr_is_real is False
        assert r.ivr is not None
