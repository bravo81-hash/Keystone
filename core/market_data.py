"""Unified market data with graceful fallback.

When live TWS data isn't available (not connected, no subscription, or a failed
request), Keystone falls back to free sources — **yfinance** then **Finnhub
(free tier)** — so prices/history still flow. Order:

    TWS  ->  yfinance  ->  Finnhub

Providers are lazy (imports happen only when used) and injectable, so the test
suite never touches the network. Each provider returns ``None`` on any failure,
and the facade moves to the next one, recording which source answered.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

from core.models import DailyBar

logger = logging.getLogger(__name__)


@dataclass
class DataPoint:
    """A value plus the source that produced it ('tws' | 'yfinance' | 'finnhub')."""

    value: Any
    source: str


# --------------------------------------------------------------------------- #
# Providers
# --------------------------------------------------------------------------- #
class TwsPriceProvider:
    name = "tws"

    def __init__(self, host: Optional[str] = None, port: Optional[int] = None) -> None:
        self.host = host
        self.port = port

    def last_price(self, symbol: str) -> Optional[float]:
        from core.ib_client import ib_module, with_ib

        def job(ib: Any) -> Optional[float]:
            contract = ib_module().Stock(symbol, "SMART", "USD")
            ib.qualifyContracts(contract)
            ticker = ib.reqMktData(contract, "", snapshot=True)
            ib.sleep(2)
            px = ticker.last or ticker.close or ticker.marketPrice()
            ib.cancelMktData(contract)
            return float(px) if px and px > 0 else None

        try:
            return with_ib(job, self.host, self.port)
        except Exception as exc:  # noqa: BLE001 - fall through to next provider
            logger.info("TWS price for %s unavailable: %s", symbol, exc)
            return None

    def daily_bars(self, symbol: str, days: int = 300) -> Optional[list[DailyBar]]:
        from core.ib_client import ib_module, with_ib

        def job(ib: Any) -> list[DailyBar]:
            contract = ib_module().Stock(symbol, "SMART", "USD")
            ib.qualifyContracts(contract)
            bars = ib.reqHistoricalData(
                contract, "", f"{days} D", "1 day", "TRADES", useRTH=True, formatDate=1
            )
            return [
                DailyBar(date=b.date, open=b.open, high=b.high, low=b.low,
                         close=b.close, volume=getattr(b, "volume", 0) or 0)
                for b in bars
            ]

        try:
            return with_ib(job, self.host, self.port) or None
        except Exception as exc:  # noqa: BLE001
            logger.info("TWS history for %s unavailable: %s", symbol, exc)
            return None


class YFinanceProvider:
    name = "yfinance"

    def last_price(self, symbol: str) -> Optional[float]:
        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            info = getattr(ticker, "fast_info", None)
            if info is not None:
                px = info.get("last_price") if hasattr(info, "get") else getattr(info, "last_price", None)
                if px and px > 0:
                    return float(px)
            hist = ticker.history(period="1d")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
        except Exception as exc:  # noqa: BLE001
            logger.info("yfinance price for %s unavailable: %s", symbol, exc)
        return None

    def daily_bars(self, symbol: str, days: int = 300) -> Optional[list[DailyBar]]:
        try:
            import yfinance as yf

            hist = yf.Ticker(symbol).history(period=f"{days}d", interval="1d")
            if hist.empty:
                return None
            return [
                DailyBar(date=idx.date(), open=float(r.Open), high=float(r.High),
                         low=float(r.Low), close=float(r.Close),
                         volume=float(getattr(r, "Volume", 0) or 0))
                for idx, r in zip(hist.index, hist.itertuples())
            ]
        except Exception as exc:  # noqa: BLE001
            logger.info("yfinance history for %s unavailable: %s", symbol, exc)
            return None


HttpGet = Callable[[str, dict], dict]


class FinnhubProvider:
    name = "finnhub"
    QUOTE_URL = "https://finnhub.io/api/v1/quote"

    def __init__(self, api_key: Optional[str] = None, http_get: Optional[HttpGet] = None) -> None:
        self.api_key = api_key
        self._http_get = http_get

    def last_price(self, symbol: str) -> Optional[float]:
        if not self.api_key:
            return None
        try:
            getter = self._http_get
            if getter is None:
                from events.earnings import _default_http_get  # reuse the stdlib GET

                getter = _default_http_get
            data = getter(self.QUOTE_URL, {"symbol": symbol.upper(), "token": self.api_key})
            px = (data or {}).get("c")  # current price
            return float(px) if px and px > 0 else None
        except Exception as exc:  # noqa: BLE001
            logger.info("finnhub price for %s unavailable: %s", symbol, exc)
            return None

    # Finnhub free tier no longer serves daily candles -> no daily_bars here.


# --------------------------------------------------------------------------- #
# Facade
# --------------------------------------------------------------------------- #
class MarketData:
    """Tries each provider in order; returns the first that answers."""

    def __init__(self, providers: list) -> None:
        self.providers = providers

    def last_price(self, symbol: str) -> Optional[DataPoint]:
        for provider in self.providers:
            try:
                value = provider.last_price(symbol)
            except Exception:  # noqa: BLE001
                value = None
            if value is not None:
                return DataPoint(value, provider.name)
        return None

    def daily_bars(self, symbol: str, days: int = 300) -> Optional[DataPoint]:
        for provider in self.providers:
            fetch = getattr(provider, "daily_bars", None)
            if fetch is None:
                continue
            try:
                bars = fetch(symbol, days)
            except Exception:  # noqa: BLE001
                bars = None
            if bars:
                return DataPoint(bars, provider.name)
        return None


class TwsIVHistoryProvider:
    """Fetches 1yr daily OPTION_IMPLIED_VOLATILITY bars from TWS.

    Historical IV bars don't require a live market-data subscription — they use
    reqHistoricalData(whatToShow=OPTION_IMPLIED_VOLATILITY), same pacing budget
    as TRADES history. Returns None on any failure so callers fall back to
    realized_vol_rank().
    """

    name = "tws_iv"

    def __init__(self, host: Optional[str] = None, port: Optional[int] = None) -> None:
        self.host = host
        self.port = port

    def fetch(self, symbol: str) -> Optional[list[float]]:
        from core.ib_client import ib_module, with_ib

        def job(ib: Any) -> list[float]:
            contract = ib_module().Stock(symbol, "SMART", "USD")
            ib.qualifyContracts(contract)
            bars = ib.reqHistoricalData(
                contract, "",
                durationStr="1 Y",
                barSizeSetting="1 day",
                whatToShow="OPTION_IMPLIED_VOLATILITY",
                useRTH=True,
                formatDate=1,
            )
            return [float(b.close) for b in bars] if bars else []

        try:
            result = with_ib(job, self.host, self.port)
            return result if result else None
        except Exception as exc:  # noqa: BLE001
            logger.info("TWS IV history for %s unavailable: %s", symbol, exc)
            return None


def build_market_data(
    *,
    mode: str = "auto",
    host: Optional[str] = None,
    port: Optional[int] = None,
    finnhub_key: Optional[str] = None,
) -> MarketData:
    """Assemble the default provider chain. mode: 'auto'|'live' include TWS;
    'offline' uses only the free fallbacks."""

    from core.settings import get_finnhub_key

    providers: list = []
    if mode in ("auto", "live"):
        providers.append(TwsPriceProvider(host, port))
    providers.append(YFinanceProvider())
    key = finnhub_key if finnhub_key is not None else get_finnhub_key()
    if key:
        providers.append(FinnhubProvider(key))
    return MarketData(providers)
