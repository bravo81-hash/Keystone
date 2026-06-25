"""Single-ticker Scout: on-demand analysis of any ticker.

Pipeline:
  yfinance OHLC  ->  8-factor tech score
  yfinance chain ->  surface + IVR proxy + VRP -> stock regime
  ranker         ->  strategy cards (trading + SMSF mandates)

Works on free data (yfinance) — no TWS required. ``chain_override`` and
``ohlc_override`` bypass network calls for testing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from core.context import TradeContext
from core.models import Contract, InstrumentClass
from portfolio.account_profiles import AccountProfile, BlockedRule, Pool, classify
from regime.market_regime import MarketRegime
from regime.stock_regime import StockRegime
from selection.ranker import rank
from strategies.tech_score import TechScoreResult, compute_tech_score

logger = logging.getLogger(__name__)

# Default scout accounts (labelled separately so cards are clearly
# hypothetical, not tied to a real configured account).
_SCOUT_TRADING = AccountProfile("SCOUT-TRADING", "Trading (scout)", Pool.TRADING, nlv=100_000.0)
_SCOUT_SMSF = AccountProfile(
    "SCOUT-SMSF", "SMSF (scout)", Pool.INVESTING,
    blocked_rules=[BlockedRule(InstrumentClass.EU_CASH_INDEX, multi_expiry=True)],
    nlv=92_000.0,
)
DEFAULT_SCOUT_ACCOUNTS = [_SCOUT_TRADING, _SCOUT_SMSF]


@dataclass
class ScoutResult:
    ticker: str
    spot: Optional[float] = None
    tech: Optional[TechScoreResult] = None
    stock_regime: Optional[StockRegime] = None
    cards: dict[str, list] = field(default_factory=dict)
    ivr: Optional[float] = None
    ivr_is_real: bool = False         # True when IVR came from TWS IV history
    atm_iv: Optional[float] = None   # percent  (e.g. 25.0 for 25%)
    rv20: Optional[float] = None     # percent  (e.g. 18.0 for 18%)
    vrp: Optional[float] = None      # vol-points (e.g. 7.0 for 7v)
    error: Optional[str] = None


def run_scout(
    ticker: str,
    *,
    market_regime: Optional[MarketRegime] = None,
    accounts: Optional[list[AccountProfile]] = None,
    nlv: float = 100_000.0,
    asof: Optional[date] = None,
    chain_override: Optional[Any] = None,
    ohlc_override: Optional[dict] = None,
    iv_history_provider: Optional[Any] = None,
) -> ScoutResult:
    """Analyse a single ticker.

    ``ohlc_override``: dict with keys closes/highs/lows/volumes/
    weekly_closes/spy_closes (all list[float]) — skips yfinance.
    ``chain_override``: OptionChain — skips yfinance chain fetch.
    """
    ticker = ticker.upper().strip()
    if not ticker:
        return ScoutResult(ticker=ticker, error="ticker required")

    asof = asof or date.today()
    accts = accounts or DEFAULT_SCOUT_ACCOUNTS

    # ── 1. OHLC ─────────────────────────────────────────────────────────── #
    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    volumes: list[float] = []
    weekly_closes: list[float] = []
    spy_closes: list[float] = []

    if ohlc_override is not None:
        closes = ohlc_override.get("closes", [])
        highs = ohlc_override.get("highs", [])
        lows = ohlc_override.get("lows", [])
        volumes = ohlc_override.get("volumes", [])
        weekly_closes = ohlc_override.get("weekly_closes", [])
        spy_closes = ohlc_override.get("spy_closes", [])
    else:
        try:
            import yfinance as yf  # noqa: PLC0415 — lazy: only in requirements-live
        except ImportError:
            return ScoutResult(ticker=ticker,
                               error="yfinance not installed — pip install yfinance")
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="2y", interval="1d", auto_adjust=True)
            if hist.empty:
                return ScoutResult(ticker=ticker,
                                   error=f"No price history returned for {ticker!r}")
            closes = hist["Close"].tolist()
            highs = hist["High"].tolist()
            lows = hist["Low"].tolist()
            volumes = hist["Volume"].tolist()
            weekly_closes = hist["Close"].resample("W").last().dropna().tolist()
            spy_hist = yf.Ticker("SPY").history(period="2y", interval="1d", auto_adjust=True)
            spy_closes = spy_hist["Close"].tolist() if not spy_hist.empty else []
        except Exception as exc:  # noqa: BLE001
            return ScoutResult(ticker=ticker, error=f"Data fetch failed: {exc}")

    if not closes:
        return ScoutResult(ticker=ticker, error=f"No data available for {ticker!r}")

    spot = closes[-1]

    # ── 2. Option chain ──────────────────────────────────────────────────── #
    chain = chain_override
    if chain is None and ohlc_override is None:
        from core.yf_chain import fetch_chain_yf  # noqa: PLC0415
        chain = fetch_chain_yf(ticker, spot=spot, asof=asof)

    # ── 3. Vol context + stock regime ────────────────────────────────────── #
    sr: Optional[StockRegime] = None
    atm_iv_pct: Optional[float] = None
    rv20_pct: Optional[float] = None
    vrp_pct: Optional[float] = None
    ivr_val: Optional[float] = None
    ivr_is_real: bool = False
    vrp_decimal: Optional[float] = None

    if chain is not None:
        from core.yf_chain import atm_iv_points  # noqa: PLC0415
        from regime.stock_regime import stock_regime as _build_sr  # noqa: PLC0415
        from regime.surface import build_surface  # noqa: PLC0415
        from regime.vol_history import iv_rank, realized_vol, realized_vol_rank  # noqa: PLC0415

        points = atm_iv_points(chain, asof)
        surface = build_surface(ticker, points) if points else None
        if surface:
            atm_iv_pct = surface.iv_30d * 100.0

        rv = realized_vol(closes)
        if rv is not None:
            rv20_pct = rv * 100.0

        if atm_iv_pct is not None and rv20_pct is not None:
            vrp_pct = atm_iv_pct - rv20_pct
            vrp_decimal = vrp_pct / 100.0

        if iv_history_provider is not None:
            try:
                iv_hist = iv_history_provider(ticker)
                if iv_hist and len(iv_hist) >= 2:
                    ivr_val = iv_rank(iv_hist)
                    ivr_is_real = True
            except Exception:  # noqa: BLE001
                pass
        if ivr_val is None:
            ivr_val = realized_vol_rank(closes) or 50.0

        if surface:
            vrp_raw = surface.iv_30d - (rv or 0.0)
            sr = _build_sr(ticker, surface, ivr_val, vrp_raw)

    # ── 4. Tech score ────────────────────────────────────────────────────── #
    tech = compute_tech_score(
        ticker, closes, highs, lows, volumes, spy_closes, weekly_closes,
        vrp=vrp_decimal,
    )

    # ── 5. Strategy cards ────────────────────────────────────────────────── #
    cards: dict[str, list] = {}
    if chain is not None and chain.quotes:
        ic = classify(Contract.stock(ticker))
        is_etf = ic is InstrumentClass.US_ETF_OPT
        contexts = [
            TradeContext(
                symbol=ticker, account_id=a.account_id,
                instrument_class=ic, chain=chain,
                is_etf=is_etf, spot=spot,
                stock_regime=sr, market_regime=market_regime,
                per_position_budget=0.01 * nlv, nlv=nlv, asof=asof,
                extras={"tier": "A"},
            )
            for a in accts
        ]
        try:
            cards = rank(accts, contexts, top_n=3)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Scout ranker failed for %s: %s", ticker, exc)

    return ScoutResult(
        ticker=ticker, spot=spot, tech=tech, stock_regime=sr, cards=cards,
        ivr=ivr_val, ivr_is_real=ivr_is_real,
        atm_iv=atm_iv_pct, rv20=rv20_pct, vrp=vrp_pct,
    )
