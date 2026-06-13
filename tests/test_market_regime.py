"""Stage 4: market regime classification, 0.4/0.6 blend + veto, proximity tags."""

from __future__ import annotations

from datetime import date

import pytest

from regime.blend import blend, blended_score, stock_regime_score
from regime.market_regime import MarketRegimeState, classify_market_regime
from regime.proximity import (
    ExpiryEarningsTag,
    straddles_earnings,
    tag_expiry_vs_earnings,
    tag_structure_vs_earnings,
)
from regime.stock_regime import StockRegimeState, stock_regime
from regime.surface import Surface

_SURFACE = Surface(
    ticker="X", iv_9d=0.24, iv_30d=0.25, iv_90d=0.26,
    slope_9_30=0.01, slope_30_90=0.01, inverted_front=False,
)


def _stock(ivr: float, vrp_value: float):
    return stock_regime("X", _SURFACE, ivr=ivr, vrp_value=vrp_value)


# --------------------------------------------------------------------------- #
# Market regime classification
# --------------------------------------------------------------------------- #
def test_calm_trend():
    m = classify_market_regime(14, 15, 17, index_price=110, ma200=100, ma200_rising=True)
    assert m.state is MarketRegimeState.CALM_TREND
    assert m.score == 1.0
    assert not m.is_hard_skip and not m.is_defensive


def test_hard_skip():
    m = classify_market_regime(32, 30, 26, index_price=90, ma200=100, ma200_rising=False)
    assert m.state is MarketRegimeState.HARD_SKIP
    assert m.is_hard_skip is True
    assert m.score == 0.0


def test_defensive_from_term_backwardation():
    m = classify_market_regime(20, 18, 19, index_price=110, ma200=100, ma200_rising=True)
    assert m.state is MarketRegimeState.DEFENSIVE
    assert m.is_defensive is True
    assert m.term_front_backwardated is True


def test_defensive_from_trend_break():
    m = classify_market_regime(14, 15, 17, index_price=95, ma200=100, ma200_rising=True)
    assert m.state is MarketRegimeState.DEFENSIVE
    assert m.above_ma is False


def test_neutral():
    m = classify_market_regime(14, 15, 17, index_price=110, ma200=100, ma200_rising=False)
    assert m.state is MarketRegimeState.NEUTRAL
    assert m.score == 0.6


# --------------------------------------------------------------------------- #
# Blend math + veto
# --------------------------------------------------------------------------- #
def test_blended_score_weights():
    assert blended_score(1.0, 1.0) == pytest.approx(1.0)
    assert blended_score(0.6, 0.7) == pytest.approx(0.66)  # 0.4*0.6 + 0.6*0.7


def test_stock_regime_score_mapping():
    assert stock_regime_score(_stock(80, 0.05)) == 1.0  # PREMIUM_RICH
    assert stock_regime_score(_stock(40, 0.0)) == 0.7  # PREMIUM_FAIR


def test_blend_calm_plus_rich():
    market = classify_market_regime(14, 15, 17, 110, 100, True)
    result = blend(market, _stock(80, 0.05))
    assert result.score == pytest.approx(1.0)
    assert result.vetoed is False
    assert result.defensive is False


def test_hard_skip_vetoes_even_rich_stock():
    market = classify_market_regime(32, 30, 26, 90, 100, False)  # HARD_SKIP
    result = blend(market, _stock(85, 0.05))  # PREMIUM_RICH
    assert result.vetoed is True
    assert result.score == 0.0  # veto never softened by a great stock score
    assert result.stock_state is StockRegimeState.PREMIUM_RICH


def test_defensive_raises_flag_without_veto():
    market = classify_market_regime(20, 18, 19, 110, 100, True)  # DEFENSIVE
    result = blend(market, _stock(60, -0.05))  # NEUTRAL stock
    assert result.vetoed is False
    assert result.defensive is True
    assert result.score == pytest.approx(0.4 * 0.3 + 0.6 * 0.5)


# --------------------------------------------------------------------------- #
# Earnings proximity tagging
# --------------------------------------------------------------------------- #
EARN = date(2026, 7, 30)
BEFORE = date(2026, 7, 1)
AFTER = date(2026, 8, 5)


def test_proximity_pre():
    assert tag_expiry_vs_earnings(date(2026, 7, 18), EARN, BEFORE) is ExpiryEarningsTag.PRE


def test_proximity_straddles():
    assert tag_expiry_vs_earnings(date(2026, 8, 15), EARN, BEFORE) is ExpiryEarningsTag.STRADDLES


def test_proximity_pair_straddles_if_any_leg_after():
    pair = [date(2026, 7, 18), date(2026, 8, 15)]
    assert tag_structure_vs_earnings(pair, EARN, BEFORE) is ExpiryEarningsTag.STRADDLES
    early_pair = [date(2026, 7, 10), date(2026, 7, 18)]
    assert tag_structure_vs_earnings(early_pair, EARN, BEFORE) is ExpiryEarningsTag.PRE


def test_proximity_post_and_none():
    assert tag_expiry_vs_earnings(date(2026, 8, 15), EARN, AFTER) is ExpiryEarningsTag.POST
    assert tag_expiry_vs_earnings(date(2026, 8, 15), None, BEFORE) is ExpiryEarningsTag.NONE


def test_straddles_earnings_helper():
    assert straddles_earnings([date(2026, 8, 15)], EARN, BEFORE) is True
    assert straddles_earnings([date(2026, 7, 18)], EARN, BEFORE) is False
