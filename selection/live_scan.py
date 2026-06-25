"""Live weekly-checkpoint scan: watchlist -> chains/regime -> ranker -> cards.

Orchestrates the pieces that already exist (regime, surface, stock_regime,
ranker) over real data. Data access is injected — ``market_data`` (price/history)
and ``chain_provider`` (symbol -> OptionChain) — so the orchestration is unit
tested with fakes; the live wiring uses yfinance + the MarketData fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from config.schema import RiskConfig
from core.context import TradeContext
from core.models import Contract, InstrumentClass
from core.yf_chain import atm_iv_points
from portfolio.account_profiles import AccountProfile, classify
from regime.live import fetch_market_regime
from regime.stock_regime import StockRegime, stock_regime
from regime.surface import Surface, build_surface
from regime.vol_history import iv_rank, realized_vol, realized_vol_rank
from selection.ranker import rank
from strategies.trend_filter import TrendState, trend_state
from universe.seed import by_ticker

NY = ZoneInfo("America/New_York")

#: Default liquid, option-active trading watchlist (override in the UI).
DEFAULT_TRADING_WATCHLIST = [
    "SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMD", "META", "GOOGL", "XLE", "XLF", "TSLA",
]


@dataclass
class ScanResult:
    market_regime: Optional[Any] = None
    market_details: dict = field(default_factory=dict)
    screened: dict = field(default_factory=dict)
    cards: dict = field(default_factory=dict)
    account_labels: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def _flat_surface(symbol: str, iv: float = 0.30) -> Surface:
    return Surface(ticker=symbol, iv_9d=iv, iv_30d=iv, iv_90d=iv,
                   slope_9_30=0.0, slope_30_90=0.0, inverted_front=False)


def build_stock_regime_live(
    symbol: str,
    chain: Any,
    closes: list[float],
    asof: date,
    *,
    days_to_earnings: Optional[int] = None,
    iv_history: Optional[list[float]] = None,
) -> StockRegime:
    """Per-stock regime from a live chain + price history.

    ``iv_history``: 1yr daily OPTION_IMPLIED_VOLATILITY series from TWS.  When
    provided, IVR is computed from real implied-vol history (``iv_rank``).
    When absent, falls back to ``realized_vol_rank`` as a free-data proxy.
    """

    points = atm_iv_points(chain, asof)
    surface = build_surface(symbol, points) if points else _flat_surface(symbol)
    iv30 = surface.iv_30d
    rv20 = realized_vol(closes) or 0.0
    vrp_value = iv30 - rv20
    if iv_history and len(iv_history) >= 2:
        ivr = iv_rank(iv_history)
    else:
        ivr = realized_vol_rank(closes) or 50.0
    return stock_regime(symbol, surface, ivr, vrp_value, days_to_earnings=days_to_earnings)


def build_scan_targets(
    profiles: list[AccountProfile],
    *,
    trading_watchlist: Optional[list[str]] = None,
    smsf_watchlist: Optional[list[str]] = None,
) -> list[tuple[str, str]]:
    """(account_id, symbol) pairs: trading watchlist -> first trading account;
    SMSF watchlist -> first investing account."""

    trading = [p for p in profiles if p.is_trading()]
    smsf = [p for p in profiles if p.is_investing()]
    targets: list[tuple[str, str]] = []
    if trading:
        for sym in trading_watchlist or DEFAULT_TRADING_WATCHLIST:
            targets.append((trading[0].account_id, sym))
    if smsf and smsf_watchlist:
        for sym in smsf_watchlist:
            targets.append((smsf[0].account_id, sym))
    return targets


def run_checkpoint(
    profiles: list[AccountProfile],
    scan_targets: list[tuple[str, str]],
    *,
    market_data: Any,
    chain_provider: Callable[[str], Any],
    get_earnings: Optional[Callable[[str], Any]] = None,
    acquire_below: Optional[dict[str, float]] = None,
    nlv_overrides: Optional[dict[str, float]] = None,
    iv_history_provider: Optional[Callable[[str], Optional[list[float]]]] = None,
    asof: Optional[date] = None,
    cfg: Optional[RiskConfig] = None,
    top_n: int = 5,
    db: Any = None,
) -> ScanResult:
    """Run the full live checkpoint and return a ScanResult to drive the UI."""

    asof = asof or datetime.now(NY).date()
    cfg = cfg or RiskConfig()
    acquire_below = acquire_below or {}
    nlv_overrides = nlv_overrides or {}

    market_regime, market_details = fetch_market_regime(market_data)
    profile_by_id = {p.account_id: p for p in profiles}
    labels = {p.account_id: p.label for p in profiles}

    contexts: list[TradeContext] = []
    screened: dict = {}
    errors: list[str] = []

    for account_id, symbol in scan_targets:
        profile = profile_by_id.get(account_id)
        if profile is None:
            continue
        chain = chain_provider(symbol)
        if chain is None or not getattr(chain, "quotes", None):
            screened[symbol] = {"passed": False, "reasons": ["no option data"], "tier": "", "sector": ""}
            errors.append(f"{symbol}: no option chain data")
            continue

        bars = market_data.daily_bars(symbol, 300)
        closes = [b.close for b in bars.value] if bars is not None else []

        earnings_date = None
        days_to_earnings = None
        if get_earnings is not None:
            ev = get_earnings(symbol)
            if ev is not None and getattr(ev, "confirmed", False):
                earnings_date = ev.date
                days_to_earnings = (ev.date - asof).days

        iv_hist: Optional[list[float]] = None
        if iv_history_provider is not None:
            try:
                iv_hist = iv_history_provider(symbol)
            except Exception:  # noqa: BLE001
                pass
        sr = build_stock_regime_live(symbol, chain, closes, asof,
                                     days_to_earnings=days_to_earnings,
                                     iv_history=iv_hist)
        trend = trend_state(closes) if len(closes) >= 220 else TrendState.NONE

        seed = by_ticker(symbol)
        sector = seed.sector if seed else "UNKNOWN"
        tier = seed.tier if seed else "B"
        ic = classify(Contract.stock(symbol))
        is_etf = ic is InstrumentClass.US_ETF_OPT
        nlv = nlv_overrides.get(account_id) or profile.nlv or 100_000.0

        contexts.append(TradeContext(
            symbol=symbol, account_id=account_id, instrument_class=ic, chain=chain,
            is_etf=is_etf, spot=chain.spot, stock_regime=sr, market_regime=market_regime,
            next_earnings=earnings_date, per_position_budget=0.01 * nlv, nlv=nlv,
            acquire_below_price=acquire_below.get(symbol), asof=asof,
            extras={"tier": tier, "sector": sector, "trend": trend},
        ))
        screened[symbol] = {"passed": True, "tier": tier, "sector": sector,
                            "ivr": round(sr.ivr, 0), "is_etf": is_etf}

    cards = rank(profiles, contexts, cfg=cfg, db=db, top_n=top_n)
    return ScanResult(
        market_regime=market_regime, market_details=market_details, screened=screened,
        cards=cards, account_labels=labels, errors=errors,
    )
