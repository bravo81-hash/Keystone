"""Build an OptionChain from free option data (yfinance) with greeks from BS.

yfinance gives strike/bid/ask/impliedVolatility per option but no greeks; we
compute **delta** ourselves via core.bs_pricing, so strategies (which pick strikes
by delta) work off free data — no TWS market-data subscription, and weekends use
Friday's closes. The pure transform (:func:`build_chain_from_rows`) is unit-tested;
the network fetch (:func:`fetch_chain_yf`) is exercised live.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from core.bs_pricing import bs_greeks
from core.chain import OptionChain, OptionQuote
from core.models import Right

logger = logging.getLogger(__name__)

DEFAULT_RISK_FREE = 0.04
_MIN_IV = 0.005


def build_chain_from_rows(
    symbol: str,
    spot: float,
    rows: list[dict],
    asof: date,
    *,
    risk_free: float = DEFAULT_RISK_FREE,
) -> OptionChain:
    """Rows = [{expiry: date, strike, right: Right, bid, ask, iv}] -> OptionChain.

    Delta is computed from spot/strike/T/iv via Black-Scholes; rows without a
    usable IV are skipped (so by-delta selection stays meaningful).
    """

    quotes: list[OptionQuote] = []
    for row in rows:
        expiry, strike, right = row["expiry"], float(row["strike"]), row["right"]
        iv = float(row.get("iv") or 0.0)
        t_years = (expiry - asof).days / 365.0
        if iv < _MIN_IV or t_years <= 0 or strike <= 0:
            continue
        delta = bs_greeks(spot, strike, t_years, risk_free, iv, right)["delta"]
        quotes.append(
            OptionQuote(
                expiry=expiry, strike=strike, right=right,
                bid=float(row.get("bid") or 0.0), ask=float(row.get("ask") or 0.0),
                iv=iv, delta=delta,
            )
        )
    return OptionChain(symbol=symbol, spot=spot, quotes=quotes, asof=asof)


def atm_iv_points(chain: OptionChain, asof: date) -> list[tuple[int, float]]:
    """(days_to_expiry, ATM IV) per expiry — ATM IV = mean of the nearest-strike
    call & put IVs. Feeds the term-structure surface."""

    points: list[tuple[int, float]] = []
    for expiry in chain.expiries():
        days = (expiry - asof).days
        ivs = []
        for right in (Right.CALL, Right.PUT):
            qs = chain.quotes_for(expiry, right)
            if qs:
                atm = min(qs, key=lambda q: abs(q.strike - chain.spot))
                if atm.iv > 0:
                    ivs.append(atm.iv)
        if days > 0 and ivs:
            points.append((days, sum(ivs) / len(ivs)))
    return points


def fetch_chain_yf(
    symbol: str,
    *,
    spot: Optional[float] = None,
    asof: Optional[date] = None,
    target_dtes: tuple[int, ...] = (40, 90),
    dte_min: int = 20,
    dte_max: int = 200,
    risk_free: float = DEFAULT_RISK_FREE,
) -> Optional[OptionChain]:
    """Fetch + build an OptionChain from yfinance (network). None on failure.

    To stay network-frugal (yfinance = one request per expiry, rate-limited), we
    fetch only the expiry nearest each target DTE (default ~40 and ~90 days,
    covering credit spreads / iron condors / wheel and debit spreads).
    """

    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not installed; cannot fetch chain for %s", symbol)
        return None

    asof = asof or date.today()
    try:
        ticker = yf.Ticker(symbol)
        if spot is None:
            info = getattr(ticker, "fast_info", None)
            spot = float(info["last_price"]) if info and info.get("last_price") else None
        if not spot:
            hist = ticker.history(period="1d")
            spot = float(hist["Close"].iloc[-1]) if not hist.empty else None
        if not spot:
            return None

        available: list[tuple[int, str]] = []
        for exp_str in ticker.options:
            try:
                days = (date.fromisoformat(exp_str) - asof).days
            except ValueError:
                continue
            if dte_min <= days <= dte_max:
                available.append((days, exp_str))
        if not available:
            return None

        chosen: list[str] = []
        for target in target_dtes:
            _, exp_str = min(available, key=lambda da: abs(da[0] - target))
            if exp_str not in chosen:
                chosen.append(exp_str)

        rows: list[dict] = []
        for exp_str in chosen:
            expiry = date.fromisoformat(exp_str)
            oc = ticker.option_chain(exp_str)
            for frame, right in ((oc.calls, Right.CALL), (oc.puts, Right.PUT)):
                for r in frame.itertuples():
                    rows.append({
                        "expiry": expiry, "strike": float(r.strike), "right": right,
                        "bid": float(getattr(r, "bid", 0) or 0),
                        "ask": float(getattr(r, "ask", 0) or 0),
                        "iv": float(getattr(r, "impliedVolatility", 0) or 0),
                    })
        if not rows:
            return None
        return build_chain_from_rows(symbol, float(spot), rows, asof, risk_free=risk_free)
    except Exception as exc:  # noqa: BLE001 - network/schema issues are non-fatal
        logger.warning("yfinance chain fetch failed for %s: %s", symbol, exc)
        return None
